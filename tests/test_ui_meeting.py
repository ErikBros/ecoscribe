"""Pill / tray / prompt logic for meetings (no tk needed)."""
import json
from datetime import datetime

from ecoscribe import meetui, sessions

T0 = datetime(2026, 10, 5, 14, 0, 0)


def st(status="recording", d="D", started=T0):
    return {"meeting": {"dir": d, "app": "msteams", "lang": "sv", "started": started.isoformat(), "status": status},
            "job": None, "queue": []}


EMPTY = {"meeting": None, "job": None, "queue": []}


def test_view_elapsed_and_live_line():
    v = meetui.meeting_view(st(), now=T0.timestamp() + 12 * 60 + 4, line="hej och välkomna")
    assert v == {"label": "Taking notes 12:04", "short": "12:04", "line": "hej och välkomna", "busy": False}
    v = meetui.meeting_view(st(), now=T0.timestamp() + 3600 + 65, line=None)
    assert v["label"] == "Taking notes 1:01:05" and v["line"] == ""


def test_view_finalizing_and_none():
    assert meetui.meeting_view(st("finalizing"), now=T0.timestamp(), line="x")["label"] == "Saving…"
    assert meetui.meeting_view(st("stopping"), now=T0.timestamp(), line="x")["busy"] is True
    assert meetui.meeting_view(EMPTY, now=0, line=None) is None


def test_long_line_truncated_from_the_left():
    v = meetui.meeting_view(st(), now=T0.timestamp(), line="a" * 30 + " slutet av meningen", width=24)
    assert len(v["line"]) <= 24 and v["line"].startswith("…") and v["line"].endswith("meningen")


def test_pill_layer_state_machine():
    v = meetui.meeting_view(st(), now=T0.timestamp(), line="")
    assert meetui.pill_layer("hidden", None) == "hidden"
    assert meetui.pill_layer("hidden", v) == "meeting"
    assert meetui.pill_layer("recording", v) == "dictation"  # dictating over a meeting shows Dictando
    assert meetui.pill_layer("busy", v) == "dictation"
    assert meetui.pill_layer("hidden", v) == "meeting"  # and comes back to Tomando notas


def test_tracker_done_and_failed(tmp_path):
    d = sessions.create("Reunión", "sv", "meeting", tmp_path)
    tr = meetui.Tracker()
    assert tr.update(st(d=str(d))) == []
    sessions.write_meta(d, status="done")
    assert tr.update(EMPTY) == [("done", str(d))]
    assert tr.update(EMPTY) == []
    e = sessions.create("Reunión", "sv", "meeting", tmp_path)
    tr.update(st(d=str(e)))
    sessions.write_meta(e, status="failed")
    assert tr.update(EMPTY) == [("failed", str(e))]


def test_tracker_job_done(tmp_path):
    d = sessions.create("Podcast", "el", "import", tmp_path)
    tr = meetui.Tracker()
    tr.update({"meeting": None, "job": {"dir": str(d), "pct": 3}, "queue": []})
    sessions.write_meta(d, status="done")
    assert tr.update(EMPTY) == [("done", str(d))]


def test_tracker_says_nothing_when_a_speakers_pass_ends(tmp_path):
    """The meeting was announced ready when its transcript ended; the speakers pass is quiet (dictado-bvh)."""
    d = sessions.create("Reunión", "sv", "meeting", tmp_path)
    tr = meetui.Tracker()
    tr.update(st(d=str(d)))
    sessions.write_meta(d, status="done", speakers="pending")
    assert tr.update(EMPTY) == [("done", str(d))]
    tr.update({"meeting": None, "job": {"dir": str(d), "pct": 0, "kind": "speakers"}, "queue": []})
    sessions.write_meta(d, speakers="done")
    assert tr.update(EMPTY) == []


def test_tray_label_and_state():
    assert meetui.tray_meeting_label(EMPTY) == "Transcribe meeting now"
    assert meetui.tray_meeting_label(st()) == "Stop meeting"
    assert meetui.tray_meeting_label(st("finalizing")) == "Saving meeting…"
    assert meetui.tray_state("idle", st()) == "recording"  # red while a meeting records
    assert meetui.tray_state("idle", st("finalizing")) == "busy"
    assert meetui.tray_state("idle", EMPTY) == "idle"
    assert meetui.tray_state("busy", st()) == "busy"  # dictation states win


def test_last_live_line_reads_the_tail(tmp_path):
    p = tmp_path / "live.jsonl"
    assert meetui.last_live_line(tmp_path) is None
    with open(p, "w", encoding="utf-8") as f:
        for i in range(5000):
            f.write(json.dumps({"t0": i, "t1": i + 1, "text": f"rad {i}"}) + "\n")
        f.write('{"t0": 1, "t1"')  # a half-written line from the worker
    assert meetui.last_live_line(tmp_path) == "rad 4999"


