"""Meeting detection: who uses the microphone (per platform: Windows' consent store and live audio
sessions in ecoscribe/platform/windows/detect.py, Core Audio on macOS) and the rules on top.

A call app holding the mic is a meeting. A browser holding the mic is a meeting
only with a second signal: a meeting window title, or the browser playing sound
while it captures the mic, i.e. two-way audio. A Chrome tab
can sit on the mic for hours with no call; the Meet tab's title is only in the window
while that tab is in front. The meeting ends when its app has let go for
grace_s in a row (mute toggles and quick rejoins must not end it). A start needs
debounce_polls polls in a row (a Telegram voice note is not a call). A meeting
title only counts in a window owned by a browser. A desktop app's entry that says
"in use" while the app isn't running is a leftover from a crash and is ignored.
Read-only: nothing here prompts, records or touches the desktop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CALL_APPS = {"msteams", "ms-teams", "teams", "slack", "zoom", "discord", "signal", "telegram", "webex",
             "ciscocollabhost", "whatsapp"}
BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera"}
MEETING_TITLE = re.compile(r"\bMeet\b|Zoom|Microsoft Teams|Whereby|Jitsi|Google Meet|Huddle", re.I)
# dictado-4ar: a Google Meet tab is titled "Meet - <event> - <browser>"; an instant meeting shows only its code
MEET_TAB = re.compile(r"^(?:\(\d+\)\s*)?Meet\s+[-\u2013\u2014]\s+(.+)$")
MEET_CODE = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$")
# Chrome adds the tab's state to the window title during a call ("Meet - Retro - Camera and microphone recording - ...")
TAB_STATE = re.compile(r"\s+[-\u2013\u2014]\s+(?:Camera and microphone recording|Camera recording|Microphone recording|"
                       r"Audio playing|Audio muted|Sharing this (?:tab|window|screen)|Network error)\b.*$")
BROWSER_SUFFIX = re.compile(r"\s+[-\u2013\u2014]\s+(?:Google Chrome|Microsoft\s*Edge|Mozilla Firefox|Brave|Opera|Safari)\b.*$")


@dataclass(frozen=True)
class MicUse:
    app: str
    in_use: bool
    start: int
    stop: int
    nonpackaged: bool = False  # desktop app: `app` is its exe name, checkable against running processes
    talking: bool = False  # the process capturing the mic also plays sound right now (macOS Core Audio)


@dataclass(frozen=True)
class Event:
    kind: str  # "start" | "end"
    app: str
    at: float


def app_from_nonpackaged(key: str) -> str:
    """'C:#Program Files#Slack#slack.exe' -> 'slack'."""
    base = key.replace("/", "#").split("#")[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def app_from_packaged(key: str) -> str:
    """'MSTeams_8wekyb3d8bbwe' -> 'msteams'; 'com.notion.app.desktop.notion_x' -> 'notion'."""
    return key.split("_")[0].split(".")[-1].lower()


def meet_name(titles) -> str | None:
    """The event name in a Google Meet tab's title ("Meet - Sprint retro - Google Chrome" -> "Sprint retro"),
    or None: no Meet tab in front of a browser window, or an instant meeting that shows only its code.
    titles: (title, exe) pairs or bare titles, as Detector.update takes them. dictado-4ar"""
    for t in titles:
        title, exe = (t, None) if isinstance(t, str) else (t[0], t[1])
        if exe is not None and exe not in BROWSERS:
            continue
        m = MEET_TAB.match(TAB_STATE.sub("", BROWSER_SUFFIX.sub("", title.replace("\u200b", ""))).strip())
        if not m:
            continue
        name = re.sub(r"\s+and \d+ more pages?\b.*$", "", m.group(1)).strip()  # Edge, with several tabs (and a profile)
        if name and not MEET_CODE.match(name):
            return name
    return None


OWN_APPS = ("ecoscribe", "python", "pythonw")


def meeting_titled(titles) -> bool:
    """A meeting tab's title is in a browser window. titles: (title, exe) pairs or bare titles (owner unknown)."""
    return any(MEETING_TITLE.search(t if isinstance(t, str) else t[0])
               for t in titles if isinstance(t, str) or t[1] in BROWSERS)


