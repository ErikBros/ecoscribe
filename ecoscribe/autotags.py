"""Auto tags (dictado-fnnr): tags that stay complete without tagging every meeting by hand.

Two kinds of rule, both made from a meeting's page and listed in Settings > Meetings > Auto tags:
- title: every meeting whose calendar event has this title (case and spaces ignored) gets the tag;
- domain: every meeting with a guest from this company's email domain gets the tag.
A rule tags the meetings already there when it is made, each new meeting when its calendar info is
saved (meetings.py, window.py), and catches up when the Meetings list loads. A tag the user took off a
meeting by hand stays off it (`tags_removed` in its meta.json).

All of it is opt-in (dictado-ng5i.1): the rules run, and the page offers and suggests, only while Settings >
Meetings > Auto tags is on (`[meetings] auto_tags`, off by default and for a config from before the switch).
`enabled()` is the one place that decides. Off keeps the rules (paused) and the tags meetings already have.

The rules and the offers the user said No to live in <data dir>/autotags.json. Everything apart from
load/save and the two helpers that write meta.json is pure, so the tests need no app.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import sessions

log = logging.getLogger(__name__)
STATE = "autotags.json"
KINDS = ("title", "domain")
# free mail: a guest from one of these is a person, not a company
FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com",
             "me.com", "mac.com", "proton.me", "protonmail.com", "pm.me", "hey.com", "aol.com", "ymail.com"}
FREE_MAIL_NAMES = {"yahoo", "gmx", "hotmail", "outlook", "live"}  # yahoo.*, gmx.*, hotmail.co.uk ...
# second-level labels under a country code: customer.co.uk is one company, not "co"
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or", "go", "gv", "ltd", "plc"}
_lock = threading.Lock()


# ---------- the switch ----------

def enabled(config_path: Path | None = None) -> bool:
    """Settings > Meetings > Auto tags: True only when the config says `auto_tags = true`. Off when the file is
    missing, has no such key or can't be read. Never raises. config_path: the app's own config by default."""
    try:
        from . import config, paths
        return config.load(Path(config_path) if config_path else paths.config_path()).meetings.auto_tags is True
    except Exception:  # noqa: BLE001  a broken config never turns rules on
        log.warning("auto tags: couldn't read the config, treated as off", exc_info=True)
        return False


# ---------- pure: names and matching ----------

def title_key(title) -> str:
    """A calendar title for matching: spaces collapsed, case ignored."""
    return " ".join(str(title or "").split()).casefold()


def domain_of(email) -> str:
    s = str(email or "").strip().lower()
    return s.rsplit("@", 1)[1].strip(" .>") if "@" in s else ""


def registrable(domain) -> str:
    """The company's own domain: mail.bosch.de -> bosch.de, eu.customer.co.uk -> customer.co.uk."""
    labels = [x for x in str(domain or "").strip().lower().strip(".").split(".") if x]
    if len(labels) < 2:
        return ".".join(labels)
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_free_mail(domain) -> bool:
    reg = registrable(domain)
    return reg in FREE_MAIL or reg.split(".")[0] in FREE_MAIL_NAMES


def tag_name(domain, known=()) -> str:
    """A tag named after a company domain: customer-a.com -> "Customer A", mail.bosch.de -> "Bosch". A tag
    already in use with that name in another case keeps its spelling."""
    label = registrable(domain).split(".")[0]
    name = " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_]+", label) if w)
    name = sessions.clean_tag(name)
    for k in known or ():
        if k.casefold() == name.casefold():
            return k
    return name


def meeting_domains(meta: dict) -> list[str]:
    """The company domains of a meeting's guests (the owner is never among them), in order, once each."""
    out = []
    for e in (meta.get("calendar") or {}).get("emails") or []:
        d = registrable(domain_of(e))
        if "." in d and d not in out:
            out.append(d)
    return out


def own_domains(metas, owner_email: str = "") -> set[str]:
    """The user's own company domain(s), never suggested as a customer. From the calendar owner's address when
    known (none when that is free mail); else the domain in the most meetings with guests (all of them on a tie)."""
    owner = domain_of(owner_email)
    if owner:
        return set() if is_free_mail(owner) else {registrable(owner)}
    counts = Counter(d for m in metas for d in meeting_domains(m) if not is_free_mail(d))
    if not counts:
        return set()
    top = max(counts.values())
    return {d for d, c in counts.items() if c == top}


def removed(meta: dict) -> set[str]:
    """The tags the user took off this meeting by hand while a rule wanted them (case ignored)."""
    t = meta.get("tags_removed")
    return {x.casefold() for x in t if isinstance(x, str)} if isinstance(t, list) else set()


