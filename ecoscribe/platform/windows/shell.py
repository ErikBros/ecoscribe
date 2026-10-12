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
from ... import palette as P

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
W, H = 210, 44
RW, RH = 236, 38  # the dictating pill: dot, waveform, timer (dictado-3tl)
WAVE_N = 24  # waveform bars: about the last second of the voice (one per 50 ms tick)
WAVE_W = 130  # the waveform's width, the same with or without live text
MW, MH = 380, 56  # the meeting pill opened by the mouse: label + latest live line
CW, CH = 92, 30  # the meeting pill as it sits: a small chip, recording dot + timer (dictado-z4j)
LW, LH = 440, 66  # the dictating pill with one line of live text under it (dictado-live)
KEY = "#010203"  # transparent color key, gives the pill round ends


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]


class Overlay:
    def __init__(self, root: tk.Tk, level_fn=lambda: 0.0, hint: str = "Right Ctrl + Esc to cancel"):
        self.level_fn = level_fn
        self.hint = hint
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-alpha", 0.93)
        self.top.attributes("-transparentcolor", KEY)
        self.top.geometry(f"{W}x{H}+0+0")
        self.c = tk.Canvas(self.top, width=W, height=H, bg=KEY, highlightthickness=0, bd=0)
        self.c.pack()
        self.top.update_idletasks()
        self.hwnd = int(self.top.wm_frame(), 16)
        ex = u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                           ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        u32.ShowWindow(self.hwnd, SW_HIDE)
        self.mode = "hidden"
        self._t0 = 0.0
        self._flash_until = 0.0
        self._flash_msg = ""
        self.w, self.h = W, H
        self.meeting: dict | None = None  # meetui.meeting_view(); shown whenever dictation isn't
        self._drawn = None  # what the meeting layer last drew (no redraw, no flicker)
        self.live_text = ""  # what the live transcript has heard so far (this recording)
        self._levels: list[float] = []  # the waveform: voice level per tick, newest last
        import tkinter.font as tkf
        self._live_font = tkf.Font(family="Segoe UI", size=10)
        self.open = False  # the meeting chip is opened by the mouse over it (dictado-z4j)

    def ex_style(self) -> int:
        return u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)

    def _place_and_show(self) -> None:
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = u32.MonitorFromWindow(u32.GetForegroundWindow(), 2)
        if mon and u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            r = mi.rcWork
            x, y = (r.left + r.right - self.w) // 2, r.bottom - self.h - 80
        else:
            x, y = 600, 900
        u32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        u32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def _size(self, w_: int, h_: int) -> None:
        if (w_, h_) != (self.w, self.h):
            self.w, self.h = w_, h_
            self.top.geometry(f"{w_}x{h_}")
            self.c.config(width=w_, height=h_)

    def _pill(self, dot: str, label: str) -> None:
        self._size(W, H)
        self._drawn = None
        c = self.c
        c.delete("all")
        r = H // 2
        bg = P.INK
        c.create_oval(0, 0, H, H, fill=bg, outline=bg)
        c.create_oval(W - H, 0, W, H, fill=bg, outline=bg)
        c.create_rectangle(r, 0, W - r, H, fill=bg, outline=bg)
        if dot:
            c.create_oval(16, r - 6, 28, r + 6, fill=dot, outline=dot)
        c.create_text(40 if dot else W // 2, r, text=label, fill=P.PAPER,
                      font=("Segoe UI", 11), anchor="w" if dot else "center")

    def _dictating_pill(self, secs: int, level: float) -> None:
        """A slim ink pill (dictado-3tl, the user picked it): the recording dot, a waveform of the
        last second or so of the voice, the timer. How to cancel shows in the waveform's place
        for the first 2 s. With live text, a second line under it: the newest words."""
        self._levels.append(level)
        del self._levels[:-WAVE_N]
        live = self.live_text
        w_, h_ = (LW, LH) if live else (RW, RH)
        grew = (w_, h_) != (self.w, self.h)
        self._size(w_, h_)
        if grew:
            self._place_and_show()  # stay centered above the taskbar at the new size
        self._drawn = None
        c = self.c
        c.delete("all")
        bg, r = P.INK, min(h_, 2 * RH) // 2 if not live else 18
        c.create_oval(0, 0, 2 * r, 2 * r, fill=bg, outline=bg)
        c.create_oval(w_ - 2 * r, 0, w_, 2 * r, fill=bg, outline=bg)
        c.create_oval(0, h_ - 2 * r, 2 * r, h_, fill=bg, outline=bg)
        c.create_oval(w_ - 2 * r, h_ - 2 * r, w_, h_, fill=bg, outline=bg)
        c.create_rectangle(r, 0, w_ - r, h_, fill=bg, outline=bg)
        c.create_rectangle(0, r, w_, h_ - r, fill=bg, outline=bg)
        mid = RH // 2
        on = int(time.monotonic() * 2) % 2 == 0 or level > 0.05  # the dot breathes while it's quiet
        if on:  # a soft halo while it's lit (dictado-6oe.9)
            c.create_oval(12, mid - 9, 30, mid + 9, fill=P.TILE_HALO, outline="")
        c.create_oval(16, mid - 5, 26, mid + 5, fill=P.TILE if on else P.TILE_DIM, outline="")
        c.create_text(w_ - 16, mid, text=f"{secs // 60}:{secs % 60:02d}", fill=P.PAPER,
                      font=("Segoe UI", 10, "bold"), anchor="e")
        x0 = 38
        x1 = x0 + WAVE_W
        if secs < 2:  # how to cancel, drawn as the keys themselves (dictado-6oe.9)
            keys = self.hint.split(" to ")[0].split(" + ")
            x = _keycaps(c, x0, mid, keys)
            c.create_text(x + 6, mid, text="cancels", fill=P.LINE, font=("Segoe UI", 9), anchor="w")
        else:  # the waveform: newest on the right, each bar from the middle line
            step = (x1 - x0) / WAVE_N
            pad = [0.0] * (WAVE_N - len(self._levels)) + self._levels
            for i, lv in enumerate(pad):
                hh = 2 + (lv ** 1.5) * (RH - 18)
                x = x0 + i * step + step / 2
                c.create_line(x, mid - hh / 2, x, mid + hh / 2, fill=P.PAPER if lv > 0.04 else P.PILL_OFF,
                              width=2, capstyle="round")
        if live:
            f = self._live_font
            text, room = " ".join(live.split()), w_ - 32
            if f.measure(text) > room:  # one line: the newest words, cut on the left
                while text and f.measure("…" + text) > room:
                    text = text.split(" ", 1)[1] if " " in text else text[1:]
                text = "…" + text
            c.create_text(16, RH + 6, text=text, fill=P.PAPER, font=f, anchor="w")

    def _hover(self) -> bool:
        pt, rc = w.POINT(), w.RECT()
        if not (u32.GetCursorPos(ctypes.byref(pt)) and u32.GetWindowRect(self.hwnd, ctypes.byref(rc))):
            return False
        return meetui.hovering((pt.x, pt.y), (rc.left, rc.top, rc.right, rc.bottom))

    def _meeting_chip(self, view: dict) -> None:
        """The meeting as it sits: a small dark chip, recording dot + timer. Click-through."""
        self._size(CW, CH)
        c = self.c
        c.delete("all")
        r, bg = CH // 2, P.INK
        c.create_oval(0, 0, CH, CH, fill=bg, outline=bg)
        c.create_oval(CW - CH, 0, CW, CH, fill=bg, outline=bg)
        c.create_rectangle(r, 0, CW - r, CH, fill=bg, outline=bg)
        dot = P.AEGEAN_SOFT if view["busy"] else P.TILE
        c.create_oval(12, r - 5, 22, r + 5, fill=dot, outline=dot)
        c.create_text(30, r, text=view.get("short") or view["label"], fill=P.PAPER, font=("Segoe UI", 10), anchor="w")

    def _meeting_pill(self, view: dict) -> None:
        key = (view["label"], view["line"], view["busy"], self.open)
        if key == self._drawn:
            return
        if not self.open:
            self._meeting_chip(view)
            self._place_and_show()
            self._drawn = key
            return
        self._size(MW, MH)
        c = self.c
        c.delete("all")
        r, bg = MH // 2, P.INK
        c.create_oval(0, 0, MH, MH, fill=bg, outline=bg)
        c.create_oval(MW - MH, 0, MW, MH, fill=bg, outline=bg)
        c.create_rectangle(r, 0, MW - r, MH, fill=bg, outline=bg)
        dot = P.AEGEAN_SOFT if view["busy"] else P.TILE
        c.create_oval(18, r - 6, 30, r + 6, fill=dot, outline=dot)
        if view["line"]:
            c.create_text(42, 18, text=view["label"], fill=P.PAPER, font=("Segoe UI", 10, "bold"), anchor="w")
            c.create_text(42, 38, text=view["line"], fill=P.LINE, font=("Segoe UI", 10), anchor="w")
        else:
            c.create_text(42, r, text=view["label"], fill=P.PAPER, font=("Segoe UI", 11), anchor="w")
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
        self._place_and_show()
        self.tick()

    def busy(self) -> None:
        """Transcribing: three soft dots and what it's doing (dictado-6oe.9)."""
        self.mode = "busy"
        self.live_text = ""
        self._pill("", "")
        c, r = self.c, H // 2
        for i, col in enumerate((P.AEGEAN_BRIGHT, "#7fa6c4", "#c9dcea")):
            c.create_oval(22 + i * 11, r - 3, 28 + i * 11, r + 3, fill=col, outline="")
        c.create_text(62, r, text="Writing it down", fill=P.PAPER, font=("Segoe UI", 10, "bold"), anchor="w")
        self._place_and_show()

    def idle(self) -> None:
        self.mode = "hidden"
        self.live_text = ""
        if time.monotonic() >= self._flash_until:
            self._show_layer()

    def flash(self, msg: str, seconds: float = 2.0) -> None:
        self._flash_msg, self._flash_until = msg, time.monotonic() + seconds
        if self.mode == "recording":
            return
        self._pill("", msg)
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


