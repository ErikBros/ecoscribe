from ecoscribe.detect import Detector, MicUse, app_from_nonpackaged, app_from_packaged, uses_from_entries


def use(app, on=True):
    return MicUse(app=app, in_use=on, start=1, stop=0 if on else 2)


def run(det, frames, step=2.0, t0=0.0):
    """frames: list of (uses, titles); returns events with their times."""
    out = []
    for i, (uses, titles) in enumerate(frames):
        ev = det.update(uses, titles, t0 + i * step)
        if ev:
            out.append(ev)
    return out


def test_call_app_starts_meeting():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome", False)], [], 0.0) is None
    ev = d.update([use("msteams")], [], 2.0)
    assert ev.kind == "start" and ev.app == "msteams" and ev.at == 2.0


def test_browser_without_second_signal_ignored():
    d = Detector(debounce_polls=1)
    frames = [([use("chrome")], ["Inbox - Gmail", "Ecoscribe"])] * 900  # 30 min at 2 s
    assert run(d, frames) == []


def test_browser_with_meet_title_starts():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome")], ["Inbox - Gmail"], 0.0) is None
    ev = d.update([use("chrome")], ["Meet - abc-defg-hij - Google Chrome"], 2.0)
    assert ev.kind == "start" and ev.app == "chrome"


def test_browser_that_talks_starts_without_a_title():
    d = Detector(debounce_polls=1)
    talk = MicUse(app="chrome", in_use=True, start=1, stop=0, talking=True)
    ev = d.update([talk], ["Docs - Google Chrome"], 0.0)
    assert ev.kind == "start" and ev.app == "chrome"
    assert d.update([talk], [], 2.0) is None  # still in the call
    d.update([use("chrome")], [], 4.0)  # call over, the tab keeps the mic
    assert d.update([use("chrome")], [], 20.0).kind == "end"


def test_a_call_app_that_talks_is_still_just_a_call_app():
    d = Detector(debounce_polls=1)
    ev = d.update([MicUse(app="spotify", in_use=True, start=1, stop=0, talking=True)], [], 0.0)
    assert ev is None  # neither a call app nor a browser


def test_own_process_excluded():
    d = Detector(debounce_polls=1)
    frames = [([use("ecoscribe"), use("pythonw")], ["Microsoft Teams"])] * 50
    assert run(d, frames) == []


def test_short_release_within_grace_keeps_meeting():
    d = Detector(debounce_polls=1)
    frames = ([([use("msteams")], [])] * 5 + [([use("msteams", False)], [])] * 5
              + [([use("msteams")], [])] * 20 + [([use("msteams", False)], [])] * 4)
    evs = run(d, frames)
    assert [e.kind for e in evs] == ["start"]


def test_release_past_grace_ends():
    d = Detector(debounce_polls=1)
    assert d.update([use("msteams")], [], 0.0).kind == "start"
    assert d.update([use("msteams", False)], [], 100.0) is None  # released, seen at 100
    assert d.update([use("msteams", False)], [], 108.0) is None
    ev = d.update([use("msteams", False)], [], 110.0)
    assert ev.kind == "end" and ev.app == "msteams" and ev.at == 110.0  # 10 s (dictado-mtc)
    assert d.update([use("msteams", False)], [], 112.0) is None


def test_one_meeting_at_a_time():
    d = Detector(debounce_polls=1)
    assert d.update([use("msteams")], [], 0.0).kind == "start"
    assert d.update([use("msteams"), use("slack")], [], 2.0) is None
    d.update([use("msteams", False), use("slack")], [], 4.0)
    ev = d.update([use("msteams", False), use("slack")], [], 30.0)
    assert ev.kind == "end" and ev.app == "msteams"
    ev = d.update([use("msteams", False), use("slack")], [], 32.0)
    assert ev.kind == "start" and ev.app == "slack"


def test_browser_meeting_ends_when_title_goes_even_if_tab_keeps_mic():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome")], ["Meet - x"], 0.0).kind == "start"
    d.update([use("chrome")], ["Inbox - Gmail"], 2.0)
    ev = d.update([use("chrome")], ["Inbox - Gmail"], 22.0)
    assert ev.kind == "end" and ev.app == "chrome"


