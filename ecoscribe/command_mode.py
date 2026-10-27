"""Command mode (dictado-ua2), opt-in: `[text] command_mode = true`.

Select text anywhere, press dictation key + E, let go and say what to change ("make this shorter",
"translate to Swedish"), then tap the dictation key. The selection goes to Claude Haiku through the
user's own Claude Code login (claude_cli) with the spoken instruction; the answer is pasted over the
selection, so the app's own Ctrl+Z undoes it. Nothing is changed when anything fails.

With a writing style file set (dictado-jq7p), its text goes with every edit and the edit uses Sonnet:
the result reads the way the user writes, not the way they speak.

Trial before building (2026-10-22, 20 invented cases through Haiku): 17 clean, 2 minor (a word
choice in a translation, an unasked emoji), 1 added a detail that wasn't in the text; 2.2-2.6 s each.
With the rules below in the request (in the system prompt alone they didn't hold): 17 clean, 3 did a
little less than asked (two "make it shorter" barely shorter, the same word choice), none added a
fact or an emoji; 2.3-3.7 s.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import claude_cli

log = logging.getLogger(__name__)

SYSTEM = ("You edit a piece of text the user selected, following their spoken instruction. Reply with the "
          "replacement text only: no quotes, no comments, no explanation.")
# In the request itself: as the system prompt alone, Haiku still added details and emoji (2026-10-22)
RULES = ("Rules: keep the original language unless the instruction asks for another; keep line breaks and "
         "formatting unless asked to change them; change only what the instruction asks; never add facts, "
         "results, names, numbers or details that are not in the text; no emoji unless asked.")
STYLE_RULE = ("Write the result in the user's own writing style, described in <style> below; where the instruction "
              "asks for something else, the instruction wins. Take only the style from it, never its examples' content.")
STYLE_MAX = 20_000  # characters: a style guide, not a book


def style_text(cfg) -> str:
    """The user's writing style file, read now (edits to it apply on the next edit); "" when none is set or it
    can't be read: the edit then goes ahead without it."""
    path = (getattr(cfg.text, "command_style_file", "") or "").strip()
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text(encoding="utf-8-sig", errors="replace").strip()[:STYLE_MAX]
    except OSError as e:
        log.warning("command mode: writing style file not read (%s)", type(e).__name__)
        return ""


class EditError(Exception):
    """Why the selection was left as it was, in words for the pill."""


def edit(selection: str, instruction: str, cfg, ask=None) -> str:
    """The selection rewritten as the instruction says. Raises EditError, never pastes half an answer."""
    instruction = " ".join(instruction.split())
    if not instruction:
        raise EditError("Didn't hear what to change")
    style = style_text(cfg)
    rules = f"{RULES}\n{STYLE_RULE}\n\n<style>\n{style}\n</style>" if style else RULES
    model = (cfg.text.command_style_model or cfg.text.command_model) if style else cfg.text.command_model
    try:
        out = (ask or claude_cli.ask)(f"Instruction: {instruction}\n{rules}\n\nSelected text:\n{selection}", SYSTEM,
                                      model=model, timeout=cfg.text.command_timeout_s,
                                      command=cfg.claude.command or None)
    except claude_cli.ClaudeError as e:
        raise EditError(f"Claude didn't answer: {e}"[:120]) from e
    except Exception as e:
        raise EditError(f"Claude didn't answer ({type(e).__name__})") from e
    out = out.strip("\n")
    if not out.strip():
        raise EditError("Claude answered nothing")
    return out