def is_call_app(app: str) -> bool:
    # prefix match: packaged names carry suffixes (whatsappdesktop)
    return app in CALL_APPS or any(app.startswith(c) for c in CALL_APPS)


def uses_from_entries(entries) -> list[MicUse]:
    """entries: (key name, start, stop, nonpackaged). One MicUse per app; in use if ANY entry is."""
    by: dict[str, MicUse] = {}
    for name, start, stop, nonpackaged in entries:
        app = app_from_nonpackaged(name) if nonpackaged else app_from_packaged(name)
        u = MicUse(app=app, in_use=bool(start) and stop == 0, start=int(start or 0), stop=int(stop or 0),
                   nonpackaged=bool(nonpackaged))
        prev = by.get(app)
        if prev is None or (u.in_use and not prev.in_use) or (u.in_use == prev.in_use and u.start > prev.start):
            by[app] = u
    return list(by.values())


def with_sessions(uses: list[MicUse], capturing: set[str], playing: set[str], now: int) -> list[MicUse]:
    """Add what the live audio sessions show (Windows, dictado-pprg): an app with an active session on a
    capture device is on the mic even when the consent store has nothing (Windows can stop updating it),
    and one that also has an active session on an output device talks: two-way audio, as macOS reads it.
    capturing / playing: exe names; now: a FILETIME, the start of a use the consent store missed."""
    by = {u.app: u for u in uses}
    for app in capturing:
        u = by.get(app)
        if u is None or not u.in_use:
            u = MicUse(app=app, in_use=True, start=max(now, u.start if u else 0), stop=0,
                       nonpackaged=u.nonpackaged if u else True)
        by[app] = MicUse(u.app, u.in_use, u.start, u.stop, u.nonpackaged, talking=u.talking or app in playing)
    return list(by.values())


def call_app_now(uses: list[MicUse], running: set[str] | None = None, foreground: str = "") -> str | None:
    """The call app holding the mic right now (t0u.33, for meetings started by hand): the
    foreground one if several, else the one that took the mic last. None if no call app has it.
    A browser counts when it talks (mic in + sound out): a call in a tab."""
    live = [u for u in uses if u.in_use and (is_call_app(u.app) or (u.talking and u.app in BROWSERS))
            and not (running is not None and u.nonpackaged and u.app not in running)]
    if not live:
        return None
    for u in live:
        if foreground and u.app == foreground:
            return u.app
    return max(live, key=lambda u: u.start).app


if __import__("sys").platform == "darwin":  # Core Audio process objects + Accessibility (ecoscribe/platform/macos/detect.py)
    from .platform.macos.detect import (BROWSER_APPS, foreground_app, health, read_consent,  # noqa: F401
                                        running_apps, window_titles)
    from .platform.macos.procs import exe_of_pid as _exe_of_pid  # noqa: F401
    CALL_APPS = CALL_APPS | {"facetime"}
    BROWSERS = BROWSERS | BROWSER_APPS  # safari, arc, vivaldi...: the Mac reader names them
else:  # the consent store, EnumWindows, the process list (ecoscribe/platform/windows/detect.py)
    from .platform.windows.detect import (_exe_of_pid, foreground_app, health, read_consent,  # noqa: F401
                                          running_apps, window_titles)


