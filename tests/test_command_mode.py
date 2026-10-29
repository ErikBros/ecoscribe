"""Command mode (dictado-ua2): select text, dictation key + E, say what to change. Invented text only."""
import sys

import pytest

from ecoscribe import claude_cli, command_mode
from ecoscribe.app import UNDO_KEYS, App
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


def test_a_writing_style_file_goes_with_the_edit_and_uses_sonnet(tmp_path):
    """dictado-jq7p: the user's own style guide (invented here), read on every edit."""
    style = tmp_path / "style.md"
    style.write_text("\ufeffShort sentences. Warm, never formal. Swedish: du, not ni.\n", encoding="utf-8")
    c = _cfg()
    c.text.command_style_file = str(style)
    seen = {}

    def ask(text, system, model, timeout, command):
        seen.update(text=text, model=model)
        return "Hej! Butiken öppnar nio."
    assert command_mode.edit("The shop opens at nine.", "translate to Swedish", c, ask=ask) == "Hej! Butiken öppnar nio."
    assert seen["model"] == "sonnet"
    assert "<style>\nShort sentences. Warm, never formal. Swedish: du, not ni.\n</style>" in seen["text"]
    assert seen["text"].index("never add facts") < seen["text"].index("<style>") < seen["text"].index("Selected text:")
    style.write_text("Long and formal.", encoding="utf-8")  # edited: the next edit takes the new text
    command_mode.edit("x", "make it shorter", c, ask=ask)
    assert "<style>\nLong and formal.\n</style>" in seen["text"]


def test_a_missing_style_file_edits_without_it(tmp_path):
    c = _cfg()
    c.text.command_style_file = str(tmp_path / "gone.md")
    seen = {}

    def ask(text, system, model, timeout, command):
        seen.update(text=text, model=model)
        return "ok"
    assert command_mode.edit("x", "make it shorter", c, ask=ask) == "ok"
    assert seen["model"] == "haiku" and "<style>" not in seen["text"]


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
    assert pasted == ["The shop opens at nine."] and f"Changed: {UNDO_KEYS} undoes it" in flashes(app)
    assert app.last_text == ""  # an edit isn't a dictation: paste-again keeps the last dictation
    kept = command_mode.recent(tmp_path)  # dictado-kgjf: kept next to the history, to rerun exactly
    assert [(k["selection"], k["instruction"], k["result"], k["error"]) for k in kept] == [
        ("Teh shop opens at nine.", "fix the spelling", "The shop opens at nine.", None)]


def test_a_failed_edit_pastes_nothing(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise claude_cli.ClaudeError("Not logged in")
    monkeypatch.setattr(claude_cli, "ask", fail)
    app, pasted = _app(tmp_path, "fix the spelling")
    _edit(app)
    assert pasted == [] and any("nothing changed" in f for f in flashes(app))
    assert "Not logged in" in command_mode.recent(tmp_path)[0]["error"]


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


def test_the_command_mode_keys_again_stop_the_instruction(tmp_path, monkeypatch):
    """dictado-a1d: with a combo of its own, pressing it again is the stop; the pill says so."""
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: "The shop opens at nine.")
    app, pasted = _app(tmp_path, "fix the spelling")
    app.cfg.text.command_key = "ctrl+shift+e"
    app.on_action("edit")
    assert wait(lambda: app.state == "recording")
    assert "Say what to change, then press Ctrl+Shift+E again" in flashes(app)
    app.on_action("edit")
    assert wait(lambda: pasted == ["The shop opens at nine."])


def test_the_default_keys_say_tap_the_dictation_key(tmp_path):
    app, _ = _app(tmp_path, "fix the spelling")
    app.on_action("edit")
    assert wait(lambda: app.state == "recording")
    assert "Say what to change, then tap Right Ctrl" in flashes(app) or sys.platform == "darwin"
    app.on_action("cancel")


# ---------------- dictado-7rcc: "make this shorter" gets a word budget ----------------
LONG = " ".join(["The new build is ready and the tests pass on both machines."] * 4)  # 48 words, invented


@pytest.mark.parametrize("instruction,budget", [
    ("make this shorter", 24), ("shorten it", 24), ("make it much shorter", 16), ("hazlo más corto", 24),
    ("gör den kortare", 24), ("tighten this up", 24)])
def test_a_shortening_instruction_gets_a_word_budget(instruction, budget):
    assert command_mode.budget(instruction, LONG) == budget
    rule = command_mode.length_rule(instruction, LONG)
    assert "48 words" in rule and f"never more than {budget}" in rule


@pytest.mark.parametrize("instruction", ["make it shorter, about 20 words", "translate to Swedish", "fix the typos",
                                         "make it more formal"])
def test_other_instructions_and_a_said_number_get_none(instruction):
    assert command_mode.length_rule(instruction, LONG) == "" and command_mode.budget(instruction, LONG) is None


def test_the_budget_goes_in_the_request():
    asked = []
    command_mode.edit(LONG, "make this shorter", _cfg(), ask=lambda text, system, **k: asked.append(text) or "Short.")
    assert "never more than 24" in asked[0] and asked[0].index("never more than 24") < asked[0].index("Selected text:")


def test_with_a_style_file_the_budget_comes_after_it(tmp_path):
    style = tmp_path / "style.md"
    style.write_text("Short sentences.", encoding="utf-8")
    c = _cfg()
    c.text.command_style_file = str(style)
    asked = []
    command_mode.edit(LONG, "make this shorter", c, ask=lambda text, system, **k: asked.append(text) or "Short.")
    assert asked[0].index("</style>") < asked[0].index("never more than 24") < asked[0].index("Selected text:")


def test_only_the_last_five_edits_are_kept_and_never_logged(tmp_path, caplog):
    for i in range(7):
        command_mode.remember(tmp_path, f"Text {i}.", f"instruction {i}", result=f"Result {i}.")
    kept = command_mode.recent(tmp_path)
    assert [k["instruction"] for k in kept] == [f"instruction {i}" for i in range(2, 7)]
    assert "instruction" not in caplog.text and "Text " not in caplog.text
    command_mode.remember(None, "x", "y")  # no data folder (tests, --test): nothing kept, nothing raised
    (tmp_path / command_mode.RECENT).write_text("not json", encoding="utf-8")
    assert command_mode.recent(tmp_path) == []
