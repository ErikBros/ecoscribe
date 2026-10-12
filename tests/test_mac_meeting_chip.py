"""The Mac meeting pill as a chip that opens on hover (dictado-f6o) and the prompt as a dark card
(dictado-jfz). Drawn offscreen: nothing is shown and the mouse is never moved."""
import sys
import time
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")

VIEW = {"label": "Taking notes 12:34", "short": "12:34", "line": "we move the release to Thursday", "busy": False}


@pytest.fixture
def overlay():
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe.platform.macos import shell
    o = shell.Overlay(level_fn=lambda: 0.0)
    o._place_and_show = lambda: setattr(o, "visible", True)  # never on screen
    o._hide = lambda: setattr(o, "visible", False)
    return o


def test_meeting_sits_as_a_chip_with_the_timer(overlay):
    from ecoscribe.platform.macos import shell
    overlay.set_meeting(VIEW)
    assert (overlay.w, overlay.h) == (shell.CW, shell.CH)
    assert [t[0] for t in overlay.view.spec["texts"]] == ["12:34"]


def test_mouse_on_the_chip_opens_the_full_pill_and_leaving_closes_it(overlay, monkeypatch):
    from ecoscribe.platform.macos import shell
    frame = SimpleNamespace(origin=SimpleNamespace(x=500, y=80), size=SimpleNamespace(width=92, height=30))
    overlay.panel = SimpleNamespace(frame=lambda: frame, setContentSize_=lambda s: None, orderOut_=lambda x: None)
    overlay.set_meeting(VIEW)
    monkeypatch.setattr(shell, "_mouse", lambda: SimpleNamespace(x=520, y=95))  # inside, AppKit's y-up coords
    overlay.tick()
    assert overlay.open and (overlay.w, overlay.h) == (shell.MW, shell.MH)
    assert [t[0] for t in overlay.view.spec["texts"]] == [VIEW["label"], VIEW["line"]]
    monkeypatch.setattr(shell, "_mouse", lambda: SimpleNamespace(x=520, y=400))  # well above it
    overlay.tick()
    assert not overlay.open and (overlay.w, overlay.h) == (shell.CW, shell.CH)


def test_hover_flips_appkit_y(overlay, monkeypatch):
    """AppKit's y grows upward: a mouse just below the panel's bottom edge is outside, not inside."""
    from ecoscribe.platform.macos import shell
    frame = SimpleNamespace(origin=SimpleNamespace(x=500, y=80), size=SimpleNamespace(width=92, height=30))
    overlay.panel = SimpleNamespace(frame=lambda: frame)
    overlay.visible = True
    for y, inside in ((95, True), (112, True), (60, False), (130, False)):
        monkeypatch.setattr(shell, "_mouse", lambda y=y: SimpleNamespace(x=540, y=y))
        assert overlay._hover() is inside, y


def test_prompt_card_language_chip_and_countdown(monkeypatch):
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe import meetui
    from ecoscribe.platform.macos import shell
    monkeypatch.setattr(meetui, "LANGS", [("en", "English"), ("sv", "Swedish"), ("es", "Spanish")])
    monkeypatch.setattr(shell, "_bottom_center", lambda w, h, lift=0: (-5000, -5000))  # off every screen
    got = []
    pw = shell.PromptWindow(None, lambda p, c, lang: got.append((c, lang)))
    p = meetui.Prompt("start", "zoom", "en", time.monotonic())
    pw.show(p)
    try:
        assert pw.lang_chip.title() == "English"
        assert pw._btns["ahora_no"].title() == "Not now (10)"
        p.opened_at -= 3
        pw.tick()
        assert pw._btns["ahora_no"].title() == "Not now (7)"
        pw._pick_lang("Spanish")
        assert pw.lang_chip.title() == "Spanish"
        pw._btns["transcribir"].mouseDown_(None)  # the primary button answers with the chosen language
        assert got == [("transcribir", "es")] and pw.panel is None
    finally:
        pw._close()


def test_prompt_card_has_its_tile_and_a_draining_countdown_line(monkeypatch):
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe import meetui
    from ecoscribe.platform.macos import shell
    monkeypatch.setattr(shell, "_bottom_center", lambda w, h, lift=0: (-5000, -5000))  # off every screen
    pw = shell.PromptWindow(None, lambda *a: None)
    p = meetui.Prompt("end?", None, None, time.monotonic())
    pw.show(p)
    try:
        box = pw.panel.contentView()
        assert box.kind == "end?" and box.left == 1.0
        assert pw.panel.frame().size.width >= shell.PromptWindow.PW
        p.opened_at -= p.timeout_s / 2
        pw.tick()
        assert abs(box.left - 0.5) < 0.05
        title = [v for v in box.subviews() if hasattr(v, "stringValue") and v.stringValue() == p.title][0]
        assert title.frame().origin.x >= shell.PromptWindow.PAD + shell.PromptWindow.TILE  # beside the tile
        primary = pw._btns["parar"]
        assert primary._fill == shell.P.PAPER and primary._ink == shell.P.INK
        shell.snapshot(box, __import__("pathlib").Path("/dev/null"))  # draws every glyph path without error
    finally:
        pw._close()
