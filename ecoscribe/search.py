"""Meeting search that ignores accents and ranks results (dictado-8h8).

An SQLite FTS5 index of every session's turns (export.turns), kept in the transcripts folder
(.search.sqlite). SQLite's own diacritics folding only handles Latin letters, so Greek without
its accents found nothing (radar FU2, measured); fold() runs on the text and on every query instead
(casefold, no accents in any script). The raw text is kept for the answer. The index catches up by
itself: each search re-reads only the sessions whose transcript changed since the last one, and
a missing or broken index file is rebuilt from the transcripts. Results are ranked (BM25) and
grouped by session. Swedish "för" and "for" fold to the same word: some noise, ranking absorbs it.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

from . import export, sessions

log = logging.getLogger(__name__)
SCHEMA = 1
CONTEXT_WORDS = 25  # words either side of the first hit in a snippet


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").casefold())
    return "".join(c for c in s if not unicodedata.combining(c))


def _words(q: str) -> list[str]:
    return re.findall(r"\w+", fold(q))


def terms(q: str) -> list[str]:
    """The query's phrases (in double quotes) and words, folded: "release moves", budget."""
    out, rest = [], q
    for phrase in re.findall(r'"([^"]+)"', q):
        w = _words(phrase)
        if w:
            out.append(" ".join(w))
        rest = rest.replace(f'"{phrase}"', " ")
    return out + [w for w in _words(rest) if w not in out]


def fts_query(q: str) -> str | None:
    """Any of the terms, each word also as a word start ("entrada" finds "entradas"); search() then
    keeps the calls that have every term somewhere."""
    parts = [f'"{t}"' if " " in t else f'"{t}"*' for t in terms(q)]
    return " OR ".join(parts) or None


def has(text_words: str, term: str) -> bool:
    """term (a word start or a phrase) in ' '-joined folded words."""
    return f" {term}" in f" {text_words}"


def snippet(raw: str, q: str) -> str:
    words, want = raw.split(), _words(q)
    at = next((i for i, w in enumerate(words) if any(fold(w).strip(".,;:!?¿¡()\"'«»").startswith(x) for x in want)), 0)
    lo, hi = max(0, at - CONTEXT_WORDS), at + CONTEXT_WORDS
    return ("… " if lo else "") + " ".join(words[lo:hi]) + (" …" if hi < len(words) else "")


class Index:
    def __init__(self, db: Path, root: Path):
        self.db, self.root = Path(db), Path(root)
        self.con = self._open()

    def _open(self) -> sqlite3.Connection:
        try:
            con = self._connect()
            if con.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
                con.close()
                raise sqlite3.DatabaseError("old schema")
            return con
        except sqlite3.DatabaseError:  # broken or old: it's only a cache of the transcripts
            log.info("search index rebuilt (%s)", self.db)
            for p in (self.db, Path(str(self.db) + "-wal"), Path(str(self.db) + "-shm")):
                p.unlink(missing_ok=True)
            con = self._connect()
            con.executescript(f"""
                CREATE TABLE seen(id TEXT PRIMARY KEY, mtime REAL);
                CREATE VIRTUAL TABLE turns USING fts5(text, id UNINDEXED, t0 UNINDEXED, speaker UNINDEXED,
                                                     raw UNINDEXED, tokenize='unicode61 remove_diacritics 0');
                PRAGMA user_version={SCHEMA};""")
            return con

    def _connect(self) -> sqlite3.Connection:
        self.db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.db), timeout=5, check_same_thread=False)
        try:
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            con.close()  # Windows can't delete a file that is still open
            raise
        return con

    def refresh(self) -> int:
        """Re-index sessions whose transcript.json changed; drop deleted ones. Returns how many changed."""
        seen = dict(self.con.execute("SELECT id, mtime FROM seen"))
        now, changed = {}, 0
        for d in (p for p in self.root.iterdir() if p.is_dir()) if self.root.is_dir() else ():
            f = d / "transcript.json"
            try:
                now[d.name] = f.stat().st_mtime
            except OSError:
                continue
        with self.con:
            for sid in set(seen) - set(now):
                self.con.execute("DELETE FROM turns WHERE id = ?", (sid,))
                self.con.execute("DELETE FROM seen WHERE id = ?", (sid,))
                changed += 1
            for sid, mtime in now.items():
                if seen.get(sid) == mtime:
                    continue
                try:
                    segs = json.loads((self.root / sid / "transcript.json").read_text(encoding="utf-8"))["segments"]
                except (OSError, ValueError, KeyError):
                    continue
                self.con.execute("DELETE FROM turns WHERE id = ?", (sid,))
                self.con.executemany("INSERT INTO turns(text, id, t0, speaker, raw) VALUES (?, ?, ?, ?, ?)",
                                     [(fold(t["text"]), sid, t["t0"], t.get("speaker") or "", t["text"])
                                      for t in export.turns(segs)])
                self.con.execute("INSERT OR REPLACE INTO seen(id, mtime) VALUES (?, ?)", (sid, mtime))
                changed += 1
        return changed

    def hits(self, q: str, limit: int = 5000) -> list[tuple]:
        """(id, t0, speaker, raw, folded, rank) of lines with any of the terms, best first."""
        fq = fts_query(q)
        if fq is None:
            return []
        self.refresh()
        return self.con.execute("SELECT id, t0, speaker, raw, text, bm25(turns) AS r FROM turns WHERE turns MATCH ? "
                                "ORDER BY r LIMIT ?", (fq, int(limit))).fetchall()

    def _calls(self, q: str) -> list[tuple[str, list]]:
        """Calls that have every term somewhere, best first (the sum of their lines' BM25: more and better lines win)."""
        want = terms(q)
        groups: dict[str, list] = {}
        for sid, t0, spk, raw, text, rank in self.hits(q):
            groups.setdefault(sid, []).append((rank, t0, spk, raw, " ".join(_words(text))))
        full = [(sid, rows) for sid, rows in groups.items() if all(any(has(r[4], t) for r in rows) for t in want)]
        return sorted(full, key=lambda kv: sum(r[0] for r in kv[1]))

    def session_ids(self, q: str) -> set[str]:
        return {sid for sid, _ in self._calls(q)}

    def search(self, q: str, limit: int = 10, per_session: int = 3, keep=lambda meta: True) -> list[dict]:
        """Calls best first, each with its best lines (in time order) as snippets."""
        out = []
        for sid, rows in self._calls(q):
            try:
                meta = sessions.read_meta(self.root / sid)
            except (OSError, ValueError):
                continue
            if not keep(meta):
                continue
            names = meta.get("speaker_names") or {}
            best = sorted(rows[:per_session], key=lambda r: r[1])
            out.append({"id": sid, "title": meta.get("title", ""), "date": export._date(meta), "lines": len(rows),
                        "hits": [{"at": export._hms(r[1]), "speaker": names.get(r[2]) or export._SPEAKER.get(r[2], r[2]) or "",
                                  "text": snippet(r[3], q)} for r in best]})
            if len(out) >= max(1, int(limit)):
                break
        return out

    def close(self) -> None:
        self.con.close()


FILE = ".search.sqlite"  # inside the transcripts folder: list_sessions only looks at folders


def open_index(root: Path) -> Index:
    return Index(Path(root) / FILE, root)