class Detector:
    """Feed it a poll every couple of seconds; it returns start / end events."""

    def __init__(self, grace_s: float = 10.0, own_apps=OWN_APPS, debounce_polls: int = 2):
        self.grace_s = grace_s
        # python/pythonw are excluded because Ecoscribe runs as Python in development; neither is a
        # call app nor a browser, so this can never hide a real meeting.
        self.own = {a.lower() for a in own_apps}
        self.debounce = max(1, debounce_polls)
        self.app: str | None = None  # the app whose meeting is running
        self.released_at: float | None = None
        self._cand: str | None = None
        self._cand_n = 0

    def _active(self, app: str, in_use: set[str], titled: bool, talking: set[str]) -> bool:
        if app not in in_use:
            return False
        # a browser meeting needs its title or two-way audio too: the tab may keep the mic after the call
        return (titled or app in talking) if app in BROWSERS else True

    def update(self, uses: list[MicUse], titles: list, now: float, running: set[str] | None = None) -> Event | None:
        """titles: (title, exe) pairs, or bare titles (owner unknown, treated as a browser's)."""
        in_use = {u.app for u in uses if u.in_use and u.app not in self.own
                  and not (running is not None and u.nonpackaged and u.app not in running)}
        talking = {u.app for u in uses if u.in_use and u.talking}
        titled = meeting_titled(titles)
        if self.app is None:
            calls = sorted(a for a in in_use if is_call_app(a))
            browsers = sorted(a for a in in_use if a in BROWSERS and (titled or a in talking))
            app = calls[0] if calls else (browsers[0] if browsers else None)
            if app is None or app != self._cand:
                self._cand, self._cand_n = app, (1 if app else 0)
            else:
                self._cand_n += 1
            if app is None or self._cand_n < self.debounce:
                return None
            self.app, self.released_at, self._cand, self._cand_n = app, None, None, 0
            return Event("start", app, now)
        if self._active(self.app, in_use, titled, talking):
            self.released_at = None
            return None
        if self.released_at is None:
            self.released_at = now
        if now - self.released_at >= self.grace_s:
            app, self.app, self.released_at = self.app, None, None
            return Event("end", app, now)
        return None


# ---------- why (not) a call: the detector log and the probe (dictado-nhn) ----------
def _seen(uses, running, own) -> list:
    return sorted((u for u in uses if u.in_use and u.app not in own
                   and not (running is not None and u.nonpackaged and u.app not in running)), key=lambda u: u.app)


def explain(uses: list[MicUse], titles: list, running: set[str] | None = None, own=OWN_APPS) -> list[str]:
    """One line per app on the mic: is it a call to the Detector, and why (app names only, never a title)."""
    titled = meeting_titled(titles)
    lines = []
    for u in sorted((u for u in uses if u.in_use), key=lambda u: u.app):
        a = u.app
        if a in own:
            lines.append(f"{a}: Ecoscribe itself on the mic -> ignored")
        elif running is not None and u.nonpackaged and a not in running:
            lines.append(f"{a}: marked as using the mic but not running (a leftover) -> ignored")
        elif is_call_app(a):
            lines.append(f"{a}: call app on the mic -> a call")
        elif a in BROWSERS:
            if u.talking:
                lines.append(f"{a}: browser on the mic and playing sound -> a call")
            elif titled:
                lines.append(f"{a}: browser on the mic with a meeting tab title in a window -> a call")
            else:
                lines.append(f"{a}: browser on the mic, plays no sound and no meeting tab title -> not a call")
        else:
            lines.append(f"{a}: on the mic, not a known call app or browser -> not a call")
    return lines or ["no app holds the mic"]


def signal_summary(uses: list[MicUse], titles: list, running: set[str] | None = None, health: dict | None = None,
                   own=OWN_APPS) -> str:
    """'mic=chrome+sound,slack title=no': what the detector sees, for detect.log when it changes. The title flag
    only when a browser is on the mic; health only what isn't fine (mic_api=unavailable, accessibility=...)."""
    seen = _seen(uses, running, own)
    parts = ["mic=" + (",".join(u.app + ("+sound" if u.talking else "") for u in seen) or "-")]
    if any(u.app in BROWSERS for u in seen):
        parts.append("title=" + ("yes" if meeting_titled(titles) else "no"))
    for k, v in sorted((health or {}).items()):
        if v not in ("ok", "granted", "unknown"):
            parts.append(f"{k}={v.replace(' ', '-')}")
    return " ".join(parts)


