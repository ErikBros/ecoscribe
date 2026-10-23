"""Open Ecoscribe finds the app's own window, not a look-alike with the same title (dictado-le7)."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows window lookup")


def _desktop(monkeypatch, windows):
    import win32gui
    by = {w["hwnd"]: w for w in windows}

    def enum(cb, extra):
        for w in windows:
            if not cb(w["hwnd"], extra):
                raise win32gui.error(0, "EnumWindows", "stopped")  # what pywin32 does when the callback says stop

    monkeypatch.setattr(win32gui, "EnumWindows", enum)
    monkeypatch.setattr(win32gui, "GetWindowText", lambda h: by[h]["title"])
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda h: by[h]["visible"])
    monkeypatch.setattr(win32gui, "GetClassName", lambda h: by[h]["cls"])


TAB = {"hwnd": 1, "title": "Ecoscribe", "visible": True, "cls": "Windows.Internal.Shell.TabProxyWindow"}
QUIET = {"hwnd": 2, "title": "Ecoscribe", "visible": False, "cls": "WindowsForms10.Window.8.app.0.aec740_r23_ad1"}
REAL = {"hwnd": 3, "title": "Ecoscribe", "visible": True, "cls": "WindowsForms10.Window.8.app.0.aec740_r23_ad1"}
OTHER = {"hwnd": 4, "title": "Notes", "visible": True, "cls": "WindowsForms10.Window.8.app.0.aec740_r23_ad1"}


def test_a_browser_tab_or_a_hidden_test_copy_is_not_the_window(monkeypatch):
    from ecoscribe.platform.windows import ipc
    _desktop(monkeypatch, [TAB, QUIET, OTHER])
    assert ipc.find_ui() == 0
    assert ipc.focus_ui() is False  # so Open starts a window


def test_the_real_window_is_found_behind_a_look_alike(monkeypatch):
    from ecoscribe.platform.windows import ipc
    _desktop(monkeypatch, [TAB, QUIET, REAL, OTHER])
    assert ipc.find_ui() == 3
