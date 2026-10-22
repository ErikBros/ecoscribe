"""The Ecoscribe window (its own process: Ecoscribe.exe --ui).

pywebview + WebView2 renders ecoscribe/web/. The Api below is what the page calls
(window.pywebview.api.*). It talks to the background app only through files
(config.toml, status.json, history.jsonl) and the reload event, so a crash here
can never affect dictation. Non-method attributes are _private on purpose:
pywebview exposes every public attribute of the API object to JavaScript.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, commands, config, diarize, hotkeys, export, ipc, meetings, paths, search, sessions, status, tomlw
from .languages import ALL as ALL_LANGS, BASE as BASE_LANGS, available, meeting_options, valid_extra, valid_meeting_lang
from .routing import LANG_NAMES

log = logging.getLogger(__name__)
HOTKEYS = [("rctrl", "Right Ctrl (recommended)"), ("scrolllock", "Scroll Lock"), ("pause", "Pause")] + \
          [(f"f{n}", f"F{n}") for n in range(13, 25)]
if sys.platform == "darwin":  # a MacBook has no Right Ctrl (decision D2: Right Command)
    HOTKEYS = [("rcmd", "Right Command (recommended)"), ("fn", "Fn / Globe"),
               ("rctrl", "Right Control (external keyboard)")] + [(f"f{n}", f"F{n}") for n in range(13, 20)]
MEET_MODES = [("prompt", "Ask"), ("auto", "Start by itself"), ("off", "Don't detect")]
# seconds the call app is off the mic before its meeting stops; no 20: config.load reads a saved 20 as 10 (dictado-mtc)
MEET_ENDS = [(5, "5 seconds"), (10, "10 seconds"), (15, "15 seconds"), (30, "30 seconds"), (60, "1 minute"), (120, "2 minutes")]


def _voice_command_list() -> list[dict]:
    """Settings > Voice commands > See all commands (t0u.38): from the table the matcher uses."""
    from .text import VOICE_COMMANDS
    return [{"what": what, **{lang: ", ".join(f'"{p}"' for p in ps) for lang, ps in langs.items()}}
            for _, what, langs in VOICE_COMMANDS]


def _correction_list() -> list[dict]:
    """Settings > Fix it when you correct yourself > See all phrases (dictado-bd6): the tables the rules use."""
    from .corrections import SCRATCH, TRIGGERS
    return [{"what": what, **{lang: ", ".join(f'"{p}"' for p in ps) for lang, ps in table.items()}}
            for what, table in (("Drops the sentence before it", SCRATCH), ("Claude applies the correction", TRIGGERS))]


# Kept for older callers: the built-in dictation languages (dictado-ehs; added ones come from the config).
LANGUAGES = [("en", "English"), ("sv", "Swedish")]


def parse_languages(value, extra=()) -> list[str]:
    """'sv,en' -> ['en', 'sv']: any mix of the available languages (English, Swedish and the
    added ones, dictado-ehs), in that order."""
    from .languages import available
    avail = available(extra)
    got = {x.strip() for x in str(value).split(",") if x.strip()}
    if not got or got - set(avail):
        raise ValueError("languages")
    return [c for c in avail if c in got]


def save_dictation_languages(config_path: Path, value) -> list[str]:
    """The tray's "Dictation language >": save it; the caller then signals the reload."""
    c = config.load(Path(config_path))
    c.whisper.languages = parse_languages(value, c.whisper.extra_languages)
    tomlw.save(c, Path(config_path))
    return c.whisper.languages


def pretty_mic(name: str) -> str:
    """'Microphone (Anker PowerConf C20' -> 'Anker PowerConf C20' (MME cuts names at 31 chars)."""
    m = re.match(r"^[^(]*\((.+?)\)?$", name or "")
    return m.group(1).strip() if m else (name or "")


if sys.platform == "darwin":  # ecoscribe/platform/macos/desktop.py + procs.py
    from .platform.macos.desktop import DEFAULT_MIC_LABEL, WEBVIEW_GUI
    from .platform.macos.desktop import input_names as _mme_input_names
    from .platform.macos.desktop import reveal as _reveal
    from .platform.macos.desktop import startfile as _startfile
    from .platform.macos.procs import alive as _pid_alive
else:  # ecoscribe/platform/windows/desktop.py + procs.py
    from .platform.windows.desktop import DEFAULT_MIC_LABEL, WEBVIEW_GUI
    from .platform.windows.desktop import input_names as _mme_input_names
    from .platform.windows.desktop import reveal as _reveal
    from .platform.windows.desktop import startfile as _startfile
    from .platform.windows.procs import alive as _pid_alive


def _gpu() -> str:
    """The NVIDIA card and driver, and the newest CUDA the driver runs (Ecoscribe needs 12): debug info."""
    from . import gpu
    if sys.platform != "win32":
        return "n/a"
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    cuda = gpu.driver_cuda()
    return f"{out or 'no NVIDIA card found'}; driver runs CUDA {gpu._version(cuda) if cuda else 'none'}"


def _platform() -> str:
    import platform
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
    return f"Windows {platform.release()} ({platform.version()})"


def _copy(text: str) -> None:
    from .deliver import set_clipboard_text
    set_clipboard_text(text, private=False)


MAILTO_MAX = 1800  # longer mailto: links get cut by Windows and some mail programs: copy the transcript instead


def _open_url(url: str) -> None:
    """Hand a link to the system: mailto: opens a draft in the user's mail program, https: the browser."""
    if sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", url])
    else:
        os.startfile(url)  # noqa: S606  (the shell's handler for mailto:)


