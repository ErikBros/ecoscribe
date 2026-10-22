"""dictado-u34: with the word list as a prompt, Whisper once turned 12 s of real Greek into a single
subtitle credit; credits are stripped, so the speech was lost. Such a stretch is done again without it."""
from types import SimpleNamespace

import numpy as np

from ecoscribe import transcribe as T
from ecoscribe.config import TextCfg, TranscribeCfg, WhisperCfg
from ecoscribe.engine import SR, Engine
from ecoscribe.text import only_credits

CREDIT = " Υπότιτλοι AUTHORWAVE"


class PromptSpooked:
    """Answers a credit whenever a prompt is given, the real words without one."""
    def __init__(self, *a, **k):
        self.prompts = []

    def transcribe(self, audio, language=None, initial_prompt=None, **kw):
        self.prompts.append(initial_prompt)
        n = len(audio) / SR
        text = CREDIT if initial_prompt else f" Real words in {language}."
        return iter([SimpleNamespace(start=0.0, end=n, text=text, no_speech_prob=0.01)]), \
            SimpleNamespace(duration=n, duration_after_vad=n, language=language)

    def detect_language(self, audio, **kw):
        return "el", 0.99, [("el", 0.99), ("es", 0.01)]


def test_only_credits():
    assert only_credits(CREDIT) and only_credits("Subtítulos por la comunidad de Amara.org")
    assert not only_credits("Γεια σας και καλώς ήρθατε.") and not only_credits("")
    assert not only_credits("Real words. Subtitles by the Amara.org community")


def test_a_mixed_piece_that_is_only_a_credit_is_done_again_without_the_prompt():
    m = PromptSpooked()
    audio = np.zeros(SR * 6, np.float32)
    segs = list(T.mixed_segments(m, audio, ["el", "es"], TranscribeCfg(), "Ecoscribe, Göteborg.",
                                 speech=lambda a: [(0.0, 5.0)]))
    assert [s.text for s in segs] == [" Real words in el."] and m.prompts == ["Ecoscribe, Göteborg.", None]


def test_a_one_language_credit_segment_is_done_again_and_real_text_is_kept():
    m = PromptSpooked()
    audio = np.zeros(SR * 10, np.float32)
    gen = [SimpleNamespace(start=0.0, end=4.0, text=" Hola a todos."),
           SimpleNamespace(start=4.0, end=8.0, text=CREDIT),
           SimpleNamespace(start=8.0, end=8.5, text=CREDIT)]  # too short to be speech lost: left to the cleaner
    out = list(T.credit_retry(m, audio, gen, "es", TranscribeCfg(), "Ecoscribe."))
    assert [(s.start, s.text) for s in out] == [(0.0, " Hola a todos."), (4.0, " Real words in es."), (8.0, CREDIT)]
    assert m.prompts == [None]


def test_without_a_word_list_nothing_is_redone():
    m = PromptSpooked()
    gen = [SimpleNamespace(start=0.0, end=4.0, text=CREDIT)]
    assert [s.text for s in T.credit_retry(m, np.zeros(SR * 5, np.float32), gen, "el", TranscribeCfg(), None)] == [CREDIT]
    assert m.prompts == []


def test_dictation_that_is_only_a_credit_is_done_again_without_the_word_list():
    e = Engine(WhisperCfg(device="cuda", languages=["el"]), TextCfg(vocabulary=["Ecoscribe"]),
               model_factory=PromptSpooked, resolve=lambda n: n)
    e.model = PromptSpooked()
    r = e.transcribe(np.full(SR * 4, 0.1, np.float32))
    assert "Real words in el" in r.text and e.model.prompts[0] and e.model.prompts[-1] is None
