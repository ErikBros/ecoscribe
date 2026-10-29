"""Rule-based transcript cleanup. No LLM: speed is the product."""
from __future__ import annotations

import functools
import json
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


# dictado-0qr5: a name Whisper hears as a common word even when the name is in Your words (the prompt alone
# doesn't win). Fixed only for a name in Your words, and only where the word reads as the name: never after an
# article or a word that makes it the common thing ("the cloud", "Google Cloud"), never before a word that does
# ("cloud storage"), never the plural. {name: (heard as, keep after, keep before)}
SOUND_ALIKES = {
    "Claude": ("cloud",
               {"the", "a", "an", "this", "that", "our", "your", "my", "his", "her", "their", "its", "any", "some",
                "no", "each", "every", "one", "own", "public", "private", "hybrid", "dark", "rain", "storm", "white",
                "big", "google", "oracle", "ibm", "microsoft", "aws", "azure", "alibaba", "salesforce", "tencent",
                "el", "la", "un", "una", "del", "al", "en", "ett", "word", "point", "tag", "mushroom"},
               {"storage", "computing", "service", "services", "provider", "providers", "platform", "platforms",
                "server", "servers", "infrastructure", "native", "based", "backup", "backups", "cost", "costs",
                "account", "accounts", "drive", "hosting", "console", "migration", "security", "environment",
                "environments", "resources", "instance", "instances", "function", "functions", "run", "cover",
                "burst", "formation", "formations", "nine", "bill", "billing", "data", "sync", "app", "apps",
                "solution", "solutions", "version", "first", "engineer", "engineers", "architecture", "cluster"}),
}
_WORD_RE = re.compile(r"[\w'’-]+")


def sound_alikes(s: str, vocabulary, lang: str = "") -> str:
    """'I asked cloud to fix it' -> 'I asked Claude to fix it' when Claude is in Your words; 'the data is
    in the cloud' stays. Spanish "a" is "to", not an article ("le pregunté a cloud")."""
    if not s:
        return s
    have = {" ".join(str(v).split()).lower() for v in vocabulary or []}
    for name, (heard, keep_after, keep_before) in SOUND_ALIKES.items():
        if name.lower() not in have or heard not in s.lower():
            continue
        after = keep_after - {"a"} if "es" in lang.split("+") else keep_after
        words = list(_WORD_RE.finditer(s))
        out, last = [], 0
        for i, m in enumerate(words):
            w = m.group(0)
            base, tail = (w[:-2], w[-2:]) if w.lower()[-2:] in ("'s", "’s") else (w, "")
            if base.lower() != heard:
                continue
            prev = words[i - 1].group(0).lower() if i else ""
            nxt = words[i + 1].group(0).lower() if i + 1 < len(words) else ""
            joined = i + 1 < len(words) and s[m.end():words[i + 1].start()] in ("", "-")
            if prev in after or (nxt in keep_before and not tail) or joined:
                continue
            end = m.end()
            if nxt == "code" and not tail:  # "cloud code": Claude Code, the product
                tail, end = s[m.end():words[i + 1].start()] + "Code", words[i + 1].end()
            out.append(s[last:m.start()] + name + tail)
            last = end
        s = "".join(out) + s[last:]
    return s


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
PHRASE_MAX, PHRASES_MAX = 40, 8  # dictado-67v: per phrase (characters), per command and language


def clean_phrase(p) -> str:
    """'  Next Line! ' -> 'next line': lower case, single spaces, no punctuation at the ends."""
    return " ".join(str(p or "").lower().split()).strip(" .,;:!?\"'\u201c\u201d")[:PHRASE_MAX].strip()


def phrase_table(custom=None) -> dict[str, dict[str, list[str]]]:
    """{command: {lang: [phrases]}}: the built-in phrases with the user's own lists over them (dictado-67v).
    A list the user saved replaces that language's built-in one; an empty list switches it off."""
    out = {k: {lang: list(ps) for lang, ps in langs.items()} for k, _, langs in VOICE_COMMANDS}
    for k, langs in (custom or {}).items():
        if k in out and isinstance(langs, dict):
            for lang, ps in langs.items():
                out[k][str(lang)] = list(dict.fromkeys(p for p in map(clean_phrase, ps if isinstance(ps, list) else []) if p))[:PHRASES_MAX]
    return out