def test_any_version_in_use_counts():
    # slack keeps one ConsentStore entry per app version: in use if ANY is
    uses = uses_from_entries([("C:#Users#E#AppData#Local#slack#app-4.51.191#slack.exe", 5, 9, True),
                              ("C:#Users#E#AppData#Local#slack#app-4.52.162#slack.exe", 7, 0, True)])
    assert [u.app for u in uses if u.in_use] == ["slack"]
    assert Detector(debounce_polls=1).update(uses, [], 0.0).app == "slack"


def test_parse_nonpackaged_path():
    assert app_from_nonpackaged("C:#Program Files#Slack#slack.exe") == "slack"
    assert app_from_nonpackaged("C:#Users#alex#AppData#Local#WisprFlow#app-1.5.433#Wispr Flow.exe") == "wispr flow"


def test_parse_packaged_name():
    assert app_from_packaged("MSTeams_8wekyb3d8bbwe") == "msteams"
    assert app_from_packaged("5319275A.WhatsAppDesktop_cv1g1gvanyjgm") == "whatsappdesktop"
    assert app_from_packaged("com.notion.app.desktop.notion_87smfmv0eebam") == "notion"


def test_whatsapp_desktop_counts_as_call_app():
    assert Detector(debounce_polls=1).update([use("whatsappdesktop")], [], 0.0).app == "whatsappdesktop"


def test_in_use_rule():
    uses = uses_from_entries([("MSTeams_8wekyb3d8bbwe", 5, 0, False), ("Claude_pzs8sxrjxfjjc", 0, 0, False),
                              ("C:#x#zoom.exe", 5, 6, True)])
    by = {u.app: u.in_use for u in uses}
    assert by == {"msteams": True, "claude": False, "zoom": False}


def test_start_needs_two_polls_by_default():
    d = Detector()
    assert d.update([use("telegram")], [], 0.0) is None  # a voice-note blip
    assert d.update([use("telegram", False)], [], 2.0) is None
    assert d.update([use("msteams")], [], 4.0) is None
    ev = d.update([use("msteams")], [], 6.0)
    assert ev.kind == "start" and ev.app == "msteams" and ev.at == 6.0


def test_meeting_title_only_counts_in_a_browser_window():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome")], [("Notes: Zoom with Anna", "notepad")], 0.0) is None
    ev = d.update([use("chrome")], [("Meet - abc - Google Chrome", "chrome")], 2.0)
    assert ev.kind == "start" and ev.app == "chrome"


def test_stale_desktop_entry_ignored_when_app_not_running():
    stale = MicUse(app="slack", in_use=True, start=1, stop=0, nonpackaged=True)
    d = Detector(debounce_polls=1)
    assert d.update([stale], [], 0.0, running={"chrome", "explorer"}) is None
    assert d.update([stale], [], 2.0, running={"slack"}).app == "slack"


def test_packaged_entries_not_checked_against_processes():
    # MSTeams' package family name is not its exe name (ms-teams.exe): never drop it
    d = Detector(debounce_polls=1)
    assert d.update([use("msteams")], [], 0.0, running={"explorer"}).app == "msteams"


def test_uses_from_entries_marks_nonpackaged():
    uses = {u.app: u for u in uses_from_entries([("MSTeams_8wekyb3d8bbwe", 5, 0, False), ("C:#x#zoom.exe", 5, 0, True)])}
    assert uses["zoom"].nonpackaged and not uses["msteams"].nonpackaged


def test_meet_name_from_the_tab_title():
    """dictado-4ar: no calendar link, the Meet tab still says which meeting it is."""
    from ecoscribe.detect import meet_name
    assert meet_name([("Meet - Sprint retro, week 41 - Google Chrome", "chrome")]) == "Sprint retro, week 41"
    assert meet_name([("Inbox - Google Chrome", "chrome"), ("Meet - Ana / Johan 1:1 - Google Chrome", "chrome")]) == "Ana / Johan 1:1"
    assert meet_name([("Meet – Design review — Mozilla Firefox", "firefox")]) == "Design review"
    assert meet_name([("Meet - Planning and 2 more pages - Personal - Microsoft​ Edge", "msedge")]) == "Planning"
    assert meet_name(["(1) Meet - Budget check"]) == "Budget check"  # bare titles, macOS without the suffix


def test_meet_name_without_chromes_tab_state():
    """In a live call Chrome adds the tab's state to the title, before the browser's name (or alone on the Mac)."""
    from ecoscribe.detect import meet_name
    for state in ("Camera and microphone recording", "Camera recording", "Microphone recording", "Audio playing",
                  "Audio muted", "Sharing this tab", "Sharing this window", "Sharing this screen", "Network error"):
        assert meet_name([(f"Meet - Sprint retro - {state} - Google Chrome", "chrome")]) == "Sprint retro", state
        assert meet_name([f"Meet - Sprint retro - {state}"]) == "Sprint retro", state