def rule_matches(rule: dict, meta: dict) -> bool:
    if rule.get("kind") == "title":
        return bool(rule.get("match")) and title_key((meta.get("calendar") or {}).get("title")) == rule["match"]
    if rule.get("kind") == "domain":
        return rule.get("match") in meeting_domains(meta)
    return False


def wanted(meta: dict, rules) -> list[str]:
    """The tags the rules give this meeting, in rule order, once each."""
    out = []
    for r in rules or ():
        if rule_matches(r, meta) and r.get("tag") and all(t.casefold() != r["tag"].casefold() for t in out):
            out.append(r["tag"])
    return out


def apply(meta: dict, rules, known=()) -> list[str] | None:
    """The meeting's tags with the rules' tags added, or None when nothing changes (already there, taken
    off by hand, or the meeting is full)."""
    have, gone = sessions.tags_of(meta), removed(meta)
    add = [t for t in wanted(meta, rules) if not sessions.has_tag(meta, t) and t.casefold() not in gone]
    if not add:
        return None
    new = sessions.normalize_tags(have + add, known)
    return new if new != have else None


def removals(meta: dict, old, new, rules) -> list[str]:
    """meta's `tags_removed` after the user changed its tags from `old` to `new`: a tag a rule would add that
    the user took off is remembered; one the user put back is forgotten."""
    want = {t.casefold() for t in wanted(meta, rules)}
    now = {t.casefold() for t in new}
    keep = [t for t in meta.get("tags_removed") or [] if isinstance(t, str) and t.casefold() not in now]
    for t in old:
        k = t.casefold()
        if k not in now and k in want and all(x.casefold() != k for x in keep):
            keep.append(t)
    return keep


def dismiss_key(kind: str, match: str, tag: str = "") -> str:
    return f"title|{title_key(match)}|{sessions.clean_tag(tag).casefold()}" if kind == "title" \
        else f"domain|{registrable(match)}"


def has_rule(state: dict, kind: str, match: str, tag: str = "") -> bool:
    key = title_key(match) if kind == "title" else registrable(match)
    return any(r["kind"] == kind and r["match"] == key and (kind != "title" or r["tag"].casefold() == tag.casefold())
               for r in state.get("rules") or [])


def offer(meta: dict, tag: str, state: dict, metas) -> dict | None:
    """After the user tags a meeting from a calendar event: offer to tag every meeting of that event, with how
    many of the others it would tag now. None when there's no event title, a rule already does it, or the
    user said No to it before."""
    title = " ".join(str((meta.get("calendar") or {}).get("title") or "").split())
    tag = sessions.clean_tag(tag)
    key = title_key(title)
    if not key or not tag or has_rule(state, "title", title, tag) or dismiss_key("title", title, tag) in state.get("dismissed", []):
        return None
    me = meta.get("dir")
    others = sum(1 for m in metas if m.get("dir") != me and title_key((m.get("calendar") or {}).get("title")) == key
                 and not sessions.has_tag(m, tag) and tag.casefold() not in removed(m))
    return {"title": title, "tag": tag, "others": others}


def suggestion(meta: dict, own, state: dict, known=()) -> dict | None:
    """One customer tag for this meeting from its guests' email domains: the domain with the most guests that
    isn't the user's own company, free mail, dismissed or already a rule, and whose tag the meeting lacks."""
    counts = Counter(registrable(domain_of(e)) for e in (meta.get("calendar") or {}).get("emails") or [])
    gone = removed(meta)
    ruled = {r["match"] for r in state.get("rules") or [] if r["kind"] == "domain"}
    for d, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        if "." not in d or d in own or is_free_mail(d) or d in ruled or dismiss_key("domain", d) in state.get("dismissed", []):
            continue
        name = tag_name(d, known)
        if not name or sessions.has_tag(meta, name) or name.casefold() in gone:
            continue
        return {"domain": d, "tag": name}
    return None


# ---------- the file ----------

def _valid_rule(r) -> dict | None:
    if not isinstance(r, dict) or r.get("kind") not in KINDS:
        return None
    tag = sessions.clean_tag(r.get("tag"))
    match = title_key(r.get("match")) if r["kind"] == "title" else registrable(r.get("match"))
    if not tag or not match:
        return None
    out = {"kind": r["kind"], "match": match, "tag": tag}
    if r["kind"] == "title":
        out["label"] = " ".join(str(r.get("label") or match).split())
    if r.get("made"):
        out["made"] = str(r["made"])
    return out


