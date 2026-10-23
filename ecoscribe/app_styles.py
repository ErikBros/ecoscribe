"""Per-app dictation styles (dictado-h0m): a small table of how a dictation is written, per kind of app.

At the paste the app you dictate into (and, in a browser, the site the tab is on) picks one of four kinds:
terminal, chat, email or other. Each kind says whether the text starts with a capital letter, keeps the
full stop at the end, and listens for voice commands. Off by default ([text] per_app_styles); with it off
nothing here runs. The window title is read only to tell the kind and is never kept.
"""
from __future__ import annotations

import re

from .coach import BROWSERS, TITLE_SEP, _app

KINDS = [("terminal", "Terminal"), ("chat", "Chat"), ("email", "Email"), ("other", "Everything else")]
OPTIONS = [("capital", "Capital letter at the start"), ("full_stop", "Full stop at the end"),
           ("commands", "Voice commands")]
# The starting table when the user turns styles on: a shell wants "git status", a chat line has no full
# stop, an email and everything else are written as today.
DEFAULTS = {
    "terminal": {"capital": False, "full_stop": False, "commands": True},
    "chat": {"capital": True, "full_stop": False, "commands": True},
    "email": {"capital": True, "full_stop": True, "commands": True},
    "other": {"capital": True, "full_stop": True, "commands": True},
}
# App names as Windows (.exe) and macOS (bundle id key or localized name) report them, normalized like coach._app.
TERMINAL_APPS = set("""windowsterminal wt cmd powershell pwsh conhost openconsole terminal iterm2 iterm warp ghostty
    alacritty wezterm weztermgui kitty mintty hyper tabby""".split())
CHAT_APPS = set("""slack msteams teams microsoftteams whatsapp whatsapproot telegram telegramdesktop signal
    discord messages messenger skype element viber mattermost zoom claude chatgpt perplexity copilot""".split())
EMAIL_APPS = set("""outlook olk microsoftoutlook hxoutlook mail thunderbird spark airmail superhuman mailspring
    emclient""".split())
# A browser tab's site, from the title's last parts ("Subject - Inbox - Gmail - Google Chrome").
EMAIL_SITES = ("gmail", "inbox", "outlook", "mail", "proton mail", "yahoo mail", "fastmail")
CHAT_SITES = ("slack", "whatsapp", "messenger", "teams", "discord", "telegram", "signal", "claude", "chatgpt",
              "gemini", "perplexity", "copilot", "le chat", "mistral", "grok", "deepseek")
EXAMPLES = {"terminal": "Windows Terminal, PowerShell, iTerm2, Warp",
            "chat": "Slack, Teams, WhatsApp, Claude, ChatGPT, and their sites",
            "email": "Outlook, Mail, Thunderbird, Gmail in a browser",
            "other": "Word, Notepad, a code editor, any other app"}


def kind(app, title: str = "") -> str:
    """'terminal', 'chat', 'email' or 'other' for the app you dictate into (and the browser tab's site)."""
    a = _app(app)
    if a in TERMINAL_APPS:
        return "terminal"
    if a in EMAIL_APPS:
        return "email"
    if a in CHAT_APPS:
        return "chat"
    if a not in BROWSERS or not title:
        return "other"
    for part in reversed(TITLE_SEP.split(str(title).lower())):
        part = part.strip()
        if any(part == s or part.startswith(s + " ") or part.endswith(" " + s) for s in EMAIL_SITES):
            return "email"
        if any(part == s or part.startswith(s + " ") or part.endswith(" " + s) for s in CHAT_SITES):
            return "chat"
    return "other"


def table(saved) -> dict[str, dict[str, bool]]:
    """The full table: what the user saved, the defaults for anything missing or unreadable."""
    saved = saved if isinstance(saved, dict) else {}
    out = {}
    for k, _ in KINDS:
        row = saved.get(k) if isinstance(saved.get(k), dict) else {}
        out[k] = {o: bool(row[o]) if isinstance(row.get(o), bool) else DEFAULTS[k][o] for o, _ in OPTIONS}
    return out


def clean_table(rows) -> dict[str, dict[str, bool]]:
    """What Settings sends ([{kind, capital, full_stop, commands}] or {kind: {...}}) as a valid table."""
    if isinstance(rows, list):
        rows = {str(r.get("kind")): r for r in rows if isinstance(r, dict)}
    rows = rows if isinstance(rows, dict) else {}
    return table({k: {o: bool(v.get(o)) for o, _ in OPTIONS if o in v}
                  for k, v in rows.items() if isinstance(v, dict)})


_FIRST = re.compile(r"^(\W*)(\w)(\w*)")
_FULL_STOP = re.compile(r"(?<![.\s])\.(\s*)$")  # one closing full stop; an ellipsis "..." stays


def apply(text: str, style: dict) -> str:
    """The text in this style: first letter lowered when 'capital' is off (not for "I", an acronym or a
    name with a capital inside), the closing full stop dropped when 'full_stop' is off (? and ! stay)."""
    if not text:
        return text
    if not style.get("capital", True):
        m = _FIRST.match(text)
        if m:
            word = m.group(2) + m.group(3)
            keep = word == "I" or (len(word) > 1 and any(c.isupper() for c in word[1:]))
            if not keep and m.group(2).isupper():
                text = m.group(1) + m.group(2).lower() + text[m.end(2):]
    if not style.get("full_stop", True):
        text = _FULL_STOP.sub(r"\1", text)
    return text
