"""The Windows shell: overlay pill, prompt box and tray icon (macOS: ecoscribe/platform/macos/shell.py).

The overlay must never take focus or clicks, otherwise it would steal the
very window you navigated to: it is a no-activate, click-through, tool window
shown only with SW_SHOWNOACTIVATE. Other threads never touch tk directly;
they post to a queue the tk main loop drains.
"""
from __future__ import annotations

import ctypes
import logging
import math
import os
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes as w
from pathlib import Path

from ... import meetui
from ...notice import notice
from ... import palette as P
from . import pillart as art
from .pillart import CH, CW, LH, LW, MH, MW, RH, RW, WAVE_N, WAVE_W  # noqa: F401  the pill's sizes, read here by tests

log = logging.getLogger(__name__)
u32 = ctypes.windll.user32
u32.GetWindowLongW.argtypes = (w.HWND, ctypes.c_int)
u32.SetWindowLongW.argtypes = (w.HWND, ctypes.c_int, ctypes.c_long)
u32.ShowWindow.argtypes = (w.HWND, ctypes.c_int)
u32.SetWindowPos.argtypes = (w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT)
u32.MonitorFromWindow.argtypes = (w.HWND, w.DWORD)
u32.MonitorFromWindow.restype = w.HANDLE
u32.GetForegroundWindow.restype = w.HWND
u32.GetCursorPos.argtypes = (ctypes.POINTER(w.POINT),)
u32.GetWindowRect.argtypes = (w.HWND, ctypes.POINTER(w.RECT))

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x08000000, 0x80, 0x8
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = w.HWND(-1)
SWP_NOSIZE, SWP_NOACTIVATE = 0x1, 0x10
W, H = 210, 44  # the window before its first picture
KEY = "#010203"  # transparent color key, gives the prompt box round corners
_u = ctypes.WinDLL("user32", use_last_error=True)  # own handles: argtypes here don't leak to other modules
_gdi = ctypes.WinDLL("gdi32")


class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD)]


_u.GetDC.argtypes, _u.GetDC.restype = (w.HWND,), w.HDC
_u.ReleaseDC.argtypes = (w.HWND, w.HDC)
_u.UpdateLayeredWindow.argtypes = (w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE), w.HDC,
                                   ctypes.POINTER(w.POINT), w.COLORREF, ctypes.POINTER(_BLEND), w.DWORD)
_gdi.CreateCompatibleDC.argtypes, _gdi.CreateCompatibleDC.restype = (w.HDC,), w.HDC
_gdi.CreateDIBSection.argtypes = (w.HDC, ctypes.POINTER(_BIH), w.UINT, ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD)
_gdi.CreateDIBSection.restype = w.HBITMAP
_gdi.SelectObject.argtypes, _gdi.SelectObject.restype = (w.HDC, w.HGDIOBJ), w.HGDIOBJ
_gdi.DeleteObject.argtypes = (w.HGDIOBJ,)
_gdi.DeleteDC.argtypes = (w.HDC,)
ULW_ALPHA, AC_SRC_ALPHA = 2, 1
_EMPTY = art.Image.new("RGBA", (1, 1), (0, 0, 0, 0))


def update_layered(hwnd: int, img, x: int, y: int) -> bool:
    """Show `img` (RGBA) as the whole window at x, y: per-pixel alpha, no colour key (dictado-acm)."""
    w_, h_ = img.size
    bits = img.convert("RGBa").tobytes("raw", "BGRa")  # what a layered window wants: premultiplied BGRA
    screen = _u.GetDC(None)
    mem = _gdi.CreateCompatibleDC(screen)
    ptr = ctypes.c_void_p()
    bih = _BIH(ctypes.sizeof(_BIH), w_, -h_, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down rows
    bmp = _gdi.CreateDIBSection(screen, ctypes.byref(bih), 0, ctypes.byref(ptr), None, 0)
    try:
        if not bmp or not ptr.value:
            return False
        ctypes.memmove(ptr, bits, len(bits))
        old = _gdi.SelectObject(mem, bmp)
        ok = _u.UpdateLayeredWindow(hwnd, screen, ctypes.byref(w.POINT(x, y)), ctypes.byref(w.SIZE(w_, h_)), mem,
                                    ctypes.byref(w.POINT(0, 0)), 0, ctypes.byref(_BLEND(0, 0, 255, AC_SRC_ALPHA)), ULW_ALPHA)
        _gdi.SelectObject(mem, old)
        return bool(ok)
    finally:
        if bmp:
            _gdi.DeleteObject(bmp)
        _gdi.DeleteDC(mem)
        _u.ReleaseDC(None, screen)


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]


