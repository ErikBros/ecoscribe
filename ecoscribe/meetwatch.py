"""The detector thread: turns detect.Detector events into a prompt, a start or a stop.

Every 2 s it reads who holds the mic (ConsentStore), the window titles and the
running exes, and feeds detect.Detector. A call start either asks near the pill
("prompt") or starts recording ("auto"); "Not now" ignores that call until its
end. A call end stops the meeting the detector started for that app, and one started
by hand during that call (it records the call's app, dictado-2s7), or shortly before it (it
joins the call when the detector sees it start); a meeting started by hand with no call is
the user's to stop. Backup for a missed end: both tracks
silent for silence_stop_s asks "Did the meeting end?" and stops 60 s later unless
the user says Keep going. Each app remembers its last language (meeting_langs.json). Every
event and answer goes to detect.log, to audit the detector against real calls.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from . import detect, paths

log = logging.getLogger(__name__)
LANGS = "meeting_langs.json"
END_ANSWER_S = 60  # no answer to "Did the meeting end?" in this long: stop
JOIN_S = 300  # a meeting started by hand this recently joins the call that starts now
SILENT = 1e-3


def _foreground() -> str:
    try:
        return detect.foreground_app()
    except Exception:
        return ""


_failing: dict[str, str] = {}  # reader -> its last error, logged once until it works again


def _reader(name: str, fn, default):
    """One reader's result, or `default` when it fails: a broken window-title read (say, no Accessibility on
    the Mac) must not also hide who holds the mic (dictado-nhn). Each failure is logged once, and its recovery."""
    try:
        out = fn()
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if _failing.get(name) != err:
            _failing[name] = err
            log.warning("meetwatch: %s failed (%s)", name, err, exc_info=True)
        return default
    if _failing.pop(name, None) is not None:
        log.info("meetwatch: %s works again", name)
    return out


def _read_world():
    return (_reader("mic reader", detect.read_consent, []), _reader("window titles", detect.window_titles, []),
            _reader("running apps", detect.running_apps, None))


def _health() -> dict:
    try:
        h = dict(detect.health())
    except Exception:
        h = {}
    for name, err in _failing.items():
        h[name.replace(" ", "_")] = "failing"
    return h


class MeetWatch(threading.Thread):
    def __init__(self, controller, cfg, ui_prompt, read=_read_world, clock=time.monotonic,
                 data_dir: Path | None = None, interval_s: float = 2.0, health=_health):
        super().__init__(name="ecoscribe-meetwatch", daemon=True)
        self.ctl, self.cfg, self.ui_prompt = controller, cfg.meetings, ui_prompt
        self.read, self.clock, self.interval, self.health = read, clock, interval_s, health
        self.data = Path(data_dir) if data_dir else paths.data_dir()
        self.detector = detect.Detector(grace_s=self.cfg.grace_s)
        self.call: str | None = None  # app of the call the detector sees right now
        self.pending: str | None = None  # app whose start prompt is open
        self.suppressed: str | None = None  # "Not now" for this call
        self.auto_app: str | None = None  # the detector started the running meeting for this app
        self.silent_since: float | None = None
        self.end_asked_at: float | None = None
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._signal: str | None = None  # the last signal line written to detect.log
        self._tick_error: str | None = None

    # -- language memory ------------------------------------------------------------------
    def _langs(self) -> dict:
        try:
            return json.loads((self.data / LANGS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def call_app_now(self) -> str | None:
        """For a meeting started by hand (t0u.33): the call the detector sees, else the call app on the mic now."""
        if self.call:
            return self.call
        try:
            uses, _titles, running = self.read()
            return detect.call_app_now(uses, running, foreground=_foreground())
        except Exception:
            log.debug("no call app for a manual start", exc_info=True)
            return None

    def meet_name(self) -> str | None:
        """The Google Meet tab's event name right now (dictado-4ar): names a call the calendar doesn't know."""
        try:
            return detect.meet_name(self.read()[1])
        except Exception:
            log.debug("no Meet tab name", exc_info=True)
            return None

    def lang_for(self, app: str | None) -> str:
        return self._langs().get(app or "", self.cfg.default_lang) if app else self.cfg.default_lang

    def remember(self, app: str | None, lang: str) -> None:
        if not app:
            return
        langs = self._langs()
        langs[app] = lang
        try:
            (self.data / LANGS).write_text(json.dumps(langs, ensure_ascii=False), encoding="utf-8")
        except OSError:
            log.exception("meeting_langs.json not written")

    def _audit(self, msg: str) -> None:
        log.info("meetwatch: %s", msg)
        try:
            with open(self.data / "detect.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
        except OSError:
            pass

    # -- the loop ------------------------------------------------------------------------
    def run(self) -> None:
        self._audit(f"watching mode={self.cfg.mode}")
        while not self._halt.wait(self.interval):
            try:
                self.tick()
                self._tick_error = None
            except Exception as e:
                log.exception("meetwatch tick failed")
                err = f"{type(e).__name__}: {e}"
                if err != self._tick_error:  # once per kind of failure, in the log the user's checks read
                    self._tick_error = err
                    self._audit(f"tick failed: {type(e).__name__}")

    def stop(self) -> None:
        self._halt.set()

    def tick(self) -> None:
        if self.cfg.mode == "off":
            return
        with self._lock:
            uses, titles, running = self.read()
            now = self.clock()
            self._note_signal(uses, titles, running)
            ev = self.detector.update(uses, titles, now, running)
            if ev is not None:
                self._on_event(ev)
            self._silence(now)

    def _note_signal(self, uses, titles, running) -> None:
        """detect.log gets a line each time what the detector sees changes: app names on the mic, whether
        they play sound, a meeting tab title yes/no, and a reader or permission that is failing (dictado-nhn).
        A missed call then shows why in the log (app names only, never a window title)."""
        try:
            line = detect.signal_summary(uses, titles, running, self.health())
        except Exception:
            log.debug("signal summary failed", exc_info=True)
            return
        if line != self._signal:
            self._signal = line
            self._audit("signal " + line)

    def _meeting(self) -> dict | None:
        return self.ctl.state().get("meeting")

    def _recording(self) -> bool:
        """A meeting records (or waits to record). One that is only saving doesn't count:
        a new call right after the last one must still be offered."""
        st = self.ctl.state()
        m = st.get("meeting")
        return bool(st.get("next_meeting")) or (m is not None and m.get("status") == "recording")

    def _just_started_by_hand(self) -> bool:
        m = self._meeting()
        if m is None or m.get("app") or m.get("status") != "recording" or not m.get("started"):
            return False
        try:
            age = (datetime.now() - datetime.fromisoformat(m["started"])).total_seconds()
        except (TypeError, ValueError):
            return False
        return age <= JOIN_S

    def _on_event(self, ev) -> None:
        if ev.kind == "start":
            self.call = ev.app
            lang = self.lang_for(ev.app)
            if self._recording():
                if self._just_started_by_hand() and self.ctl.set_app(ev.app):
                    self._audit(f"start {ev.app}: the meeting started by hand joins this call")
                else:
                    self._audit(f"start {ev.app}: a meeting already records, nothing to do")
                return
            if self.cfg.mode == "auto":
                self._audit(f"start {ev.app}: auto start lang={lang}")
                self.ctl.start_meeting(lang, app=ev.app)
                self.auto_app = ev.app
            else:
                self._audit(f"start {ev.app}: prompt lang={lang}")
                self.pending = ev.app
                self.ui_prompt("start", ev.app, lang)
            return
        self._audit(f"end {ev.app}")
        if self.pending == ev.app:
            self.pending = None
            self.ui_prompt("dismiss", ev.app, None)
        if self.suppressed == ev.app:
            self.suppressed = None
        m = self._meeting()
        mine = self.auto_app == ev.app
        by_hand = m is not None and m.get("app") == ev.app and m.get("status") == "recording"  # dictado-2s7
        if mine:
            self.auto_app = None
        if m is not None and (mine or by_hand):
            self._audit(f"stop {ev.app}: call ended" + ("" if mine else " (started by hand)"))
            self.ctl.stop_meeting()
        self.call = None

    def _silence(self, now: float) -> None:
        m = self._meeting()
        if m is None or m.get("status") != "recording":
            if self.end_asked_at is not None:  # stopped some other way: the question is moot
                self.ui_prompt("dismiss_end", None, None)
            self.silent_since = self.end_asked_at = None
            return
        if self.end_asked_at is not None:
            if now - self.end_asked_at >= END_ANSWER_S:
                self._audit("stop: no answer to the end prompt")
                self.end_asked_at = self.silent_since = None
                self.auto_app = None
                self.ctl.stop_meeting()
            return
        lv = self.ctl.levels()
        if lv is None or max(lv) >= SILENT:
            self.silent_since = None
            return
        if self.silent_since is None:
            self.silent_since = now
        elif now - self.silent_since >= self.cfg.silence_stop_s:
            self._audit(f"silence {now - self.silent_since:.0f} s: end prompt")
            self.end_asked_at = now
            self.ui_prompt("end?", None, None)

    # -- answers from the prompt (tk thread) ---------------------------------------------
    def answer(self, choice: str, lang: str | None = None) -> None:
        """transcribir | ahora_no (also the prompt timeout) | seguir | parar."""
        with self._lock:
            self._audit(f"answer {choice}" + (f" lang={lang}" if lang else ""))
            if choice == "transcribir":
                app, self.pending = self.pending, None
                if app is None or app != self.call:
                    return  # a late click after the call ended
                lang = lang or self.lang_for(app)
                self.remember(app, lang)
                self.ctl.start_meeting(lang, app=app)
                self.auto_app = app
            elif choice == "ahora_no":
                if self.pending is not None:
                    self.suppressed, self.pending = self.pending, None
            elif choice == "seguir":
                self.end_asked_at = self.silent_since = None
            elif choice == "parar":
                self.end_asked_at = self.silent_since = None
                self.ctl.stop_meeting()
