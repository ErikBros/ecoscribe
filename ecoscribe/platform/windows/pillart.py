"""The pill drawn as a picture (dictado-acm): smooth edges, real transparency, a soft shadow and
the app's own font (Hanken Grotesk, the window's font).

Each state is a function that returns an RGBA image; shell.Overlay hands it to a layered window
(UpdateLayeredWindow), so the corners are truly see-through and nothing is a colour key. Drawn at
SS times the size and scaled down, which gives the round ends, dots and bars their anti-aliasing.
The image is the pill plus M pixels on every side for the shadow; the window is that size.
Same layout as the canvas pill A (dictado-v5g) it replaces: only how it is drawn changed.
"""
from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ... import palette as P
from ...notice import Notice

SS = 3  # drawn 3x, scaled down: anti-aliased shapes
M = 14  # room around the pill for its shadow
BODY_ALPHA = 238  # the ink body lets a hint of what's behind through; text and dots are solid
SHADOW = (0, 0, 0, 92)  # the shadow's darkest, under the middle of the pill
SHADOW_BLUR, SHADOW_DY = 7, 3
FONT = Path(__file__).resolve().parents[2] / "web" / "fonts" / "hanken-grotesk-latin-wght-normal.woff2"
FALLBACK = ("segoeui.ttf", "segoeuib.ttf")  # if the app's font can't be read: Windows' own

RH = 40  # every capsule is 40 tall (pill A); the live line makes the dictating one taller
WAVE_N, WAVE_W = 24, 130
RW, LW, LH = 236, 440, 66
CW, CH = 92, 30
MW, MH = 380, 56


def _rgba(hex_color: str, a: int = 255) -> tuple[int, int, int, int]:
    return (*P.rgb(hex_color), a)


@lru_cache(maxsize=32)
def font(size: float, weight: int = 400) -> ImageFont.FreeTypeFont:
    """The app's font at `size` logical px (drawn SS times larger)."""
    try:
        f = ImageFont.truetype(str(FONT), round(size * SS))
        f.set_variation_by_axes([weight])
        return f
    except (OSError, ValueError):
        return ImageFont.truetype(FALLBACK[weight >= 600], round(size * SS))


def measure(text: str, size: float, weight: int = 400) -> float:
    return font(size, weight).getlength(text) / SS


