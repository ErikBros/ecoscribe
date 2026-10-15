from ecoscribe.choose import pick_device, pick_language
from ecoscribe.text import clean, is_hallucination, strip_credits


def test_fillers():
    assert clean("um so, uh, I think we ship it.") == "So, I think we ship it. "


def test_keeps_words_containing_fillers():
    assert clean("the umbrella hummed") == "The umbrella hummed "


def test_space_before_punct():
    assert clean("hello , world .") == "Hello, world. "


def test_empty():
    assert clean("   ") == ""


def test_only_fillers_is_empty():
    assert clean("Um, uh.") == ""


def test_no_append():
    assert clean("hi.", append_space=False) == "Hi."


def test_no_strip():
    assert clean("um hi", strip_fillers=False) == "Um hi "


def test_spanish_kept():
    assert clean("eh, mañana voy.") == "Mañana voy. "


def test_first_letter_accented():
    assert clean("él viene") == "Él viene "


def test_halluc():
    assert is_hallucination("Thank you.", 0.1)
    assert not is_hallucination("Thank you.", 2.0)
    assert is_hallucination("", 5)
    assert is_hallucination("Gracias por ver el video.", 0.2)
    assert not is_hallucination("Send the report.", 0.2)


def test_short_real_thanks_kept():
    # spoken "Thank you." / "Gracias." is ~0.5-0.9 s of speech: a real dictation
    assert not is_hallucination("Thank you.", 0.6, no_speech_prob=0.05)
    assert not is_hallucination("Gracias.", 0.5, no_speech_prob=0.1)


def test_halluc_when_whisper_says_no_speech():
    assert is_hallucination("Thank you.", 0.8, no_speech_prob=0.8)
    assert not is_hallucination("Send the report.", 0.8, no_speech_prob=0.8)


def test_subtitle_credits_stripped_anywhere():
    # credits nobody dictates: dropped even after real speech, with no speech gate
    assert strip_credits("Υπότιτλοι AUTHORWAVE") == ""
    assert strip_credits("Θα πάω στο σπίτι. Υπότιτλοι AUTHORWAVE") == "Θα πάω στο σπίτι."
    assert strip_credits("Send the report. Subtitles by the Amara.org community") == "Send the report."
    assert strip_credits("Υπότιτλοι από την κοινότητα Amara.org") == ""
    assert strip_credits("Οι υπότιτλοι είναι καλοί.") == "Οι υπότιτλοι είναι καλοί."
    assert strip_credits("Send the report.") == "Send the report."


def test_lang_allow():
    assert pick_language([("cy", .5), ("en", .3), ("es", .2)], ["en", "es"]) == "en"


def test_lang_spanish_wins():
    assert pick_language([("pt", .5), ("es", .4), ("en", .1)], ["en", "es"]) == "es"


def test_lang_none():
    assert pick_language([("cy", 1.0)], ["en", "es"]) == "en"


DEV = [{"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2},
       {"name": "Headset (Zone Vibe 100)", "hostapi": 0, "max_input_channels": 1},
       {"name": "Microphone (Anker PowerConf C20", "hostapi": 0, "max_input_channels": 2},
       {"name": "Speakers", "hostapi": 0, "max_input_channels": 0},
       {"name": "Microphone (Anker PowerConf C200)", "hostapi": 2, "max_input_channels": 2}]
HOST = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]


def test_dev_by_name():
    assert pick_device(DEV, HOST, "Anker PowerConf", "MME") == 2


def test_dev_case_insensitive():
    assert pick_device(DEV, HOST, "anker powerconf", "mme") == 2


def test_dev_other_host():
    assert pick_device(DEV, HOST, "Anker PowerConf", "Windows WASAPI") == 4


def test_dev_missing():
    assert pick_device(DEV, HOST, "Blue Yeti", "MME") is None


def test_dev_skips_outputs():
    assert pick_device(DEV, HOST, "Speakers", "MME") is None


def test_more_known_inventions_on_silence():
    for s in ("Tack för att ni tittade!", "Untertitel der Amara.org-Community", "[Música]",
              "Ευχαριστώ πολύ.", "Merci d'avoir regardé !", "Don't forget to like and subscribe!"):
        assert is_hallucination(s, 0.1), s
        assert not is_hallucination(s, 1.5), s  # really said: kept


def test_a_real_sentence_with_the_same_words_is_kept():
    assert not is_hallucination("Tack för att ni tittade på förslaget igår.", 0.1)
    assert not is_hallucination("Thanks for watching the kids yesterday.", 0.2)


def test_replacements_anywhere_whole_words_any_case():
    """The Replace list (dictado-b7u): heard -> written, anywhere in the text."""
    from ecoscribe.text import replacements
    t = {"poll request": "pull request", "eco scribe": "Ecoscribe", "pr": "PR"}
    assert replacements("Open a Poll  request for it.", t) == "Open a pull request for it."
    assert replacements("eco scribe is open, eco scribe again", t) == "Ecoscribe is open, Ecoscribe again"
    assert replacements("a pr, not a prize or april", t) == "a PR, not a prize or april"  # whole words only
    assert replacements("nothing here", t) == "nothing here" and replacements("x", {}) == "x" and replacements("", t) == ""
    assert replacements("poll requests", {"poll request": "pull request", "poll requests": "pull requests"}) == "pull requests"