class Overlay:
    """The pill. Each state is a picture from pillart (smooth, see-through, a soft shadow, dictado-acm)
    handed to the layered window whole; the tk window only owns the handle and never paints."""

    def __init__(self, root: tk.Tk, level_fn=lambda: 0.0, hint: str = "Right Ctrl + Esc to cancel"):
        self.level_fn = level_fn
        self.hint = hint
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.geometry(f"{W}x{H}+0+0")
        self.top.update_idletasks()
        self.hwnd = int(self.top.wm_frame(), 16)
        ex = u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                           ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        # a first (empty) picture before it is ever hidden: a layered window hidden before its first
        # UpdateLayeredWindow refuses every later one (error 87; measured 2026-10-22)
        update_layered(self.hwnd, _EMPTY, 0, 0)
        u32.ShowWindow(self.hwnd, SW_HIDE)
        self.mode = "hidden"
        self._t0 = 0.0
        self._flash_until = 0.0
        self._flash_msg = ""
        self.w, self.h = W, H  # the pill's own size (the window is pillart.M larger all round, for the shadow)
        self._img = None
        self._anchor: tuple[int, int] | None = None  # the pill's bottom centre on screen
        self._ulw_ok = True
        self.meeting: dict | None = None  # meetui.meeting_view(); shown whenever dictation isn't
        self._drawn = None  # what the meeting layer last drew (no redraw, no flicker)
        self.live_text = ""  # what the live transcript has heard so far (this recording)
        self._levels: list[float] = []  # the waveform: voice level per tick, newest last
        self.open = False  # the meeting chip is opened by the mouse over it (dictado-z4j)

    def ex_style(self) -> int:
        return u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)

    def _present(self, img) -> None:
        """A new picture of the pill: same bottom centre, so it grows up and both ways."""
        self._img = img
        self.w, self.h = img.width - 2 * art.M, img.height - 2 * art.M
        if self._anchor:
            self._blit()

    def _origin(self) -> tuple[int, int]:
        cx, bottom = self._anchor or (600 + W // 2, 900 + H)
        return cx - self.w // 2 - art.M, bottom - self.h - art.M

    def _blit(self) -> None:
        if self._img is None:
            return
        x, y = self._origin()
        if not update_layered(self.hwnd, self._img, x, y) and self._ulw_ok:
            self._ulw_ok = False  # say it once, not 20 times a second
            log.warning("the pill couldn't be drawn (UpdateLayeredWindow failed, error %s)", ctypes.get_last_error())

    def _place_and_show(self) -> None:
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = u32.MonitorFromWindow(u32.GetForegroundWindow(), 2)
        if mon and u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            r = mi.rcWork
            self._anchor = ((r.left + r.right) // 2, r.bottom - 80)
        else:
            self._anchor = (600 + W // 2, 900 + H)
        self._blit()
        x, y = self._origin()
        u32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        u32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def _notice(self, msg: str) -> None:
        """A flash: an icon (a struck mic, a language badge, a warning), the words, the mic's name."""
        self._drawn = None
        self._present(art.notice(notice(msg)))

    def _dictating_pill(self, secs: int, level: float) -> None:
        """The recording dot, a waveform of the last second or so of the voice, the timer (dictado-3tl).
        How to cancel shows in the waveform's place for the first 2 s. With live text, a second line."""
        self._levels.append(level)
        del self._levels[:-art.WAVE_N]
        self._drawn = None
        keys = self.hint.split(" to ")[0].split(" + ")
        self._present(art.dictating(secs, self._levels, keys, self.live_text))

    def _hover(self) -> bool:
        pt = w.POINT()
        if not u32.GetCursorPos(ctypes.byref(pt)) or not self._anchor:
            return False
        x, y = self._origin()  # the pill itself, not its shadow
        return meetui.hovering((pt.x, pt.y), (x + art.M, y + art.M, x + art.M + self.w, y + art.M + self.h))

    def _meeting_pill(self, view: dict) -> None:
        key = (view["label"], view["line"], view["busy"], self.open)
        if key == self._drawn:
            return
        self._present(art.meeting_open(view) if self.open else art.meeting_chip(view))
        self._place_and_show()
        self._drawn = key

    def _show_layer(self) -> None:
        """Dictation idle and no flash: the meeting pill, or nothing."""
        if meetui.pill_layer(self.mode, self.meeting) == "meeting":
            self._meeting_pill(self.meeting)
        else:
            self._drawn = None
            u32.ShowWindow(self.hwnd, SW_HIDE)

    def set_meeting(self, view: dict | None) -> None:
        self.meeting = view
        if self.mode == "hidden" and time.monotonic() >= self._flash_until:
            self._show_layer()

    def live(self, text: str) -> None:
        if self.mode == "recording":
            self.live_text = text or ""

    def recording(self, t0: float) -> None:
        self.mode, self._t0 = "recording", t0
        self.live_text = ""
        self._levels = []
        self._dictating_pill(0, 0.0)
        self._place_and_show()

    def busy(self) -> None:
        """Transcribing: a turning arc and what it's doing (pill A, dictado-v5g)."""
        self.mode = "busy"
        self.live_text = ""
        self._busy_frame()
        self._place_and_show()

    def _busy_frame(self) -> None:
        self._drawn = None
        self._present(art.busy())

    def idle(self) -> None:
        self.mode = "hidden"
        self.live_text = ""
        if time.monotonic() >= self._flash_until:
            self._show_layer()

    def flash(self, msg: str, seconds: float = 2.0) -> None:
        self._flash_msg, self._flash_until = msg, time.monotonic() + seconds
        if self.mode == "recording":
            return
        self._notice(msg)
        self._place_and_show()

    def tick(self) -> None:
        """Called every 50 ms by the UI loop."""
        now = time.monotonic()
        if self.mode == "recording":
            self._dictating_pill(int(now - self._t0), min(1.0, math.sqrt(self.level_fn()) * 4))
        elif self.mode == "hidden" and self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            self._show_layer()
        elif self.mode == "hidden" and self.meeting and not self._flash_until:
            hover = self._hover()  # the chip opens to the live line while the mouse is on it
            if hover != self.open:
                self.open = hover
                self._show_layer()
        elif self.mode == "busy" and self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            self.busy()
        elif self.mode == "busy" and not self._flash_until:
            self._busy_frame()  # the arc turns


PW = 360  # the prompt box's least width


def _prompt_icon(c: tk.Canvas, x: float, y: float, kind: str) -> None:
    """A 38 px tile with a glyph for the box's kind: a call (the clay dot), silence (a clock),
    a transcript (a page), no sound (a mic, struck through)."""
    _round_rect(c, x, y, x + 38, y + 38, 11, fill=P.TILE_CALL if kind == "start" else P.TILE_NOTE)
    cx, cy, g = x + 19, y + 19, P.AEGEAN_MUTED
    if kind == "start":
        c.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=P.CLAY_BRIGHT, outline="")
    elif kind == "end?":
        c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, outline=g, width=2)
        c.create_line(cx, cy - 4, cx, cy, cx + 3, cy + 2, fill=g, width=2, capstyle="round")
    elif kind == "nomic":
        _round_rect(c, cx - 4, cy - 9, cx + 4, cy + 3, 4, fill="", outline=g, width=2)
        c.create_line(cx - 9, cy - 9, cx + 9, cy + 9, fill=g, width=2, capstyle="round")
    else:  # done / failed: a page with lines
        c.create_rectangle(cx - 7, cy - 9, cx + 7, cy + 9, outline=g, width=2)
        for dy in (-3, 1, 5):
            c.create_line(cx - 3, cy + dy, cx + 4, cy + dy, fill=g, width=2)


def _round_rect(c: tk.Canvas, x0, y0, x1, y1, r, **kw):
    """A filled rounded rectangle on a canvas (a smoothed polygon)."""
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    kw.setdefault("outline", "")
    return c.create_polygon(pts, smooth=True, splinesteps=12, **kw)


class _CanvasText:
    """A canvas text item with a Label's cget/config("text"): the countdown on a button."""

    def __init__(self, c: tk.Canvas, item):
        self.c, self.item = c, item

    def cget(self, key):
        return self.c.itemcget(self.item, key)

    def config(self, **kw):
        self.c.itemconfig(self.item, **kw)


class PromptWindow:
    """The clickable box above the pill: a call started, long silence, transcript ready.
    No-activate (clicking it never takes focus from the call window), not click-through."""

    def __init__(self, root: tk.Tk, on_answer):
        self.root, self.on_answer = root, on_answer
        self.prompt: meetui.Prompt | None = None
        self.top = None
        self._later: list[meetui.Prompt] = []  # done/failed notes waiting behind a question
        self._btns: dict = {}  # choice -> button label, for the countdown

    def show(self, prompt: meetui.Prompt) -> None:
        """A question (start, end?) is never replaced by a note (done, failed): the note waits.
        A question over a question just replaces it (the detector sees one call at a time, so
        the old one is already moot; answering it here could suppress the new call)."""
        if meetui.placement(self.prompt, prompt) == "queue":
            self._later.append(prompt)
            return
        self._close()
        self.prompt = prompt
        top = self.top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-transparentcolor", KEY)  # round corners, like the pill (dictado-2df)
        top.configure(bg=KEY)
        f_title, f_text, f_btn = tkfont.Font(family="Segoe UI", size=11, weight="bold"), \
            tkfont.Font(family="Segoe UI", size=10), tkfont.Font(family="Segoe UI", size=10, weight="bold")
        pad, bh, gap = 18, 32, 8
        now = time.monotonic()
        labels = [(prompt.button_text(c, now), c) for _l, c in prompt.buttons]  # "Not now (10)": the widest
        bws = [f_btn.measure(t) + 32 for t, _c in labels]
        width = max(PW, sum(bws) + gap * (len(bws) - 1) + 2 * pad, f_title.measure(prompt.title) + 2 * pad)
        c = tk.Canvas(top, width=width, height=10, bg=KEY, highlightthickness=0, bd=0)
        c.pack()
        _prompt_icon(c, pad, pad, prompt.kind)  # what it's about, at a glance (dictado-6oe.9)
        tx = pad + 38 + 14
        y = pad + 1
        c.create_text(tx, y, text=prompt.title, fill=P.PAPER, font=f_title, anchor="nw")
        y += f_title.metrics("linespace") + 4
        self.lang = tk.StringVar(value=dict(meetui.LANGS).get(prompt.lang or "sv", "Swedish"))
        if prompt.question:
            t = c.create_text(tx, y, text=prompt.question, fill=P.LINE, font=f_text, anchor="nw", width=width - tx - pad)
            y = c.bbox(t)[3] + 4
        y = max(y, pad + 38)
        if prompt.kind == "start":  # the language: a rounded chip that opens a menu
            menu = tk.Menu(c, tearoff=0, bg=P.PAPER, fg=P.INK, activebackground=P.AEGEAN, activeforeground=P.PAPER, font=f_text)
            for _code, name in meetui.LANGS:
                menu.add_radiobutton(label=name, variable=self.lang, value=name)
            cw = max(f_text.measure(n) for _, n in meetui.LANGS) + 44
            ch = 28
            _round_rect(c, tx, y + 4, tx + cw, y + 4 + ch, ch // 2, fill=P.INK_2, tags=("lang", "lang-bg"))
            lt = c.create_text(tx + 12, y + 4 + ch / 2, text=self.lang.get(), fill=P.PAPER, font=f_text, anchor="w", tags=("lang",))
            c.create_text(tx + cw - 14, y + 4 + ch / 2, text="▾", fill=P.LINE, font=f_text, tags=("lang",))
            self.lang.trace_add("write", lambda *_a: c.itemconfig(lt, text=self.lang.get()))
            c.tag_bind("lang", "<Button-1>", lambda e: menu.tk_popup(e.x_root, e.y_root))
            c.tag_bind("lang", "<Enter>", lambda _e: (c.itemconfig("lang-bg", fill=P.PILL_OFF), c.config(cursor="hand2")))
            c.tag_bind("lang", "<Leave>", lambda _e: (c.itemconfig("lang-bg", fill=P.INK_2), c.config(cursor="")))
            y += ch + 12
        y += 10
        self._btns = {}
        x = width - pad
        for i, ((text, choice), bw) in reversed(list(enumerate(zip(labels, bws)))):
            primary = i == 0
            # the primary is light on dark, so it stands out (dictado-6oe.9)
            fill, hover, ink = (P.PAPER, P.PAPER_HOVER, P.INK) if primary else (P.PILL_OFF, P.INK_2, P.PAPER)
            tag = f"btn-{choice}"
            _round_rect(c, x - bw, y, x, y + bh, bh // 2, fill=fill, tags=(tag, tag + "-bg"))
            item = c.create_text(x - bw / 2, y + bh / 2, text=text, fill=ink, font=f_btn, tags=(tag,))
            c.tag_bind(tag, "<Button-1>", lambda _e, ch=choice: self._answer(ch))
            c.tag_bind(tag, "<Enter>", lambda _e, t=tag, h=hover: (c.itemconfig(t + "-bg", fill=h), c.config(cursor="hand2")))
            c.tag_bind(tag, "<Leave>", lambda _e, t=tag, f=fill: (c.itemconfig(t + "-bg", fill=f), c.config(cursor="")))
            self._btns[choice] = _CanvasText(c, item)
            x -= bw + gap
        height = y + bh + pad + 2
        c.config(height=height)
        _round_rect(c, 0, 0, width, height, 20, fill=P.INK, tags=("card",))
        c.tag_lower("card")
        self._drain = (c, c.create_line(20, height - 2, width - 20, height - 2, fill=P.AEGEAN_MID, width=3, capstyle="round"), width)
        top.update_idletasks()
        hwnd = int(top.wm_frame(), 16)
        ex = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = u32.MonitorFromWindow(u32.GetForegroundWindow(), 2)
        pw, ph = top.winfo_reqwidth(), top.winfo_reqheight()
        if mon and u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            r = mi.rcWork
            x, y = (r.left + r.right - pw) // 2, r.bottom - MH - 80 - ph - 12
        else:
            x, y = 600, 760
        u32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        u32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

    def _lang_code(self) -> str:
        names = {n: c for c, n in meetui.LANGS}
        return names.get(self.lang.get(), "sv")

    def _answer(self, choice: str) -> None:
        p = self.prompt
        lang = self._lang_code() if p and p.kind == "start" else None
        self.hide()
        if p is not None and choice != "hide":
            try:
                self.on_answer(p, choice, lang)
            except Exception:
                log.exception("prompt answer failed")

    def dismiss(self, kind: str = "start") -> None:
        if self.prompt is not None and self.prompt.kind == kind:
            self.hide()

    def _close(self) -> None:
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top, self.prompt = None, None

    def hide(self) -> None:
        self._close()
        if self._later:
            nxt = self._later.pop(0)
            nxt.opened_at = time.monotonic()  # a note that waited still gets its full time on screen
            self.show(nxt)

    def tick(self) -> None:
        if self.prompt is not None:
            now = time.monotonic()
            what = self.prompt.expired(now)
            if what is not None:
                self._answer(what)
                return
            c, line, w = getattr(self, "_drain", (None, None, 0))
            if c is not None:  # the countdown also drains along the bottom edge (dictado-6oe.9)
                left = max(0.0, 1 - (now - self.prompt.opened_at) / self.prompt.timeout_s)
                try:
                    c.coords(line, 20, c.winfo_reqheight() - 2, 20 + (w - 40) * left, c.winfo_reqheight() - 2)
                except tk.TclError:
                    pass
            for choice, b in self._btns.items():  # "Not now (7)": the countdown
                text = self.prompt.button_text(choice, now)
                if b.cget("text") != text:
                    b.config(text=text)


class Tray:
    def __init__(self, app_ref, log_path: Path, on_quit, open_window=None, meeting_label=None, on_meeting=None,
                 open_meetings=None, meeting_state=None, last_lang=None, start_meeting=None,
                 dict_langs=None, dict_lang=None, set_dict_lang=None):
        import pystray

        from ...icon import TRAY, tray_image
        self._images = {state: tray_image(state) for state in TRAY}
        meeting_items = []
        if meeting_label and on_meeting and meeting_state and start_meeting:
            # idle: "Transcribe meeting now >" with a language submenu (last one ticked);
            # recording: "Stop meeting" / "Saving meeting..." (the user 2026-10-05: no language choice from the tray)
            def lang_item(code, name):
                return pystray.MenuItem(name, lambda: start_meeting(code),
                                        checked=lambda _i: (last_lang() if last_lang else "sv") == code, radio=True)
            langs = pystray.Menu(*[lang_item(c, n) for c, n, _ in meetui.tray_lang_items("sv")])
            idle = lambda _i: not meetui.tray_recording(meeting_state())  # noqa: E731
            meeting_items = [pystray.MenuItem("Transcribe meeting now", langs, visible=idle),
                             pystray.MenuItem(lambda _i: meeting_label(), lambda: on_meeting(),
                                              visible=lambda _i: meetui.tray_recording(meeting_state())),
                             pystray.MenuItem("Open Meetings", lambda: open_meetings and open_meetings()),
                             pystray.Menu.SEPARATOR]
        dict_items = []
        if dict_langs and dict_lang and set_dict_lang:  # t0u.24: switch without opening the window
            def dict_item(code, name):
                return pystray.MenuItem(name, lambda: set_dict_lang(code),
                                        checked=lambda _i: dict_lang() == code, radio=True)
            dict_items = [pystray.MenuItem("Next dictation in", pystray.Menu(*[dict_item(c, n) for c, n in dict_langs]))]
        menu = pystray.Menu(
            pystray.MenuItem("Open Ecoscribe", lambda: open_window and open_window(), default=True),
            pystray.Menu.SEPARATOR,
            *dict_items,
            *meeting_items,
            pystray.MenuItem("Copy last", lambda: app_ref().copy_last()),
            pystray.MenuItem("Cancel recording", lambda: app_ref().on_action("cancel")),
            pystray.MenuItem("Open log", lambda: os.startfile(str(log_path))),
            pystray.MenuItem("Quit", lambda: on_quit()),
        )
        self.icon = pystray.Icon("ecoscribe", self._images["idle"], "Ecoscribe", menu)
        threading.Thread(target=self.icon.run, name="ecoscribe-tray", daemon=True).start()

    def set_state(self, state: str) -> None:
        try:
            self.icon.icon = self._images.get(state, self._images["idle"])
        except Exception:
            pass

    def refresh(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
