"""The small icons outside the window, in the window's icon family (A, Fluent: dictado-2yb).

The pill's notices and the meeting prompt's tile draw these on Windows (Pillow, Tk) and on the Mac
(AppKit), so all three show the same shapes as the window's SVG icons. Each glyph is drawn on the
window's 24-unit grid, y down, as a few plain parts every drawing kit has:

    ("rrect", x0, y0, x1, y1, r)   a rounded rectangle, outlined
    ("circle", cx, cy, r)          a circle, outlined
    ("arc", cx, cy, r, a0, a1)     part of a circle, degrees clockwise from 3 o'clock (y down)
    ("poly", closed, points)       a line through the points, round ends and joins
    ("dot", cx, cy, r)             a filled circle

`placed` scales a glyph to `size` px centred on (cx, cy); the caller picks the line width.
"""
from __future__ import annotations

GLYPHS: dict[str, list[tuple]] = {
    # the window's mic, struck through: dictation heard nothing
    "nomic": [("rrect", 8.5, 3, 15.5, 14.5, 3.5), ("arc", 12, 11, 6.5, 0, 180),
              ("poly", False, [(12, 17.5), (12, 21)]), ("poly", False, [(4, 4), (20, 20)])],
    # the window's warning: a triangle with round corners, a line and a dot
    "warn": [("poly", True, [(12, 4.2), (20.8, 19.5), (3.2, 19.5)]),
             ("poly", False, [(12, 9.5), (12, 13.8)]), ("dot", 12, 16.8, 1.1)],
    # a clock: still there?
    "end?": [("circle", 12, 12, 8), ("poly", False, [(12, 7.5), (12, 12), (15, 14)])],
    # the window's document with a waveform: a transcript is ready (or failed)
    "doc": [("poly", True, [(6, 3), (13, 3), (18, 8), (18, 21), (6, 21)]),
            ("poly", False, [(13, 3), (13, 8), (18, 8)]),
            ("poly", False, [(9.5, 13.5), (9.5, 16)]), ("poly", False, [(12, 11.5), (12, 18)]),
            ("poly", False, [(14.5, 13), (14.5, 16.5)])],
    # a switch, off: a setting that is off
    "cmdoff": [("rrect", 3, 7, 21, 17, 5), ("dot", 8, 12, 2.5)],
}


def placed(name: str, cx: float, cy: float, size: float) -> list[tuple]:
    """The glyph's parts in pixels: `size` px square, centred on (cx, cy)."""
    k = size / 24
    x = lambda v: cx + (v - 12) * k  # noqa: E731
    y = lambda v: cy + (v - 12) * k  # noqa: E731
    out = []
    for part in GLYPHS[name]:
        kind = part[0]
        if kind == "rrect":
            _, x0, y0, x1, y1, r = part
            out.append(("rrect", x(x0), y(y0), x(x1), y(y1), r * k))
        elif kind in ("circle", "dot"):
            _, px, py, r = part
            out.append((kind, x(px), y(py), r * k))
        elif kind == "arc":
            _, px, py, r, a0, a1 = part
            out.append(("arc", x(px), y(py), r * k, a0, a1))
        else:
            _, closed, pts = part
            out.append(("poly", closed, [(x(px), y(py)) for px, py in pts]))
    return out