def clean_custom(value) -> dict[str, dict[str, list[str]]]:
    """What Settings saves (dictado-67v): only the lists that differ from the built-in ones. Raises ValueError
    (in words for the user) for a phrase two commands share."""
    from .languages import ALL
    builtin = phrase_table()
    out: dict[str, dict[str, list[str]]] = {}
    for k, langs in (value or {}).items():
        if k not in builtin or not isinstance(langs, dict):
            raise ValueError(f"unknown voice command: {k}")
        for lang, ps in langs.items():
            if lang not in ALL:
                raise ValueError(f"unknown language: {lang}")
            got = phrase_table({k: {lang: ps if isinstance(ps, list) else []}})[k][lang]
            if got != builtin[k].get(lang, []):
                out.setdefault(k, {})[lang] = got
    seen: dict[str, str] = {}
    names = {k: what.split(" (")[0] for k, what, _ in VOICE_COMMANDS}
    for k, langs in phrase_table(out).items():
        for p in {p for ps in langs.values() for p in ps}:
            if p in seen and seen[p] != k:
                raise ValueError(f"\u201c{p}\u201d can't be both {names[seen[p]]} and {names[k]}: keep it in one")
            seen[p] = k
    return out


def _alternation(words) -> str:
    """One regex alternation, accent-tolerant ("envialo" = "envíalo"), longest first."""
    rx = lambda p: r"\s+".join("".join(_ACCENTS.get(c, re.escape(c)) for c in w) for w in p.split())  # noqa: E731
    return "|".join(rx(p) for p in sorted(set(words), key=len, reverse=True))


def _phrases(key: str, table=None) -> str:
    """Alternation for one command, over every language's phrases."""
    return _alternation([p for ps in (table or phrase_table())[key].values() for p in ps])


_B = r"(^|[.,;:!?])\s*"
_E = r"\s*([.,;:!?]|$)\s*"


@functools.lru_cache(maxsize=8)
def _matchers(custom_json: str = "{}"):
    """(paragraph, line, enter) regexes for a phrase table; None for a command with no phrase left."""
    table = phrase_table(json.loads(custom_json))
    def rx(key, tail):
        alt = _phrases(key, table)
        return re.compile(_B + f"(?:{alt})" + tail, re.IGNORECASE) if alt else None
    return rx("paragraph", _E), rx("line", _E), rx("enter", r"\s*[.!]?\s*$")


_PARAGRAPH, _LINE, _ENTER = _matchers()


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


def voice_commands(s: str, custom=None) -> tuple[str, bool]:
    """"new line" -> line break, "new paragraph" -> blank line, a closing "send it" -> (text, press Enter).
    custom: the user's own phrases ([text] voice_phrases, dictado-67v) over the built-in ones."""
    enter = False
    para, line, enter_rx = _matchers(json.dumps(custom or {}, sort_keys=True, ensure_ascii=False))
    m = enter_rx.search(s) if enter_rx else None
    if m:
        s, enter = s[:m.start()] + _end(m.group(1)), True
    for rx, brk in ((para, "\n\n"), (line, "\n")):
        if rx is not None:
            s = rx.sub(lambda m: _end(m.group(1)) + brk, s)
    s = re.sub(r"\n([a-zà-ÿ])", lambda m: "\n" + m.group(1).upper(), s)
    s = s.lstrip("\n")
    return (s.rstrip() if enter else s), enter


def _replace_rx(table):
    """{heard: write} folded to lower case and single spaces, and one regex for all of them (longest first)."""
    rep = {" ".join(k.lower().split()): v for k, v in (table or {}).items() if k and k.strip() and v is not None}
    if not rep:
        return rep, None
    alts = "|".join(r"\s+".join(map(re.escape, k.split())) for k in sorted(rep, key=len, reverse=True))
    return rep, re.compile(rf"(?<!\w)({alts})(?!\w)", re.IGNORECASE)


def replacements(s: str, table) -> str:
    """The Replace list (dictado-b7u): each heard phrase, anywhere, as whole words and in any case,
    becomes what the user wrote; the longest phrase wins where two overlap."""
    if not table or not s:
        return s
    rep, rx = _replace_rx(table)
    if rx is None:
        return s
    return rx.sub(lambda m: rep[" ".join(m.group(1).lower().split())], s)


def replace_counted(texts, table) -> tuple[list[str], dict[str, int]]:
    """The Replace list over many texts (a saved transcript, dictado-9lo): the new texts and how many
    places each heard phrase changed. A match already written that way ("Ecoscribe" for
    eco scribe -> Ecoscribe in any case) changes nothing and isn't counted."""
    rep, rx = _replace_rx(table)
    texts = list(texts)
    if rx is None:
        return texts, {}
    counts: dict[str, int] = {}

    def sub(m):
        key = " ".join(m.group(1).lower().split())
        if m.group(1) != rep[key]:
            counts[key] = counts.get(key, 0) + 1
        return rep[key]
    return [rx.sub(sub, t) if t else t for t in texts], counts


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
