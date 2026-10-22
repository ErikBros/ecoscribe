"""Command mode (dictado-ua2): select text, dictation key + E, say what to change. Invented text only."""
import pytest

from ecoscribe import claude_cli, command_mode
from ecoscribe.app import App
from ecoscribe.config import Config
from ecoscribe.deliver import DeliveryResult
from ecoscribe.engine import Result
from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait


def _cfg(on=True):
    c = Config()
    c.text.command_mode = on
    return c


def test_the_selection_and_the_instruction_go_to_haiku():
    seen = {}

    def ask(text, system, model, timeout, command):
        seen.update(text=text, system=system, model=model, timeout=timeout)
        return "The shop opens at nine.\n"
    out = command_mode.edit("Teh shop opens at nine.", "  fix the   spelling ", _cfg(), ask=ask)
    assert out == "The shop opens at nine."
    assert seen["text"].startswith("Instruction: fix the spelling\nRules: ")
    assert seen["text"].endswith("\n\nSelected text:\nTeh shop opens at nine.") and "never add facts" in seen["text"]
    assert seen["model"] == "haiku" and seen["timeout"] == 20.0


@pytest.mark.parametrize("instruction, answer, why", [
    ("", "x", "Didn't hear what to change"),
    ("make it shorter", claude_cli.ClaudeError("Not logged in"), "Claude didn't answer: Not logged in"),
    ("make it shorter", TimeoutError(), "Claude didn't answer (TimeoutError)"),
    ("make it shorter", "  \n", "Claude answered nothing"),
])
def test_every_failure_leaves_the_selection_alone(instruction, answer, why):
    def ask(*a, **k):
        if isinstance(answer, Exception):
            raise answer
        return answer
    with pytest.raises(command_mode.EditError, match=why.replace("(", r"\(").replace(")", r"\)")):
        command_mode.edit("Some text.", instruction, _cfg(), ask=ask)


class Said:
    def __init__(self, *texts):
        self.texts = list(texts)

    def transcribe(self, audio):
        return Result(text=self.texts.pop(0), lang="en", speech_s=1.0, ms=5)


def _app(tmp_path, *said, on=True, selection="Teh shop opens at nine."):
    pasted = []
    app = App(_cfg(on), FakeRecorder(), Said(*said),
              lambda t: pasted.append(t) or DeliveryResult(True, "notes.exe", "ok", window=3), FakeUi(),
              gate=FakeGate(), history_path=tmp_path / "h.jsonl", press_enter=lambda: None,
              copy_selection=lambda: selection)
    app.start()
    return app, pasted


def flashes(app):
    return [e[1] for e in app.ui.events if e[0] == "flash"]


def _edit(app):
    app.on_action("edit")
    assert wait(lambda: app.state == "recording")
    app.on_action("toggle")
    assert wait(lambda: app._pending == 0 and any(f.startswith(("Changed", "Claude", "Didn't")) or "nothing" in f
                                                  for f in flashes(app)))


def test_the_answer_replaces_the_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: "The shop opens at nine.")
    app, pasted = _app(tmp_path, "fix the spelling")
    _edit(app)
    assert pasted == ["The shop opens at nine."] and "Changed: Ctrl+Z undoes it" in flashes(app)
    assert app.last_text == ""  # an edit isn't a dictation: paste-again keeps the last dictation


def test_a_failed_edit_pastes_nothing(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise claude_cli.ClaudeError("Not logged in")
    monkeypatch.setattr(claude_cli, "ask", fail)
    app, pasted = _app(tmp_path, "fix the spelling")
    _edit(app)
    assert pasted == [] and any("nothing changed" in f for f in flashes(app))


def test_off_or_nothing_selected_records_nothing(tmp_path):
    app, _ = _app(tmp_path, on=False)
    app.on_action("edit")
    assert wait(lambda: any(e[0] == "prompt" for e in app.ui.events)) and app.state == "idle"
    assert ("prompt", "cmdoff", None, None) in app.ui.events  # a box with a button to the switch (dictado-1b7)
    app, _ = _app(tmp_path, selection="")
    app.on_action("edit")
    assert wait(lambda: "Select some text first" in flashes(app)) and app.state == "idle"


def test_a_cancelled_edit_leaves_the_next_dictation_a_dictation(tmp_path):
    app, pasted = _app(tmp_path, "Plain words. ")
    app.on_action("edit")
    assert wait(lambda: app.state == "recording")
    app.on_action("cancel")
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: pasted) and pasted == ["Plain words. "]
