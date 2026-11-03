"""Moving the Mac pill by dragging it (dictado-8dy): click-through except on the pill, drag, drop, double-click.
The panel is a fake: nothing is shown and the mouse is never moved."""
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")

VIEW = {"label": "Taking notes 0:42", "short": "0:42", "line": "", "busy": False}
WORK = (0.0, -1000.0, 1600.0, -20.0)  # one screen: visible area in meetui's coordinates (y down)


class Panel:
    def __init__(self):
        self.origin = [700.0, 40.0]
        self.size = [92.0, 30.0]
        self.ignores = True

    def frame(self):
        return SimpleNamespace(origin=SimpleNamespace(x=self.origin[0], y=self.origin[1]),
                               size=SimpleNamespace(width=self.size[0], height=self.size[1]))

    def setFrameOrigin_(self, xy):
        self.origin = [float(xy[0]), float(xy[1])]

    def setContentSize_(self, wh):
        self.size = [float(wh[0]), float(wh[1])]

    def setIgnoresMouseEvents_(self, on):
        self.ignores = bool(on)

    def orderFrontRegardless(self):
        pass

    def orderOut_(self, x):
        pass


@pytest.fixture
def pill(monkeypatch, tmp_path):
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe.platform.macos import shell
    o = shell.Overlay(level_fn=lambda: 0.0)
    o.panel = Panel()
    o.view.setFrame_ = lambda r: None
    monkeypatch.setattr(shell, "_work_at", lambda x, y: WORK)
    monkeypatch.setattr(shell, "_bottom_center", lambda w, h, lift=0: (800 - w / 2, 40.0))
    mouse = SimpleNamespace(x=0.0, y=0.0, down=False)
    monkeypatch.setattr(shell, "_mouse", lambda: SimpleNamespace(x=mouse.x, y=mouse.y))
    monkeypatch.setattr(shell, "_primary_down", lambda: mouse.down)
    o.remember_at(tmp_path / "pill.json")
    clock = SimpleNamespace(t=100.0)
    monkeypatch.setattr(shell.time, "monotonic", lambda: clock.t)
    return o, mouse, clock, tmp_path / "pill.json"


def _step(o, mouse, clock, x, y, down):
    mouse.x, mouse.y, mouse.down = x, y, down
    clock.t += 0.05
    o.tick()


def test_clicks_pass_through_until_the_mouse_is_on_the_chip(pill):
    o, mouse, clock, _ = pill
    o.set_meeting(VIEW)
    _step(o, mouse, clock, 100, 500, False)
    assert o.panel.ignores
    x, y = o.panel.origin
    _step(o, mouse, clock, x + 10, y + 10, False)
    assert not o.panel.ignores


def test_drag_moves_the_chip_and_the_spot_is_kept(pill):
    from ecoscribe import meetui
    o, mouse, clock, path = pill
    o.set_meeting(VIEW)
    x, y = o.panel.origin
    _step(o, mouse, clock, x + 10, y + 10, False)  # the chip opens (wider), still centred
    x, y = o.panel.origin
    _step(o, mouse, clock, x + 10, y + 10, True)
    _step(o, mouse, clock, x - 290, y + 410, True)  # 300 left, 400 up (AppKit's y grows up)
    _step(o, mouse, clock, x - 290, y + 410, False)
    assert o.panel.origin[0] == pytest.approx(x - 300) and o.panel.origin[1] == pytest.approx(y + 400)
    spot = meetui.load_spot(path)
    assert spot == (int(x - 300 + o.w / 2), int(-(y + 400)))
    o.set_meeting(None)
    o.recording(clock.t)  # the dictating pill shows at the same spot, centred on it
    assert o.panel.origin[0] + o.w / 2 == pytest.approx(spot[0], abs=1) and o.panel.origin[1] == pytest.approx(-spot[1], abs=1)


def test_double_click_puts_it_back(pill):
    from ecoscribe import meetui
    o, mouse, clock, path = pill
    meetui.save_spot(path, (300, -500))
    o.remember_at(path)
    o.set_meeting(VIEW)
    x, y = o.panel.origin
    assert (x, y) != (800 - o.w / 2, 40.0)
    _step(o, mouse, clock, x + 5, y + 5, False)  # the chip opens
    x, y = o.panel.origin
    for down in (True, False, True, False):
        _step(o, mouse, clock, x + 5, y + 5, down)
    assert tuple(o.panel.origin) == (800 - o.w / 2, 40.0) and meetui.load_spot(path) is None


def test_the_dictating_pill_drags_too_but_not_a_notice(pill):
    o, mouse, clock, _ = pill
    o.recording(clock.t)
    x, y = o.panel.origin
    _step(o, mouse, clock, x + 10, y + 10, False)
    _step(o, mouse, clock, x + 10, y + 10, True)
    _step(o, mouse, clock, x + 110, y + 10, True)
    assert o.panel.origin[0] == pytest.approx(x + 100)
    _step(o, mouse, clock, x + 110, y + 10, False)
    o.idle()
    o.flash("No mic", 2.0)
    _step(o, mouse, clock, o.panel.origin[0] + 5, o.panel.origin[1] + 5, False)
    assert o.panel.ignores  # a notice never catches the mouse


def test_a_spot_off_screen_is_pulled_back(pill):
    from ecoscribe import meetui
    o, mouse, clock, path = pill
    meetui.save_spot(path, (5000, 100))  # right of the screen and below it
    o.remember_at(path)
    o.set_meeting(VIEW)
    left, bottom = o.panel.origin
    assert left + o.w <= WORK[2] and -bottom <= WORK[3]
