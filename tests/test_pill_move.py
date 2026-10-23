"""Moving the pill (dictado-06i): drag the meeting chip, it stays there; a double-click puts it back."""
from ecoscribe import meetui
from ecoscribe.meetui import Drag, fit_spot, load_spot, save_spot

WORK = (0, 0, 1920, 1040)


def run(drag, steps):
    """steps: (time, cursor, button down, over the chip); the answers that weren't None."""
    out = []
    for t, cur, down, over in steps:
        a = drag.step(t, cur, down, over, (960, 960))
        if a:
            out.append(a)
    return out


def test_a_press_on_the_chip_then_a_move_drags_it():
    d = Drag()
    got = run(d, [(0, (950, 940), False, True), (0.05, (950, 940), True, True),
                  (0.10, (952, 941), True, True),  # under the threshold: still a click
                  (0.15, (700, 500), True, True), (0.20, (700, 500), False, True)])
    assert got == [("move", (710, 520)), ("drop", None)]
    assert not d.held and not d.moving


def test_a_press_elsewhere_does_not_drag_even_when_it_passes_over_the_chip():
    d = Drag()
    got = run(d, [(0, (100, 100), True, False), (0.05, (950, 940), True, True), (0.10, (700, 500), True, True),
                  (0.15, (700, 500), False, True)])
    assert got == [] and not d.held


def test_a_double_click_puts_it_back_and_a_slow_one_does_not():
    click = lambda t: [(t, (950, 940), True, True), (t + 0.05, (950, 940), False, True)]
    assert run(Drag(), click(0) + click(0.2)) == [("reset", None)]
    assert run(Drag(), click(0) + click(1.0)) == []


def test_a_drag_then_a_click_is_not_a_double_click():
    d = Drag()
    run(d, [(0, (950, 940), True, True), (0.05, (900, 900), True, True), (0.1, (900, 900), False, True)])
    assert run(d, [(0.2, (900, 900), True, True), (0.25, (900, 900), False, True)]) == []


def test_fit_spot_keeps_the_whole_pill_on_screen():
    assert fit_spot((960, 960), (120, 40), WORK) == (960, 960)
    assert fit_spot((10, 5), (120, 40), WORK) == (60, 40)  # top left corner
    assert fit_spot((1919, 2000), (120, 40), WORK) == (1860, 1040)  # bottom right, past the edge
    assert fit_spot((-500, 300), (121, 40), (-1920, 0, 0, 1080)) == (-500, 300)  # a monitor left of the main one


def test_the_spot_is_kept_and_put_back(tmp_path):
    p = tmp_path / "pill.json"
    assert load_spot(p) is None  # nothing yet: bottom centre
    save_spot(p, (300, 700))
    assert load_spot(p) == (300, 700)
    save_spot(p, None)
    assert load_spot(p) is None and p.exists()
    p.write_text("not json", encoding="utf-8")
    assert load_spot(p) is None


def test_the_drag_threshold_and_double_click_are_sensible():
    assert 2 <= meetui.DRAG_START <= 8 and 0.25 <= meetui.DOUBLE_S <= 0.6
