"""The small icons outside the window (dictado-2yb): one set for the pill and the prompt box, on both
platforms, on the window's 24 grid."""
import sys

import pytest

from ecoscribe import glyphs


def _points(part):
    kind = part[0]
    if kind == "rrect":
        return [part[1:3], part[3:5]]
    if kind in ("circle", "dot", "arc"):
        _, x, y, r = part[:4]
        return [(x - r, y - r), (x + r, y + r)]
    return part[2]


@pytest.mark.parametrize("name", list(glyphs.GLYPHS))
def test_each_glyph_stays_inside_the_window_icons_drawing_area(name):
    for part in glyphs.GLYPHS[name]:
        assert part[0] in ("rrect", "circle", "arc", "poly", "dot")
        for x, y in _points(part):
            assert 2.5 <= x <= 21.5 and 2.5 <= y <= 21.5, (name, part)


def test_placed_scales_around_the_centre():
    parts = glyphs.placed("end?", 100, 50, 48)  # twice the grid
    assert parts[0] == ("circle", 100, 50, 16)
    assert parts[1] == ("poly", False, [(100, 41), (100, 50), (106, 54)])


def test_every_prompt_and_notice_icon_has_a_glyph():
    """The prompt kinds with their own icon are glyphs (start is the clay dot, the rest the document);
    the pill's notices too."""
    from ecoscribe.meetui import Prompt
    for kind in ("end?", "nomic", "cmdoff"):
        assert f"{kind} (" in Prompt.__doc__ and kind in glyphs.GLYPHS
    assert {"nomic", "warn", "doc"} <= set(glyphs.GLYPHS)


@pytest.mark.skipif(sys.platform != "win32", reason="platform/windows is never imported on macOS")
@pytest.mark.parametrize("name", list(glyphs.GLYPHS))
def test_the_windows_picture_draws_it_smooth_on_a_clear_sheet(name):
    pytest.importorskip("PIL")
    from ecoscribe.platform.windows import pillart as A
    im = A.glyph_image(name, 38, 22, "#9fb4c7", 1.8)
    assert im.mode == "RGBA" and im.size == (38, 38)
    alpha = im.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0 and alpha.getpixel((37, 37)) == 0  # nothing outside the icon
    assert alpha.getextrema()[1] == 255  # the line is solid
    assert any(0 < a < 255 for a in alpha.getdata())  # and its edges are smoothed
