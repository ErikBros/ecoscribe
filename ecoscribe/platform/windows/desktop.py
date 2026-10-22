"""Small desktop helpers on Windows: open a file or folder, list mic names, the webview backend
(macOS: ecoscribe/platform/macos/desktop.py)."""
from __future__ import annotations

import os


def startfile(path: str) -> None:
    """The default app for a file, Explorer for a folder."""
    os.startfile(path)


def reveal(path: str) -> None:
    """Explorer on the file's folder with the file selected (dictado-yq9)."""
    import subprocess
    subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')  # noqa: S602,S603,S607 (explorer wants /select,"path" as is)


def input_names() -> list[str]:
    """Names of the MME input devices (what Settings offers as mics)."""
    import sounddevice as sd
    names = []
    for d in sd.query_devices():
        host = sd.query_hostapis(d["hostapi"])["name"]
        if host == "MME" and d["max_input_channels"] > 0 and "Sound Mapper" not in d["name"]:
            if d["name"] not in names:
                names.append(d["name"])
    return names


WEBVIEW_GUI = "edgechromium"
DEFAULT_MIC_LABEL = "Windows default"


def system_dark() -> bool:
    """dictado-u9h: Windows is set to dark for apps (Settings > Personalisation > Colours > Choose your app mode)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Windows 10 20H1 and later


def dark_title_bar(title: str, dark: bool) -> bool:
    """dictado-u9h: this process's window called `title` gets a dark (or light) title bar, like Windows 11
    apps in dark mode. False when the window isn't found or Windows is too old for it."""
    import ctypes
    import ctypes.wintypes as wt

    import win32gui
    import win32process
    found = []

    def mine(hwnd, _):
        if win32gui.GetWindowText(hwnd) == title and win32process.GetWindowThreadProcessId(hwnd)[1] == os.getpid():
            found.append(hwnd)
        return True
    win32gui.EnumWindows(mine, None)
    ok = False
    for hwnd in found:
        v = wt.BOOL(1 if dark else 0)
        ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
                                                        ctypes.byref(v), ctypes.sizeof(v)) == 0 or ok
        if ok:  # repaint the frame now, not at the next focus change
            win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    return ok
