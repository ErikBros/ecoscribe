"""Local MCP server (t0u.31): `Ecoscribe.exe --mcp` lets the Claude app read your meetings.

Claude desktop (or any MCP client) starts it as a child process and talks newline-delimited
JSON-RPC 2.0 over stdin/stdout. Four read-only tools over the transcripts folder:
list_meetings, read_meeting, search_meetings, calls_with_person, and one prompt, "Debrief my call"
(debrief_call). Nothing is sent anywhere and nothing is changed (only search.py's index, a cache next
to the transcripts, is written): the client gets only what it asks for. No SDK: the protocol subset is small and stable.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from . import __version__, export, meaning, search, sessions

log = logging.getLogger(__name__)
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
RO = {"readOnlyHint": True, "openWorldHint": False}
TOOLS = [
    {"name": "list_meetings", "annotations": RO,
     "description": "List your recorded meetings, calls and transcribed files from Ecoscribe, newest first: "
                    "id, title, date, app (signal, msteams, slack...), duration, language, status, speaker names, "
                    "calendar guests, whether a checked summary exists.",
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
                    "when looking for a topic, search again with the words in each of those languages. "
                    "When no call has all the words, and search by meaning is on (it switches itself on after the "
                    "first such miss), the calls closest in meaning come back instead, in any language, marked "
                    "found_by: meaning with a score (about 0.7 unrelated to 0.9 the same thing said): read them "
                    "before trusting them. by_meaning: true searches by meaning straight away (a topic, a question).",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "by_meaning": {"type": "boolean", "description": "Search by meaning instead of by words"},
         "since": {"type": "string", "description": "Only sessions on or after this date, YYYY-MM-DD"},
         "limit": {"type": "integer", "description": "At most this many calls (default 10)"}},
         "required": ["text"]}},
    {"name": "calls_with_person", "annotations": RO,
     "description": "Find the calls with someone, newest first: the calls where they are a named speaker (a name the "
                    "user gave a voice, or one Ecoscribe recognised) or a guest of the calendar invite, plus calls "
                    "with their name in the title. Each row says how it matched. Part of a name is enough (\"ana\" "
                    "finds \"Ana María\"; every word given must start a word of the name); case and accents don't "
                    "matter. Unnamed voices ('Others', 'Speaker N') can't match: when this finds nothing, try "
                    "search_meetings with the name to find calls where it was said.",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "The person's name, or part of it"},
         "since": {"type": "string", "description": "Only sessions on or after this date, YYYY-MM-DD"},
         "limit": {"type": "integer", "description": "At most this many calls (default 30)"}},
         "required": ["name"]}},
]


DEBRIEF = """Debrief this call for me ("Me" in the transcript is me). Answer in the language I write to you in; \
quotes stay in the language spoken.

1. To-dos: every to-do from the call, mine and what the others promised me, one per line: what, who, by when \
(only if a date was said), with the [hh:mm:ss] time and the words it comes from. When the call has a checked \
summary, start from its to-dos and leave out items marked "not found in the call".
2. Tickets: propose one ticket per to-do: a short title, one or two lines with the time and quote, the owner, \
the due date if one was said. Create nothing yet. Ask me which ones to make, and make only the ones I say OK to, \
with the task or issue tool I have connected; with none connected, give them ready to paste.
3. Follow-up: draft a short follow-up message to the other side, ready to paste: what we agreed, who does what, \
by when. Plain words, no filler, in the language the call was held in.

Never open my mailbox or calendar, never send, schedule or invite anything, and never create a ticket before \
I say OK. Only use what the call says; when something is unclear, say so instead of guessing."""

PROMPTS = [
    {"name": "debrief_call", "title": "Debrief my call",
     "description": "Your call's to-dos as proposed tickets (made only after your OK) and a follow-up message to "
                    "paste. Reads nothing but the call.",
     "arguments": [{"name": "id", "required": False,
                    "description": "The call's id from list_meetings; empty = your latest finished call"}]},
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
            "guests": list((m.get("calendar") or {}).get("attendees") or []),
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


def _name_matches(name: str, words: list[str]) -> bool:
    """Every query word starts a word of the name, accents and case ignored ("ana g" -> "Ana García")."""
    have = re.findall(r"\w+", search.fold(name))
    return bool(words) and all(any(h.startswith(w) for h in have) for w in words)


def _people(m: dict) -> dict[str, list[str]]:
    """Who a session says was in it: names given to its voices, its invite's guests (and their addresses)."""
    cal = m.get("calendar") or {}
    return {"speaker": [str(v) for v in (m.get("speaker_names") or {}).values() if v],
            "guest": [str(v) for v in list(cal.get("attendees") or []) + list(cal.get("emails") or []) if v],
            "title": [str(m.get("title") or "")]}


def calls_with_person(root: Path, name: str, since: str = "", limit: int = 30) -> list[dict]:
    """dictado-igs: the calls with someone, by named speaker, calendar guest or title, newest first."""
    words = re.findall(r"\w+", search.fold(name))
    if not words:
        raise ValueError("say whose calls to find")
    rows = []
    for m in sessions.list_sessions(root):
        if not _visible(m) or (since and str(m.get("created", ""))[:10] < since[:10]):
            continue
        matched = {how: sorted({n for n in names if _name_matches(n, words)})
                   for how, names in _people(m).items()}
        matched = {how: names for how, names in matched.items() if names}
        if matched:
            rows.append({**_row(m), "matched": matched})
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


