"""Ecoscribe's mark, logo A "Lines" (dictado-6oe.1), drawn with Pillow at any size (app icon + tray states)."""
from __future__ import annotations

from PIL import Image, ImageDraw

from . import palette as P


def mark_image(size: int, bg: str = P.AEGEAN, fg: str = P.PAPER, shape: str = "square",
               dot: bool | None = None) -> Image.Image:
    """Logo A, "Lines" (dictado-6oe.1): three rounded lines, written text and an E; the middle one is
    shorter and, on the app icon, ends in a clay dot (the moment you speak). Rounded square (app icon)
    or circle (tray). Drawn on a 48-unit grid at 4x and downsampled."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bgc = P.rgb(bg) + (255,)
    fgc = P.rgb(fg) + (255,)
    if shape == "circle":
        d.ellipse((0, 0, s - 1, s - 1), fill=bgc)
    else:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 11 / 48), fill=bgc)
    u = s / 48
    small = size <= 24
    dot = (not small) if dot is None else dot
    stroke = (6.0 if small else 4.2) * u
    x0, x1, xm = (11 if small else 13) * u, (37 if small else 35) * u, (30 if small else 28) * u
    ys = (14, 24, 34) if small else (15, 24, 33)

    def line(xa, xb, y):
        r = stroke / 2
        d.rounded_rectangle((xa - r, y * u - r, xb + r, y * u + r), radius=r, fill=fgc)
    line(x0, x1, ys[0])
    line(x0, xm, ys[1])
    line(x0, x1, ys[2])
    if dot:
        r = 2.6 * u
        cx, cy = 34 * u, 24 * u
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=P.rgb(P.CLAY_LIGHT) + (255,))
    return img.resize((size, size), Image.LANCZOS)


mic_image = mark_image  # the old name: callers (Mac template, build_mac, make_icon) keep working


def save_ico(path) -> None:
    """Every size drawn natively (Pillow would otherwise just downscale the 256 image)."""
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [mark_image(n) for n in sizes]
    imgs[-1].save(path, format="ICO", sizes=[(n, n) for n in sizes], append_images=imgs[:-1])


TRAY = {"idle": P.INK, "recording": P.TILE, "busy": P.AEGEAN}


def tray_image(state: str) -> Image.Image:
    """Windows shows tray icons at 16-24 px; use the small geometry, upscaled cleanly."""
    return mark_image(24, bg=TRAY.get(state, P.INK), shape="circle").resize((64, 64), Image.LANCZOS)