class Api:
    def __init__(self, data_dir: Path | None = None, config_path: Path | None = None, startup_mod=None,
                 signal_reload=None, list_mic_names=None, copy=None, send_command=None, downloads=None,
                 page: str | None = None, open_url=None):
        from . import startup as _startup
        self._page = page
        self._data_dir = Path(data_dir) if data_dir else paths.data_dir()
        self._config_path = Path(config_path) if config_path else paths.config_path()
        self._startup = startup_mod or _startup
        self._signal = signal_reload or ipc.signal_reload
        self._list_mic_names = list_mic_names or _mme_input_names
        self._copy = copy or _copy
        self._commands = send_command or commands.send
        self._downloads = Path(downloads) if downloads else Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"
        self._mic = None  # (recorder, gate) during the mic check
        self._open_url = open_url or _open_url
        import threading
        self._mic_lock = threading.Lock()

    def initial_page(self) -> str | None:
        """The page to open on. Not a ?page= query: WebView2 on Windows takes index.html?page=x for a
        missing file ("File not found"), which is how the first-run window used to open."""
        return self._page

    def take_page(self) -> str | None:
        """A page another process asked this open window to show (ipc.open_ui), once."""
        p = self._data_dir / ipc.PAGE_FILE
        try:
            page = p.read_text(encoding="utf-8").strip()
            p.unlink()
        except OSError:
            return None
        return page or None

    # ---------------- status ----------------
    def get_status(self) -> dict:
        s = status.read(self._data_dir / "status.json") or {}
        alive = _pid_alive(s.get("pid"))
        if not alive:
            s = {"state": "stopped"}
        s["alive"] = alive
        s["version"] = __version__
        return s

    def start_app(self) -> dict:
        if self.get_status()["alive"]:
            return {"ok": True}
        ipc.spawn([])
        return {"ok": True}

    def restart_app(self) -> dict:
        return {"ok": bool(self._signal())}

    # ---------------- settings ----------------
    def _load(self) -> config.Config:
        try:
            return config.load(self._config_path)
        except Exception:
            log.exception("bad config, showing defaults")
            return config.Config()

    def get_settings(self) -> dict:
        c = self._load()
        try:
            labels = self._list_mic_names()
        except Exception:
            log.exception("could not list mics")
            labels = []
        mics = [{"value": "", "label": DEFAULT_MIC_LABEL}] + [{"value": n, "label": pretty_mic(n)} for n in labels]
        cur = c.audio.device
        if cur and cur not in [m["value"] for m in mics]:
            match = next((m for m in mics[1:] if cur.lower() in m["value"].lower()), None)
            if match:
                match["value"] = cur  # keep the saved substring so nothing changes on save
            else:
                mics.append({"value": cur, "label": f"{cur} (not connected)"})
        return {
            "values": {
                "hotkey": c.hotkey.key, "hotkey_label": hotkeys.label(c.hotkey.key), "mic": cur, "languages": ",".join(c.whisper.languages),
                "sounds": c.ui.sounds, "overlay": c.ui.overlay, "live_text": c.ui.live_text, "insights": c.ui.insights, "speech_feedback": c.ui.speech_feedback, "unmute": c.audio.unmute_while_recording,
                "startup": self._startup.is_enabled(),
                "meet_mode": c.meetings.mode, "meet_end": str(int(c.meetings.grace_s)), "meet_lang": c.meetings.default_lang, "on_demand": c.whisper.on_demand,
                "speakers": c.meetings.speakers, "vocabulary": "\n".join(c.text.vocabulary),
                "voice_commands": c.text.voice_commands,
                "self_corrections": c.text.self_corrections, "command_mode": c.text.command_mode,  # dictado-bd6
                "screen_names": c.text.screen_names,
                "hold_to_talk": c.hotkey.hold_to_talk, "numpad_enter": c.hotkey.numpad_enter, "voice_memory": c.meetings.voice_memory,
                "calendar_url": c.meetings.calendar_url, "my_name": c.meetings.my_name, "debug_log": c.ui.debug_log,
                "update_check": c.ui.update_check,
                "export_dir": str(self._export_dir()), "export_default": not c.ui.export_dir,
                "extra_languages": list(c.whisper.extra_languages),
                "snippets": [{"trigger": k, "text": v} for k, v in c.text.snippets.items()],
                "replacements": [{"heard": k, "write": v} for k, v in c.text.replacements.items()],
            },
            "speakers_addon": diarize.addon_exe().is_file(),
            "voice_command_list": _voice_command_list(),
            "correction_list": _correction_list(),
            "options": {
                "hotkeys": [{"value": v, "label": l} for v, l in HOTKEYS],
                "mics": mics,
                "languages": [{"value": v, "label": ALL_LANGS[v]} for v in available(c.whisper.extra_languages)],
                "all_languages": sorted(({"value": v, "label": l} for v, l in ALL_LANGS.items()
                                         if v not in available(c.whisper.extra_languages)), key=lambda o: o["label"]),
                "base_languages": list(BASE_LANGS),
                "meet_modes": [{"value": v, "label": l} for v, l in MEET_MODES],
                "meet_ends": [{"value": str(v), "label": l} for v, l in MEET_ENDS]
                + ([] if int(c.meetings.grace_s) in dict(MEET_ENDS)  # a value typed into config.toml stays selectable
                   else [{"value": str(int(c.meetings.grace_s)), "label": f"{int(c.meetings.grace_s)} seconds"}]),
                "meet_langs": [{"value": v, "label": l} for v, l in meeting_options(available(c.whisper.extra_languages))],
            },
            "can_startup": self._startup.app_command() is not None,
        }

    def check_hotkey(self, value: str) -> dict:
        """The Settings recorder asks before saving: is this shortcut allowed, and how to show it."""
        try:
            k = hotkeys.normalize(value)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "value": k, "label": hotkeys.label(k)}

    def save_settings(self, values: dict) -> dict:
        c = self._load()
        try:
            if "hotkey" in values:
                try:
                    c.hotkey.key = hotkeys.normalize(values["hotkey"])
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
            if "mic" in values:
                c.audio.device = str(values["mic"])
            if "vocabulary" in values:  # one word or name per line; blanks and repeats dropped
                seen, words = set(), []
                for line in str(values["vocabulary"]).splitlines():
                    w = " ".join(line.split())[:60]
                    if w and w.lower() not in seen:
                        seen.add(w.lower())
                        words.append(w)
                c.text.vocabulary = words[:100]
            if "snippets" in values:  # [{trigger, text}]; trigger lower-cased, blanks and repeats dropped
                table = {}
                for row in values["snippets"] or []:
                    k = " ".join(str(row.get("trigger", "")).lower().split())[:60]
                    if k and k not in table and str(row.get("text", "")).strip():
                        table[k] = str(row["text"])[:2000]
                c.text.snippets = dict(list(table.items())[:50])
            if "replacements" in values:  # [{heard, write}] (dictado-b7u); heard lower-cased, blanks and repeats dropped
                table = {}
                for row in values["replacements"] or []:
                    k = " ".join(str(row.get("heard", "")).lower().split())[:60]
                    v = " ".join(str(row.get("write", "")).split())[:200]
                    if k and v and k not in table:
                        table[k] = v
                c.text.replacements = dict(list(table.items())[:200])
            if "extra_languages" in values:  # dictado-ehs: Add a language / remove one
                c.whisper.extra_languages = valid_extra(values["extra_languages"])
                avail = available(c.whisper.extra_languages)
                c.whisper.languages = [x for x in c.whisper.languages if x in avail] or ["en"]
                if not valid_meeting_lang(c.meetings.default_lang) or any(
                        x not in avail for x in c.meetings.default_lang.split(",") if x != "auto"):
                    c.meetings.default_lang = "sv"
            if "languages" in values:
                c.whisper.languages = parse_languages(values["languages"], c.whisper.extra_languages)
            if "meet_mode" in values:
                if values["meet_mode"] not in dict(MEET_MODES):
                    raise ValueError("meet_mode")
                c.meetings.mode = values["meet_mode"]
            if "meet_end" in values:
                end = int(str(values["meet_end"]))  # ValueError on junk
                if end != int(c.meetings.grace_s) and end not in dict(MEET_ENDS):
                    raise ValueError("meet_end")
                c.meetings.grace_s = end
            if "calendar_url" in values:
                from .calendar_ics import valid_url
                url = str(values["calendar_url"] or "").strip()
                if url and not valid_url(url):
                    return {"ok": False, "error": "That isn't a calendar link: paste the secret address in iCal format "
                                                  "(it starts with https://)."}
                c.meetings.calendar_url = url
            if "my_name" in values:
                c.meetings.my_name = " ".join(str(values["my_name"] or "").split())[:40]
            if "meet_lang" in values:
                if not valid_meeting_lang(values["meet_lang"]):
                    raise ValueError("meet_lang")
                c.meetings.default_lang = values["meet_lang"]
            for key, (section, name) in {"sounds": ("ui", "sounds"), "overlay": ("ui", "overlay"), "live_text": ("ui", "live_text"), "insights": ("ui", "insights"), "speech_feedback": ("ui", "speech_feedback"),
                                         "unmute": ("audio", "unmute_while_recording"),
                                         "on_demand": ("whisper", "on_demand"),
                                         "speakers": ("meetings", "speakers"),
                                         "voice_commands": ("text", "voice_commands"),
                                         "self_corrections": ("text", "self_corrections"), "command_mode": ("text", "command_mode"),
                                         "screen_names": ("text", "screen_names"),
                                         "hold_to_talk": ("hotkey", "hold_to_talk"), "numpad_enter": ("hotkey", "numpad_enter"),
                                         "voice_memory": ("meetings", "voice_memory"),
                                         "debug_log": ("ui", "debug_log"), "update_check": ("ui", "update_check")}.items():
                if key in values:
                    setattr(getattr(c, section), name, bool(values[key]))
        except ValueError as e:
            return {"ok": False, "error": f"invalid value: {e}"}
        tomlw.save(c, self._config_path)
        if "startup" in values:
            cmd = self._startup.app_command()
            if values["startup"] and cmd:
                self._startup.enable(cmd)
            elif not values["startup"]:
                self._startup.disable()
        restarting = bool(self._signal())
        return {"ok": True, "restarting": restarting}

    # ---------------- mic check ----------------
    def mic_test_start(self, device: str | None = None) -> dict:
        # pywebview calls each API method on its own thread: serialize, never leak a gate
        with self._mic_lock:
            self._mic_stop_locked()
            from .audio import Recorder
            from .micgate import MicGate
            c = self._load()
            if device is not None:
                c.audio.device = device
            gate = MicGate(c.audio.device, c.audio.unmute_volume, enabled=c.audio.unmute_while_recording)
            rec = Recorder(c.audio)
            try:
                gate.open()
                rec.open()
                rec.begin()
            except Exception as e:
                log.exception("mic test could not start")
                for undo in (rec.abort, rec.close, gate.restore):
                    try:
                        undo()
                    except Exception:
                        pass
                return {"device": "", "fell_back": False, "error": str(e)}
            self._mic = (rec, gate)
            return {"device": rec.device_name, "fell_back": rec.fell_back}

    def mic_test_level(self) -> float:
        m = self._mic
        return m[0].level() if m else 0.0

    def mic_test_stop(self) -> dict:
        with self._mic_lock:
            self._mic_stop_locked()
        return {"ok": True}

    def _mic_stop_locked(self) -> None:
        if self._mic:
            rec, gate = self._mic
            self._mic = None
            try:
                rec.abort()
                rec.close()
            finally:
                gate.restore()

    # ---------------- history ----------------
    def _history_rows(self) -> list[dict]:
        rows = []
        try:
            with open(self._data_dir / "history.jsonl", encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and r.get("text"):
                        rows.append(r)
        except FileNotFoundError:
            pass
        return rows

    def get_history(self, limit: int = 200, query: str = "") -> dict:
        rows = self._history_rows()
        today = time.strftime("%Y-%m-%d")
        words = lambda r: len(re.findall(r"\w+", r["text"]))  # noqa: E731
        stats = {"total": len(rows), "total_words": sum(map(words, rows)),
                 "today_words": sum(words(r) for r in rows if str(r.get("ts", "")).startswith(today))}
        q = query.strip().lower()
        items = [r for r in reversed(rows) if not q or q in r["text"].lower()][:limit]
        kept = {f.stem for f in (self._data_dir / "recent").glob("*.wav")}  # Retry only where the audio still is
        items = [{**r, "audio": r.get("id") in kept} for r in items]
        return {"items": items, "stats": stats}

    # ---------------- insights (dictado-3je) ----------------
    def get_insights(self, days: int | None = None) -> dict:
        from . import coach, insights
        days = int(days) if days else None
        c = self._load()
        out = insights.compute(self._history_rows(), list(c.text.vocabulary), days, typing_wpm=c.ui.typing_wpm)
        out["meetings"] = coach.meetings_summary(self._recorded_meetings(), days=days)
        return out

    def _recorded_meetings(self) -> list[dict]:
        """dictado-9jc.5: recorded meetings with their Me / Others segments (imports have no Me)."""
        out = []
        for m in sessions.list_sessions(self._root()):
            if m.get("source") != "meeting":
                continue
            try:
                segs = json.loads((Path(m["dir"]) / "transcript.json").read_text(encoding="utf-8"))["segments"]
            except (OSError, ValueError, KeyError):
                continue
            out.append({"created": m.get("created"), "title": m.get("title"), "lang": m.get("lang"), "segments": segs})
        return out

    def add_word(self, word: str) -> dict:
        """Insights > Words to add: one name into Your words (restarts the background app like Save)."""
        w = " ".join(str(word or "").split())[:60]
        if not w:
            return {"ok": False, "error": "empty"}
        c = self._load()
        if w.lower() not in {v.lower() for v in c.text.vocabulary}:
            c.text.vocabulary.append(w)
            tomlw.save(c, self._config_path)
            self._signal()
        return {"ok": True, "vocabulary": list(c.text.vocabulary)}

    def set_typing_wpm(self, wpm) -> dict:
        """Insights > your typing speed (dictado-d8e): only the window reads it, so no restart."""
        try:
            n = max(10, min(200, int(wpm)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "A number of words a minute, like 60."}
        c = self._load()
        c.ui.typing_wpm = n
        tomlw.save(c, self._config_path)
        return {"ok": True, "typing_wpm": n}

    def insights_for_claude(self) -> dict:
        from . import insights
        text = insights.week_for_claude(self._history_rows())
        self._copy(text)
        return {"ok": True, "chars": len(text)}

    def copy_text(self, text: str) -> dict:
        self._copy(text)
        return {"ok": True}

    def delete_dictation(self, rid: str = "", ts: str = "") -> dict:
        """History > Delete (dictado-vfo): the background app owns history.jsonl, so it deletes; when
        it isn't running nothing else writes the file and the window does it."""
        from . import commands, histfile
        out = self._send("delete_dictation", {"id": rid, "ts": ts})
        if not out.get("ok") and out.get("error") in (commands.NOT_RUNNING, "Dictation isn't running"):
            return {"ok": True, "gone": histfile.delete(self._data_dir / "history.jsonl", rid or None, ts or None)}
        return out

    def edit_dictation(self, rid: str = "", ts: str = "", text: str = "") -> dict:
        """History > Edit (dictado-1ph): saves the new text (the background app owns history.jsonl, like
        Delete) and says what the change could teach: a name for Your words, or a Replace rule."""
        from . import commands, histfile, learn
        text = str(text or "").strip()
        if not text:
            return {"ok": False, "error": "The text is empty: use Delete to remove the dictation."}
        old = next((r for r in self._history_rows()
                    if (rid and r.get("id") == rid) or (not rid and not r.get("id") and r.get("ts") == ts)), None)
        if old is None:
            return {"ok": False, "error": "That dictation isn't in the history any more."}
        out = self._send("edit_dictation", {"id": rid, "ts": ts, "text": text})
        if not out.get("ok") and out.get("error") in (commands.NOT_RUNNING, "Dictation isn't running"):
            out = {"ok": histfile.edit(self._data_dir / "history.jsonl", rid or None, ts or None, text)}
        if not out.get("ok"):
            return {"ok": False, "error": out.get("error") or "Couldn't save it."}
        c = self._load()
        return {"ok": True, "text": text, "learn": learn.suggest(old.get("text", ""), text, c.text.vocabulary, c.text.replacements)}

    def learn_word(self, kind: str, write: str, heard: str = "") -> dict:
        """History > Edit > Keep (dictado-1ph): a name into Your words, or a Replace rule from what was heard."""
        if kind == "word":
            return self.add_word(write)
        heard, write = " ".join(str(heard or "").lower().split())[:60], " ".join(str(write or "").split())[:200]  # like Settings
        if kind != "replace" or not heard or not write:
            return {"ok": False, "error": "nothing to learn"}
        c = self._load()
        c.text.replacements[heard] = write
        tomlw.save(c, self._config_path)
        self._signal()
        return {"ok": True}

    def clear_history(self) -> dict:
        p = self._data_dir / "history.jsonl"
        if p.exists():
            p.replace(self._data_dir / f"history-{time.strftime('%Y%m%d-%H%M%S')}.bak")
        return {"ok": True}

    # ---------------- reuniones ----------------
    def _root(self) -> Path:
        return sessions.root_dir(self._load().transcribe.root)

    def _session(self, name: str) -> Path:
        d = self._root() / Path(str(name)).name  # a bare folder name: never a path out of the root
        if not (d / sessions.META).is_file():
            raise FileNotFoundError(name)
        return d

    def _me(self) -> str:
        return self._load().meetings.my_name

    @staticmethod
    def _row(m: dict, me: str = "") -> dict:
        d = Path(m["dir"])
        prog = {}
        try:
            prog = json.loads((d / "progress.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return {"name": d.name, "title": m.get("title", ""), "lang": m.get("lang"),
                "lang_name": LANG_NAMES.get(m.get("lang_used") or m.get("lang"), m.get("lang") or ""),
                "duration_s": m.get("duration_s") or m.get("recorded_s"), "status": m.get("status"),
                "source": m.get("source"), "created": m.get("created"), "error": m.get("error"),
                "pct": prog.get("pct"), "slow": m.get("slow", False),
                "speakers": m.get("speakers"), "speaker_names": {**({"Me": me} if me else {}), **(m.get("speaker_names") or {})},
                "recognised": [(m.get("speaker_names") or {}).get(x, x) for x in m.get("speakers_recognised") or []],
                "people": list((m.get("calendar") or {}).get("attendees") or []), "app": m.get("app"),  # dictado-6oe.4
                "summary": m.get("summary")}  # dictado-nl5: running / done / failed, or None

    def list_sessions(self, query: str = "") -> dict:
        """The search box finds a title or anything said in the call, accents and case ignored (dictado-8h8)."""
        q = str(query or "").strip()
        me = self._me()
        rows = [self._row(m, me) for m in sessions.list_sessions(self._root())]
        if q:
            said = set()
            try:
                idx = search.open_index(self._root())
                try:
                    said = idx.session_ids(q)
                finally:
                    idx.close()
            except Exception:
                log.exception("meeting search failed; titles only")
            fq = search.fold(q)
            rows = [r for r in rows if fq in search.fold(r["title"]) or r["name"] in said]
        return {"items": rows, "state": self.meetings_state()}

    def get_session(self, name: str) -> dict:
        d = self._session(name)
        m = sessions.read_meta(d)
        m["dir"] = str(d)
        segs = []
        try:
            segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
        except (OSError, ValueError, KeyError):
            pass
        summ = None
        try:  # dictado-nl5: the checked summary, shown above the transcript
            from .summary import JSON
            summ = json.loads((d / JSON).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return {"session": self._row(m, self._me()), "segments": export.turns(segs),  # read in turns, like the .md
                "notes": export.read_notes(d), "summary": summ,
                "exports": [p.name for p in d.glob("transcript.*") if p.suffix in (".txt", ".md", ".srt")]}

    def get_live(self, name: str, since: int = 0) -> dict:
        """live.jsonl lines after the first `since`: a 2-hour meeting is never re-sent whole."""
        d = self._session(name)
        lines = []
        try:
            with open(d / "live.jsonl", encoding="utf-8") as f:
                for i, raw in enumerate(f):
                    if i < since:
                        continue
                    try:
                        lines.append(json.loads(raw))
                    except ValueError:
                        break  # the worker is writing this line right now
        except FileNotFoundError:
            pass
        m = sessions.read_meta(d)
        m["dir"] = str(d)
        return {"lines": lines, "next": int(since) + len(lines), "session": self._row(m, self._me()),
                "notes": export.read_notes(d)}

    # ---------------- Google Calendar (dictado-k19) ----------------
    _gcal_http = None  # tests swap in a fake Google

    def _gcal(self):
        from . import gcal
        return gcal.GoogleCalendar(self._data_dir, **({"http": self._gcal_http} if self._gcal_http else {}))

    def google_calendar(self) -> dict:
        g = self._gcal()
        return {"connected": g.connected, "client": g.client() is not None}

    def connect_google(self) -> dict:
        """Settings > Meetings > Connect Google Calendar: the browser asks the user once, then the
        background app restarts to read the calendar."""
        g = self._gcal()
        out = g.connect(self._open_url)
        if not out["ok"]:
            return {"ok": False, "error": {
                "no_client": "This copy of Ecoscribe has no Google sign-in set up yet.",
                "timeout": "No answer from Google in 3 minutes. Try again.",
                "denied": "Google didn't give access. If your work account blocks it, ask its admin to allow Ecoscribe.",
            }.get(out["error"], "Couldn't connect to Google. Try again.")}
        g.refresh(force=True)
        ev = g.lookup()
        self._signal()
        return {"ok": True, "today": len(g.today()), "now": ev.title if ev else None}

    def disconnect_google(self) -> dict:
        self._gcal().disconnect()
        self._signal()
        return {"ok": True}

    def _google_event(self, name: str, meta: dict) -> dict | None:
        """A meeting recorded without its invite: ask Google for the event at its start, keep it."""
        from datetime import datetime

        from .calendar_ics import meta_info
        g = self._gcal()
        if not g.connected or not meta.get("created"):
            return None
        try:
            ev = g.event_at(datetime.fromisoformat(str(meta["created"])).astimezone(), meta.get("app"))
        except Exception as e:
            log.warning("Google Calendar lookup for an older meeting failed (%s)", type(e).__name__)
            return None
        if ev is None:
            return None
        info = meta_info(ev)
        sessions.write_meta(self._session(name), calendar=info)
        return info

    def claude_app(self) -> dict:
        from . import claude_link
        return {"connected": claude_link.is_connected(claude_link.config_files()),
                "frozen": bool(getattr(sys, "frozen", False))}

    def connect_claude_app(self) -> dict:
        """Settings > Meetings > Claude app: add Ecoscribe's read-only MCP server to Claude desktop."""
        from . import claude_link
        if not getattr(sys, "frozen", False):
            return {"ok": False, "error": "Only from the installed Ecoscribe"}
        try:
            done = claude_link.connect(claude_link.config_files(), claude_link.server_entry())
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"Couldn't update Claude's settings: {e}"}
        return {"ok": True, "files": [str(f) for f in done]}

    _calendar_fetch = None  # tests swap in a fake download

    def test_calendar(self, url: str, now: str | None = None) -> dict:
        """Settings > Meetings > Calendar > Test: download the link now, say what it found."""
        from datetime import datetime

        from . import calendar_ics as cal
        if not cal.valid_url(url):
            return {"ok": False, "error": "Paste the secret address in iCal format first."}
        kw = {"fetch": self._calendar_fetch} if self._calendar_fetch else {}
        feed = cal.CalendarFeed(url, self._data_dir, **kw)
        if not feed.refresh(force=True):
            return {"ok": False, "error": "Couldn't read a calendar from that link. Check you copied the secret "
                                          "address in iCal format, and that you're online."}
        when = datetime.fromisoformat(now) if now else None
        ev = feed.lookup(when)
        return {"ok": True, "today": len(feed.today(when)), "now": ev.title if ev else None}

    def save_notes(self, name: str, text: str) -> dict:
        """Notes typed in the session view (t0u.30); empty removes the file."""
        d = self._session(name)
        text = str(text or "")[:50000]
        p = d / export.NOTES
        if text.strip():
            tmp = p.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, p)
        elif p.exists():
            p.unlink()
        return {"ok": True}

    def meetings_state(self) -> dict:
        st = meetings.read_state(self._data_dir)
        out = {"meeting": None, "job": None, "queue": [Path(q).name for q in st.get("queue", [])]}
        if st.get("meeting"):
            out["meeting"] = {**st["meeting"], "name": Path(st["meeting"]["dir"]).name}
        if st.get("job"):
            out["job"] = {**st["job"], "name": Path(st["job"]["dir"]).name}
        return out

    def start_meeting(self, lang: str = "") -> dict:
        return self._send("start_meeting", {"lang": lang} if lang else {})

    def set_meeting_lang(self, lang: str) -> dict:
        return self._send("set_meeting_lang", {"lang": lang})

    def stop_meeting(self) -> dict:
        return self._send("stop_meeting")

    def import_files(self, paths: list, lang: str = "auto") -> dict:
        paths = [str(p) for p in (paths or []) if str(p).strip()]
        if not paths:
            return {"ok": False, "error": "No files"}
        return self._send("import_files", {"paths": paths, "lang": lang or "auto"})

    def pick_files(self) -> dict:
        import webview
        kinds = ("Audio and video (*.mp3;*.m4a;*.wav;*.ogg;*.opus;*.flac;*.mp4;*.webm;*.mkv;*.mov)", "All files (*.*)")
        got = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=kinds)
        return {"paths": list(got or [])}

    def rename_session(self, name: str, title: str) -> dict:
        title = str(title or "").strip()
        if not title:
            return {"ok": False, "error": "The title can't be empty"}
        sessions.rename(self._session(name), title)
        return {"ok": True}

    def delete_session(self, name: str) -> dict:
        d = self._session(name)
        st = meetings.read_state(self._data_dir)
        busy = {Path(x["dir"]).name for x in (st.get(k) for k in ("meeting", "job", "next_meeting")) if x}
        busy |= {Path(q).name for q in st.get("queue", [])}
        if d.name in busy or sessions.read_meta(d).get("status") in meetings.ACTIVE:
            return {"ok": False, "error": "It's running: stop it before deleting it"}
        sessions.delete(d)
        return {"ok": True}

    def open_folder(self, name: str) -> dict:
        _startfile(str(self._session(name)))
        return {"ok": True}

    def rename_speaker(self, name: str, label: str, new: str) -> dict:
        """Name a speaker of one session ("Speaker 2" -> "Mamá"); empty = back to the label."""
        d = self._session(name)
        try:
            segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
        except (OSError, ValueError, KeyError):
            segs = []
        label = str(label)
        if label not in {s.get("speaker") for s in segs} or label in ("", "None"):
            return {"ok": False, "error": "No such speaker in this session"}
        names = dict(sessions.read_meta(d).get("speaker_names") or {})
        new = " ".join(str(new or "").split())[:40]
        into = next((x for x in dict.fromkeys(s.get("speaker") for s in segs)
                     if x and x != label and new and new.lower() in (str(x).lower(), str(names.get(x, "")).lower())), None)
        if into:  # dictado-gk9: the same name as another speaker = one person: merge into that one
            for s in segs:
                if s.get("speaker") == label:
                    s["speaker"] = into
            tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
            tr["segments"] = segs
            sessions._write_json(d / "transcript.json", tr)
            names.pop(label, None)
            sessions.write_meta(d, speaker_names=names)
            export.write_all(d, self._me())
            return {"ok": True, "names": names, "merged": into}
        if new and new != label:
            names[label] = new
        else:
            names.pop(label, None)
        sessions.write_meta(d, speaker_names=names)
        export.write_all(d, self._me())
        if new and new != label and self._load().meetings.voice_memory:
            try:  # t0u.32: this voice is `new` from now on, in later calls too
                emb = json.loads((d / "voices.json").read_text(encoding="utf-8")).get(label)
                if emb:
                    from . import voices
                    voices.learn(self._data_dir / "voices.json", new, emb)
            except (OSError, ValueError):
                pass
        return {"ok": True, "names": names}

    def voices_info(self) -> dict:
        from . import voices
        n = voices.names(self._data_dir / "voices.json")
        return {"count": len(n), "names": n, "on": self._load().meetings.voice_memory}

    def forget_voices(self) -> dict:
        from . import voices
        voices.forget(self._data_dir / "voices.json")
        return {"ok": True}

    def copy_transcript(self, name: str, kind: str = "text") -> dict:
        s = self.get_session(name)
        meta = sessions.read_meta(self._session(name))
        text = export.for_claude(meta, s["segments"], s["notes"], self._me()) if kind == "claude" \
            else export.summary_prompt(meta, s["segments"], s["notes"], self._me()) if kind == "summary" else export.to_txt(s["segments"])
        self._copy(text)
        return {"ok": True, "chars": len(text)}

    def email_participants(self, name: str) -> dict:
        """Meetings > Email to participants (dictado-fnw): a draft in the user's own mail program,
        To: the invite's guests, the transcript in the body when it fits, else copied to paste in.
        Ecoscribe sends nothing itself."""
        from urllib.parse import quote
        s = self.get_session(name)
        meta = sessions.read_meta(self._session(name))
        info = meta.get("calendar") or {}
        if not info.get("emails") and meta.get("source") == "meeting":
            info = self._google_event(name, meta) or info
        to = [e for e in info.get("emails") or [] if "@" in e]
        title = info.get("title") or meta.get("title") or "our meeting"
        day = str(meta.get("created") or "")[:10]
        transcript = export.to_txt(s["segments"]).strip()
        note = ("Hi,\n\nHere's the transcript of our call. It was made automatically by Ecoscribe from a "
                "recording, so expect some mistakes.\n\n")
        subject = f"Transcript: {title}" + (f" ({day})" if day else "")

        def url(body: str) -> str:
            return (f"mailto:{','.join(to)}?subject={quote(subject)}&body={quote(body)}")
        full = url(note + transcript + "\n")
        inline = len(full) <= MAILTO_MAX
        self._copy(transcript)
        self._open_url(full if inline else url(note + "(The transcript follows: paste it here.)\n"))
        return {"ok": True, "to": to, "inline": inline, "chars": len(transcript)}

    def save_export(self, name: str, fmt: str) -> dict:
        if fmt not in ("txt", "md", "srt"):
            return {"ok": False, "error": "formato"}
        d = self._session(name)
        src = d / f"transcript.{fmt}"
        if (d / "transcript.json").exists():
            export.write_all(d, self._me())  # fresh every time: a rename since the meeting must show in the file
        import shutil
        title = sessions.read_meta(d).get("title") or "transcript"
        out = self._export_dir()
        try:
            out.mkdir(parents=True, exist_ok=True)  # one click, no dialog (the user, 2026-10-05)
        except OSError:
            return {"ok": False, "error": f"Can't write to {out}: pick another folder in Settings › Meetings."}
        base = f"{d.name[:16]}_{sessions.slug(title)}"
        dest, n = out / f"{base}.{fmt}", 2
        while dest.exists():
            dest, n = out / f"{base}-{n}.{fmt}", n + 1
        shutil.copyfile(src, dest)
        self._last_export = dest
        return {"ok": True, "path": str(dest), "name": dest.name, "folder": out.name or str(out)}

    def _export_dir(self) -> Path:
        """Where Download puts files: the folder picked in Settings, else Downloads."""
        picked = self._load().ui.export_dir
        return Path(picked).expanduser() if picked else self._downloads

    def show_export(self, path: str) -> dict:
        """The toast's Open folder: the folder, the file selected. Only the file just saved."""
        last = getattr(self, "_last_export", None)
        if last is None or Path(path) != last or not last.exists():
            return {"ok": False, "error": "That file is gone."}
        _reveal(str(last))
        return {"ok": True}

    def pick_export_dir(self) -> dict:
        """Settings > Meetings > Downloads go to > Change: a folder dialog, saved at once."""
        import webview
        got = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER, directory=str(self._export_dir()))
        if not got:
            return {"ok": False}
        return self.set_export_dir(got[0] if isinstance(got, (list, tuple)) else got)

    def set_export_dir(self, path: str) -> dict:
        """Empty = back to Downloads. Only the window reads it, so no restart."""
        path = str(path or "").strip()
        if path and not Path(path).expanduser().is_dir():
            return {"ok": False, "error": "That folder doesn't exist."}
        c = self._load()
        c.ui.export_dir = path
        tomlw.save(c, self._config_path)
        return {"ok": True, "export_dir": str(self._export_dir()), "export_default": not path}

    def _send(self, cmd: str, args: dict | None = None, **kw) -> dict:
        return self._commands(self._data_dir, cmd, args, **kw)

    def retry_dictation(self, rid: str, lang: str = "") -> dict:
        """History > Retry (dictado-a2r): the background app transcribes the kept audio again."""
        return self._send("retry", {"id": rid, "lang": lang or None}, wait_s=120.0)

    # ---------------- misc ----------------
    # ---------- troubleshooting (t0u.37) ----------
    def crashes(self) -> dict:
        """Home: crashes the user hasn't dismissed, newest first; gave_up when the watchdog stopped."""
        from . import crash
        out = []
        for d in crash.unseen(self._data_dir, "user")[:5]:
            rep = (d / "report.md").read_text(encoding="utf-8", errors="replace")
            m = re.search(r"- Exit: (.*)", rep)
            out.append({"name": d.name, "when": d.name[:15].replace("_", " "), "exit": m.group(1) if m else "",
                        "gave_up": "stopped restarting" in rep})
        st = status.read(self._data_dir / "status.json") or {}
        return {"items": out, "gave_up": st.get("state") == "crashed"}

    def copy_crash_report(self, name: str) -> dict:
        from . import crash
        d = self._crash_dir(name)
        if d is None:
            return {"ok": False, "error": "Report not found"}
        self._copy(crash.for_claude(d))
        crash.mark_seen(d, "user")
        return {"ok": True}

    def dismiss_crash(self, name: str) -> dict:
        from . import crash
        d = self._crash_dir(name)
        if d is not None:
            crash.mark_seen(d, "user")
        return {"ok": True}

    def _crash_dir(self, name: str):
        from . import crash
        d = crash.crashes_dir(self._data_dir) / Path(str(name)).name
        return d if (d / "report.md").exists() else None

    def debug_info(self) -> str:
        """Settings > Troubleshooting > Copy debug info for Claude: everything to start debugging."""
        from . import __version__, crash
        d = self._data_dir

        def tail(name, n):
            p = d / name
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
            except OSError:
                return f"(no {name})"
            return "\n".join(lines)
        cfg = ""
        try:
            cfg = re.sub(r'(?m)^(calendar_url\s*=\s*).*$', r'\1"<removed>"',
                         self._config_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
        reps = crash.reports(d)[:5]
        live = sorted((crash.crashes_dir(d) / "live").glob("freeze-*.log")) if (crash.crashes_dir(d) / "live").exists() else []
        parts = [f"Ecoscribe debug info. Please find what's wrong. Data folder: {d}", "",
                 f"Version: {__version__}", f"Platform: {_platform()}", f"GPU: {_gpu()}", f"Status: {json.dumps(status.read(d / 'status.json') or {}, ensure_ascii=False)}", "",
                 "Recent crashes: " + (", ".join(p.name for p in reps) or "none"),
                 "Freezes recorded: " + (", ".join(p.name for p in live[-5:]) or "none"), "",
                 "## config.toml (calendar link removed)", "```", cfg.strip(), "```", ""]
        logs = (("ecoscribe.log", 200), ("engine-worker.log", 40), ("engine-worker-fault.log", 60),
                ("gpu-failed.json", 5), ("supervisor.log", 30), ("detect.log", 20))
        if sys.platform == "darwin":  # native libraries (MLX, PyObjC) print their errors to stderr.log
            logs += (("stderr.log", 40),)
        for name, n in logs:
            parts += [f"## {name} (last {n} lines)", "```", tail(name, n), "```", ""]
        for p in live[-2:]:
            parts += [f"## {p.name}", "```", p.read_text(encoding="utf-8", errors="replace")[:5000], "```", ""]
        return "\n".join(parts)

    def copy_debug_info(self) -> dict:
        self._copy(self.debug_info())
        return {"ok": True}

    def open_logs_folder(self) -> dict:
        _startfile(str(self._data_dir))  # Explorer / Finder
        return {"ok": True}

    def open_log(self) -> dict:
        _startfile(str(self._data_dir / "ecoscribe.log"))
        return {"ok": True}

    # ---------- a newer version (dictado-cjk) ----------
    def update_notice(self) -> dict:
        """Home: {"version", "url"} when a newer release is out and not dismissed; {} otherwise.
        Only reads what the app's daily check saved (updates.py): never waits on the network."""
        from . import updates
        if not self._load().ui.update_check:
            return {}
        return updates.notice(updates.load(self._data_dir), __version__) or {}

    def open_update(self) -> dict:
        from . import updates
        n = updates.notice(updates.load(self._data_dir), __version__)
        if not n:
            return {"ok": False}
        self._open_url(n["url"])  # the release page: the .exe and the .dmg are both there
        return {"ok": True}

    def dismiss_update(self, version: str = "") -> dict:
        from . import updates
        updates.dismiss(self._data_dir, version)
        return {"ok": True}

    def get_welcome(self) -> dict:
        return {"done": (self._data_dir / "welcome_done").exists()}

    def finish_welcome(self) -> dict:
        (self._data_dir / "welcome_done").write_text(time.strftime("%Y-%m-%d"), encoding="utf-8")
        return {"ok": True}

    # ---------------- first-run setup (dictado-zpz) ----------------
    def setup_info(self, languages: str = "") -> dict:
        """The speech models for these languages (required / recommended, downloaded or not) and,
        on the Mac, the permissions dictation needs."""
        from . import models
        c = self._load()
        langs = [x.strip() for x in str(languages).split(",") if x.strip()] or c.whisper.languages
        rows = models.setup_models(c.whisper, langs)
        for m in rows:
            m["ready"] = models.is_ready(m["name"])
        perms = []
        if sys.platform == "darwin":
            from .platform.macos import permissions
            st = permissions.status()
            perms = [{"key": k, "label": permissions.PANES[k][0], "granted": bool(st.get(k)),
                      "ask": not st.get(k) and permissions.can_ask(k)} for k in permissions.DICTATION]
        return {"models": rows, "permissions": perms}

    def open_permission(self, key: str) -> dict:
        if sys.platform == "darwin":
            from .platform.macos import permissions
            if key in permissions.PANES:
                return {"ok": True, "did": permissions.ask_or_open(key)}
        return {"ok": False}

    def setup_models_start(self, names: list) -> dict:
        """Download `names` one after another in the background; poll setup_models_progress()."""
        import threading
        from . import models
        dl = getattr(self, "_dl", None)
        if dl and dl["running"]:
            return self.setup_models_progress()
        dl = self._dl = {"running": True, "error": None,
                         "models": {n: {"done": 0, "total": None, "ready": models.is_ready(n)} for n in names}}

        def run():
            try:
                for n in names:
                    row = dl["models"][n]
                    if row["ready"]:
                        continue

                    def progress(done, total, row=row):
                        row["done"], row["total"] = done, total
                    models.prepare(n, progress=progress)
                    row["ready"] = True
            except Exception as e:
                log.exception("setup model download failed")
                dl["error"] = str(e) or type(e).__name__
            finally:
                dl["running"] = False
        threading.Thread(target=run, name="ecoscribe-setup-models", daemon=True).start()
        return self.setup_models_progress()

    def models_info(self) -> dict:
        """Settings > Speech models (dictado-z4q): both models, what each is for, on disk or not."""
        from . import models
        c = self._load()
        rows = models.setup_models(c.whisper, c.whisper.languages)
        for m in rows:
            m["ready"] = models.is_ready(m["name"])
            m["disk"] = models.disk_size(m["name"]) if m["ready"] else 0
        return {"models": rows}

    def delete_model(self, name: str) -> dict:
        from . import models
        c = self._load()
        if name not in (c.whisper.model, c.whisper.sv_model):
            return {"ok": False, "error": "unknown model"}
        try:
            return {"ok": models.delete(name)}
        except OSError:
            log.exception("model delete failed")
            return {"ok": False, "error": "It's in use right now. Try again in a few minutes, when Ecoscribe has been idle."}

    def setup_models_progress(self) -> dict:
        dl = getattr(self, "_dl", None) or {"running": False, "error": None, "models": {}}
        return {"running": dl["running"], "error": dl["error"], "models": {k: dict(v) for k, v in dl["models"].items()}}


def _listen_for_focus(win) -> None:
    import threading
    from .platform.macos import signals
    lst = signals.Listener(ipc.UI_FOCUS)

    def run():
        while True:
            msg = lst.wait(None)
            if msg is None:
                return
            try:
                win.restore()
                win.show()
                from AppKit import NSApplication
                from PyObjCTools import AppHelper
                AppHelper.callAfter(NSApplication.sharedApplication().activateIgnoringOtherApps_, True)  # main thread
                if msg.startswith(b"page:"):
                    win.evaluate_js(f"window.__ecoscribe.show({json.dumps(msg[5:].decode())})")
            except Exception:
                log.exception("focus request failed")
    threading.Thread(target=run, name="ecoscribe-ui-focus", daemon=True).start()
    win.events.closed += lst.close


def web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


# Tests only (dictado-0up): ECOSCRIBE_QUIET_WINDOW=<port> opens a test copy off-screen that never takes
# focus, next to the user's own window, with WebView2's debug port on localhost:<port> for Playwright.
QUIET_ENV = "ECOSCRIBE_QUIET_WINDOW"
OFF_SCREEN = -32000


def main(page: str | None = None) -> int:
    from . import palette as P
    from . import winutil
    winutil.setup_logging(paths.data_dir() / "window.log")
    quiet = os.environ.get(QUIET_ENV)
    if not quiet and not winutil.single_instance(ipc.UI_MUTEX):
        ipc.focus_ui()
        return 0
    import webview
    api = Api(page=page)
    url = (web_dir() / "index.html").as_uri()
    kw = {}
    if quiet:
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(quiet)
        kw = {"x": OFF_SCREEN, "y": OFF_SCREEN, "focus": False, "hidden": True}
    win = webview.create_window(ipc.UI_TITLE, url, js_api=api, width=980, height=720, min_size=(820, 560),
                                background_color=P.PAPER, text_select=True, **kw)
    win.events.closed += lambda: api.mic_test_stop()

    def on_drop(e):  # pywebview fills pywebviewFullPath only for drops handled from Python
        paths = [f.get("pywebviewFullPath") for f in (e.get("dataTransfer") or {}).get("files", [])]
        win.evaluate_js(f"window.__ecoscribe.dropped({json.dumps([p for p in paths if p])})")

    def on_loaded():
        from webview.dom import DOMEventHandler
        win.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True, stop_propagation=True)
    win.events.loaded += on_loaded
    if sys.platform == "darwin":  # no FindWindow: a second launch asks us over a socket to come forward
        _listen_for_focus(win)
    webview.start(gui=WEBVIEW_GUI, private_mode=False,
                  storage_path=str(paths.data_dir() / "webview"), debug=bool(os.environ.get("ECOSCRIBE_DEVTOOLS")))
    api.mic_test_stop()
    return 0
