"""Languages as add-ons (dictado-ehs)."""
import pytest

from ecoscribe import languages as L
from ecoscribe.config import WhisperCfg
from ecoscribe.engine import dictation_model


def test_same_languages_as_whisper():
    tok = pytest.importorskip("faster_whisper.tokenizer")
    assert set(L.ALL) == set(tok._LANGUAGE_CODES)


def test_built_in_two_plus_added():
    assert L.available([]) == ["en", "sv"]
    assert L.available(["es", "el", "es", "xx", "en"]) == ["en", "sv", "es", "el"]
    assert L.valid_extra(["ES", "el", "sv", "el"]) == ["es", "el"]  # built-ins and repeats dropped
    with pytest.raises(ValueError):
        L.valid_extra(["klingon"])


def test_names_and_meeting_options():
    assert L.name("en,sv") == "English + Swedish" and L.name("auto") == "Detect" and L.name("yue") == "Cantonese"
    assert L.meeting_options(["en", "sv"]) == [("en", "English"), ("sv", "Swedish"), ("en,sv", "English + Swedish"),
                                               ("auto", "Detect")]
    assert L.valid_meeting_lang("el,es") and L.valid_meeting_lang("de") and not L.valid_meeting_lang("xx,en")


def test_model_follows_the_languages():
    assert dictation_model(WhisperCfg(languages=["en"]))[0] == "large-v3-turbo"
    assert dictation_model(WhisperCfg(languages=["en", "es", "fr"]))[0] == "large-v3-turbo"
    for langs in (["sv"], ["en", "sv"], ["el"], ["is"], ["en", "fi"]):
        assert "turbo" not in dictation_model(WhisperCfg(languages=langs))[0], langs


def test_user_langs_are_only_the_users_own():
    """dictado-607: ticked, added and the meeting language; a built-in nobody picked stays out."""
    assert L.user_langs(["en"], []) == ["en"]
    assert L.user_langs(["en"], [], "sv") == ["en", "sv"]
    assert L.user_langs(["sv", "en"], ["es"], "auto") == ["en", "sv", "es"]
    assert L.user_langs(["en"], [], "el,en") == ["en", "el"]  # a saved mix outside the list still shows
    assert L.user_langs([], []) == ["en"]
