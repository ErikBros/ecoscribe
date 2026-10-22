"""Which sessions count as personal (dictado-qlj): automatic steps over meetings only touch these."""
from ecoscribe import personal
from ecoscribe.config import Config


def _cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c.personal, k, v)
    return c


def test_work_calls_are_not_personal():
    for app in ("chrome", "msteams", "slack", "zoom", None):
        assert not personal.is_personal({"title": "Weekly sync", "app": app, "lang": "en"}, _cfg())


def test_messenger_calls_are_personal_also_with_a_suffix():
    for app in ("signal", "whatsapp", "whatsappdesktop", "telegram", "discord", "Signal"):
        assert personal.is_personal({"title": "Call", "app": app}, _cfg())


def test_title_prefix_marks_a_call_personal():
    assert personal.why({"title": "p-dentist follow-up", "app": "chrome"}, _cfg()) == "title starts with 'p-'"
    assert personal.is_personal({"title": "P-Call", "app": "msteams"}, _cfg())
    assert not personal.is_personal({"title": "pipeline review", "app": "chrome"}, _cfg())
    assert not personal.is_personal({"title": "p-thing", "app": "chrome"}, _cfg(title_prefix=""))


def test_a_listed_language_marks_a_call_personal_also_in_a_mix():
    cfg = _cfg(languages=["el"])
    assert personal.why({"title": "Lesson", "lang": "el,es", "lang_used": "el,es"}, cfg) == "language el"
    assert personal.is_personal({"title": "x", "lang": "auto", "detected_lang": "el"}, cfg)
    assert not personal.is_personal({"title": "x", "lang": "es"}, cfg)
    assert not personal.is_personal({"title": "Lesson", "lang": "el"}, _cfg())  # no languages listed by default


def test_the_session_flag_wins_both_ways():
    assert not personal.is_personal({"title": "p-x", "app": "signal", "personal": False}, _cfg())
    assert personal.why({"title": "Sync", "app": "msteams", "personal": True}, _cfg()) == "marked personal"
