"""What a pill notice shows (dictado-v5g, pill A): one dark capsule, an icon on the left, the
words, maybe a soft detail after them. Pure, so Windows and macOS draw the same notice from the
same flash message without changing who sends it."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .languages import ALL, name


@dataclass(frozen=True)
class Notice:
    text: str
    icon: str = ""    # "" | "nomic" (a struck mic) | "lang" (a badge with the code) | "warn"
    badge: str = ""   # the code on a "lang" icon: "EN", "AUTO", "EL+ES"
    detail: str = ""  # soft words after the text: the mic's name


_UNHEARD = re.compile(r"^Didn't hear you(?: \((.+)\))?$")
_NEXT = re.compile(r"^(Next|This) dictation: (.+)$")
_HEARD = re.compile(r"^✓ ([A-Z]{2,3}(?:\+[A-Z]{2,3})*)(?: · (.+))?$")
_WARN = ("Error", "Couldn't", "No mic", "No GPU", "Ecoscribe crashed", "Ecoscribe needs")
_CODES = {v: k for k, v in ALL.items()}


def notice(msg: str) -> Notice:
    msg = " ".join(str(msg or "").split())
    m = _UNHEARD.match(msg)
    if m:
        return Notice("Didn't hear anything", "nomic", detail=m.group(1) or "")
    m = _NEXT.match(msg)
    if m:
        which, lang = m.group(1), m.group(2)
        if lang == "auto":
            return Notice(f"{which} dictation: any language", "lang", "AUTO")
        return Notice(f"{which} dictation in {lang}", "lang", _CODES.get(lang, lang[:2]).upper())
    m = _HEARD.match(msg)
    if m:
        code = m.group(1)
        return Notice(m.group(2) or name(code.lower().replace("+", ",")), "lang", code)
    if msg.startswith(_WARN):
        return Notice(msg, "warn")
    return Notice(msg)
