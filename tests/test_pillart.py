"""The smooth pill (dictado-acm): every state draws, at the size the window expects, see-through
around a soft shadow. Pure pictures, no window; Windows only, like the rest of platform/windows."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="platform/windows is never imported on macOS")
pytest.importorskip("PIL")
from ecoscribe.notice import notice  # noqa: E402
from ecoscribe.platform.windows import pillart as A  # noqa: E402

VIEW = {"label": "Taking notes 0:05", "short": "0:05", "line": "the newest words", "busy": False}


@pytest.mark.parametrize("img, size", [
    (lambda: A.dictating(0, [], ["Right Ctrl", "Esc"], now=0.0), (A.RW, A.RH)),
    (lambda: A.dictating(7, [0.3] * 30, None, now=0.0), (A.RW, A.RH)),
    (lambda: A.dictating(9, [0.3], None, live="some words heard so far", now=0.0), (A.LW, A.LH)),
    (lambda: A.meeting_chip(VIEW), (A.CW, A.CH)),
    (lambda: A.meeting_open(VIEW), (A.MW, A.MH)),
])
def test_each_state_is_its_pill_plus_room_for_the_shadow(img, size):
    im = img()
    assert im.mode == "RGBA" and im.size == (size[0] + 2 * A.M, size[1] + 2 * A.M)


def test_see_through_corners_a_soft_shadow_and_a_solid_body():
    im = A.busy(now=0.0)
    w, h = im.size
    assert im.getpixel((0, 0))[3] == 0  # the window's corner: nothing
    assert im.getpixel((A.M + 1, A.M + 1))[3] < 120  # the pill's round corner is see-through, smoothly
    under = im.getpixel((w // 2, h - A.M + 4))  # just below the pill: shadow, not body
    assert 0 < under[3] < 90 and under[:3] == (0, 0, 0)
    mid = im.getpixel((w - A.M - 8, A.M + A.RH // 2))
    assert mid[3] >= A.BODY_ALPHA - 2  # the ink body, nearly opaque


def test_notices_fit_their_words():
    short, long = A.notice(notice("Scratched")), A.notice(notice("No GPU: dictating on the CPU, slower."))
    assert short.width - 2 * A.M >= 120 and long.width > short.width
    assert A.notice(notice("Didn't hear you (Zone Vibe 100)")).width > A.notice(notice("Didn't hear you")).width


def test_a_frame_is_quick_enough_for_the_20_per_second_tick():
    A.dictating(3, [0.2] * 24, None, live="warm up the fonts", now=0.0)
    t = time.perf_counter()
    for i in range(20):
        A.dictating(3 + i, [0.1 * (i % 9)] * 24, None, live="words " * i, now=0.0)
    assert (time.perf_counter() - t) / 20 < 0.03  # well under the 50 ms between ticks
