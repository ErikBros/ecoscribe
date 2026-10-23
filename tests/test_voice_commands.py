"""Spoken commands (market deep dive 2026-10-05): "new line", "new paragraph", "send it".

Off by default ([text] voice_commands = false): today's text is unchanged unless the user turns it on.
"""
import pytest

from ecoscribe.text import voice_commands


def test_new_line_and_paragraph_in_three_languages():
    assert voice_commands("Hello team. New line. The deploy is fixed. ") == ("Hello team.\nThe deploy is fixed. ", False)
    assert voice_commands("First point, new paragraph, second point. ") == ("First point.\n\nSecond point. ", False)
    assert voice_commands("Hola. Nueva línea. Qué tal. ") == ("Hola.\nQué tal. ", False)
    assert voice_commands("Hej. Ny rad. Vi ses. ") == ("Hej.\nVi ses. ", False)


def test_send_it_at_the_end_presses_enter():
    assert voice_commands("Run the tests again, send it. ") == ("Run the tests again.", True)
    assert voice_commands("Check the logs. Press enter.") == ("Check the logs.", True)
    assert voice_commands("Vale, envíalo. ") == ("Vale.", True)
    assert voice_commands("Send it. ") == ("", True)  # only the command: just press Enter


def test_words_inside_a_sentence_are_left_alone():
    assert voice_commands("Did you send it to her yesterday? ") == ("Did you send it to her yesterday? ", False)
    assert voice_commands("We need a new line of products. ") == ("We need a new line of products. ", False)


def _app(tmp_path, said, on, phrases=None):
    from ecoscribe.app import App
    from ecoscribe.config import Config
    from ecoscribe.deliver import DeliveryResult
    from ecoscribe.engine import Result
    from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait
    cfg = Config()
    cfg.text.voice_commands = on
    cfg.text.voice_phrases = phrases or {}
    delivered, enters = [], []

    class Eng:
        def transcribe(self, audio):
            return Result(text=said, lang="en", speech_s=1.0, ms=5)
    app = App(cfg, FakeRecorder(), Eng(), lambda t: delivered.append(t) or DeliveryResult(True, "x.exe", "ok"),
              FakeUi(), gate=FakeGate(), history_path=tmp_path / "h.jsonl", press_enter=lambda: enters.append(1))
    app.start()
    app.on_action("toggle"); app.on_action("toggle")
    wait(lambda: delivered or enters)
    import time
    time.sleep(0.3)
    return delivered, enters


def test_app_pastes_then_presses_enter_when_on(tmp_path):
    assert _app(tmp_path, "Run the tests again, send it. ", True) == (["Run the tests again."], [1])


def test_off_by_default_pastes_exactly_what_was_said(tmp_path):
    assert _app(tmp_path, "Run the tests again, send it. ", False) == (["Run the tests again, send it. "], [])


def test_settings_list_comes_from_the_matcher_table(tmp_path):
    """t0u.38: every phrase in the Settings list is one the matcher really understands."""
    from ecoscribe.text import VOICE_COMMANDS, voice_commands
    from ecoscribe.window import Api
    rows = Api(data_dir=tmp_path, config_path=tmp_path / "c.toml", signal_reload=lambda: True).get_settings()["voice_command_list"]
    assert [r["what"] for r in rows] == [w for _, w, _ in VOICE_COMMANDS]
    assert rows[0]["es"] == '"nuevo párrafo", "punto y aparte"'
    for key, _, langs in VOICE_COMMANDS:
        for phrases in langs.values():
            for p in phrases:
                out, enter = voice_commands(f"Hola. {p}.")
                assert (enter if key == "enter" else "\n" in out), p


# -- the user's own phrases (dictado-67v) ------------------------------------------------------------
def test_own_phrases_replace_that_languages_built_in_ones():
    mine = {"line": {"en": ["next line"]}, "enter": {"en": ["ship it"]}}
    assert voice_commands("Hello. Next line. Bye. ", mine) == ("Hello.\nBye. ", False)
    assert voice_commands("Hello. New line. Bye. ", mine) == ("Hello. New line. Bye. ", False)  # replaced, not added
    assert voice_commands("Hej. Ny rad. Vi ses. ", mine) == ("Hej.\nVi ses. ", False)  # Swedish keeps its own
    assert voice_commands("Run the tests, ship it. ", mine) == ("Run the tests.", True)
    assert voice_commands("Hello. New line. Bye. ", {"line": {"en": [], "es": [], "sv": []}}) == ("Hello. New line. Bye. ", False)
    assert voice_commands("Hello. New line. Bye. ") == ("Hello.\nBye. ", False)  # the built-in table is untouched


def test_saved_phrases_are_cleaned_and_only_what_differs_is_kept():
    from ecoscribe.text import clean_custom, phrase_table
    got = clean_custom({"line": {"en": ["New line", "  Next   Line! ", "next line"], "sv": ["ny rad"]}, "enter": {"de": ["schick es"]}})
    assert got == {"line": {"en": ["new line", "next line"]}, "enter": {"de": ["schick es"]}}  # Swedish = built in: dropped
    assert phrase_table(got)["enter"]["de"] == ["schick es"] and phrase_table(got)["enter"]["en"] == ["send it", "press enter"]
    for bad in ({"line": {"en": ["send it"]}}, {"nope": {"en": ["x"]}}, {"line": {"xx": ["x"]}}):
        with pytest.raises(ValueError):
            clean_custom(bad)


def test_app_uses_the_users_phrases(tmp_path):
    assert _app(tmp_path, "Run the tests again, ship it. ", True, {"enter": {"en": ["ship it"]}}) == (["Run the tests again."], [1])


def test_settings_edit_the_phrases_and_reset_them(tmp_path):
    from ecoscribe import config
    from ecoscribe.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "c.toml", signal_reload=lambda: True)
    assert api.save_settings({"voice_phrases": {"line": {"en": ["new line", "next line"]}}})["ok"]
    assert config.load(tmp_path / "c.toml").text.voice_phrases == {"line": {"en": ["new line", "next line"]}}
    row = api.get_settings()["voice_command_list"][1]
    assert row["key"] == "line" and row["phrases"]["en"] == ["new line", "next line"] and row["builtin"]["en"] == ["new line"]
    assert row["en"] == '"new line", "next line"'
    bad = api.save_settings({"voice_phrases": {"line": {"en": ["send it"]}}})
    assert not bad["ok"] and "Line break" in bad["error"] and "Press Enter" in bad["error"]
    assert api.save_settings({"voice_phrases": {}})["ok"]  # Back to the built-in phrases
    assert config.load(tmp_path / "c.toml").text.voice_phrases == {}


# -- spoken quotes (dictado-y52): always on, needs the opening and the closing words -------------
from ecoscribe.text import spoken_quotes  # noqa: E402


def test_quote_end_quote_writes_quotation_marks():
    assert spoken_quotes("We could call it, quote, the weekly review, end quote. Or not.") == \
        'We could call it "the weekly review". Or not.'
    assert spoken_quotes("Name it quote north star unquote and move on.") == 'Name it "north star" and move on.'
    assert spoken_quotes("She said quote no end quote and quote yes close quote.") == 'She said "no" and "yes".'


def test_a_lone_quote_stays_text():
    assert spoken_quotes("Can you get a quote from them?") == "Can you get a quote from them?"
    assert spoken_quotes("") == ""


def test_spanish_and_swedish_quotes():
    assert spoken_quotes("Lo llamamos abre comillas el plan cierra comillas.") == 'Lo llamamos "el plan".'
    assert spoken_quotes("Vi kallar det citat planen slut citat.") == 'Vi kallar det "planen".'
