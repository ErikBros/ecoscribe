"""Self-corrections in dictation (dictado-ehc), opt-in: `[text] self_corrections = true`.

Two layers. "Scratch that" (and its Spanish, Swedish and Greek forms) drops the sentence before it
with plain rules, no model. A dictation where the speaker corrects themselves mid-sentence ("on
Tuesday, no wait, on Thursday") goes to Claude Haiku through the user's own Claude Code login
(claude_cli), only when one of the trigger phrases below was said; any error, a slow answer
(`correction_timeout_s`) or an answer that doesn't look like the same dictation pastes the text as
heard. A Haiku call through Claude Code took 2.4 to 3.2 s (Windows, 2026-10-22), so the default
limit is 5 s.
"""
from __future__ import annotations

import logging
import re

from . import claude_cli

log = logging.getLogger(__name__)

# One table for the rules and for Settings, like text.VOICE_COMMANDS. A phrase counts only as its
# own clause (after the start or a punctuation mark): "scratch that itch" stays text.
SCRATCH = {"en": ["scratch that", "delete that", "strike that"], "es": ["borra eso", "tacha eso"],
           "sv": ["stryk det", "sudda det"], "el": ["σβήσε το", "σβήσ' το"]}
TRIGGERS = {"en": ["no wait", "sorry I mean", "sorry I meant", "correction"],
            "es": ["no perdón", "no espera", "perdón quise decir", "corrijo"],
            "sv": ["nej förlåt", "nej vänta", "förlåt jag menar", "rättelse"],
            "el": ["όχι συγγνώμη", "όχι περίμενε", "συγγνώμη εννοώ"]}

SYSTEM = ("You fix dictated text where the speaker corrected themselves while talking. Apply each "
          "correction and remove the correction words. Change nothing else: same language, same words, "
          "same punctuation style. Reply with the corrected text only, no quotes, no comments.")


def _alt(ps) -> str:
    """Alternation; spaces match any run of spaces or a comma ("no, wait" = "no wait")."""
    return "|".join(r"[\s,]+".join(map(re.escape, p.split())) for p in sorted(ps, key=len, reverse=True))


_SCRATCH_ALT = _alt(p for ps in SCRATCH.values() for p in ps)
_SCRATCH = re.compile(r"(?:^|(?<=[.,;:!?]))\s*(?:" + _SCRATCH_ALT +
                      r")\s*(?:[.,;:!?]+|$)", re.IGNORECASE)
_TRIGGER = re.compile(r"(?:^|(?<=[\s.,;:!?]))(?:" + _alt(p for ps in TRIGGERS.values() for p in ps) +
                      r")(?=[\s.,;:!?]|$)", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?…]\s+")


def scratch_that(s: str) -> str:
    """Each "scratch that" drops itself and the sentence before it. Alone, it leaves nothing."""
    if not _SCRATCH.search(s):
        return s
    tail = " " if s.endswith(" ") else ""
    while (m := _SCRATCH.search(s)):
        body = s[:m.start()].rstrip(".,;:!?… ")
        keep = body[:max((e.end() for e in _SENTENCE_END.finditer(body)), default=0)].rstrip()
        rest = s[m.end():].strip()
        if rest and (not keep or keep[-1] in ".!?…"):
            rest = rest[0].upper() + rest[1:]
        s = f"{keep} {rest}".strip()
    return s + tail if s else ""


def scratch_only(s: str) -> bool:
    """The whole dictation is "scratch that": take back the previous paste (dictado-ost)."""
    return bool(re.fullmatch(r"\s*(?:" + _SCRATCH_ALT + r")\s*[.,;:!?]*\s*", s, re.IGNORECASE))


def wants_model(s: str) -> bool:
    return bool(_TRIGGER.search(s))


def _plausible(raw: str, fixed: str) -> bool:
    """The model's answer is the same dictation, shorter or about as long: not a reply or a rewrite."""
    fixed = fixed.strip()
    return bool(fixed) and len(fixed) <= len(raw) + 15 and not fixed.lower().startswith(("here", "sure", "aquí", "här"))


def apply(s: str, cfg, ask=None) -> str:
    """The dictation as meant. Never raises; never waits longer than the configured limit."""
    if not s or not getattr(cfg.text, "self_corrections", False):
        return s
    out = scratch_that(s)
    if out != s:
        log.info("self-correction: scratch that")
    if not out or not wants_model(out):
        return out
    try:
        fixed = (ask or claude_cli.ask)(out, SYSTEM, model=cfg.text.correction_model, timeout=cfg.text.correction_timeout_s,
                    command=cfg.claude.command or None)
    except Exception as e:  # timeout, not logged in, no Claude Code: the text as heard
        log.warning("self-correction skipped: %s", type(e).__name__)
        return out
    if not _plausible(out, fixed):
        log.warning("self-correction answer didn't look like the dictation: kept the text as heard")
        return out
    log.info("self-correction applied")
    return fixed.strip() + (" " if out.endswith(" ") else "")
