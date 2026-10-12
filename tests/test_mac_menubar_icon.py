"""The menu-bar icon (dictado-6oe.1): the logo as a template that fills its slot, dot included."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")


def test_template_is_the_cropped_mark_with_its_dot():
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe.platform.macos import shell
    img = shell._template_mic()
    w, h = img.size
    left, top, right, bottom = img.getbbox()
    assert right - left >= 0.85 * w  # fills the slot: no circle padding around a tiny glyph
    assert all(p[:3] == (0, 0, 0) for p in img.getdata() if p[3])  # a template: black and alpha only
    alpha = img.split()[3]
    mid = top + (bottom - top) // 2
    row = [alpha.getpixel((x, mid)) for x in range(w)]
    runs, inside = 0, False
    for a in row:
        if a > 128 and not inside:
            runs += 1
        inside = a > 128
    assert runs == 2  # the middle line, then the separate dot
