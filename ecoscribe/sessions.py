"""Transcription sessions: one folder per meeting or imported file.

<root>/<yyyy-mm-dd_hhmm>_<slug>[-N]/ holds audio/, meta.json, transcript.json,
transcript.{txt,md,srt} and progress.json. Plain files: the user and Claude read them.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)
META = "meta.json"


def root_dir(cfg_root: str = "") -> Path:
    return Path(cfg_root) if cfg_root else paths.data_dir() / "transcripts"


def slug(title: str) -> str:
    """Folder-safe ascii slug; Windows-illegal characters can't survive [a-z0-9-]."""
    s = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")
    return s or "sesion"


def replace_retry(tmp: Path, path: Path, tries: int = 20, wait_s: float = 0.05) -> None:
    """os.replace, retried: on Windows it raises PermissionError while any reader (the
    window polling the file, antivirus) has the target open."""
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == tries - 1:
                try:
                    os.unlink(tmp)  # don't leave an orphan .tmp behind
                except OSError:
                    pass
                raise
            time.sleep(wait_s)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_retry(tmp, path)


def create(title: str, lang: str, source: str, root: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = f"{now:%Y-%m-%d_%H%M}_{slug(title)}"
    n = 1
    while True:
        d = root / (base if n == 1 else f"{base}-{n}")
        try:
            d.mkdir()  # atomic claim: two creators in the same minute can't share a folder
            break
        except FileExistsError:
            n += 1
    (d / "audio").mkdir()
    _write_json(d / META, {"title": title, "lang": lang, "source": source,
                           "created": now.isoformat(timespec="seconds"), "status": "new",
                           "duration_s": None, "model": None, "compute_type": None, "slow": False})
    return d


def import_file(src: Path, lang: str, root: Path, title: str | None = None) -> Path:
    src = Path(src)
    d = create(title or src.stem, lang, "import", root)
    shutil.copy2(src, d / "audio" / src.name)
    return d


def read_meta(d: Path) -> dict:
    return json.loads((Path(d) / META).read_text(encoding="utf-8"))


def write_meta(d: Path, **changes) -> dict:
    m = read_meta(d)
    m.update(changes)
    _write_json(Path(d) / META, m)
    return m


def list_sessions(root: Path) -> list[dict]:
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            m = read_meta(d)
        except Exception as e:
            log.warning("session %s skipped: unreadable meta (%s)", d.name, e)
            continue
        m["dir"] = str(d)
        out.append(m)
    out.sort(key=lambda m: (str(m.get("created", "")), Path(m["dir"]).name), reverse=True)
    return out


# ---------- tags: the user's own labels on a meeting, e.g. a customer or a recurring call (dictado-4vms) ----------
TAG_MAX_LEN = 40
TAGS_MAX = 10


def tags_of(m: dict) -> list[str]:
    """A meta's tags, whatever meta.json holds (a hand-edited file may hold anything)."""
    t = m.get("tags")
    return [x for x in t if isinstance(x, str) and x.strip()] if isinstance(t, list) else []


def clean_tag(tag) -> str:
    """One tag: no control characters, spaces collapsed and trimmed, at most TAG_MAX_LEN characters."""
    s = "".join(" " if unicodedata.category(c).startswith("C") else c for c in str(tag or ""))
    return " ".join(s.split())[:TAG_MAX_LEN].strip()


def normalize_tags(tags, known=()) -> list[str]:
    """Cleaned, case-insensitive duplicates dropped (the first spelling stays), at most TAGS_MAX. A tag that
    another meeting already has in another case takes that spelling (`known`, first one wins)."""
    if isinstance(tags, str):
        tags = [tags]
    spelling: dict[str, str] = {}
    for k in known or ():
        spelling.setdefault(k.casefold(), k)
    out, seen = [], set()
    for t in tags or ():
        t = clean_tag(t)
        key = t.casefold()
        if not t or key in seen:
            continue
        seen.add(key)
        out.append(spelling.get(key, t))
        if len(out) >= TAGS_MAX:
            break
    return out


def tag_counts(metas: list[dict]) -> list[dict]:
    """Every tag in use with how many meetings have it, most used first, then by name. Case-insensitive:
    the spelling seen first (newest meeting first in list_sessions' order) names it."""
    counts: dict[str, list] = {}
    for m in metas:
        for t in {x.casefold(): x for x in reversed(tags_of(m))}.values():
            counts.setdefault(t.casefold(), [t, 0])[1] += 1
    return [{"name": n, "count": c} for n, c in sorted(counts.values(), key=lambda x: (-x[1], x[0].casefold()))]


def has_tag(m: dict, tag: str) -> bool:
    key = clean_tag(tag).casefold()
    return bool(key) and any(t.casefold() == key for t in tags_of(m))


def set_tags(d: Path, tags, known=()) -> list[str]:
    clean = normalize_tags(tags, known)
    write_meta(d, tags=clean)
    return clean


def rename(d: Path, title: str) -> dict:
    return write_meta(d, title=title)


def delete(d: Path) -> None:
    shutil.rmtree(d)
