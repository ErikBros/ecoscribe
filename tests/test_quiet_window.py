"""The real Ecoscribe window, driven without the user's mouse or keyboard (dictado-0up).

A test copy of the window opens hidden and off-screen (ECOSCRIBE_QUIET_WINDOW), with its own empty
data and config folders. Playwright talks to its WebView2 over the debug port: clicks, typing and
screenshots go through the browser engine, never the mouse or keyboard, and the window never takes
focus while it is driven. Unlike the jsdom smoke test this is the real page with the real Python
bridge and real layout. Needs Windows and `pip install playwright` (no browser download: it attaches
to WebView2); skipped otherwise.

One limit, measured 2026-10-22: pywebview's WinForms backend calls Form.Show() even for a hidden
window, which takes focus for about 60 ms at start (WS_EX_NOACTIVATE, SW_SHOWNOACTIVATE and a WMI
launch don't stop it). So the test is marked `win`: it waits for 45 s of idle like the other desktop
tests, and its focus check starts once the page is up.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.win, pytest.mark.win32_api, pytest.mark.skipif(sys.platform != "win32", reason="WebView2 is Windows")]
pw = pytest.importorskip("playwright.sync_api", reason="pip install playwright")

APP = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _focus_pid() -> int:
    import win32gui
    import win32process
    return win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1]


class FocusWatch:
    """Samples which process has focus every 50 ms while the test runs: the test window must never."""

    def __init__(self):
        import threading
        self.pids, self._stop = set(), threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        while not self._stop.is_set():
            self.pids.add(_focus_pid())
            time.sleep(0.05)

    def stop(self) -> set:
        self._stop.set()
        self._t.join(2)
        return self.pids


@pytest.fixture
def window(tmp_path):
    port = _free_port()
    env = {**os.environ, "ECOSCRIBE_QUIET_WINDOW": str(port),
           "LOCALAPPDATA": str(tmp_path / "local"), "APPDATA": str(tmp_path / "roaming"),
           "WEBVIEW2_USER_DATA_FOLDER": str(tmp_path / "webview2")}
    (tmp_path / "local" / "ecoscribe").mkdir(parents=True)
    (tmp_path / "local" / "ecoscribe" / "welcome_done").write_text("test")  # straight to Home, not the setup
    si = subprocess.STARTUPINFO()  # the window's first ShowWindow uses this: shown without being activated
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 4  # SW_SHOWNOACTIVATE
    proc = subprocess.Popen([sys.executable, "-m", "ecoscribe", "--ui", "--page", "inicio"], cwd=str(APP), env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=si)
    with pw.sync_playwright() as p:
        browser = None
        end = time.monotonic() + 60
        while browser is None:
            try:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            except Exception:
                if time.monotonic() > end or proc.poll() is not None:
                    proc.kill()
                    pytest.fail(f"the test window never opened its debug port (exit {proc.poll()})")
                time.sleep(0.5)
        page = None
        while page is None:
            page = next((pg for c in browser.contexts for pg in c.pages if pg.url.startswith("file:")), None)
            if page is None:
                if time.monotonic() > end:
                    proc.kill()
                    pytest.fail("the test window never loaded its page")
                time.sleep(0.3)
        page.wait_for_selector("body[data-ready='1']", timeout=30000)
        watch = FocusWatch()  # from here on: the start-up flash is pywebview's Show(), see above
        try:
            yield page, (watch, proc.pid), tmp_path
        finally:
            browser.close()
            proc.kill()
            proc.wait(10)


def test_real_window_is_driven_without_focus_or_mouse(window):
    page, (watch, pid), tmp_path = window
    page.get_by_role("button", name="Settings").first.click()
    page.wait_for_selector("#settings", state="visible")
    page.get_by_role("button", name="Languages and words").click()
    words = page.locator("#f-vocabulary")
    words.fill("Quintavelle")
    assert page.locator("#savebar").is_visible()  # the real page reacted to typing
    page.screenshot(path=str(tmp_path / "settings.png"))
    assert (tmp_path / "settings.png").stat().st_size > 10_000
    page.get_by_role("button", name="Meetings").first.click()
    page.wait_for_selector("#r-list-view", state="visible")
    assert page.evaluate("typeof window.pywebview.api.list_sessions") == "function"  # the real Python bridge
    assert pid not in watch.stop(), "the test window took focus"
