"""Rule-based transcript cleanup. No LLM: speed is the product."""
from __future__ import annotations

import re

_FILLERS = r"(?:um+|uh+|erm|er|hmm+|mm+|eh|em|ehm)"
_FILLER_RE = re.compile(rf"(?<![\w'])({_FILLERS})(?![\w'])[,.]?", re.IGNORECASE)
_SPACE_PUNCT = re.compile(r"\s+([,.!?;:])")
_DOUBLE_COMMA = re.compile(r",\s*([,.!?])")

# Whisper invents these on silence. Only dropped with barely any speech or a high no-speech prob.
# Whisper's stock inventions on silence or noise (subtitle credits, video sign-offs), in the
# languages people dictate in. Only ever dropped with almost no speech (is_hallucination's gate),
# so a real spoken "Thank you." stays. Written as said; matched after _norm.
_HALLUCINATION_PHRASES = (
    # English
    "Thank you.", "Thank you very much.", "Thank you so much.", "Thanks.", "Thanks for watching!",
    "Thank you for watching!", "Thank you so much for watching!", "Thanks for watching, see you next time.",
    "Please subscribe.", "Like and subscribe.", "Don't forget to like and subscribe!",
    "See you in the next video.", "See you next time.", "Bye.", "Bye-bye.", "You", "The end.",
    "Subtitles by the Amara.org community", "[Music]", "[Applause]", "[Laughter]", "[Silence]",
    # Swedish
    "Tack.", "Tack så mycket.", "Tack för att du tittade!", "Tack för att ni tittade!",
    "Tack för att ni har tittat.", "Undertexter från Amara.org-gemenskapen", "Svensktextning", "Textning",
    "[Musik]",
    # Spanish
    "Gracias.", "Muchas gracias.", "Gracias por ver.", "Gracias por ver el video.", "Gracias por ver el vídeo.",
    "¡Suscríbete!", "Suscríbete al canal.", "Hasta la próxima.", "Nos vemos en el próximo video.",
    "Subtítulos realizados por la comunidad de Amara.org", "Subtítulos por la comunidad de Amara.org", "[Música]",
    # Greek
    "Ευχαριστώ.", "Ευχαριστώ πολύ.", "Ευχαριστούμε για την παρακολούθηση.", "Ευχαριστώ που παρακολουθήσατε.",
    # German
    "Vielen Dank.", "Danke.", "Danke fürs Zuschauen!", "Bis zum nächsten Mal.",
    "Untertitel der Amara.org-Community", "Untertitel im Auftrag des ZDF für funk, 2017",
    # French
    "Merci.", "Merci d'avoir regardé !", "Sous-titres réalisés par la communauté d'Amara.org",
    # Finnish
    "Kiitos.", "Kiitos katsomisesta!",
)


def clean(s: str, strip_fillers: bool = True, append_space: bool = True) -> str:
    s = s.strip()
    if strip_fillers:
        s = _FILLER_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _SPACE_PUNCT.sub(r"\1", s)
    s = _DOUBLE_COMMA.sub(r"\1", s)
    s = s.lstrip(",.;: ").strip()
    if not re.search(r"\w", s):
        return ""
    s = s[0].upper() + s[1:]
    return s + " " if append_space else s


VOCAB_MAX_CHARS = 400  # Whisper's prompt is at most half its 448-token window: keep it short


def vocab_prompt(words) -> str | None:
    """The user's word list as a Whisper prompt ("Ecoscribe, pyannote, Göteborg."), or None when empty.
    A prompt steers spelling without forcing words in (faster-whisper's `hotwords` broke large-v3)."""
    seen, out = set(), []
    for w in words or []:
        w = " ".join(str(w).split())
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    while out and len(", ".join(out)) + 1 > VOCAB_MAX_CHARS:
        out.pop()
    return ", ".join(out) + "." if out else None


# Spoken commands ([text] voice_commands, off by default). A command only counts as its own
# clause: after the start or a punctuation mark, and before one or the end. "We need a new line
# of products" and "did you send it to her" stay text.
# One table for the matcher AND the list in Settings (t0u.38), so the two can't drift apart.
VOICE_COMMANDS = [
    ("paragraph", "Paragraph break", {"en": ["new paragraph"], "es": ["nuevo párrafo", "punto y aparte"],
                                      "sv": ["nytt stycke"]}),
    ("line", "Line break", {"en": ["new line"], "es": ["nueva línea"], "sv": ["ny rad"]}),
    ("enter", "Press Enter after the text (at the very end only)",
     {"en": ["send it", "press enter"], "es": ["envíalo", "enviar"], "sv": ["skicka"]}),
]
_ACCENTS = {"á": "[aá]", "é": "[eé]", "í": "[ií]", "ó": "[oó]", "ú": "[uú]"}


def _phrases(key: str) -> str:
    """Alternation for one command, accent-tolerant ("envialo" = "envíalo")."""
    words = [p for k, _, langs in VOICE_COMMANDS if k == key for ps in langs.values() for p in ps]
    rx = lambda p: r"\s+".join("".join(_ACCENTS.get(c, re.escape(c)) for c in w) for w in p.split())  # noqa: E731
    return "|".join(rx(p) for p in sorted(words, key=len, reverse=True))


_B = r"(^|[.,;:!?])\s*"
_E = r"\s*([.,;:!?]|$)\s*"
_PARAGRAPH = re.compile(_B + f"(?:{_phrases('paragraph')})" + _E, re.IGNORECASE)
_LINE = re.compile(_B + f"(?:{_phrases('line')})" + _E, re.IGNORECASE)
_ENTER = re.compile(_B + f"(?:{_phrases('enter')})" + r"\s*[.!]?\s*$", re.IGNORECASE)