class Art:
    """A pill being drawn: logical coordinates (0, 0 is the pill's top left), SS-times canvas."""

    def __init__(self, w: int, h: int, r: float | None = None):
        self.w, self.h, self.r = w, h, RH / 2 if r is None else r
        self.img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.d.rounded_rectangle(self._box(0, 0, w, h), radius=self.r * SS, fill=_rgba(P.INK, BODY_ALPHA))
        # a hairline of light along the top edge: the pill sits above the page, not on it
        self.d.rounded_rectangle(self._box(0, 0, w, h), radius=self.r * SS, outline=(255, 255, 255, 22), width=SS)

    @staticmethod
    def _box(x0, y0, x1, y1):
        return [x0 * SS, y0 * SS, x1 * SS - 1, y1 * SS - 1]

    def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, width=1.0):
        self.d.rounded_rectangle(self._box(x0, y0, x1, y1), radius=r * SS, fill=fill and _rgba(fill),
                                 outline=outline and _rgba(outline), width=max(1, round(width * SS)))

    def dot(self, cx, cy, r, fill):
        self.d.ellipse(self._box(cx - r, cy - r, cx + r, cy + r), fill=_rgba(fill))

    def ring(self, cx, cy, r, color, width=2.0):
        self.d.ellipse(self._box(cx - r, cy - r, cx + r, cy + r), outline=_rgba(color), width=round(width * SS))

    def arc(self, cx, cy, r, start, extent, color, width=2.0):
        self.d.arc(self._box(cx - r, cy - r, cx + r, cy + r), start, start + extent, fill=_rgba(color), width=round(width * SS))

    def line(self, x0, y0, x1, y1, color, width=2.0):
        """A line with round ends."""
        c, w_ = _rgba(color), width * SS
        self.d.line([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=c, width=round(w_))
        for x, y in ((x0, y0), (x1, y1)):
            self.d.ellipse([x * SS - w_ / 2, y * SS - w_ / 2, x * SS + w_ / 2, y * SS + w_ / 2], fill=c)

    def text(self, x, y, s, color, size=13.5, weight=400, anchor="lm"):
        self.d.text((x * SS, y * SS), s, fill=_rgba(color), font=font(size, weight), anchor=anchor)

    def done(self) -> Image.Image:
        """The pill at its real size on a transparent sheet M px larger all round, over its shadow."""
        pill = self.img.convert("RGBa").reduce(SS).convert("RGBA")
        sheet = _shadow(self.w, self.h, self.r).copy()
        sheet.alpha_composite(pill, (M, M))
        return sheet


@lru_cache(maxsize=16)
def _shadow(w: int, h: int, r: float) -> Image.Image:
    """The soft shadow under a pill this size, on its transparent sheet (the same every frame)."""
    shade = Image.new("L", (w + 2 * M, h + 2 * M), 0)
    ImageDraw.Draw(shade).rounded_rectangle([M, M + SHADOW_DY, M + w - 1, M + h - 1 + SHADOW_DY], radius=r, fill=SHADOW[3])
    sheet = Image.new("RGBA", shade.size, SHADOW[:3] + (0,))
    sheet.putalpha(shade.filter(ImageFilter.GaussianBlur(SHADOW_BLUR)))
    return sheet


def _keycaps(a: Art, x: float, mid: float, keys) -> float:
    """Keys as small outlined caps: [Right Ctrl] + [Esc]. Returns where they end."""
    for i, k in enumerate(keys):
        if i:
            a.text(x + 4, mid, "+", P.LINE, 11)
            x += 14
        w_ = measure(k, 11, 700) + 12
        a.rrect(x, mid - 9, x + w_, mid + 9, 5, outline=P.KEYCAP_LINE, width=1)
        a.text(x + w_ / 2, mid, k, P.PAPER, 11, 700, anchor="mm")
        x += w_
    return x


def dictating(secs: int, levels: list[float], hint_keys=None, live: str = "", now: float | None = None) -> Image.Image:
    """The recording dot, a waveform of the last second of the voice, the timer. The first 2 s show
    how to cancel (the keys) in the waveform's place. With live text, the newest words under it."""
    now = time.monotonic() if now is None else now
    level = levels[-1] if levels else 0.0
    w_, h_ = (LW, LH) if live else (RW, RH)
    a = Art(w_, h_)
    mid = RH / 2
    on = int(now * 2) % 2 == 0 or level > 0.05  # the dot breathes while it's quiet
    if on:
        a.dot(21, mid, 9, P.TILE_HALO)
    a.dot(21, mid, 5, P.CLAY_BRIGHT if on else P.TILE_DIM)
    a.text(w_ - 16, mid, f"{secs // 60}:{secs % 60:02d}", P.PAPER, 13.5, 700, anchor="rm")
    x0 = 38
    if secs < 2 and hint_keys:
        x = _keycaps(a, x0, mid, hint_keys)
        a.text(x + 6, mid, "cancels", P.AEGEAN_PALE, 12)
    else:
        step = WAVE_W / WAVE_N
        pad = [0.0] * (WAVE_N - len(levels)) + list(levels[-WAVE_N:])
        for i, lv in enumerate(pad):
            hh = 2 + (lv ** 1.5) * (RH - 18)
            x = x0 + i * step + step / 2
            col = (P.AEGEAN_PALE if lv > 0.25 else P.AEGEAN_MID) if lv > 0.04 else P.PILL_OFF
            a.line(x, mid - hh / 2, x, mid + hh / 2, col, 2)
    if live:
        text, room = " ".join(live.split()), w_ - 32
        if measure(text, 12.5) > room:  # one line: the newest words, cut on the left
            while text and measure("…" + text, 12.5) > room:
                text = text.split(" ", 1)[1] if " " in text else text[1:]
            text = "…" + text
        a.text(16, RH + 5, text, P.PAPER, 12.5)
    return a.done()


def busy(now: float | None = None) -> Image.Image:
    """Transcribing: a turning arc and what it's doing."""
    now = time.monotonic() if now is None else now
    label = "Writing it down"
    a = Art(round(16 + 16 + 10 + measure(label, 13.5, 700) + 18), RH)
    mid, cx = RH / 2, 16 + 7
    a.ring(cx, mid, 7, P.PILL_OFF)
    a.arc(cx, mid, 7, (now * 360) % 360, 90, P.AEGEAN_PALE)
    a.text(16 + 16 + 10, mid, label, P.PAPER, 13.5, 700)
    return a.done()


def notice(n: Notice) -> Image.Image:
    """A flash: an icon (a struck mic, a language badge, a warning), the words, a soft detail."""
    mid = RH / 2
    badge_w = measure(n.badge, 11, 700) + 16 if n.icon == "lang" else 0
    icon_w = {"nomic": 16, "warn": 16, "lang": badge_w}.get(n.icon, 0)
    x = 8 if n.icon == "lang" else 16
    tw = measure(n.text, 13.5, 700)
    w_ = x + icon_w + (10 if icon_w else 0) + tw + (10 + measure(n.detail, 12) if n.detail else 0) + 18
    a = Art(round(max(w_, 120)), RH)
    if n.icon == "lang":
        a.rrect(x, mid - 12, x + badge_w, mid + 12, 12, fill=P.AEGEAN)
        a.text(x + badge_w / 2, mid, n.badge, P.PAPER, 11, 700, anchor="mm")
    elif n.icon == "nomic":
        _mic_struck(a, x + 8, mid, P.CLAY_BRIGHT)
    elif n.icon == "warn":
        a.ring(x + 8, mid, 8, P.CLAY_BRIGHT)
        a.text(x + 8, mid, "!", P.CLAY_BRIGHT, 11, 800, anchor="mm")
    x += icon_w + (10 if icon_w else 0)
    if not n.icon:
        x = (a.w - tw) / 2
    a.text(x, mid, n.text, P.PAPER, 13.5, 700)
    if n.detail:
        a.text(x + tw + 10, mid, n.detail, P.AEGEAN_MUTED, 12)
    return a.done()


def _mic_struck(a: Art, cx: float, cy: float, col: str) -> None:
    a.rrect(cx - 3, cy - 7, cx + 3, cy + 2, 3, outline=col, width=1.6)
    a.arc(cx, cy, 5, 0, 180, col, 1.6)
    a.line(cx, cy + 5, cx, cy + 7, col, 1.6)
    a.line(cx - 6, cy - 6, cx + 6, cy + 6, col, 1.6)


def meeting_chip(view: dict) -> Image.Image:
    """The meeting as it sits: a small chip, recording dot + timer."""
    a = Art(CW, CH, CH / 2)
    a.dot(17, CH / 2, 5, P.AEGEAN_SOFT if view["busy"] else P.TILE)
    a.text(30, CH / 2, view.get("short") or view["label"], P.PAPER, 13)
    return a.done()


def meeting_open(view: dict) -> Image.Image:
    """The chip opened by the mouse: the label and the latest live line."""
    a = Art(MW, MH, MH / 2)
    r = MH / 2
    a.dot(24, r, 6, P.AEGEAN_SOFT if view["busy"] else P.TILE)
    if view["line"]:
        a.text(42, 18, view["label"], P.PAPER, 13.5, 700)
        a.text(42, 38, view["line"], P.LINE, 13)
    else:
        a.text(42, r, view["label"], P.PAPER, 14.5)
    return a.done()
