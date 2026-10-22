"""Self-corrections in dictation (dictado-ehc). Invented text only."""
import pytest

from ecoscribe import claude_cli, corrections
from ecoscribe.config import Config


def _cfg(on=True):
    c = Config()
    c.text.self_corrections = on
    return c


@pytest.mark.parametrize("said, written", [
    ("Send it Monday. Call the shop Tuesday, scratch that, call the shop Wednesday. ",
     "Send it Monday. Call the shop Wednesday. "),
    ("First point. Second point. Scratch that.", "First point."),
    ("Scratch that. ", ""),
    ("Hola. Esto no va. Borra eso. Esto sí. ", "Hola. Esto sí. "),
    ("Ett. Två. Stryk det. Tre.", "Ett. Tre."),
    ("Καλημέρα. Λάθος. Σβήσε το. Καλησπέρα.", "Καλημέρα. Καλησπέρα."),
])
def test_scratch_that_drops_the_sentence_before_it(said, written):
    assert corrections.scratch_that(said) == written


@pytest.mark.parametrize("said", ["I need to scratch that itch. ", "Scratch that itch.", "Please delete that file."])
def test_scratch_that_inside_a_sentence_stays_text(said):
    assert corrections.scratch_that(said) == said


def test_only_a_correction_phrase_wants_the_model():
    assert corrections.wants_model("Meet on Tuesday, no wait, on Thursday.")
    assert corrections.wants_model("El martes, no perdón, el jueves.")
    assert corrections.wants_model("På tisdag, nej förlåt, på torsdag.")
    assert not corrections.wants_model("There is no waiting room.")
    assert not corrections.wants_model("Meet on Thursday.")


def _ask(answer=None, error=None):
    calls = []

    def ask(text, system, model, timeout, command):
        calls.append({"text": text, "model": model, "timeout": timeout})
        if error:
            raise error
        return answer
    return ask, calls


def test_off_by_default_and_nothing_sent_without_a_phrase():
    ask, calls = _ask("x")
    said = "Meet on Tuesday, no wait, on Thursday. "
    assert corrections.apply(said, Config(), ask=ask) == said
    assert corrections.apply("Meet on Thursday. ", _cfg(), ask=ask) == "Meet on Thursday. "
    assert calls == []


def test_a_correction_goes_to_haiku_with_a_hard_limit():
    ask, calls = _ask("Meet on Thursday.")
    assert corrections.apply("Meet on Tuesday, no wait, on Thursday. ", _cfg(), ask=ask) == "Meet on Thursday. "
    assert calls[0]["model"] == "haiku" and calls[0]["timeout"] == 5.0


@pytest.mark.parametrize("error", [claude_cli.ClaudeError("timed out"), OSError("gone")])
def test_any_failure_pastes_the_text_as_heard(error):
    ask, _ = _ask(error=error)
    said = "Meet on Tuesday, no wait, on Thursday. "
    assert corrections.apply(said, _cfg(), ask=ask) == said


@pytest.mark.parametrize("answer", ["", "Sure! Here is the corrected text: Meet on Thursday.",
                                    "Meet on Thursday. " + "And a lot more words the speaker never said. " * 2])
def test_an_answer_that_is_not_the_dictation_is_ignored(answer):
    ask, _ = _ask(answer)
    said = "Meet on Tuesday, no wait, on Thursday. "
    assert corrections.apply(said, _cfg(), ask=ask) == said


def test_scratch_that_runs_before_the_model_and_needs_no_model():
    ask, calls = _ask("unused")
    assert corrections.apply("Wrong start. Scratch that. Right start. ", _cfg(), ask=ask) == "Right start. "
    assert calls == []


def test_the_app_pastes_the_corrected_dictation(tmp_path, monkeypatch):
    from ecoscribe.app import App
    from ecoscribe.deliver import DeliveryResult
    from ecoscribe.engine import Result
    from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: "Meet on Thursday.")
    delivered = []

    class Eng:
        def transcribe(self, audio):
            return Result(text="Meet on Tuesday, no wait, on Thursday. ", lang="en", speech_s=1.0, ms=5)
    app = App(_cfg(), FakeRecorder(), Eng(), lambda t: delivered.append(t) or DeliveryResult(True, "x.exe", "ok"),
              FakeUi(), gate=FakeGate(), history_path=tmp_path / "h.jsonl", press_enter=lambda: None)
    app.start()
    app.on_action("toggle"); app.on_action("toggle")
    wait(lambda: delivered)
    assert delivered == ["Meet on Thursday. "]