def _safe(fn, default, errors: list, name: str):
    try:
        return fn()
    except Exception as e:  # the probe shows a broken reader instead of dying on it
        errors.append(f"{name} failed: {type(e).__name__}: {e}")
        return default


def probe(seconds: float = 120.0, interval: float = 1.0, raw: bool = False, out=print, read_mic=None,
          read_titles=None, read_running=None, read_front=None, read_health=None, read_raw=None,
          clock=None, sleep=None) -> int:
    """Print each detection signal live: who is on the mic (and plays sound), the app in front, whether a
    meeting tab title is in a browser window (never the title), and the verdict. Records nothing.
    seconds <= 0: until Ctrl+C. raw (macOS): every audio process with its bundle id and the app it counts as."""
    import sys as _sys
    import time as _time
    read_mic, read_titles = read_mic or read_consent, read_titles or window_titles
    read_running, read_front, read_health = read_running or running_apps, read_front or foreground_app, read_health or health
    clock, sleep = clock or _time.monotonic, sleep or _time.sleep
    if raw and read_raw is None and _sys.platform == "darwin":
        from .platform.macos.detect import app_of_process, audio_processes

        def read_raw():
            return [(pid, b, cap, play, app_of_process(pid, b)) for pid, b, cap, play in (audio_processes() or [])]
    out("Ecoscribe call-detection probe: records nothing, shows no window titles (only whether a meeting tab is "
        "there). Start or join a call now; Ctrl+C stops.")
    det = Detector()
    t0 = clock()
    try:
        while True:
            errors: list[str] = []
            uses = _safe(read_mic, [], errors, "mic reader")
            titles = _safe(read_titles, [], errors, "window titles")
            running = _safe(read_running, None, errors, "running apps")
            front = _safe(read_front, "", errors, "front app")
            hl = _safe(read_health, {}, errors, "health")
            now = clock()
            seen = _seen(uses, running, OWN_APPS)
            mic = ", ".join(u.app + (" (+sound)" if u.talking else "") for u in seen) or "nobody"
            line = (f"[{now - t0:5.0f}s] mic: {mic} | front: {front or '?'} | meeting title in a browser window: "
                    f"{'yes' if meeting_titled(titles) else 'no'}")
            if hl:
                line += " | " + ", ".join(f"{k}: {v}" for k, v in sorted(hl.items()))
            rows = _safe(read_raw, [], errors, "audio processes") if raw and read_raw is not None else []
            out(line)
            for e in errors:
                out("   ! " + e)
            for x in explain(uses, titles, running):
                out("   " + x)
            for pid, bundle, cap, play, app in rows:
                out(f"   process {pid} {bundle or '-'} mic={'yes' if cap else 'no'} sound={'yes' if play else 'no'}"
                    f" -> {app or '?'}")
            ev = det.update(uses, titles, now, running)
            if ev is not None:
                out(f"   => Ecoscribe would now {'offer to record' if ev.kind == 'start' else 'end'} the {ev.app} call")
            if hl.get("accessibility") not in (None, "granted", "unknown"):
                out("   (Accessibility is granted per app: run from a terminal, this is the terminal's grant)")
            if seconds > 0 and now - t0 >= seconds:
                return 0
            sleep(interval)
    except KeyboardInterrupt:
        return 0


def main(argv=None) -> int:
    """python -m ecoscribe.callprobe [--seconds N] [--raw]: the live signals, for a real-call check."""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m ecoscribe.callprobe", description=probe.__doc__)
    ap.add_argument("--seconds", type=float, default=120.0, help="how long (0: until Ctrl+C)")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--raw", action="store_true", help="macOS: every audio process, its bundle id and app")
    args = ap.parse_args(argv)
    return probe(args.seconds, args.interval, raw=args.raw, out=lambda s: print(s, flush=True))
