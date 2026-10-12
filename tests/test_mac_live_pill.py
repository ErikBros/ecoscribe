"""The Mac dictation pill (dictado-dlm, dictado-6oe.9): breathing dot, scrolling waveform, timer, the
keycaps hint, one live line. Drawn offscreen, nothing shown on screen."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")


@pytest.fixture
def overlay():
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe.platform.macos import shell
    o = shell.Overlay(level_fn=lambda: 0.0)
    o._place_and_show = lambda: None  # never on screen
    o._hide = lambda: None
    return o


def texts(o):
    return [t[0] for t in o.view.spec["texts"]]


def test_the_first_seconds_show_the_cancel_keys_then_the_waveform(overlay):
    from ecoscribe.platform.macos import shell
    overlay.recording(time.monotonic() - 0.5)
    overlay.tick()
    assert [c[4] for c in overlay.view.spec["caps"]] == ["Right ⌘", "Esc"] and "cancels" in texts(overlay)
    assert "lines" not in overlay.view.spec
    overlay._t0 = time.monotonic() - shell.HINT_S - 0.1
    overlay.tick()
    assert "caps" not in overlay.view.spec and overlay.view.spec["lines"]
    assert overlay.w == overlay._rw >= shell.RW and overlay.h == shell.RH


def test_waveform_scrolls_in_from_the_right_and_keeps_the_last_n(overlay):
    from ecoscribe.platform.macos import shell
    overlay.recording(time.monotonic() - 5)
    for v in (0.0, 0.0, 0.3):
        overlay.level_fn = lambda v=v: v
        overlay.tick()
    lines = overlay.view.spec["lines"]
    assert len(lines) == 4  # recording() ticks once itself
    assert lines[-1][0] > lines[0][0] and lines[-1][0] > shell.WAVE_X + shell.WAVE_W - 10  # newest on the right
    loud, quiet = lines[-1], lines[0]
    assert loud[2] - loud[1] > quiet[2] - quiet[1] and loud[3] == shell.P.AEGEAN_PALE and quiet[3] == shell.P.PILL_OFF
    for _ in range(shell.WAVE_N + 10):
        overlay.tick()
    assert len(overlay.view.spec["lines"]) == shell.WAVE_N


def test_dot_breathes_lit_while_loud_and_blinks_when_quiet(overlay):
    from ecoscribe.platform.macos import shell
    overlay.recording(time.monotonic() - 5)
    overlay.level_fn = lambda: 0.3
    overlay.tick()
    assert [o[3] for o in overlay.view.spec["ovals"]] == [shell.P.TILE_HALO, shell.P.CLAY_BRIGHT]
    overlay.level_fn = lambda: 0.0
    seen = set()
    for t0 in (5.0, 5.5):  # two half-second phases: one lit, one dim
        overlay._t0 = time.monotonic() - t0 - 0.2
        overlay.tick()
        seen.add(tuple(o[3] for o in overlay.view.spec["ovals"]))
    assert (shell.P.TILE_DIM,) in seen and (shell.P.TILE_HALO, shell.P.CLAY_BRIGHT) in seen


def test_timer_is_right_aligned_and_does_not_move_the_waveform(overlay):
    overlay.recording(time.monotonic() - 7)
    overlay._t0 -= 5
    overlay.tick()
    t = overlay.view.spec["texts"][0]
    assert t[0] == "0:12"
    from ecoscribe.platform.macos import shell
    assert abs(t[1] + shell._text_width("0:12", shell.TIMER_FONT, True) - (overlay.w - 16)) < 0.5


def test_live_text_grows_the_box_and_shows_the_newest_words(overlay):
    from ecoscribe.platform.macos import shell
    overlay.recording(time.monotonic() - 5)
    overlay.tick()
    assert overlay.h == shell.RH
    long = " ".join(f"word{i}" for i in range(80))
    overlay.live(long)
    overlay.tick()
    assert (overlay.w, overlay.h) == (shell.LW, shell.LH)
    line = texts(overlay)[-1]
    assert line.startswith("…") and line.endswith("word79")
    assert shell._text_width(line, shell.LIVE_FONT, False) <= shell.LW - 36


def test_live_text_only_while_recording_and_cleared_after(overlay):
    from ecoscribe.platform.macos import shell
    overlay.live("too early")
    assert overlay.live_text == ""
    overlay.recording(time.monotonic())
    overlay.live("hola")
    overlay.busy()
    assert overlay.live_text == "" and overlay.h == shell.RH
    assert "Writing it down" in texts(overlay) and len(overlay.view.spec["arcs"]) == 2
    overlay.recording(time.monotonic())
    overlay.tick()
    assert (overlay.w, overlay.h) == (overlay._rw, shell.RH)  # a new dictation starts without the old text


def test_busy_is_a_capsule_with_a_turning_arc(overlay, monkeypatch):
    from ecoscribe.platform.macos import shell
    clock = [100.0]
    monkeypatch.setattr(shell.time, "monotonic", lambda: clock[0])
    overlay.busy()
    assert overlay.h == shell.RH and "Writing it down" in texts(overlay)
    ring, arc = overlay.view.spec["arcs"]
    assert (ring[4], ring[5]) == (360, shell.P.PILL_OFF) and (arc[4], arc[5]) == (90, shell.P.AEGEAN_PALE)
    clock[0] += 0.25  # a quarter second: a quarter turn
    overlay.tick()
    assert abs((overlay.view.spec["arcs"][1][3] - arc[3]) % 360 - 90) < 1e-6


def test_waveform_colors():
    from ecoscribe.platform.macos import shell
    assert [shell.wave_color(v) for v in (0.0, 0.1, 0.5)] == [shell.P.PILL_OFF, shell.P.AEGEAN_MID, shell.P.AEGEAN_PALE]


def test_cancels_is_pale(overlay):
    from ecoscribe.platform.macos import shell
    overlay.recording(time.monotonic())
    assert [t for t in overlay.view.spec["texts"] if t[0] == "cancels"][0][5] == shell.P.AEGEAN_PALE


def test_flash_goes_through_notice(overlay):
    from ecoscribe.platform.macos import shell
    overlay.flash("Next dictation: English")
    spec = overlay.view.spec
    assert spec["badges"][0][4] == "EN" and texts(overlay) == ["Next dictation in English"] and overlay.h == shell.RH
    overlay.flash("Didn't hear you (MacBook Pro Microphone)")
    spec = overlay.view.spec
    assert spec["glyphs"] == [("nomic", 24, shell.RH / 2, shell.P.CLAY_BRIGHT)]
    assert texts(overlay) == ["Didn't hear anything", "MacBook Pro Microphone"] and spec["texts"][1][5] == shell.P.AEGEAN_MUTED
    assert spec["texts"][1][1] > spec["texts"][0][1] and overlay.w > spec["texts"][1][1] + shell._text_width("MacBook Pro Microphone", shell.DETAIL_FONT, False)
    overlay.flash("Couldn't paste")
    assert overlay.view.spec["glyphs"][0][0] == "warn"
    overlay.flash("Copied")
    spec = overlay.view.spec
    assert "glyphs" not in spec and "badges" not in spec and spec["texts"][0][6] is True  # no icon: centred
    assert overlay.w == 120


def test_keycaps_from_each_hint():
    from types import SimpleNamespace
    from ecoscribe.platform.macos import shell
    tap = shell.cancel_hint(SimpleNamespace(key="rcmd", hold_to_talk=False))
    hold = shell.cancel_hint(SimpleNamespace(key="rcmd", hold_to_talk=True))
    assert shell.keycaps(tap) == (["Right ⌘", "Esc"], "cancels")
    assert shell.keycaps(hold) == (["Right ⌘", "Esc"], "cancels")
    assert shell.keycaps("Press F5 again to finish · Cancel: menu bar") == ([], "")


def test_fit_tail_keeps_the_end():
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe.platform.macos import shell
    assert shell.fit_tail("short one", 400, 13) == "short one"
    out = shell.fit_tail("a" * 300, 100, 13)
    assert out.startswith("…") and shell._text_width(out, 13, False) <= 100


def test_ui_forwards_live_text_to_the_mac_pill():
    from ecoscribe.platform.macos import shell
    assert hasattr(shell.Overlay, "live")  # ui.Ui.live only forwards to an overlay that has one
