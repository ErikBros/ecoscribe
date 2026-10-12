from PIL import Image

from ecoscribe.icon import TRAY, mic_image, save_ico, tray_image


def test_ico_has_every_size(tmp_path):
    p = tmp_path / "d.ico"
    save_ico(p)
    sizes = set(Image.open(p).info["sizes"])
    assert {(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)} <= sizes


def test_images_are_square_rgba():
    for n in (16, 24, 64, 256):
        im = mic_image(n)
        assert im.size == (n, n) and im.mode == "RGBA"
    for state in TRAY:
        assert tray_image(state).size == (64, 64)


def test_tray_states_differ():
    px = {s: tray_image(s).getpixel((10, 32)) for s in TRAY}
    assert len(set(px.values())) == 3


def test_the_mark_is_three_lines_with_a_clay_dot_on_the_app_icon():
    from ecoscribe import palette as P
    from ecoscribe.icon import mark_image
    big = mark_image(256)
    assert all(abs(a - b) <= 6 for a, b in zip(big.getpixel((128, int(256 * 15 / 48)))[:3], P.rgb(P.PAPER)))  # the top line, through the middle
    dot = big.getpixel((int(256 * 34 / 48), 128))[:3]
    assert dot[0] > dot[2] + 60  # clay, warm: the moment you speak
    small = mark_image(16)  # tray size: no dot, fatter lines
    assert small.size == (16, 16)
