"""Names fixed once stay fixed (dictado-1ph).

When the user edits a dictation in History, each changed stretch of one to three words is a hint:
the new spelling is a name or a term Whisper got wrong. A new one is offered for Your words; one
that is already there (Whisper still slipped) is offered as a Replace rule from what was heard.
Only spellings that look like names count (a capital mid-word or mid-sentence, or a digit), close
to what was heard, and never common words: rewording a sentence teaches nothing.
"""
from __future__ import annotations

import difflib
import re

from .insights import COMMON_CAPS, STOP

TOKEN = re.compile(r"[\w'’-]+", re.UNICODE)
SENTENCE_END = re.compile(r"(^|[.!?¿¡:;\n])\s*$")
MAX_WORDS = 3  # a longer change is a rewrite, not a misheard name
CLOSE = 0.5  # how alike the heard and the written letters must be
_COMMON = set().union(*STOP.values()) | COMMON_CAPS


def _letters(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _looks_like_a_name(write: str, at_start: bool) -> bool:
    words = TOKEN.findall(write)
    if not words or all(w.lower() in _COMMON for w in words) or write.lower() in COMMON_CAPS:
        return False
    if any(ch.isdigit() for ch in write):
        return True
    caps = [w for i, w in enumerate(words) if any(ch.isupper() for ch in (w if i or not at_start else w[1:]))]
    return bool(caps)


def suggest(old: str, new: str, vocabulary: list[str], replacements: dict[str, str], top: int = 3) -> list[dict]:
    """[{"kind": "word", "write": "Quintavelle"} or {"kind": "replace", "heard": "quinta well", "write": ...}]"""
    a, b = list(TOKEN.finditer(old)), list(TOKEN.finditer(new))
    have = {v.lower() for v in vocabulary}
    reps = {k.lower() for k in replacements}
    out: list[dict] = []
    sm = difflib.SequenceMatcher(None, [m.group(0).lower() for m in a], [m.group(0).lower() for m in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":  # the same words but for their case: "ecoscribe" → "Ecoscribe"
            pairs = [(a[i1 + k].group(0), b[j1 + k], b[j1 + k]) for k in range(i2 - i1)
                     if a[i1 + k].group(0) != b[j1 + k].group(0)]
        elif op == "replace" and i2 - i1 <= MAX_WORDS and j2 - j1 <= MAX_WORDS:
            pairs = [(old[a[i1].start():a[i2 - 1].end()], b[j1], b[j2 - 1])]
        else:
            continue
        for heard, first, last in pairs:
            write = new[first.start():last.end()]
            if write.lower() in {o["write"].lower() for o in out}:
                continue
            if not _looks_like_a_name(write, bool(SENTENCE_END.search(new[:first.start()]))):
                continue
            if difflib.SequenceMatcher(None, _letters(heard), _letters(write)).ratio() < CLOSE:
                continue
            if write.lower() not in have:
                out.append({"kind": "word", "write": write})
            elif heard.lower() not in reps:
                out.append({"kind": "replace", "heard": heard, "write": write})
            if len(out) >= top:
                return out
    return out