def test_prompt_texts_and_timeout():
    p = meetui.Prompt("start", "msteams", "sv", opened_at=100.0)
    assert p.title == "Are you in a meeting? Take notes?"
    assert p.question == "Teams is using the mic. Language:"
    assert p.buttons == [("Take notes", "transcribir"), ("Not now", "ahora_no")]
    assert p.expired(109.9) is None
    assert p.expired(110.0) == "ahora_no"  # no answer in 10 s = Not now (t0u.21)
    assert p.countdown(100.0) == 10 and p.countdown(105.5) == 5 and p.countdown(109.9) == 1
    assert p.button_text("ahora_no", 103.2) == "Not now (7)" and p.button_text("transcribir", 103.2) == "Take notes"
    e = meetui.Prompt("end?", None, None, opened_at=0.0)
    assert e.title == "Did the meeting end?"
    assert e.buttons == [("Stop", "parar"), ("Keep going", "seguir")]
    assert e.expired(59.0) is None and e.expired(61.0) == "hide"  # the watcher stops it by itself
    assert e.countdown(10.0) == 50 and e.button_text("seguir", 10.0) == "Keep going"
    assert e.button_text("parar", 10.0) == "Stop (50)"  # no answer stops it: the count is on Stop
    d = meetui.Prompt("done", "C:/x/2026-10-05_1400_reunion", None, opened_at=0.0)
    assert d.title == "Transcript ready" and d.buttons[0] == ("Open", "abrir")
    assert meetui.app_name("slack") == "Slack" and meetui.app_name("chrome") == "Chrome"


def test_no_em_dashes_in_strings():
    import inspect
    assert "\u2014" not in inspect.getsource(meetui)


import time

import pytest


@pytest.mark.win
def test_tk_meeting_pill_and_prompt_box():
    """Real tk: the meeting layer resizes the pill, dictation wins it, the prompt answers.
    Opens two no-activate windows for under a second; no OS input is injected."""
    import tkinter as tk
    from ecoscribe.platform.windows import shell as ui
    root = tk.Tk()
    root.withdraw()
    try:
        ov = ui.Overlay(root)
        view = meetui.meeting_view(st(), now=T0.timestamp() + 5, line="hej")
        ov.set_meeting(view)
        assert (ov.w, ov.h) == (ui.CW, ui.CH) and ov._drawn == ("Taking notes 0:05", "hej", False, False)  # the chip
        ov.open = True  # the mouse on it (dictado-z4j): the live line
        ov._show_layer()
        assert (ov.w, ov.h) == (ui.MW, ui.MH) and ov._drawn == ("Taking notes 0:05", "hej", False, True)
        ov.open = False
        ov.recording(0.0)
        assert (ov.w, ov.h) == (ui.RW, ui.RH)  # Dictando wins, with the cancel line (t0u.36)
        ov.idle()
        assert (ov.w, ov.h) == (ui.CW, ui.CH)  # back to the meeting chip
        ov.set_meeting(None)
        assert ov._drawn is None
        answers = []
        pw = ui.PromptWindow(root, lambda p, c, lang: answers.append((p.kind, c, lang)))
        meetui.set_langs(["es", "el"])  # Greek and Spanish added (dictado-ehs)
        pw.show(meetui.Prompt("start", "msteams", "el", opened_at=0.0))
        root.update()
        assert pw.top.winfo_exists() and pw._lang_code() == "el"
        pw._answer("transcribir")
        assert answers == [("start", "transcribir", "el")] and pw.top is None
        pw.show(meetui.Prompt("start", "slack", "sv", opened_at=-1e9))
        pw.tick()  # long expired: Ahora no
        assert answers[-1] == ("start", "ahora_no", "sv")
        pw.show(meetui.Prompt("start", "signal", "es", opened_at=time.monotonic() - 3.2))
        pw.tick()
        assert pw._btns["ahora_no"].cget("text") == "Not now (7)"  # t0u.21: the countdown on screen
        pw._answer("ahora_no")
    finally:
        meetui.set_langs([])  # the language list is module state: don't leak Greek + Spanish into later tests
        root.destroy()


