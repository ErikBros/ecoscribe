"""A short summary next to every personal call (dictado-crf), each item checked against the call (dictado-xu2).

After a personal call's transcript (and its speakers pass) is done, the Sweeper starts
`--summarize <dir>`, which asks Claude (claude_cli, the user's own login) for decisions, the user's
to-dos and open questions, shaped by the kind of call. Every item carries the time and the exact
words it came from; check() looks for those words in the transcript near that time and marks the
items it can't find, because a model's own summary of a call can't be trusted line by line.
Writes summary.json and summary.md into the session folder. Work calls are never touched
(personal.py); `--summarize` by hand works on any session.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
import unicodedata
from pathlib import Path

from . import claude_cli, export, personal, sessions

log = logging.getLogger(__name__)
JSON, MD = "summary.json", "summary.md"
WINDOW_S = 120  # a quote is looked for this far either side of its time
MATCH = 0.85  # fuzzy match a quote must reach (Whisper misspells; Greek accents differ)
SECTIONS = (("decisions", "Decisions"), ("todos", "To-dos"), ("open_questions", "Open questions"))
EVERY_S = 60
STALE_S = 900  # a "running" summary with no worker after this long failed
MAX_TRIES = 2

SYSTEM = ("You write short, faithful summaries of recorded calls as JSON. Never invent anything: every item "
          "comes from a line of the transcript and quotes it exactly.")

ASK = """Summarize this call for the user ("Me" in the transcript). Reply with JSON only, no code fence:
{"kind": "language class" | "family or friends" | "job" | "general",
 "summary": "two or three sentences",
 "decisions": [ITEM], "todos": [ITEM], "open_questions": [ITEM]}
ITEM = {"text": "the point, short", "at": "hh:mm:ss of the line it comes from",
        "quote": "3 to 15 words copied character for character from that line"}
Rules: todos are what Me will do or was asked to do; add "who" to an item that someone else will do.
A language class: decisions = what was taught or corrected, todos = homework and practice,
open_questions = what to ask next class. A job call: the next steps and dates. Family or friends:
plans, promises and dates. Leave a list empty rather than stretch. Write in the language the call
was mostly in, and call Me "you" (never "Me").

