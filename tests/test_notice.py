"""Pill A notices: a flash message -> icon, words, detail (dictado-v5g)."""
from ecoscribe.notice import Notice, notice


def test_unheard_shows_a_struck_mic_and_the_mic_name():
    assert notice("Didn't hear you (Desk Mic 100)") == Notice("Didn't hear anything", "nomic", detail="Desk Mic 100")
    assert notice("Didn't hear you") == Notice("Didn't hear anything", "nomic")


def test_language_switch_shows_the_code_as_a_badge():
    assert notice("Next dictation: English") == Notice("Next dictation in English", "lang", "EN")
    assert notice("This dictation: Swedish") == Notice("This dictation in Swedish", "lang", "SV")
    assert notice("Next dictation: auto") == Notice("Next dictation: any language", "lang", "AUTO")


def test_heard_language_and_a_note():
    assert notice("✓ EN") == Notice("English", "lang", "EN")
    assert notice("✓ EL+ES") == Notice("Greek + Spanish", "lang", "EL+ES")
    assert notice("✓ EN · 3 fillers") == Notice("3 fillers", "lang", "EN")


def test_errors_get_a_warning_and_the_rest_stays_plain():
    assert notice("Error, see the log").icon == "warn"
    assert notice("No GPU: slow mode").icon == "warn"
    assert notice("Cancelled") == Notice("Cancelled")
    assert notice("") == Notice("")