PW = 360  # the prompt box's least width


def _prompt_icon(c: tk.Canvas, x: float, y: float, kind: str) -> None:
    """A 38 px tile with a glyph for the box's kind: a call (the clay dot), silence (a clock),
    a transcript (a page), no sound (a mic, struck through)."""
    _round_rect(c, x, y, x + 38, y + 38, 11, fill="#3a2a22" if kind == "start" else "#2a3542")
    cx, cy, g = x + 19, y + 19, "#9db7cc"
    if kind == "start":
        c.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill="#e06a35", outline="")
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


def _keycaps(c: tk.Canvas, x: float, mid: float, keys) -> float:
    """Keys as small outlined caps on ink: [Right Ctrl] + [Esc]. Returns where they end."""
    import tkinter.font as tkf
    f = tkf.Font(family="Segoe UI", size=8, weight="bold")
    for i, k in enumerate(keys):
        if i:
            c.create_text(x + 4, mid, text="+", fill=P.LINE, font=("Segoe UI", 8), anchor="w")
            x += 14
        w = f.measure(k) + 12
        _round_rect(c, x, mid - 9, x + w, mid + 9, 5, fill="", outline="#4a5563", width=1)
        c.create_text(x + w / 2, mid, text=k, fill=P.PAPER, font=f)
        x += w
    return x


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
            fill, hover, ink = (P.PAPER, "#dfe5ea", P.INK) if primary else (P.PILL_OFF, P.INK_2, P.PAPER)
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
        self._drain = (c, c.create_line(20, height - 2, width - 20, height - 2, fill="#7fa6c4", width=3, capstyle="round"), width)
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
