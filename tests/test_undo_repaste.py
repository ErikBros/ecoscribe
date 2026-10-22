"""Take back the last paste by saying "scratch that", paste it again with dictation key + R (dictado-ost).
Invented text only."""
import sys
import time

import pytest

from ecoscribe import corrections
from ecoscribe.app import App
from ecoscribe.config import Config
from ecoscribe.deliver import DeliveryResult
from ecoscribe.engine import Result
from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait

RCTRL = 0xA3


def test_only_a_lone_scratch_that_takes_back_a_paste():
    assert corrections.scratch_only("Scratch that.") and corrections.scratch_only(" borra eso ")
    assert corrections.scratch_only("Stryk det!") and corrections.scratch_only("Σβήσε το.")
    assert not corrections.scratch_only("Hello. Scratch that.")
    assert not corrections.scratch_only("Scratch that itch.")


class Said:
    def __init__(self, *texts):
        self.texts = list(texts)

    def transcribe(self, audio):
        return Result(text=self.texts.pop(0), lang="en", speech_s=1.0, ms=5)


def _app(tmp_path, *texts, windows=(7,), undo_ok=True, on="voice_commands"):
    cfg = Config()
    setattr(cfg.text, on, True)
    pasted, undos, focus = [], [], list(windows)

    def deliver(t):
        pasted.append(t)
        return DeliveryResult(True, "notes.exe", "ok", window=focus[0])

    def undo():
        undos.append(1)
        return undo_ok
    app = App(cfg, FakeRecorder(), Said(*texts), deliver, FakeUi(), gate=FakeGate(),
              history_path=tmp_path / "h.jsonl", press_enter=lambda: None, undo=undo, window_now=lambda: focus[0])
    app.start()
    return app, pasted, undos, focus


def _dictate(app, n_before):
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: app._pending == 0 and len(app.ui.events) > n_before)
    time.sleep(0.2)


def flashes(app):
    return [e[1] for e in app.ui.events if e[0] == "flash"]


def test_scratch_that_alone_undoes_the_last_paste_in_the_same_window(tmp_path):
    app, pasted, undos, _ = _app(tmp_path, "Buy milk tomorrow. ", "Scratch that. ")
    _dictate(app, 0)
    _dictate(app, len(app.ui.events))
    assert pasted == ["Buy milk tomorrow. "] and undos == [1]
    assert "Took back the last dictation" in flashes(app)


def test_never_undoes_in_another_window_or_later_or_twice(tmp_path):
    app, pasted, undos, focus = _app(tmp_path, "Buy milk tomorrow. ", "Scratch that. ")
    _dictate(app, 0)
    focus[0] = 9  # the user moved to another window: Ctrl+Z there would undo their own typing
    _dictate(app, len(app.ui.events))
    assert undos == [] and "Nothing to take back here" in flashes(app)
    app._last_paste = (9, time.monotonic() - 61, "x")  # a minute later
    assert not app.undo_last() and undos == []
    app._last_paste = (9, time.monotonic(), "x")
    assert app.undo_last() and not app.undo_last() and undos == [1]  # only once


def test_off_unless_voice_commands_or_self_corrections(tmp_path):
    app, pasted, undos, _ = _app(tmp_path, "Buy milk tomorrow. ", "Scratch that. ", on="strip_fillers")
    _dictate(app, 0)
    _dictate(app, len(app.ui.events))
    assert pasted == ["Buy milk tomorrow. ", "Scratch that. "] and undos == []


def test_a_dictation_scratched_inside_itself_pastes_nothing_and_is_not_unheard(tmp_path):
    app, pasted, undos, _ = _app(tmp_path, "Wrong words. Scratch that. ", on="self_corrections")
    _dictate(app, 0)
    assert pasted == [] and undos == [] and "Scratched" in flashes(app) and app._unheard == 0


def test_dictation_key_r_pastes_the_last_dictation_again(tmp_path):
    app, pasted, undos, _ = _app(tmp_path, "Buy milk tomorrow. ")
    app.on_action("repaste")
    assert wait(lambda: "Nothing to paste yet" in flashes(app))
    _dictate(app, len(app.ui.events))
    app.on_action("repaste")
    assert wait(lambda: len(pasted) == 2) and pasted == ["Buy milk tomorrow. "] * 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows hook")
def test_hook_swallows_r_only_with_the_dictation_key_held():
    from ecoscribe.platform.windows.hook import VK_EDIT, VK_REPASTE, HookThread
    events = []
    h = HookThread(lambda a: None, RCTRL, 0.3, emit=events.append, consume=False)
    assert not h.action_key(VK_REPASTE, True)  # a normal R: typed as usual
    h._toggle_down = True
    assert h.action_key(VK_REPASTE, True) and h.action_key(VK_REPASTE, True)
    assert h.action_key(VK_EDIT, True)
    assert [e[0] for e in events] == ["repaste", "edit"]  # auto-repeat fires once
    h._toggle_down = False
    assert h.action_key(VK_REPASTE, False) and h.action_key(VK_EDIT, False) and not h._action_held
    assert not h.action_key(0x43, True)  # Right Ctrl + C is untouched