def test_meet_name_none_without_a_named_meet_tab():
    from ecoscribe.detect import meet_name
    assert meet_name([("Meet - abc-defg-hij - Google Chrome", "chrome")]) is None  # an instant meeting
    assert meet_name([("Google Meet - Google Chrome", "chrome"), ("Calendar - Google Chrome", "chrome")]) is None
    assert meet_name([("Meet - Sprint retro | Microsoft Teams", "ms-teams")]) is None  # not a browser
    assert meet_name([]) is None


# ---------- why (not) a call: explain, the detector log line, the probe (dictado-nhn) ----------
from ecoscribe import detect as _d  # noqa: E402


def talk(app):
    return MicUse(app=app, in_use=True, start=1, stop=0, talking=True)


def test_explain_says_why_each_app_on_the_mic_is_or_is_not_a_call():
    lines = _d.explain([use("zoom"), use("chrome"), use("ecoscribe"), use("notes"), use("slack", False)],
                       [("Inbox - Mail", "chrome")])
    assert lines == ["chrome: browser on the mic, plays no sound and no meeting tab title -> not a call",
                     "ecoscribe: Ecoscribe itself on the mic -> ignored",
                     "notes: on the mic, not a known call app or browser -> not a call",
                     "zoom: call app on the mic -> a call"]
    assert _d.explain([talk("chrome")], []) == ["chrome: browser on the mic and playing sound -> a call"]
    assert _d.explain([use("chrome")], [("Meet - abc-defg-hij", "chrome")]) == [
        "chrome: browser on the mic with a meeting tab title in a window -> a call"]
    assert _d.explain([], []) == ["no app holds the mic"]


def test_signal_summary_has_app_names_and_flags_never_a_title():
    titles = [("Meet - Secret project review", "chrome")]
    s = _d.signal_summary([talk("chrome"), use("slack"), use("ecoscribe")], titles,
                          health={"mic_api": "ok", "accessibility": "not granted"})
    assert s == "mic=chrome+sound,slack title=yes accessibility=not-granted"
    assert "Secret" not in s
    assert _d.signal_summary([], [], health={"mic_api": "unavailable"}) == "mic=- mic_api=unavailable"
    assert _d.signal_summary([use("msteams")], titles) == "mic=msteams"  # the title flag only with a browser on the mic


def test_probe_prints_the_signals_and_the_verdict_without_titles():
    frames = iter([[], [use("zoom")], [use("zoom")], [use("zoom")]])
    t = [0.0]
    lines = []

    def tick(_s):
        t[0] += 1.0
    rc = _d.probe(seconds=3, interval=1, out=lines.append, read_mic=lambda: next(frames),
                  read_titles=lambda: [("Meet - Secret project review", "chrome")], read_running=lambda: None,
                  read_front=lambda: "zoom", read_health=lambda: {"accessibility": "not granted"},
                  clock=lambda: t[0], sleep=tick)
    text = "\n".join(lines)
    assert rc == 0
    assert "mic: nobody" in text and "mic: zoom" in text and "front: zoom" in text
    assert "zoom: call app on the mic -> a call" in text
    assert "=> Ecoscribe would now offer to record the zoom call" in text
    assert "accessibility: not granted" in text and "terminal's grant" in text
    assert "Secret" not in text


def test_probe_survives_a_broken_reader():
    t = [0.0]
    lines = []

    def boom():
        raise PermissionError("no access")

    def tick(_s):
        t[0] += 1.0
    _d.probe(seconds=1, out=lines.append, read_mic=lambda: [use("msteams")], read_titles=boom,
             read_running=lambda: None, read_front=lambda: "", read_health=lambda: {}, clock=lambda: t[0], sleep=tick)
    text = "\n".join(lines)
    assert "! window titles failed: PermissionError: no access" in text
    assert "msteams: call app on the mic -> a call" in text


def test_probe_command_line(monkeypatch):
    seen = {}
    monkeypatch.setattr(_d, "probe", lambda seconds, interval, raw, out: seen.update(s=seconds, raw=raw) or 0)
    assert _d.main(["--seconds", "5", "--raw"]) == 0 and seen == {"s": 5.0, "raw": True}