# Spoken quotes (dictado-y52): "called, quote, weekly review, end quote." -> called "weekly review".
# Always on in dictation: it needs both the opening and the closing words, so a lone "quote"
# ("get a quote") stays text.
QUOTES = {"en": (["open quote", "quote"], ["end quote", "close quote", "end of quote", "unquote"]),
          "es": (["abre comillas", "comillas"], ["cierra comillas", "fin de comillas"]),
          "sv": (["citat"], ["slut citat", "citat slut"])}


def _alt(ps) -> str:
    return "|".join(r"\s+".join(map(re.escape, p.split())) for p in sorted(ps, key=len, reverse=True))


_QUOTE = re.compile(
    r"[,:]?\s*(?<!\w)(?:" + _alt([p for o, _ in QUOTES.values() for p in o]) + r")(?!\w)[,:.]?\s*"
    r"(\S.*?)[,.;:]?\s*(?<!\w)(?:" + _alt([p for _, c in QUOTES.values() for p in c]) + r")(?!\w)",
    re.IGNORECASE | re.DOTALL)


def spoken_quotes(s: str) -> str:
    """Words said between "quote" and "end quote" (or "unquote") come out in quotation marks."""
    if not s:
        return s
    out = _QUOTE.sub(lambda m: ' "' + m.group(1).strip() + '"', s)
    return out.lstrip() if out != s else s


def _end(punct: str) -> str:
    return punct if punct in ".!?" else ("." if punct else "")


def voice_commands(s: str) -> tuple[str, bool]:
    """"new line" -> line break, "new paragraph" -> blank line, a closing "send it" -> (text, press Enter)."""
    enter = False
    m = _ENTER.search(s)
    if m:
        s, enter = s[:m.start()] + _end(m.group(1)), True
    for rx, brk in ((_PARAGRAPH, "\n\n"), (_LINE, "\n")):
        s = rx.sub(lambda m: _end(m.group(1)) + brk, s)
    s = re.sub(r"\n([a-zà-ÿ])", lambda m: "\n" + m.group(1).upper(), s)
    s = s.lstrip("\n")
    return (s.rstrip() if enter else s), enter


def replacements(s: str, table) -> str:
    """The Replace list (dictado-b7u): each heard phrase, anywhere, as whole words and in any case,
    becomes what the user wrote; the longest phrase wins where two overlap."""
    if not table or not s:
        return s
    rep = {" ".join(k.lower().split()): v for k, v in table.items() if k and k.strip() and v is not None}
    if not rep:
        return s
    alts = "|".join(r"\s+".join(map(re.escape, k.split())) for k in sorted(rep, key=len, reverse=True))
    rx = re.compile(rf"(?<!\w)({alts})(?!\w)", re.IGNORECASE)
    return rx.sub(lambda m: rep[" ".join(m.group(1).lower().split())], s)


def snippets(s: str, table) -> str:
    """Snippets (t0u.29): a clause that is exactly a trigger ("my email") becomes its saved text.
    Same clause rule as voice commands; case is ignored; the longest trigger wins. The
    punctuation Whisper put after the trigger is dropped: the snippet brings its own."""
    if not table or not s:
        return s
    trig = {" ".join(k.lower().split()): v for k, v in table.items() if k and k.strip()}
    if not trig:
        return s
    alts = "|".join(r"\s+".join(map(re.escape, k.split())) for k in sorted(trig, key=len, reverse=True))
    rx = re.compile(rf"(?:^|(?<=[.,;:!?]))(\s*)({alts})(?:\s*[.,;:!?]|\s*$)", re.IGNORECASE)
    return rx.sub(lambda m: m.group(1) + trig[" ".join(m.group(2).lower().split())], s)


def _norm(s: str) -> str:
    return re.sub(r"[^\w ]", "", s.lower()).strip()


_HALLUCINATIONS = {_norm(x) for x in _HALLUCINATION_PHRASES}


# Subtitle credits Whisper learned from video captions. Nobody dictates them, so they go wherever
# they appear, even tacked onto real speech, with no speech gate.
_CREDITS_RE = re.compile(
    r"\s*(?:Υπότιτλοι\s+AUTHORWAVE|[^.!?]*\bAmara\.org\b[^.!?]*)[.!?]?", re.IGNORECASE)


def strip_credits(s: str) -> str:
    return _CREDITS_RE.sub("", s).strip()


def only_credits(s: str) -> bool:
    """True when Whisper's text is nothing but a subtitle credit. With the word list as a prompt it can
    turn a whole stretch of real speech into one ("Υπότιτλοι AUTHORWAVE" for 12 s of Greek); the
    stretch is then done again without the prompt (dictado-u34)."""
    from .segclean import is_credit, strip_tags
    s = strip_tags(s or "")
    return bool(s) and (not re.search(r"\w", strip_credits(s)) or is_credit(s))


def is_hallucination(s: str, speech_s: float, no_speech_prob: float = 0.0) -> bool:
    """True for Whisper's classic silence inventions ("Thank you.", "Gracias.").

    A real spoken "Thank you." has ~0.5-1 s of speech, so length alone can't
    decide: drop a listed phrase only with almost no speech, or when Whisper
    itself says the segment is probably not speech.
    """
    n = _norm(s)
    if not n:
        return True
    return n in _HALLUCINATIONS and (speech_s < 0.3 or no_speech_prob > 0.6)
