"""Local MCP server (t0u.31): `Ecoscribe.exe --mcp` lets the Claude app read your meetings.

Claude desktop (or any MCP client) starts it as a child process and talks newline-delimited
JSON-RPC 2.0 over stdin/stdout. Three read-only tools over the transcripts folder:
list_meetings, read_meeting, search_meetings. Nothing is sent anywhere and nothing is changed (only
search.py's index, a cache next to the transcripts, is written):
the client gets only what it asks for. No SDK: the protocol subset is small and stable.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from . import __version__, export, search, sessions

log = logging.getLogger(__name__)
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
RO = {"readOnlyHint": True, "openWorldHint": False}
TOOLS = [
    {"name": "list_meetings", "annotations": RO,
     "description": "List your recorded meetings, calls and transcribed files from Ecoscribe, newest first: "
                    "id, title, date, app (signal, msteams, slack...), duration, language, status, speaker names, "
                    "whether a checked summary exists.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Only titles containing this text"},
         "since": {"type": "string", "description": "Only sessions on or after this date, YYYY-MM-DD"},
         "limit": {"type": "integer", "description": "At most this many (default 30)"}}}},
    {"name": "read_meeting", "annotations": RO,
     "description": "The full transcript of one session (id from list_meetings): its summary first when one was made "
                    "(each item with its time and quote; items marked 'not found in the call' failed the check), "
                    "a header (date, app, duration, "
                    "language), the user's own notes if any were typed, then who said what with [hh:mm:ss] timestamps. "
                    "'Me' is the user (the mic); 'Others' or 'Speaker N' (or a name the user gave) the other side.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "search_meetings", "annotations": RO,
     "description": "Find the calls where some words were said, ranked best first and grouped by call: id, title, date, "
                    "how many lines matched, and up to 3 of the best lines with time and speaker. Case and accents don't "
                    "matter (Greek too). Every word must appear in the call; a word also finds longer words that start "
                    "with it; put an exact phrase in double quotes. Calls are mostly in Swedish, English and Spanish: "
                    "when looking for a topic, search again with the words in each of those languages.",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "since": {"type": "string", "description": "Only sessions on or after this date, YYYY-MM-DD"},
         "limit": {"type": "integer", "description": "At most this many calls (default 10)"}},
         "required": ["text"]}},
]


def _visible(m: dict) -> bool:
    return not str(m.get("title", "")).lower().startswith("prueba")  # Ecoscribe's own test sessions


def _segments(d: Path) -> list[dict]:
    try:
        return json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
    except (OSError, ValueError, KeyError):
        pass
    out = []  # a meeting still recording, or a final pass that never ran: the live text
    try:
        for line in (d / "live.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                break
    except OSError:
        pass
    return out


def _row(m: dict) -> dict:
    return {"id": Path(m["dir"]).name, "title": m.get("title", ""), "date": export._date(m), "app": export._app(m),
            "duration": export._duration(m.get("duration_s") or m.get("recorded_s")), "language": export._lang(m),
            "status": m.get("status"), "speakers": m.get("speaker_names") or {},
            "summary": (Path(m["dir"]) / "summary.md").is_file()}


def list_meetings(root: Path, query: str = "", since: str = "", limit: int = 30) -> list[dict]:
    q = (query or "").lower()
    rows = []
    for m in sessions.list_sessions(root):
        if not _visible(m) or (q and q not in str(m.get("title", "")).lower()):
            continue
        if since and str(m.get("created", ""))[:10] < since[:10]:
            continue
        rows.append(_row(m))
        if len(rows) >= max(1, int(limit or 30)):
            break
    return rows


def _session(root: Path, sid: str) -> Path:
    d = Path(root) / Path(str(sid)).name  # a bare folder name: never a path out of the root
    if not sid or not (d / sessions.META).is_file():
        raise FileNotFoundError(f"no session called {sid!r}: use list_meetings for the ids")
    return d


def read_meeting(root: Path, sid: str) -> str:
    d = _session(root, sid)
    meta = sessions.read_meta(d)
    text = export.for_claude(meta, _segments(d), export.read_notes(d))
    try:  # dictado-crf: its checked summary first, when one was made
        return (d / "summary.md").read_text(encoding="utf-8").strip() + "\n\n---\n\n" + text
    except OSError:
        return text


def search_meetings(root: Path, text: str, limit: int = 10, since: str = "") -> list[dict]:
    """dictado-8h8: ranked, accent-proof, grouped by call (search.py)."""
    if not str(text or "").strip():
        raise ValueError("say what to look for")
    keep = lambda m: _visible(m) and (not since or str(m.get("created", ""))[:10] >= since[:10])  # noqa: E731
    idx = search.open_index(root)
    try:
        return idx.search(text, limit=limit or 10, keep=keep)
    finally:
        idx.close()


def _call(root: Path, name: str, args: dict) -> dict:
    try:
        if name == "list_meetings":
            out = json.dumps(list_meetings(root, args.get("query", ""), args.get("since", ""), args.get("limit", 30)),
                             ensure_ascii=False, indent=1)
        elif name == "read_meeting":
            out = read_meeting(root, args.get("id", ""))
        elif name == "search_meetings":
            out = json.dumps(search_meetings(root, args.get("text", ""), args.get("limit", 10), args.get("since", "")),
                             ensure_ascii=False, indent=1)
        else:
            return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
    except (OSError, ValueError) as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    return {"content": [{"type": "text", "text": out}]}


def handle(root: Path, msg: dict) -> dict | None:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None  # a notification (notifications/initialized, cancelled): no answer
    if method == "initialize":
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "ecoscribe", "version": __version__},
                  "instructions": "The user's meetings and calls, transcribed locally by Ecoscribe. Read-only."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = _call(root, params.get("name", ""), params.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(inp, out, root: Path) -> None:
    for raw in iter(inp.readline, b""):
        if not raw.strip():
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            try:
                reply = handle(root, msg)
            except Exception as e:  # never die on one bad request
                log.exception("mcp request failed")
                reply = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(e)}}
        if reply is not None:
            out.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()


def main(config_path: str | None = None) -> int:
    from . import config, paths, winutil
    from .engine_proc import std_pipes
    winutil.setup_logging(paths.data_dir() / "mcp.log", logging.INFO)
    cfg = config.load(Path(config_path) if config_path else paths.config_path())
    root = sessions.root_dir(cfg.transcribe.root)
    log.info("mcp server up root=%s", root)
    inp, out = std_pipes()
    serve(inp, out, root)
    return 0
