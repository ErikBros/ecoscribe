"""What's new, per version (dictado-owyk). One list feeds both places users read it: Home shows a card with
this version's lines once after an update, and tools/release.py writes the GitHub release notes from it. A
version bump adds its entry here (tests/test_whatsnew.py checks that the current version has one).

Every line is public text (it becomes the release notes): plain words, no names, no quotes of anyone's
dictation or meetings. `text` is optional (a short line is all title); `only` limits a line to "windows" or "mac".
`show` (dictado-3zfe) is where the feature lives, for Home's Show me: {"page": a window page, "y": how far down
that page it sits (0 top, 1 bottom, for the little map), "spots": [[selector, hint], ...], the first one on screen
gets the ring and its hint, plus "card" to open a Settings card's tab first}. The release notes leave it out.

State lives in <data dir>/whatsnew.json: {"seen": "X.Y.Z"}, the newest version whose card was shown and
closed. Pure apart from that file."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .updates import is_newer, parse

STATE = "whatsnew.json"
FIRST_CARD = "1.28.0"  # the first version with this card: a copy without whatsnew.json updated from before it
MAX_LINES = 6  # a card, not the release page: the rest is behind "All release notes"

NOTES: dict[str, list[dict]] = {
    "1.29.0": [
        {"title": "Auto tags", "text": "tag one recurring meeting and Ecoscribe offers to tag every one; a meeting "
         "with people from another company suggests that company's tag. Off until you turn it on in Settings > Meetings.",
         "show": {"page": "ajustes", "card": "autotags", "y": 0.75, "spots": [  # dictado-ng5i.1: the opt-in switch
             ["#at-head", "Turn auto tags on here. Then tagging a meeting offers to tag the rest of the series."]]}},
        {"title": "Ask Claude about one tag", "text": "Claude can search, debrief and sum up only the meetings "
         "with one tag, like everything promised to one customer."},
    ],
    "1.28.1": [
        {"title": "Show me", "text": "a new feature on this list opens its screen and points at it, with a small "
         "map of where it is."},
    ],
    "1.28.0": [
        {"title": "Tags on meetings", "text": "label a meeting, for example by customer or recurring call, then pick "
         "a tag above the list to see only those. Search and Claude find tags too.",
         "show": {"page": "reuniones", "y": 0.2, "spots": [
             ["#r-tags", "Click a tag to see only those meetings."],
             ["#r-list > li", "Open a meeting and add a tag under its title."]]}},
        {"title": "What's new on Home", "text": "after an update, Home names what the new version brings, and the "
         "update notice says it before you install."},
    ],
    "1.27.0": [
        {"title": "Share in Slack", "text": "a meeting's Share menu copies the transcript as a Markdown file, named "
         "with the meeting, who spoke and how long, and opens Slack. Paste it in a chat to attach it."},
        {"title": "Meetings in another language", "text": "when a call sounds like a different language than the "
         "one picked, Ecoscribe offers to switch."},
        {"title": "Voice commands", "text": "pick the languages they work in."},
        {"title": "Drag the pill to move it", "only": "mac"},
        {"title": "Meetings follow the call's mic", "only": "mac"},
        {"title": "Speaker names during a call", "text": "when memory allows.", "only": "mac"},
        {"title": "The title bar follows Appearance", "only": "mac"},
    ],
}


def this_platform() -> str:
    return "mac" if sys.platform == "darwin" else "windows"


def lines(version: str, platform: str | None = None) -> list[dict]:
    """The version's lines for this platform: [{"title", "text"}]."""
    platform = platform or this_platform()
    return [{"title": n["title"], "text": n.get("text", ""), **({"show": n["show"]} if n.get("show") else {})} for n in NOTES.get(str(version).lstrip("v"), [])
            if n.get("only") in (None, platform)]


def release_notes(version: str) -> str:
    """The GitHub release notes for a version: what's new on both, then each platform's own lines."""
    rows = NOTES.get(str(version).lstrip("v"), [])
    out = []
    for head, which in (("What's new", None), ("Windows", "windows"), ("Mac", "mac")):
        part = [f"- **{n['title']}:** {n['text']}" if n.get("text") else f"- **{n['title']}**"
                for n in rows if n.get("only") == which]
        if part:
            out += ([""] if out else []) + [f"## {head}", ""] + part
    return "\n".join(out) + "\n" if out else ""


def load(data_dir: Path) -> dict:
    try:
        data = json.loads((Path(data_dir) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mark_seen(data_dir: Path, version: str) -> None:
    p = Path(data_dir) / STATE
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps({"seen": str(version).lstrip("v")}), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def pending(data_dir: Path, current: str, updated: bool, platform: str | None = None) -> dict:
    """Home's card: {"version", "items"} when this copy was updated since the card was last closed; {} otherwise.
    updated: this isn't a fresh install (the welcome was finished). A fresh install marks the version seen and
    shows nothing: everything is new to them. An update from before this card existed (no whatsnew.json) shows
    every version since FIRST_CARD, so a jump from 1.27 to a later one still hears about 1.28's features.
    Several versions skipped: newest first, at most MAX_LINES lines."""
    current = str(current).lstrip("v")
    seen = load(data_dir).get("seen")
    if not parse(seen):
        if not updated:
            mark_seen(data_dir, current)
            return {}
        seen = None
    elif not is_newer(current, seen):
        return {}
    versions = sorted((v for v in NOTES if parse(v) and not is_newer(v, current) and (
        not is_newer(FIRST_CARD, v) if seen is None else is_newer(v, seen))), key=parse, reverse=True)
    items = [i for v in versions for i in lines(v, platform)][:MAX_LINES]
    if not items:
        return {}
    return {"version": current, "items": items}
