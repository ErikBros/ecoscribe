"""history.jsonl edits that rewrite the file (dictado-vfo): one place for the atomic rewrite.

The background app appends a line per dictation under its lock and calls these under the same
lock; the window calls them only when the background app isn't running."""
from __future__ import annotations

import json
import os
from pathlib import Path


def delete(path: Path, rid: str | None = None, ts: str | None = None) -> bool:
    """Drop the dictation with this id (or, for an old line without one, this timestamp) and its
    kept audio (recent/<id>.wav). True when a line went."""
    if not rid and not ts:
        return False
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    out, gone = [], False
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        hit = isinstance(rec, dict) and ((rid and rec.get("id") == rid) or (not rid and not rec.get("id") and rec.get("ts") == ts))
        if hit and not gone:
            gone = True
            continue
        out.append(line)
    if not gone:
        return False
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
    os.replace(tmp, path)
    if rid:
        try:
            (path.parent / "recent" / f"{Path(str(rid)).name}.wav").unlink()
        except OSError:
            pass
    return True