"""


def _fold(s: str) -> str:
    """casefold, no accents (Greek too), letters and digits only, single spaces."""
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def _secs(at) -> float | None:
    parts = str(at or "").strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if not 1 <= len(nums) <= 3:
        return None
    t = 0.0
    for n in nums:
        t = t * 60 + n
    return t


def found(quote: str, at, segments: list[dict]) -> bool:
    """The quote is in the transcript within WINDOW_S of `at` (anywhere when `at` is unreadable)."""
    q = _fold(quote)
    if len(q.split()) < 2:
        return False
    t = _secs(at)
    near = [s for s in segments if t is None or (s.get("t0", 0) - WINDOW_S <= t <= s.get("t1", s.get("t0", 0)) + WINDOW_S)]
    hay = _fold(" ".join(s.get("text", "") for s in near))
    if q in hay:
        return True
    words, n = hay.split(), len(q.split())
    for i in range(max(1, len(words) - n + 1)):
        if difflib.SequenceMatcher(None, q, " ".join(words[i:i + n])).ratio() >= MATCH:
            return True
    return False


def check(result: dict, segments: list[dict]) -> dict:
    """Marks every item checked true/false; adds checked/total counts."""
    n = ok = 0
    for key, _ in SECTIONS:
        items = result.get(key) or []
        result[key] = [i for i in items if isinstance(i, dict) and i.get("text")]
        for item in result[key]:
            item["checked"] = found(str(item.get("quote", "")), item.get("at"), segments)
            n += 1
            ok += item["checked"]
    result["checked"], result["total"] = ok, n
    return result


def parse(answer: str) -> dict:
    s = answer.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    d = json.loads(s[start:end + 1])
    if not isinstance(d, dict):
        raise ValueError("not a JSON object")
    return d


def to_md(meta: dict, result: dict) -> str:
    out = [f"# Summary: {meta.get('title', '')}", "",
           f"{export._date(meta)} · {export._app(meta)} · {export._duration(meta.get('duration_s'))} · {result.get('kind', '')}",
           "", f"{result['checked']} of {result['total']} items checked against the call.", ""]
    if result.get("summary"):
        out += [str(result["summary"]).strip(), ""]
    for key, title in SECTIONS:
        items = result.get(key) or []
        if not items:
            continue
        out.append(f"## {title}")
        for i in items:
            who = f" ({i['who']})" if i.get("who") else ""
            mark = "" if i["checked"] else " **(not found in the call)**"
            quote = f' "{i["quote"]}"' if i.get("quote") else ""
            out.append(f"- {i['text']}{who} [{i.get('at', '?')}]{quote}{mark}")
        out.append("")
    return "\n".join(out)


def summarize(d: Path, cfg, ask=claude_cli.ask) -> dict:
    d = Path(d)
    meta = sessions.read_meta(d)
    segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
    text = export.for_claude(meta, segs, export.read_notes(d), cfg.meetings.my_name)
    answer = ask(ASK + text, SYSTEM, model=cfg.summaries.model, timeout=cfg.summaries.timeout_s,
                 command=cfg.claude.command or None)
    result = check(parse(answer), segs)
    result.update(model=cfg.summaries.model, made=time.strftime("%Y-%m-%dT%H:%M:%S"))
    sessions._write_json(d / JSON, result)
    (d / MD).write_text(to_md(meta, result), encoding="utf-8")
    return result


def main(d: str, config_path: str | None = None) -> int:
    """`--summarize DIR`: one summary, then exit (by hand or from the Sweeper)."""
    from . import config, paths, winutil
    d = Path(d)
    winutil.setup_logging(d / "summary.log", logging.INFO)
    cfg = config.load(Path(config_path) if config_path else paths.config_path())
    sessions.write_meta(d, summary="running")
    try:
        r = summarize(d, cfg)
    except Exception as e:
        log.exception("summary failed for %s", d)
        sessions.write_meta(d, summary="failed", summary_error=f"{type(e).__name__}: {e}"[:300])
        return 1
    sessions.write_meta(d, summary="done", summary_error=None)
    log.info("summary done %s: %s of %s items checked", d.name, r["checked"], r["total"])
    return 0


def wanted(meta: dict, cfg, now: float) -> bool:
    """A finished personal session with no summary yet, recent enough, not tried too often."""
    if meta.get("status") != "done" or meta.get("speakers") in ("pending", "running"):
        return False
    if meta.get("summary") in ("done", "running") or int(meta.get("summary_tries") or 0) >= MAX_TRIES:
        return False
    if meta.get("source") != "meeting" or not personal.is_personal(meta, cfg):
        return False
    try:
        made = time.mktime(time.strptime(str(meta.get("created"))[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return False
    return now - made <= cfg.summaries.max_age_days * 86400


class Sweeper:
    """Called from the background app's 1 s meetings poll: at most every EVERY_S, starts one
    `--summarize` worker for the next session that wants one. tick() returns sessions whose
    summary just finished (for a notice)."""

    def __init__(self, cfg, root: Path, spawn, clock=time.time):
        self.cfg, self.root, self.spawn, self.clock = cfg, Path(root), spawn, clock
        self.proc, self.dir, self._at = None, None, 0.0

    def tick(self, busy: set | None = None) -> list[Path]:
        if not self.cfg.summaries.enabled:
            return []
        done = []
        if self.proc is not None and self.proc.poll() is not None:
            d, self.proc, self.dir = self.dir, None, None
            try:
                st = sessions.read_meta(d).get("summary")
            except Exception:
                st = None
            if st == "done":
                done.append(d)
            elif st == "running":  # the worker died without saying: count it as a failed try
                sessions.write_meta(d, summary="failed", summary_error="the summary worker stopped")
        now = self.clock()
        if self.proc is not None or now - self._at < EVERY_S:
            return done
        self._at = now
        busy = {Path(b) for b in (busy or ())}
        for m in sessions.list_sessions(self.root):
            d = Path(m["dir"])
            if m.get("summary") == "running" and now - (d / sessions.META).stat().st_mtime > STALE_S:
                sessions.write_meta(d, summary="failed", summary_error="no answer in time")
                continue
            if d in busy or not wanted(m, self.cfg, now):
                continue
            try:
                sessions.write_meta(d, summary="running", summary_tries=int(m.get("summary_tries") or 0) + 1)
                self.proc, self.dir = self.spawn(["--summarize", str(d)]), d
                log.info("summary started %s pid=%s", d.name, getattr(self.proc, "pid", None))
            except Exception as e:
                log.exception("summary worker did not start for %s", d)
                sessions.write_meta(d, summary="failed", summary_error=f"couldn't start: {e}")
                self.proc = self.dir = None
                continue
            break
        return done
