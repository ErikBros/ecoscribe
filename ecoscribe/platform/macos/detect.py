"""Who holds the mic on macOS (uat.9): detect.py's readers, for the shared Detector.

Windows reads the ConsentStore registry. macOS 14+ lists audio "process objects" (kAudioHardwarePropertyProcessObjectList)
and says per process whether it is capturing right now (kAudioProcessPropertyIsRunningInput), playing
(kAudioProcessPropertyIsRunningOutput) plus its bundle id. A browser that captures the mic and plays sound (in any of
its processes) is a call in a tab, even when the Meet tab isn't the one in front (its title is then not in any window).
Read-only, no permission needed. Bundle ids map to the same short app names the Windows detector uses
(msteams, slack, zoom, signal, chrome...), so Detector, the prompt texts and meeting_langs.json are shared.

The process doing the audio is often not the app itself (dictado-nhn): Chrome's audio runs in a helper, a WebKit
view's in com.apple.WebKit.GPU (Safari, but also any app built on WebKit), FaceTime's in the avconferenced daemon.
So each audio process is named after the app responsible for it (the one that launched it), then its own bundle
id, then the .app it lives in. Browser meeting tabs: window titles of running browsers, read through Accessibility
(no Accessibility grant: no titles; health() says so and the detector log shows it).
"""
from __future__ import annotations

import ctypes
import logging
import time

log = logging.getLogger(__name__)

# bundle id prefix -> detect.py app name (longest prefix wins)
BUNDLES = {
    "com.microsoft.teams": "msteams", "com.microsoft.teams2": "msteams", "us.zoom.xos": "zoom",
    "com.tinyspeck.slackmacgap": "slack", "org.whispersystems.signal-desktop": "signal",
    "ru.keepcoder.telegram": "telegram", "org.telegram.desktop": "telegram", "com.hnc.discord": "discord",
    "net.whatsapp.whatsapp": "whatsapp", "desktop.whatsapp": "whatsapp", "com.cisco.webexmeetingsapp": "webex",
    "cisco-systems.spark": "webex", "com.webex.meetingmanager": "webex", "com.apple.facetime": "facetime",
    "com.apple.avconferenced": "facetime",  # FaceTime's (and iPhone calls') audio runs in this daemon
    "com.google.chrome": "chrome", "com.microsoft.edgemac": "msedge", "org.mozilla.firefox": "firefox",
    "org.mozilla.plugincontainer": "firefox", "com.brave.browser": "brave", "com.operasoftware.opera": "opera",
    "com.apple.safari": "safari", "company.thebrowser.browser": "arc", "com.vivaldi.vivaldi": "vivaldi",
    "org.chromium.chromium": "chromium",
    "com.apple.webkit": "safari",  # Safari's mic is held by its WebKit GPU/WebContent process
    "com.erikbros.ecoscribe": "ecoscribe",  # ourselves (the meeting worker, the system-audio helper): ignored
}
# an audio process with no (useful) bundle id: its executable, or the .app it lives in -> app name
EXES = {"avconferenced": "facetime", "ecoscribe-systap": "ecoscribe"}
APP_DIRS = {
    "google chrome": "chrome", "microsoft edge": "msedge", "firefox": "firefox", "brave browser": "brave",
    "opera": "opera", "safari": "safari", "arc": "arc", "vivaldi": "vivaldi", "chromium": "chromium",
    "zoom.us": "zoom", "microsoft teams": "msteams", "slack": "slack", "signal": "signal", "telegram": "telegram",
    "discord": "discord", "whatsapp": "whatsapp", "webex": "webex", "facetime": "facetime", "ecoscribe": "ecoscribe",
}
BROWSER_APPS = {"chrome", "msedge", "firefox", "brave", "opera", "safari", "arc", "vivaldi", "chromium"}
_GENERIC = {"helper", "gpu", "webcontent", "networking", "renderer", "plugin"}  # a helper's bundle id says nothing


def known_app(bundle: str) -> str:
    """The app name for a bundle id in BUNDLES (longest prefix wins), or "" when it isn't a known app."""
    b = (bundle or "").lower()
    best = ""
    for prefix in BUNDLES:
        if b.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return BUNDLES[best] if best else ""


def app_of_bundle(bundle: str) -> str:
    b = (bundle or "").lower()
    return known_app(b) or (b.rsplit(".", 1)[-1] if b else "")


