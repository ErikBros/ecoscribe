"""The week's own to-dos from call summaries, grouped by person (dictado-xuu).

Every personal call's summary.json (summary.py) lists to-dos; the ones without a "who" are the
user's own. week() gathers them for one Monday-to-Sunday week, grouped by the person the call was
with: the calendar guests, else the named speakers, else the call's title. The Home page shows the
week so far (window.Api.week_todos) and a tick marks one done (done.json in the to-dos folder).
On Sunday evening the Collector writes the finished week to <data>/todos/<monday>.md and .json and
says so with one notice. Work calls never count (personal.py), whatever their summary says.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import personal, sessions
from .summary import JSON

log = logging.getLogger(__name__)
DIR, DONE = "todos", "done.json"
SUNDAY_HOUR = 18  # the week is collected from Sunday 18:00 on
NOTICE_H = 36  # a week collected later than this after Sunday 18:00 is written without a notice
EVERY_S = 600
MAX_NAMES = 3


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _created(meta: dict) -> datetime | None:
    try:
        return datetime.strptime(str(meta.get("created"))[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def person_of(meta: dict, me: str = "") -> str:
    """Who the call was with: the invite's guests, else the speakers given a name, else the title."""
    skip = {"me", (me or "").strip().lower()}
    names = [str(x).strip() for x in (meta.get("calendar") or {}).get("attendees") or []]
    if not [n for n in names if n and n.lower() not in skip]:
        names = sorted(set(str(v).strip() for v in (meta.get("speaker_names") or {}).values()))
    names = [n for n in dict.fromkeys(names) if n and n.lower() not in skip]
    if not names:
        return str(meta.get("title") or "").strip() or "A call"
    if len(names) > MAX_NAMES:
        return ", ".join(names[:MAX_NAMES - 1]) + f" and {len(names) - MAX_NAMES + 1} more"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def key(session: str, text: str) -> str:
    """A to-do's id for its tick: the call's folder and the words (a summary written again keeps it)."""
    return f"{session}/{' '.join(str(text).split()).lower()}"


def read_done(folder: Path) -> dict:
    try:
        d = json.loads((Path(folder) / DONE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def set_done(folder: Path, k: str, done: bool) -> dict:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    d = read_done(folder)
    if done:
        d[k] = time.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        d.pop(k, None)
    sessions._write_json(folder / DONE, d)
    return d


def week(root: Path, cfg, start: date, folder: Path | None = None) -> dict:
    """The user's own to-dos from the personal calls of the week that starts on Monday `start`."""
    start = monday(start)
    end = start + timedelta(days=7)
    done = read_done(folder) if folder else {}
    people: dict[str, list] = {}
    calls = 0
    for m in sessions.list_sessions(Path(root)):
        when = _created(m)
        if when is None or not start <= when.date() < end or not personal.is_personal(m, cfg):
            continue
        d = Path(m["dir"])
        try:
            summ = json.loads((d / JSON).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mine = [i for i in summ.get("todos") or [] if isinstance(i, dict) and i.get("text") and not i.get("who")]
        if not mine:
            continue
        calls += 1
        who = person_of(m, cfg.meetings.my_name)
        for i in mine:
            k = key(d.name, i["text"])
            people.setdefault(who, []).append({
                "text": str(i["text"]).strip(), "at": i.get("at"), "checked": bool(i.get("checked", True)),
                "session": d.name, "title": m.get("title") or "", "day": when.date().isoformat(),
                "key": k, "done": k in done})
    groups = [{"person": p, "items": sorted(v, key=lambda x: (x["day"], x["session"]))} for p, v in people.items()]
    groups.sort(key=lambda g: (-len(g["items"]), g["person"].lower()))
    n = sum(len(g["items"]) for g in groups)
    return {"start": start.isoformat(), "end": (end - timedelta(days=1)).isoformat(), "people": groups,
            "count": n, "open": sum(1 for g in groups for i in g["items"] if not i["done"]), "calls": calls}


def count_line(w: dict) -> str:
    """'7 to-dos from 4 calls' (the notice's line)."""
    n, c = w["count"], w["calls"]
    return f"{n} {'to-do' if n == 1 else 'to-dos'} from {c} {'call' if c == 1 else 'calls'}"


def to_md(w: dict) -> str:
    out = [f"# Your to-dos, week of {w['start']} to {w['end']}", "",
           count_line(w) + ".", ""]
    for g in w["people"]:
        out.append(f"## {g['person']}")
        for i in g["items"]:
            day = datetime.strptime(i["day"], "%Y-%m-%d").strftime("%a")
            miss = "" if i["checked"] else " (not found in the call)"
            out.append(f"- [{'x' if i['done'] else ' '}] {i['text']} ({day}, {i['title']}){miss}")
        out.append("")
    return "\n".join(out)


def due(now: datetime) -> tuple[date, datetime]:
    """The week the Collector should have written by `now`, and when it became due (its Sunday 18:00)."""
    this = monday(now.date())
    sunday = datetime.combine(this + timedelta(days=6), datetime.min.time()).replace(hour=SUNDAY_HOUR)
    if now >= sunday:
        return this, sunday
    return this - timedelta(days=7), sunday - timedelta(days=7)


class Collector:
    """Ticked from the background app's meetings poll (next to summary.Sweeper). From Sunday 18:00 it
    writes the week's list once; tick() returns the week when the user should hear about it."""

    def __init__(self, cfg, root: Path, folder: Path, clock=time.time):
        self.cfg, self.root, self.folder, self.clock = cfg, Path(root), Path(folder), clock
        self._at = 0.0

    def path(self, start: date) -> Path:
        return self.folder / f"{start.isoformat()}.md"

    def tick(self) -> dict | None:
        if not self.cfg.summaries.enabled:
            return None
        t = self.clock()
        if t - self._at < EVERY_S:
            return None
        self._at = t
        now = datetime.fromtimestamp(t)
        start, since = due(now)
        if self.path(start).exists():
            return None
        w = week(self.root, self.cfg, start, self.folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        sessions._write_json(self.folder / f"{start.isoformat()}.json", w)
        self.path(start).write_text(to_md(w), encoding="utf-8")
        log.info("week's to-dos written %s: %s from %s calls", start, w["count"], w["calls"])
        if w["count"] and (now - since).total_seconds() <= NOTICE_H * 3600:
            return w
        return None
