"""Which macOS privacy permissions Ecoscribe has (pre-mortem #3: never fail silently after a rebuild).

Each entry: key -> (label the user sees in System Settings, the Settings pane URL, granted?).
"""
from __future__ import annotations

PANES = {
    "accessibility": ("Accessibility", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    "input": ("Input Monitoring", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"),
    "microphone": ("Microphone", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"),
    "audio": ("Screen & System Audio Recording",
              "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"),
}


def status() -> dict[str, bool]:
    out = {}
    try:
        from ApplicationServices import AXIsProcessTrusted
        out["accessibility"] = bool(AXIsProcessTrusted())
    except Exception:
        out["accessibility"] = False
    try:
        import Quartz
        out["input"] = bool(Quartz.CGPreflightListenEventAccess())
        out["audio"] = bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        out["input"] = out["audio"] = False
    try:
        import AVFoundation as AV
        out["microphone"] = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeAudio) == 3
    except Exception:
        out["microphone"] = False
    return out


DICTATION = ("accessibility", "input", "microphone")


def missing(needed=DICTATION, st: dict | None = None) -> list[str]:
    """Labels of the permissions dictation needs and doesn't have (system audio only matters for meetings)."""
    st = status() if st is None else st
    return [PANES[k][0] for k in needed if not st.get(k)]


def watch(on_change, interval: float = 15.0, stop=None, check=status) -> None:
    """Check now, then again every `interval` s while anything is still off, and call
    on_change(new, old) on every change (old is None the first time). A permission granted
    while Ecoscribe runs (the mic is asked for at the first dictation) shows up within seconds,
    not at the next start (dictado-6qp). Returns when everything is on, or when `stop` is set."""
    import threading
    stop = stop or threading.Event()
    last = None
    while True:
        st = check()
        if st != last:
            on_change(st, last)
            last = st
        if all(st.values()) or stop.wait(interval):
            return


_asked: set[str] = set()


def _mic_status() -> int | None:
    """AVAuthorizationStatus: 0 not determined, 1 restricted, 2 denied, 3 authorized."""
    try:
        import AVFoundation as AV
        return int(AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeAudio))
    except Exception:
        return None


def can_ask(key: str) -> bool:
    """True while macOS can still show its own prompt for `key`. Until an app has asked, it isn't
    listed in that Settings pane at all, so "Open settings" would lead nowhere (dictado-zpz)."""
    if key == "microphone":
        return _mic_status() == 0  # not determined
    return key in PANES and key not in _asked


def ask(key: str) -> None:
    """macOS's own prompt for `key`; it also adds Ecoscribe to that Settings pane."""
    _asked.add(key)
    if key == "microphone":
        import AVFoundation as AV
        AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeAudio, lambda ok: None)
    elif key == "accessibility":
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    elif key == "input":
        import Quartz
        Quartz.CGRequestListenEventAccess()
    elif key == "audio":
        import Quartz
        Quartz.CGRequestScreenCaptureAccess()


def ask_or_open(key: str) -> str:
    """The setup's button: macOS's prompt the first time, the Settings pane after that."""
    if can_ask(key):
        try:
            ask(key)
            return "asked"
        except Exception:
            pass
    open_pane(key)
    return "opened"


def open_pane(key: str) -> None:
    import subprocess
    subprocess.Popen(["open", PANES[key][1]])