@pytest.mark.win
def test_the_pill_is_one_layered_picture_that_never_takes_focus():
    """dictado-acm: the pill is drawn by UpdateLayeredWindow (per-pixel alpha), at the picture's size,
    click-through and no-activate. Off-screen, so nothing shows; no OS input is injected."""
    import ctypes
    import tkinter as tk
    from ctypes import wintypes
    from ecoscribe.platform.windows import pillart
    from ecoscribe.platform.windows import shell as ui
    u32 = ctypes.WinDLL("user32")
    u32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    root = tk.Tk()
    root.withdraw()
    try:
        before = u32.GetForegroundWindow()
        ov = ui.Overlay(root)
        ov._anchor = (-4000, -4000)  # well off every screen
        ov._notice("Scratched")
        u32.ShowWindow(ov.hwnd, ui.SW_SHOWNOACTIVATE)
        root.update()
        rc = wintypes.RECT()
        u32.GetWindowRect(ov.hwnd, ctypes.byref(rc))
        assert ov._ulw_ok and (rc.right - rc.left, rc.bottom - rc.top) == (ov.w + 2 * pillart.M, ov.h + 2 * pillart.M)
        ex = ov.ex_style()
        assert ex & ui.WS_EX_LAYERED and ex & ui.WS_EX_TRANSPARENT and ex & ui.WS_EX_NOACTIVATE
        ov._levels = [0.4] * 10
        ov._dictating_pill(5, 0.5)
        root.update()
        u32.GetWindowRect(ov.hwnd, ctypes.byref(rc))
        assert (rc.right - rc.left) == ui.RW + 2 * pillart.M and rc.bottom == -4000 + pillart.M  # grows from its bottom centre
        assert u32.GetForegroundWindow() == before
    finally:
        root.destroy()


def test_a_note_never_hides_a_question():
    start = meetui.Prompt("start", "msteams", "sv", 0.0)
    end = meetui.Prompt("end?", None, None, 0.0)
    done = meetui.Prompt("done", "C:/x/d", None, 0.0)
    assert meetui.placement(None, start) == "show"
    assert meetui.placement(start, done) == "queue"  # job finished as a call started: the call prompt stays
    assert meetui.placement(end, done) == "queue"
    assert meetui.placement(done, start) == "show"  # a call prompt replaces a mere note
    assert meetui.placement(start, end) == "displace"


def test_tray_language_submenu():
    assert [n for _, n, _ in meetui.tray_lang_items("sv")] == ["English", "Swedish", "English + Swedish", "Detect"]
    meetui.set_langs(["es", "el"])  # dictado-ehs: the user's added languages join the list
    try:
        items = meetui.tray_lang_items("el")
        assert [n for _, n, _ in items] == ["English", "Swedish", "Spanish", "Greek", "Mixed: EN · SV · ES · EL", "Detect"]
        assert [c for c, _, ticked in items if ticked] == ["el"]  # the last language used is ticked
    finally:
        meetui.set_langs([])
    assert meetui.tray_recording(EMPTY) is False and meetui.tray_recording(st()) is True


def test_short_label_for_the_compact_chip():
    assert meetui.meeting_view(st("finalizing"), now=T0.timestamp(), line="x")["short"] == "Saving…"


def test_hover_inside_the_pill_with_a_margin():
    rect = (100, 500, 200, 530)  # left, top, right, bottom
    assert meetui.hovering((150, 515), rect)
    assert meetui.hovering((95, 515), rect)  # a few px off still counts: no flicker at the edge
    assert not meetui.hovering((150, 400), rect)
    assert not meetui.hovering(None, rect) and not meetui.hovering((150, 515), None)


def test_done_prompt_says_which_meeting(tmp_path):
    d = sessions.create("Weekly planning", "sv", "meeting", tmp_path)
    sessions.write_meta(d, duration_s=23 * 60 + 10)
    p = meetui.Prompt("done", str(d), None, opened_at=0.0)
    assert p.title == "Transcript ready" and p.question == "Weekly planning · 23 min"
    assert meetui.Prompt("failed", str(d), None, opened_at=0.0).question == "Weekly planning · 23 min"
    assert meetui.Prompt("done", str(tmp_path / "gone"), None, opened_at=0.0).question == ""  # no meta: no line


def test_summary_prompt_says_which_meeting_and_opens_it(tmp_path):  # dictado-nl5
    d = sessions.create("Weekly planning", "sv", "meeting", tmp_path)
    sessions.write_meta(d, duration_s=23 * 60 + 10)
    p = meetui.Prompt("summary", str(d), None, opened_at=0.0)
    assert p.title == "Summary ready" and p.question == "Weekly planning · 23 min"
    assert [c for _l, c in p.buttons] == ["abrir", "hide"]


def test_nomic_prompt_names_the_mic():
    p = meetui.Prompt("nomic", "Zone Vibe 100", None, opened_at=0.0)
    assert "Zone Vibe 100" in p.question and [c for _l, c in p.buttons] == ["mic", "hide"]
    assert p.expired(1000.0) == "hide"


def test_every_box_counts_down_on_what_its_timeout_does():
    d = meetui.Prompt("done", "C:/x/none", None, opened_at=0.0)
    assert d.button_text("hide", 3.2) == "Close (12)" and d.button_text("abrir", 3.2) == "Open"
    n = meetui.Prompt("nomic", "Zone Vibe 100", None, opened_at=0.0)
    assert n.button_text("hide", 0.0) == "Close (15)" and n.button_text("mic", 0.0) == "Check the mic"
