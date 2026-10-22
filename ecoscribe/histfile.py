"""history.jsonl edits that rewrite the file (dictado-vfo, dictado-1ph): one place for the atomic rewrite.

The background app appends a line per dictation under its lock and calls these under the same
lock; the window calls them only when the background app isn't running."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _rewrite(path: Path, rid: str | None, ts: str | None, change) -> bool:
    """Rewrite the first line with this id (or, for an old line without one, this timestamp):
    change(rec) returns the new record, or None to drop it. True when a line matched."""
    if not rid and not ts:
        return False
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    out, hit_one = [], False
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        hit = isinstance(rec, dict) and ((rid and rec.get("id") == rid) or (not rid and not rec.get("id") and rec.get("ts") == ts))
        if hit and not hit_one:
            hit_one = True
            rec = change(rec)
            if rec is None:
                continue
            line = json.dumps(rec, ensure_ascii=False)
        out.append(line)
    if not hit_one:
        return False
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
    os.replace(tmp, path)
    return True


def delete(path: Path, rid: str | None = None, ts: str | None = None) -> bool:
    """Drop the dictation with this id (or, for an old line without one, this timestamp) and its
    kept audio (recent/<id>.wav). True when a line went."""
    if not _rewrite(path, rid, ts, lambda rec: None):
        return False
    if rid:
        try:
            (Path(path).parent / "recent" / f"{Path(str(rid)).name}.wav").unlink()
        except OSError:
            pass
    return True


def edit(path: Path, rid: str | None, ts: str | None, text: str) -> bool:
    """History > Edit (dictado-1ph): the dictation's new text. The scores were about the old one."""
    def change(rec):
        rec.update(text=text, edited=True)
        for k in ("clarity", "heard", "unsure"):
            rec.pop(k, None)
        return rec
    return _rewrite(path, rid, ts, change)