def app_of_path(path: str) -> str:
    """'/Applications/Google Chrome.app/Contents/.../Google Chrome Helper.app/Contents/MacOS/...' -> 'chrome';
    '/usr/libexec/avconferenced' -> 'facetime'. "" when the path names no known app."""
    if not path:
        return ""
    parts = path.replace("\\", "/").split("/")
    exe = parts[-1].lower()
    if exe in EXES:
        return EXES[exe]
    for part in parts:  # the outermost .app is the app the user knows
        if part.lower().endswith(".app"):
            name = part[:-4].lower()
            best = max((k for k in APP_DIRS if name.startswith(k)), key=len, default="")
            return APP_DIRS[best] if best else ""
    return ""


# ---------- Core Audio through ctypes ----------
class _Addr(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mElement", ctypes.c_uint32)]


def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


_CA = None
SYSTEM = 1  # kAudioObjectSystemObject


def _ca():
    global _CA
    if _CA is None:
        _CA = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        for fn in (_CA.AudioObjectGetPropertyDataSize, _CA.AudioObjectGetPropertyData):
            fn.restype = ctypes.c_int32
    return _CA


def _get(obj: int, sel: str, ctype, n: int | None = None):
    ca = _ca()
    addr = _Addr(_fourcc(sel), _fourcc("glob"), 0)
    size = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size)):
        return None
    count = n if n is not None else max(1, size.value // ctypes.sizeof(ctype))
    buf = (ctype * count)()
    size = ctypes.c_uint32(ctypes.sizeof(buf))
    if ca.AudioObjectGetPropertyData(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size), buf):
        return None
    return list(buf)[: size.value // ctypes.sizeof(ctype)]


def _cfstring(ptr: int) -> str:
    if not ptr:
        return ""
    import objc
    s = objc.objc_object(c_void_p=ptr)
    out = str(s)
    ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation").CFRelease(ctypes.c_void_p(ptr))
    return out


def audio_processes() -> list[tuple[int, str, bool, bool]] | None:
    """(pid, bundle id, captures now, plays now) of every process Core Audio knows; None when the
    process list itself can't be read (then nothing can be detected: health() says so)."""
    objs = _get(SYSTEM, "prs#", ctypes.c_uint32)  # kAudioHardwarePropertyProcessObjectList
    if objs is None:
        return None
    out = []
    for obj in objs:
        capturing = _get(obj, "piri", ctypes.c_uint32, 1)  # kAudioProcessPropertyIsRunningInput
        playing = _get(obj, "piro", ctypes.c_uint32, 1)  # kAudioProcessPropertyIsRunningOutput
        cap, play = bool(capturing and capturing[0]), bool(playing and playing[0])
        if not (cap or play):
            continue
        pid = (_get(obj, "ppid", ctypes.c_int32, 1) or [0])[0]
        bundle = _cfstring((_get(obj, "pbid", ctypes.c_void_p, 1) or [0])[0] or 0)
        out.append((int(pid), bundle, cap, play))
    return out


# ---------- which app a process belongs to ----------
_RESP = None


def _responsible_pid(pid: int) -> int:
    """The app that launched `pid` (Chrome for its helper, Safari or another app for a WebKit process); 0 if unknown."""
    global _RESP
    try:
        if _RESP is None:
            _RESP = ctypes.CDLL("/usr/lib/libSystem.B.dylib").responsibility_get_pid_responsible_for_pid
            _RESP.restype, _RESP.argtypes = ctypes.c_int, [ctypes.c_int]
        return max(0, int(_RESP(int(pid))))
    except Exception:
        return 0


def _bundle_of_pid(pid: int) -> str:
    try:
        from AppKit import NSRunningApplication
        a = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        return str(a.bundleIdentifier() or "") if a else ""
    except Exception:
        return ""


def _path_of_pid(pid: int) -> str:
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = ctypes.create_string_buffer(4096)
        n = lib.proc_pidpath(ctypes.c_int(int(pid)), buf, ctypes.c_uint32(4096))
        return buf.value[:n].decode("utf-8", "replace") if n > 0 else ""
    except Exception:
        return ""


def _exe(pid: int) -> str:
    from .procs import exe_of_pid
    return exe_of_pid(pid)


_app_cache: dict[tuple[int, str], str] = {}


def app_of_process(pid: int, bundle: str) -> str:
    """The short app name for an audio process: its responsible app when that is a known one, else its own
    bundle id, else the .app (or daemon) it runs from, else its bundle id's last part or its exe name."""
    key = (int(pid), bundle or "")
    if key in _app_cache:
        return _app_cache[key]
    app = ""
    resp = _responsible_pid(pid) if pid else 0
    if resp and resp != pid:
        app = known_app(_bundle_of_pid(resp)) or app_of_path(_path_of_pid(resp))
    app = app or known_app(bundle) or (app_of_path(_path_of_pid(pid)) if pid else "")
    if not app:
        last = (bundle or "").lower().rsplit(".", 1)[-1]
        app = last if last and last not in _GENERIC else (_exe(pid) if pid else "")
    _app_cache[key] = app
    return app


_first_seen: dict[str, float] = {}
_status = {"mic_api": "unknown", "accessibility": "unknown"}


def _pool():
    try:
        import objc
        return objc.autorelease_pool()  # a long-lived thread has no pool: AppKit objects would pile up
    except Exception:
        import contextlib
        return contextlib.nullcontext()


def read_consent() -> list:
    """detect.read_consent for the Mac: one MicUse per app capturing now (start = when we first saw it).
    talking: any of that app's processes plays sound (Chrome may capture and play from different helpers)."""
    from ...detect import MicUse
    now = time.time()
    with _pool():
        procs = audio_processes()
        if procs is None:
            if _status["mic_api"] != "unavailable":
                log.warning("Core Audio's process list can't be read: no call can be detected")
            _status["mic_api"] = "unavailable"
            return []
        _status["mic_api"] = "ok"
        capturing, playing = set(), set()
        for pid, bundle, cap, play in procs:
            app = app_of_process(pid, bundle)
            if not app:
                continue
            if cap:
                capturing.add(app)
            if play:
                playing.add(app)
        live = {(p, b or "") for p, b, _c, _o in procs}
        for k in [k for k in _app_cache if k not in live]:
            del _app_cache[k]
    for gone in [a for a in _first_seen if a not in capturing]:
        del _first_seen[gone]
    uses = []
    for app in sorted(capturing):
        start = _first_seen.setdefault(app, now)
        uses.append(MicUse(app=app, in_use=True, start=int(start * 1000), stop=0, nonpackaged=False,
                           talking=app in playing))
    return uses


def running_apps() -> set[str]:
    from AppKit import NSWorkspace
    with _pool():
        return {app_of_bundle(str(a.bundleIdentifier() or "")) for a in NSWorkspace.sharedWorkspace().runningApplications()}


def foreground_app() -> str:
    from AppKit import NSWorkspace
    with _pool():
        a = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app_of_bundle(str(a.bundleIdentifier() or "")) if a else ""


def _ax_trusted() -> bool | None:
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return None


def _set_ax(state: str) -> None:
    if _status["accessibility"] != state:
        if state != "granted":
            log.warning("browser window titles unreadable (Accessibility: %s): a browser call counts only by "
                        "its two-way audio", state)
        _status["accessibility"] = state


def window_titles() -> list[tuple[str, str]]:
    """(title, app) of the windows of running browsers (Accessibility; only they matter to the detector)."""
    trusted = _ax_trusted()
    if trusted is False:
        _set_ax("not granted")
        return []
    from AppKit import NSWorkspace
    from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateApplication,
                                     AXUIElementSetMessagingTimeout)
    out, errors = [], set()
    with _pool():
        for a in NSWorkspace.sharedWorkspace().runningApplications():
            app = app_of_bundle(str(a.bundleIdentifier() or ""))
            if app not in BROWSER_APPS:
                continue
            el = AXUIElementCreateApplication(a.processIdentifier())
            AXUIElementSetMessagingTimeout(el, 0.05)
            err, wins = AXUIElementCopyAttributeValue(el, "AXWindows", None)
            if err not in (0, -25212):  # kAXErrorNoValue: no windows
                errors.add(int(err))
            for w in (wins or []) if err == 0 else []:
                e2, title = AXUIElementCopyAttributeValue(w, "AXTitle", None)
                if e2 == 0 and title:
                    out.append((str(title), app))
    if errors and not out:  # every browser refused: a busy one times out now and then, that alone isn't news
        _set_ax(f"error {min(errors)}")
    else:
        _set_ax("granted" if trusted else "unknown")
    return out


def health() -> dict[str, str]:
    """What the last reads could see: mic_api ok|unavailable, accessibility granted|not granted|error N."""
    return dict(_status)
