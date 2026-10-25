"""Small desktop helpers on macOS: open a file or folder, list mic names, the webview backend."""
from __future__ import annotations

import subprocess


def startfile(path: str) -> None:
    """os.startfile on Windows: the default app for a file, Finder for a folder."""
    subprocess.Popen(["open", str(path)])


def reveal(path: str) -> None:
    """Finder on the file's folder with the file selected (dictado-yq9)."""
    subprocess.Popen(["open", "-R", str(path)])


def input_names() -> list[str]:
    """Names of the Core Audio input devices (what Settings offers as mics)."""
    import sounddevice as sd
    names = []
    for d in sd.query_devices():
        host = sd.query_hostapis(d["hostapi"])["name"]
        if host == "Core Audio" and d["max_input_channels"] > 0 and d["name"] not in names:
            names.append(d["name"])
    return names


WEBVIEW_GUI = "cocoa"
DEFAULT_MIC_LABEL = "System default"


def system_dark() -> bool:
    """dictado-u9h: macOS is in Dark appearance (System Settings > Appearance)."""
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=2)
        return out.stdout.strip().lower() == "dark"
    except Exception:
        return False


def dark_title_bar(title: str, dark: bool) -> bool:
    """dictado-zkh: this process's window called `title` takes the page's look, so a forced Light or Dark
    (Settings > Appearance) colours its title bar too; with Match macOS the page asks for the system's.
    AppKit wants the main thread: the change is queued there. False when no such window exists."""
    from AppKit import NSAppearance, NSApplication
    from PyObjCTools import AppHelper
    wins = [w for w in NSApplication.sharedApplication().windows() if str(w.title() or "") == title]
    if not wins:
        return False
    look = NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua")

    def apply():
        for w in wins:
            w.setAppearance_(look)
    AppHelper.callAfter(apply)
    return True