def load(data_dir: Path) -> dict:
    """{"rules": [...], "dismissed": [...]}, whatever the file holds (missing, broken or hand-edited)."""
    try:
        raw = json.loads((Path(data_dir) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    rules = [x for x in (_valid_rule(r) for r in raw.get("rules") or []) if x] if isinstance(raw.get("rules"), list) else []
    dismissed = [x for x in raw.get("dismissed") or [] if isinstance(x, str)] if isinstance(raw.get("dismissed"), list) else []
    return {"rules": rules, "dismissed": dismissed}


def _save(data_dir: Path, state: dict) -> None:
    p = Path(data_dir) / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    sessions.replace_retry(tmp, p)


def add_rule(data_dir: Path, kind: str, match: str, tag: str, now: datetime | None = None) -> dict:
    """Adds a rule (once: the same kind, match and tag again changes nothing) and returns it."""
    rule = _valid_rule({"kind": kind, "match": match, "tag": tag, "label": match,
                        "made": (now or datetime.now()).isoformat(timespec="seconds")})
    if rule is None:
        raise ValueError("a rule needs a kind, a title or domain, and a tag")
    with _lock:
        state = load(data_dir)
        for r in state["rules"]:
            if r["kind"] == rule["kind"] and r["match"] == rule["match"] and r["tag"].casefold() == rule["tag"].casefold():
                return r
        state["rules"].append(rule)
        _save(data_dir, state)
    return rule


def remove_rule(data_dir: Path, kind: str, match: str, tag: str) -> dict:
    """Takes a rule away. The tags it already added stay on the meetings."""
    key = title_key(match) if kind == "title" else registrable(match)
    with _lock:
        state = load(data_dir)
        state["rules"] = [r for r in state["rules"] if not (r["kind"] == kind and r["match"] == key
                                                           and r["tag"].casefold() == sessions.clean_tag(tag).casefold())]
        _save(data_dir, state)
    return state


def dismiss(data_dir: Path, kind: str, match: str, tag: str = "") -> dict:
    """The user said No (a title offer, for that tag) or × (a domain suggestion): never offered again."""
    key = dismiss_key(kind, match, tag)
    with _lock:
        state = load(data_dir)
        if key not in state["dismissed"]:
            state["dismissed"].append(key)
            _save(data_dir, state)
    return state


# ---------- writing meta.json ----------

# a meeting another process is still writing (recording, transcribing): left for the next catch-up
BUSY = {"recording", "finalizing", "stopping", "queued", "new", "running", "downloading"}


def apply_all(metas, rules, known=()) -> int:
    """Tags every meeting a rule wants tagged (metas from sessions.list_sessions, updated in place), except
    the ones still being recorded or transcribed. The count."""
    n = 0
    for m in metas:
        if m.get("status") in BUSY:
            continue
        new = apply(m, rules, known)
        if new is None:
            continue
        try:
            sessions.write_meta(Path(m["dir"]), tags=new)
        except (OSError, ValueError):
            log.warning("auto tags: couldn't tag a meeting", exc_info=True)
            continue
        m["tags"] = new
        n += 1
    return n


def apply_one(d: Path, data_dir: Path, config_path: Path | None = None) -> list[str] | None:
    """A meeting's calendar info was just saved: give it the rules' tags, only while auto tags are on (None and
    meta.json untouched while off). config_path: the app's own config by default. Never fails the caller."""
    try:
        if not enabled(config_path):
            return None
        rules = load(data_dir)["rules"]
        if not rules:
            return None
        m = sessions.read_meta(d)
        new = apply(m, rules)
        if new is not None:
            sessions.write_meta(d, tags=new)
            log.info("auto tags: a new meeting got %d tag(s)", len(new) - len(sessions.tags_of(m)))
        return new
    except Exception:  # noqa: BLE001  a tag is never worth a lost meeting
        log.exception("auto tags on a new meeting failed")
        return None


def owner_email(data_dir: Path) -> str:
    """The calendar owner's address from the downloaded iCal copy (its X-WR-CALNAME), or "" when not known."""
    from .calendar_ics import CACHE
    try:
        with open(Path(data_dir) / CACHE, "rb") as f:
            head = f.read(65536).decode("utf-8", errors="replace")
    except OSError:
        return ""
    for line in head.splitlines():
        name, _, value = line.partition(":")
        if name.split(";")[0].strip().upper() == "X-WR-CALNAME" and "@" in value:
            return value.strip().lower()
    return ""