MEANING = {"mode": "auto", "models_root": ""}  # [search] meaning and the models folder, set by main()
INLINE_S = 20.0  # a search by meaning indexes at most this long itself; the background app does the rest
_EMBEDDER: dict = {}


def _by_meaning(root: Path, text: str, limit: int, keep) -> list[dict]:
    """dictado-2i1 (meaning.py): the calls closest in meaning. ValueError when it isn't ready."""
    if not meaning.switched_on(root, MEANING["mode"]):
        raise ValueError("search by meaning is off: it switches on after a word search finds nothing, "
                         "or with [search] meaning = \"on\" in Ecoscribe's config.toml")
    if not meaning.model_ready(MEANING["models_root"]):
        raise ValueError("search by meaning is getting ready: Ecoscribe downloads its model (about 0.55 GB) "
                         "when nothing is recording; try again in a few minutes")
    d = meaning.model_dir(MEANING["models_root"])
    emb = _EMBEDDER.get(d) or _EMBEDDER.setdefault(d, meaning.Embedder(d))  # loaded once per Claude app run
    idx = meaning.Index(root)
    try:
        left = idx.refresh(emb, budget_s=INLINE_S)
        out = idx.search(text, emb, limit=limit, keep=keep)
    finally:
        idx.close()
    if left:
        log.info("meaning search ran with %d calls not indexed yet", left)
        for r in out:
            r["note"] = f"{left} more calls are still being indexed and were not searched"
    return out


def search_meetings(root: Path, text: str, limit: int = 10, since: str = "", by_meaning: bool = False) -> list[dict]:
    """dictado-8h8: ranked, accent-proof, grouped by call (search.py). Nothing found: the miss is
    counted, and the search by meaning answers when it is on (dictado-2i1)."""
    if not str(text or "").strip():
        raise ValueError("say what to look for")
    keep = lambda m: _visible(m) and (not since or str(m.get("created", ""))[:10] >= since[:10])  # noqa: E731
    if by_meaning:
        return _by_meaning(root, text, int(limit or 5), keep)
    idx = search.open_index(root)
    try:
        found = idx.search(text, limit=limit or 10, keep=keep)
    finally:
        idx.close()
    if found:
        return found
    meaning.log_miss(root)
    try:
        return _by_meaning(root, text, min(int(limit or 5), 5), keep)
    except ValueError:  # not on or not ready: the word search's empty answer stands
        return []
    except Exception:
        log.exception("search by meaning failed")
        return []


def _latest_call(root: Path) -> str:
    for m in sessions.list_sessions(root):
        if _visible(m) and m.get("status") == "done":
            return Path(m["dir"]).name
    raise FileNotFoundError("no finished call yet")


def debrief(root: Path, sid: str = "") -> dict:
    """dictado-2mu: the 'Debrief my call' prompt: the steps, then the call itself (its summary first)."""
    sid = str(sid or "").strip() or _latest_call(root)
    text = read_meeting(root, sid)
    return {"description": f"Debrief of {sid}",
            "messages": [{"role": "user", "content": {"type": "text", "text": f"{DEBRIEF}\n\n---\n\n{text}"}}]}


def _call(root: Path, name: str, args: dict) -> dict:
    try:
        if name == "list_meetings":
            out = json.dumps(list_meetings(root, args.get("query", ""), args.get("since", ""), args.get("limit", 30)),
                             ensure_ascii=False, indent=1)
        elif name == "read_meeting":
            out = read_meeting(root, args.get("id", ""))
        elif name == "search_meetings":
            out = json.dumps(search_meetings(root, args.get("text", ""), args.get("limit", 10), args.get("since", ""),
                                             bool(args.get("by_meaning"))), ensure_ascii=False, indent=1)
        elif name == "calls_with_person":
            rows = calls_with_person(root, args.get("name", ""), args.get("since", ""), args.get("limit", 30))
            out = json.dumps(rows, ensure_ascii=False, indent=1) if rows else (
                "No call has this person as a named speaker, a calendar guest or in its title. Voices are named "
                "only when the user names them or Ecoscribe recognises them; try search_meetings with the name.")
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
                  "capabilities": {"tools": {}, "prompts": {}},
                  "serverInfo": {"name": "ecoscribe", "version": __version__},
                  "instructions": "The user's meetings and calls, transcribed locally by Ecoscribe. Read-only."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = _call(root, params.get("name", ""), params.get("arguments") or {})
    elif method == "prompts/list":
        result = {"prompts": PROMPTS}
    elif method == "prompts/get":
        try:
            if params.get("name") != "debrief_call":
                raise ValueError(f"unknown prompt {params.get('name')}")
            result = debrief(root, (params.get("arguments") or {}).get("id", ""))
        except (OSError, ValueError) as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": str(e)}}
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
    MEANING.update(mode=cfg.search.meaning, models_root=cfg.transcribe.models_root)
    log.info("mcp server up root=%s", root)
    inp, out = std_pipes()
    serve(inp, out, root)
    return 0
