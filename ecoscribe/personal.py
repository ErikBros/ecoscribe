"""Which recorded sessions count as personal (dictado-qlj).

Most recorded calls are work calls. Every automatic step that reads a transcript (summaries,
dictado-crf) asks is_personal() first and skips everything else; a session asked about by hand
(the Claude app, the window) is never filtered. Rules, first match wins:

1. the session's meta says "personal": true or false (set by hand)
2. its title starts with [personal] title_prefix ("p-")
3. the call app is one of [personal] apps (Signal, WhatsApp, Telegram, Discord by default)
4. it was in one of [personal] languages (none by default)
"""
from __future__ import annotations


def why(meta: dict, cfg) -> str | None:
    """The rule that makes a session personal, or None when it isn't."""
    p = cfg.personal
    flag = meta.get("personal")
    if isinstance(flag, bool):
        return "marked personal" if flag else None
    prefix = (p.title_prefix or "").strip().lower()
    if prefix and str(meta.get("title") or "").strip().lower().startswith(prefix):
        return f"title starts with {p.title_prefix!r}"
    app = str(meta.get("app") or "").lower()
    # prefix match, like call detection: packaged names carry suffixes (whatsappdesktop)
    if app and any(app.startswith(a.lower()) for a in p.apps if a):
        return f"call app {app}"
    langs = {str(x).lower() for x in p.languages if x}
    used = {str(meta.get(k) or "").lower() for k in ("lang", "lang_used", "detected_lang")}
    hit = sorted(langs & {u for x in used for u in x.replace("+", ",").split(",") if u})
    if hit:
        return f"language {hit[0]}"
    return None


def is_personal(meta: dict, cfg) -> bool:
    return why(meta, cfg) is not None
