import json
import os
import time

import pytest

from ecoscribe import config, status, tomlw
from ecoscribe.window import Api


class FakeStartup:
    def __init__(self):
        self.value = None

    def app_command(self):
        return '"C:\\Apps\\Ecoscribe\\Ecoscribe.exe"'

    def is_enabled(self):
        return self.value is not None

    def enable(self, cmd):
        self.value = cmd

    def disable(self):
        self.value = None


@pytest.fixture
def api(tmp_path):
    signals = []
    a = Api(data_dir=tmp_path / "data", config_path=tmp_path / "cfg" / "config.toml",
            startup_mod=FakeStartup(), signal_reload=lambda: signals.append(1) or True,
            list_mic_names=lambda: ["Headset (Zone Vibe 100)", "Microphone (Anker PowerConf C20"],
            copy=lambda s: signals.append(("copy", s)))
    a._signals = signals
    (tmp_path / "data").mkdir()
    return a


def write_history(api, rows):
    with open(api._data_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_get_settings_defaults_and_options(api):
    s = api.get_settings()
    assert s["values"]["languages"] == "en"
    assert "ralt" not in [h["value"] for h in s["options"]["hotkeys"]]
    assert s["can_startup"] is True
    if config.MAC:  # Right Command, the system's default mic
        assert s["values"]["hotkey"] == "rcmd" and s["values"]["mic"] == ""
        assert {"value": "rcmd", "label": "Right Command (recommended)"} in s["options"]["hotkeys"]
        assert s["options"]["mics"][0] == {"value": "", "label": "System default"}
    else:
        assert s["values"]["hotkey"] == "rctrl"
        assert s["values"]["mic"] == ""  # a fresh install uses the Windows default mic
        assert {"value": "rctrl", "label": "Right Ctrl (recommended)"} in s["options"]["hotkeys"]
        assert s["options"]["mics"][0] == {"value": "", "label": "Windows default"}
        assert {"value": "Microphone (Anker PowerConf C20", "label": "Anker PowerConf C20"} in s["options"]["mics"]


def test_current_mic_kept_even_if_unplugged(api):
    assert api.save_settings({"mic": "Anker PowerConf"})["ok"]
    api._list_mic_names = lambda: ["Headset (Zone Vibe 100)"]
    s = api.get_settings()
    assert any(m["value"] == "Anker PowerConf" for m in s["options"]["mics"])


def test_save_settings_writes_config_toggles_startup_and_reloads(api):
    r = api.save_settings({"hotkey": "f13", "mic": "Headset (Zone Vibe 100)", "extra_languages": ["es"], "languages": "en,es",
                           "sounds": False, "overlay": True, "unmute": False, "startup": True})
    assert r["ok"] and r["restarting"]
    c = config.load(api._config_path)
    assert c.hotkey.key == "f13" and c.audio.device == "Headset (Zone Vibe 100)"
    assert c.whisper.languages == ["en", "es"] and c.ui.sounds is False and c.audio.unmute_while_recording is False
    assert api._startup.value == '"C:\\Apps\\Ecoscribe\\Ecoscribe.exe"'
    assert api._signals == [1]
    api.save_settings({"startup": False})
    assert api._startup.value is None
    assert config.load(api._config_path).hotkey.key == "f13"  # partial save keeps the rest


def test_save_settings_rejects_bad_values(api):
    r = api.save_settings({"hotkey": "ralt"})
    assert not r["ok"] and "not allowed" in r["error"]  # Right Alt is AltGr on the user's layout
    assert not api._config_path.exists()
    assert not api.save_settings({"languages": "fr"})["ok"]


def test_default_mic_is_empty_string_and_disables_gate(api):
    api.save_settings({"mic": ""})
    assert config.load(api._config_path).audio.device == ""


def test_history_newest_first_search_and_stats(api):
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_history(api, [
        {"ts": "2026-09-30T10:00:00", "text": "old one here ", "target": "slack.exe", "pasted": True},
        {"ts": now, "text": "Send the report today ", "target": "WindowsTerminal.exe", "pasted": True},
        {"ts": now, "text": "Climbing on Thursday ", "target": "chrome.exe", "pasted": False},
    ])
    h = api.get_history()
    assert [r["text"] for r in h["items"]][0] == "Climbing on Thursday "
    assert h["stats"]["today_words"] == 7 and h["stats"]["total_words"] == 10 and h["stats"]["total"] == 3
    assert [r["text"] for r in api.get_history(query="report")["items"]] == ["Send the report today "]


def test_history_survives_garbage_lines(api):
    (api._data_dir / "history.jsonl").write_text('{"text": "ok "}\nnot json\n\n', encoding="utf-8")
    assert [r["text"] for r in api.get_history()["items"]] == ["ok "]


def test_history_missing_file(api):
    assert api.get_history()["items"] == []


def test_clear_history_keeps_a_backup(api):
    write_history(api, [{"text": "a "}])
    api.clear_history()
    assert api.get_history()["items"] == []
    assert list(api._data_dir.glob("history-*.bak"))


def test_copy_text(api):
    api.copy_text("hola ")
    assert ("copy", "hola ") in api._signals


def test_status_alive_and_dead(api):
    assert api.get_status()["state"] == "stopped"
    status.write(api._data_dir / "status.json", state="ready", device="cuda")
    s = api.get_status()
    assert s["state"] == "ready" and s["alive"] is True  # our own pid wrote it
    p = api._data_dir / "status.json"
    d = json.loads(p.read_text())
    d["pid"] = 999999
    p.write_text(json.dumps(d))
    assert api.get_status()["state"] == "stopped"


def test_welcome_flag(api):
    assert api.get_welcome()["done"] is False
    api.finish_welcome()
    assert api.get_welcome()["done"] is True


from ecoscribe.window import pretty_mic


def test_pretty_mic():
    assert pretty_mic("Microphone (Anker PowerConf C20") == "Anker PowerConf C20"
    assert pretty_mic("Headset (Zone Vibe 100)") == "Zone Vibe 100"
    assert pretty_mic("Line In") == "Line In"
    assert pretty_mic("") == ""


class FakeRec:
    instances = []

    def __init__(self, cfg, fail_begin=False):
        self.cfg, self.closed, self.aborted, self.device_name, self.fell_back = cfg, False, False, cfg.device, False
        self.fail_begin = fail_begin
        FakeRec.instances.append(self)

    def open(self): pass
    def begin(self):
        if self.fail_begin:
            raise OSError("no mic")
    def abort(self): self.aborted = True
    def close(self): self.closed = True
    def level(self): return 0.1


class FakeGate:
    instances = []

    def __init__(self, *a, **k):
        self.opened = self.restored = 0
        FakeGate.instances.append(self)

    def open(self): self.opened += 1
    def restore(self): self.restored += 1


def _fake_mic(api, monkeypatch, fail_begin=False):
    FakeRec.instances, FakeGate.instances = [], []
    import ecoscribe.audio
    import ecoscribe.micgate
    monkeypatch.setattr(ecoscribe.audio, "Recorder", lambda cfg: FakeRec(cfg, fail_begin))
    monkeypatch.setattr(ecoscribe.micgate, "MicGate", FakeGate)


def test_mic_test_start_stop_restores_gate(api, monkeypatch):
    _fake_mic(api, monkeypatch)
    api.mic_test_start("Anker PowerConf")
    assert api.mic_test_level() == 0.1
    api.mic_test_start("Headset")  # a second start replaces the first, never leaks it
    api.mic_test_stop()
    assert all(r.closed for r in FakeRec.instances) and all(g.restored == 1 for g in FakeGate.instances)
    assert api.mic_test_level() == 0.0


def test_mic_test_start_failure_restores_gate(api, monkeypatch):
    _fake_mic(api, monkeypatch, fail_begin=True)
    r = api.mic_test_start("Anker PowerConf")
    assert r.get("error")
    assert FakeGate.instances[0].restored == 1 and FakeRec.instances[0].closed


def test_concurrent_mic_test_calls_leak_nothing(api, monkeypatch):
    import threading
    _fake_mic(api, monkeypatch)
    ts = [threading.Thread(target=api.mic_test_start, args=("Anker",)) for _ in range(8)]
    ts += [threading.Thread(target=api.mic_test_stop) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    api.mic_test_stop()
    assert all(r.closed for r in FakeRec.instances)
    assert all(g.restored == 1 for g in FakeGate.instances)


def test_api_exposes_no_public_data_attributes(api):
    """pywebview turns every public attribute into JS API; only methods may be public."""
    leaks = [n for n in dir(api) if not n.startswith("_") and not callable(getattr(api, n))]
    assert leaks == []


def test_meeting_settings_and_on_demand_round_trip(api):
    v = api.get_settings()
    assert v["values"]["meet_mode"] == "prompt" and v["values"]["meet_lang"] == "sv" and v["values"]["on_demand"] is True
    assert [o["value"] for o in v["options"]["meet_modes"]] == ["prompt", "auto", "off"]
    assert api.save_settings({"meet_mode": "auto", "meet_lang": "el", "on_demand": False})["ok"]
    c = config.load(api._config_path)
    assert c.meetings.mode == "auto" and c.meetings.default_lang == "el" and c.whisper.on_demand is False
    assert not api.save_settings({"meet_mode": "siempre"})["ok"]
    assert not api.save_settings({"meet_lang": "xx"})["ok"]  # any Whisper language is fine; nonsense isn't


def test_meeting_end_wait_is_a_setting(api):
    v = api.get_settings()
    assert v["values"]["meet_end"] == "10"
    assert [o["value"] for o in v["options"]["meet_ends"]] == ["5", "10", "15", "30", "60", "120"]
    assert api.save_settings({"meet_end": "30"})["ok"]
    assert config.load(api._config_path).meetings.grace_s == 30
    assert not api.save_settings({"meet_end": "7"})["ok"]
    assert not api.save_settings({"meet_end": None})["ok"]
    assert config.load(api._config_path).meetings.grace_s == 30


def test_meeting_end_wait_keeps_a_hand_typed_value(api):
    c = config.load(api._config_path)
    c.meetings.grace_s = 45
    tomlw.save(c, api._config_path)
    v = api.get_settings()
    assert v["values"]["meet_end"] == "45" and v["options"]["meet_ends"][-1] == {"value": "45", "label": "45 seconds"}
    assert api.save_settings({"meet_end": "45", "meet_mode": "auto"})["ok"]  # saving the rest keeps it
    assert config.load(api._config_path).meetings.grace_s == 45



def test_combo_shortcuts(api):
    if config.MAC:
        assert api.check_hotkey("Shift + Cmd + D") == {"ok": True, "value": "shift+cmd+d", "label": "Shift+Cmd+D"}
        assert not api.check_hotkey("cmd+c")["ok"] and not api.check_hotkey("alt+d")["ok"]
        assert api.save_settings({"hotkey": "shift+cmd+d"})["ok"] and config.load(api._config_path).hotkey.vk == 0
        return
    assert api.check_hotkey("Ctrl + L") == {"ok": True, "value": "ctrl+l", "label": "Ctrl+L"}
    assert not api.check_hotkey("ctrl+c")["ok"] and not api.check_hotkey("ctrl+alt+d")["ok"]
    assert api.save_settings({"hotkey": "ctrl+shift+d"})["ok"]
    c = config.load(api._config_path)
    assert c.hotkey.key == "ctrl+shift+d" and c.hotkey.vk == 0  # combos go through hotkeys.ComboMatcher
    assert api.get_settings()["values"]["hotkey_label"] == "Ctrl+Shift+D"


def test_languages_are_add_ons(tmp_path):
    """dictado-ehs: English + Swedish built in; added languages can be ticked, removed ones drop out."""
    from ecoscribe import config
    from ecoscribe.window import Api
    cfg = tmp_path / "config.toml"
    api = Api(data_dir=tmp_path, config_path=cfg, signal_reload=lambda: True)
    s = api.get_settings()
    assert [o["value"] for o in s["options"]["languages"]] == ["en", "sv"] and s["values"]["extra_languages"] == []
    assert [o["value"] for o in s["options"]["meet_langs"]] == ["en", "sv", "en,sv", "auto"]
    assert any(o["value"] == "el" for o in s["options"]["all_languages"]) and len(s["options"]["all_languages"]) == 98
    assert not api.save_settings({"languages": "en,es"})["ok"]  # Spanish isn't added yet
    assert api.save_settings({"extra_languages": ["es", "el"], "languages": "el,sv,en,es"})["ok"]
    s = api.get_settings()
    assert s["values"]["languages"] == "en,sv,es,el" and s["values"]["extra_languages"] == ["es", "el"]
    assert [o["value"] for o in s["options"]["meet_langs"]] == ["en", "sv", "es", "el", "en,sv,es,el", "auto"]
    assert api.save_settings({"meet_lang": "el"})["ok"]
    assert api.save_settings({"extra_languages": ["es"]})["ok"]  # remove Greek
    c = config.load(cfg)
    assert c.whisper.languages == ["en", "sv", "es"] and c.meetings.default_lang == "sv"  # Greek dropped everywhere
    assert not api.save_settings({"extra_languages": ["xx"]})["ok"]


def test_setup_info_lists_both_models_and_no_permissions_off_mac(api, monkeypatch):
    monkeypatch.setattr("ecoscribe.window.sys.platform", "win32")
    monkeypatch.setattr("ecoscribe.models.is_ready", lambda name, root=None: name == "large-v3-turbo")
    info = api.setup_info("en")
    assert [m["label"] for m in info["models"]] == ["Fast", "Most accurate"]
    assert [m["ready"] for m in info["models"]] == [True, False]
    assert info["models"][0]["required"] and not info["models"][1]["required"]
    assert info["permissions"] == []
    assert api.setup_info("en,sv")["models"][1]["required"]


def test_setup_models_download_in_order_with_progress(api, monkeypatch):
    done = []

    def fake_prepare(name, progress=None, **kw):
        progress(50, 100)
        progress(100, 100)
        done.append(name)
    monkeypatch.setattr("ecoscribe.models.prepare", fake_prepare)
    monkeypatch.setattr("ecoscribe.models.is_ready", lambda name, root=None: name in done)
    api.setup_models_start(["large-v3-turbo", "Systran/faster-whisper-large-v3"])
    for _ in range(100):
        p = api.setup_models_progress()
        if not p["running"]:
            break
        time.sleep(0.02)
    assert done == ["large-v3-turbo", "Systran/faster-whisper-large-v3"]
    assert all(m["done"] == m["total"] == 100 and m["ready"] for m in p["models"].values())
    assert p["error"] is None


def test_setup_models_error_is_reported(api, monkeypatch):
    def boom(name, progress=None, **kw):
        raise OSError("no network")
    monkeypatch.setattr("ecoscribe.models.prepare", boom)
    monkeypatch.setattr("ecoscribe.models.is_ready", lambda name, root=None: False)
    api.setup_models_start(["large-v3-turbo"])
    for _ in range(100):
        p = api.setup_models_progress()
        if not p["running"]:
            break
        time.sleep(0.02)
    assert "no network" in p["error"]


def test_initial_page_comes_from_python_not_the_url(tmp_path):
    assert Api(data_dir=tmp_path, page="bienvenida").initial_page() == "bienvenida"
    assert Api(data_dir=tmp_path).initial_page() is None


def test_history_says_which_dictations_can_be_retried(api):
    write_history(api, [{"ts": "2026-10-12T09:00:00", "text": "old one", "id": "a", "audio": True},
                        {"ts": "2026-10-12T09:01:00", "text": "new one", "id": "b", "audio": True}])
    (api._data_dir / "recent").mkdir()
    (api._data_dir / "recent" / "b.wav").write_bytes(b"")
    items = api.get_history()["items"]
    assert [(i["text"], i["audio"]) for i in items] == [("new one", True), ("old one", False)]


def test_retry_goes_to_the_background_app(tmp_path):
    sent = []
    a = Api(data_dir=tmp_path, send_command=lambda d, cmd, args, **kw: sent.append((cmd, args, kw)) or {"ok": True})
    assert a.retry_dictation("b", "sv") == {"ok": True}
    assert sent == [("retry", {"id": "b", "lang": "sv"}, {"wait_s": 120.0})]


def test_models_info_and_delete(api, monkeypatch):
    monkeypatch.setattr("ecoscribe.models.is_ready", lambda name, root=None: name == "large-v3-turbo")
    monkeypatch.setattr("ecoscribe.models.disk_size", lambda name, root=None: 1_600_000_000)
    deleted = []
    monkeypatch.setattr("ecoscribe.models.delete", lambda name, root=None: deleted.append(name) or True)
    info = api.models_info()["models"]
    assert [(m["label"], m["ready"], m["disk"]) for m in info] == [("Fast", True, 1_600_000_000), ("Most accurate", False, 0)]
    assert api.delete_model("large-v3-turbo") == {"ok": True} and deleted == ["large-v3-turbo"]
    assert api.delete_model("../../something")["ok"] is False


def test_delete_model_in_use_says_so(api, monkeypatch):
    def busy(name, root=None):
        raise PermissionError("in use")
    monkeypatch.setattr("ecoscribe.models.delete", busy)
    r = api.delete_model("large-v3-turbo")
    assert r["ok"] is False and "in use" in r["error"]


def _meeting_with(tmp_path, text, emails):
    from ecoscribe import sessions as S
    root = tmp_path / "transcripts"
    d = S.create("Weekly planning", "en", "meeting", root)
    S.write_meta(d, status="done", calendar={"title": "Weekly planning", "attendees": ["Ana Ruiz"], "emails": emails})
    (d / "transcript.json").write_text(json.dumps({"segments": [{"t0": 0, "t1": 2, "text": text, "speaker": "Others"}]}),
                                       encoding="utf-8")
    return d


def test_email_participants_short_transcript_goes_in_the_draft(tmp_path, monkeypatch):
    opened, copied = [], []
    d = _meeting_with(tmp_path, "The blue bicycle is mine.", ["ana@example.com", "bo@example.com"])
    a = Api(data_dir=tmp_path, copy=copied.append, open_url=opened.append)
    monkeypatch.setattr(a, "_session", lambda name: d)
    monkeypatch.setattr(a, "get_session", lambda name: {"segments": json.loads((d / "transcript.json").read_text())["segments"], "notes": ""})
    r = a.email_participants(d.name)
    assert r["ok"] and r["to"] == ["ana@example.com", "bo@example.com"] and r["inline"]
    url = opened[0]
    assert url.startswith("mailto:ana@example.com,bo@example.com?subject=Transcript%3A%20Weekly%20planning")
    assert "blue%20bicycle" in url and "automatically" in url  # says plainly it's an automatic transcript
    assert "blue bicycle" in copied[0]


def test_email_participants_long_transcript_is_copied_to_paste(tmp_path, monkeypatch):
    opened, copied = [], []
    d = _meeting_with(tmp_path, "word " * 2000, [])
    a = Api(data_dir=tmp_path, copy=copied.append, open_url=opened.append)
    monkeypatch.setattr(a, "_session", lambda name: d)
    monkeypatch.setattr(a, "get_session", lambda name: {"segments": json.loads((d / "transcript.json").read_text())["segments"], "notes": ""})
    r = a.email_participants(d.name, "draft")  # no guests and no calendar would go to Google Calendar (dictado-qxr)
    assert r["ok"] and not r["inline"] and r["to"] == []
    assert len(opened[0]) < 1800 and "paste%20it%20here" in opened[0]
    assert copied[0].count("word") == 2000


def _no_guests(tmp_path, monkeypatch, cfg_text="", source="meeting"):
    from ecoscribe import sessions as S
    d = S.create("Call", "en", source, tmp_path / "transcripts", now=__import__("datetime").datetime(2026, 3, 7, 18, 5))
    S.write_meta(d, status="done")
    (d / "transcript.json").write_text(json.dumps({"segments": [{"t0": 0, "t1": 2, "text": "The red kite flew.", "speaker": "Others"}]}),
                                       encoding="utf-8")
    cfg = tmp_path / "config.toml"
    cfg.write_text(cfg_text, encoding="utf-8")
    opened, copied = [], []
    a = Api(data_dir=tmp_path, config_path=cfg, copy=copied.append, open_url=opened.append)
    monkeypatch.setattr(a, "_session", lambda name: d)
    monkeypatch.setattr(a, "get_session", lambda name: {"segments": json.loads((d / "transcript.json").read_text())["segments"], "notes": ""})
    return a, d, opened, copied


def test_no_guests_and_no_calendar_opens_google_calendar_on_that_day(tmp_path, monkeypatch):  # dictado-qxr
    a, d, opened, copied = _no_guests(tmp_path, monkeypatch)
    r = a.email_participants(d.name)
    assert r == {"ok": True, "to": [], "via": "calendar", "day": "2026-03-07", "chars": len("The red kite flew.")}
    assert opened == ["https://calendar.google.com/calendar/r/day/2026/3/7"]
    assert copied[0].startswith("Hi,") and "red kite" in copied[0]  # ready to paste into Email guests
    r = a.email_participants(d.name, "draft")  # "an empty email instead"
    assert r["via"] == "draft" and opened[1].startswith("mailto:?subject=")


def test_with_a_calendar_link_or_an_imported_file_it_stays_a_draft(tmp_path, monkeypatch):
    a, d, opened, _ = _no_guests(tmp_path, monkeypatch, '[meetings]\ncalendar_url = "https://example.com/basic.ics"\n')
    assert a.email_participants(d.name)["via"] == "draft" and opened[0].startswith("mailto:")
    a, d, opened, _ = _no_guests(tmp_path / "imp", monkeypatch, source="import")
    assert a.email_participants(d.name)["via"] == "draft"


def test_session_rows_carry_people_and_app_for_the_meeting_page(tmp_path):
    from ecoscribe import sessions as S
    d = S.create("Weekly planning", "en", "meeting", tmp_path)
    S.write_meta(d, app="msteams", calendar={"title": "Weekly planning", "attendees": ["Ana Ruiz", "Bo Lind"]})
    row = Api._row(S.read_meta(d) | {"dir": str(d)})
    assert row["people"] == ["Ana Ruiz", "Bo Lind"] and row["app"] == "msteams"


def test_claude_switches_round_trip_with_their_phrase_list(api):  # dictado-bd6
    v = api.get_settings()
    assert v["values"]["self_corrections"] is False and v["values"]["command_mode"] is False
    rows = {r["what"]: r for r in v["correction_list"]}
    assert '"scratch that"' in rows["Drops the sentence before it"]["en"]
    assert '"no wait"' in rows["Claude applies the correction"]["en"] and rows["Claude applies the correction"]["el"]
    assert api.save_settings({"self_corrections": True, "command_mode": True})["ok"]
    c = config.load(api._config_path)
    assert c.text.self_corrections is True and c.text.command_mode is True


def test_an_open_window_takes_the_page_it_was_asked_for_once(tmp_path, monkeypatch):  # dictado-1b7
    from ecoscribe import ipc, paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    api = Api(data_dir=tmp_path)
    assert api.take_page() is None
    ipc.ask_page("ajustes/claude")
    assert api.take_page() == "ajustes/claude"
    assert api.take_page() is None  # once
