"""Command mode (dictado-ua2), opt-in: `[text] command_mode = true`.

Select text anywhere, press dictation key + E, let go and say what to change ("make this shorter",
"translate to Swedish"), then tap the dictation key. The selection goes to Claude Haiku through the
user's own Claude Code login (claude_cli) with the spoken instruction; the answer is pasted over the
selection, so the app's own Ctrl+Z undoes it. Nothing is changed when anything fails.

Trial before building (2026-10-22, 20 invented cases through Haiku): 17 clean, 2 minor (a word
choice in a translation, an unasked emoji), 1 added a detail that wasn't in the text; 2.2-2.6 s each.
With the rules below in the request (in the system prompt alone they didn't hold): 17 clean, 3 did a
little less than asked (two "make it shorter" barely shorter, the same word choice), none added a
fact or an emoji; 2.3-3.7 s.
"""
from __future__ import annotations

from . import claude_cli

SYSTEM = ("You edit a piece of text the user selected, following their spoken instruction. Reply with the "
          "replacement text only: no quotes, no comments, no explanation.")
# In the request itself: as the system prompt alone, Haiku still added details and emoji (2026-10-22)
RULES = ("Rules: keep the original language unless the instruction asks for another; keep line breaks and "
         "formatting unless asked to change them; change only what the instruction asks; never add facts, "
         "results, names, numbers or details that are not in the text; no emoji unless asked.")


class EditError(Exception):
    """Why the selection was left as it was, in words for the pill."""


def edit(selection: str, instruction: str, cfg, ask=None) -> str:
    """The selection rewritten as the instruction says. Raises EditError, never pastes half an answer."""
    instruction = " ".join(instruction.split())
    if not instruction:
        raise EditError("Didn't hear what to change")
    try:
        out = (ask or claude_cli.ask)(f"Instruction: {instruction}\n{RULES}\n\nSelected text:\n{selection}", SYSTEM,
                                      model=cfg.text.command_model, timeout=cfg.text.command_timeout_s,
                                      command=cfg.claude.command or None)
    except claude_cli.ClaudeError as e:
        raise EditError(f"Claude didn't answer: {e}"[:120]) from e
    except Exception as e:
        raise EditError(f"Claude didn't answer ({type(e).__name__})") from e
    out = out.strip("\n")
    if not out.strip():
        raise EditError("Claude answered nothing")
    return out
