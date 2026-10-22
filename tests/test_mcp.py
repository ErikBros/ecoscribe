"""Local MCP server (t0u.31): `Ecoscribe.exe --mcp` lets the Claude app read the meetings.
Read-only, stdio, newline-delimited JSON-RPC; nothing leaves the PC except what Claude asks for."""
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from ecoscribe import mcp_server, sessions

_windows_layout = pytest.mark.skipif(sys.platform == "darwin", reason="Claude's Windows folders; macOS: test_mac_claude_config")

SEGS = [{"t0": 1.0, "t1": 3.0, "text": "Vi flyttar releasen till fredag.", "speaker": "Speaker 1"},
        {"t0": 4.0, "t1": 6.0, "text": "Okej, jag fixar budgeten.", "speaker": "Me"}]


def make(root, title, day, segs=SEGS, app="signal", status="done", **meta):
    d = sessions.create(title, "sv", "meeting", root, now=datetime(2026, 10, day, 14, 0))
    sessions.write_meta(d, status=status, duration_s=125.0, app=app, **meta)
    if segs is not None:
        (d / "transcript.json").write_text(json.dumps({"segments": segs}), encoding="utf-8")
    return d


def rpc(root, *msgs):
    inp = io.BytesIO("".join(json.dumps(m) + "\n" for m in msgs).encode())
    out = io.BytesIO()
    mcp_server.serve(inp, out, root)
    return [json.loads(l) for l in out.getvalue().decode().splitlines()]


def call(root, tool, **args):
    r = rpc(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    assert r[0]["id"] == 1 and "result" in r[0], r
    return r[0]["result"]


def test_handshake_and_tool_list(tmp_path):
    r = rpc(tmp_path, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert len(r) == 4  # the notification gets no answer
    assert r[0]["result"]["protocolVersion"] == "2025-06-18" and r[0]["result"]["serverInfo"]["name"] == "ecoscribe"
    names = {t["name"] for t in r[1]["result"]["tools"]}
    assert names == {"list_meetings", "read_meeting", "search_meetings", "calls_with_person"}
    assert all(t["annotations"]["readOnlyHint"] for t in r[1]["result"]["tools"])
    assert r[2]["result"] == {}
    assert r[3]["error"]["code"] == -32601


def test_list_newest_first_with_a_filter(tmp_path):
    make(tmp_path, "Planering", 3)
    make(tmp_path, "Retro", 5, app="msteams")
    make(tmp_path, "prueba e2e", 6)  # Ecoscribe's own tests stay out
    text = call(tmp_path, "list_meetings")["content"][0]["text"]
    rows = json.loads(text)
    assert [x["title"] for x in rows] == ["Retro", "Planering"]
    assert rows[0]["app"] == "msteams" and rows[0]["duration"] == "2:05" and rows[0]["id"].startswith("2026-10-05")
    assert [x["title"] for x in json.loads(call(tmp_path, "list_meetings", query="plan")["content"][0]["text"])] == ["Planering"]
    assert len(json.loads(call(tmp_path, "list_meetings", since="2026-10-04")["content"][0]["text"])) == 1


def test_read_meeting_has_names_and_notes(tmp_path):
    d = make(tmp_path, "Retro", 5, speaker_names={"Speaker 1": "Ana"})
    (d / "notes.md").write_text("- ask Tom", encoding="utf-8")
    text = call(tmp_path, "read_meeting", id=d.name)["content"][0]["text"]
    assert "App: signal" in text and "My notes:\n- ask Tom" in text and "Ana" in text and "releasen" in text


def test_read_a_live_meeting_and_unknown_ids(tmp_path):
    d = make(tmp_path, "Live", 5, segs=None, status="recording")
    (d / "live.jsonl").write_text(json.dumps(SEGS[0]) + "\n", encoding="utf-8")
    assert "releasen" in call(tmp_path, "read_meeting", id=d.name)["content"][0]["text"]
    bad = call(tmp_path, "read_meeting", id="..\\..\\Windows")
    assert bad["isError"] is True


def test_search_finds_lines_with_time_and_speaker(tmp_path):
    make(tmp_path, "Retro", 5, speaker_names={"Speaker 1": "Ana"})
    make(tmp_path, "Planering", 3, segs=[{"t0": 0, "t1": 1, "text": "Inget om det.", "speaker": "Me"}])
    text = call(tmp_path, "search_meetings", text="RELEASEN")["content"][0]["text"]
    hits = json.loads(text)
    assert len(hits) == 1 and hits[0]["title"] == "Retro"
    assert hits[0]["hits"][0]["at"] == "00:00:01" and hits[0]["hits"][0]["speaker"] == "Ana"


def test_runs_as_a_real_process(tmp_path):
    """The way the Claude app starts it: a child process, JSON lines on stdin/stdout."""
    make(tmp_path, "Retro", 5)
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[transcribe]\nroot = "{tmp_path.as_posix()}"\n', encoding="utf-8")
    app_dir = Path(__file__).resolve().parent.parent
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_meetings", "arguments": {}}}]
    p = subprocess.run([sys.executable, "-m", "ecoscribe", "--mcp", "--config", str(cfg)], cwd=str(app_dir),
                       input="".join(json.dumps(m) + "\n" for m in msgs).encode(), capture_output=True, timeout=60,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = [json.loads(l) for l in p.stdout.decode().splitlines()]
    assert [l["id"] for l in lines] == [0, 1], p.stderr.decode()[-500:]
    assert "Retro" in lines[1]["result"]["content"][0]["text"]


@_windows_layout
def test_connect_to_claude_desktop_keeps_the_rest(tmp_path):
    from ecoscribe import claude_link
    store = tmp_path / "local" / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    (store / "claude_desktop_config.json").write_text(json.dumps({"preferences": {"x": 1}, "mcpServers": {"other": {"command": "a"}}}))
    files = claude_link.config_files(tmp_path / "roaming", tmp_path / "local")
    assert files == [store / "claude_desktop_config.json"]  # the Store build only
    assert not claude_link.is_connected(files)
    claude_link.connect(files, claude_link.server_entry(r"C:\Apps\Ecoscribe.exe"))
    data = json.loads((store / "claude_desktop_config.json").read_text())
    assert data["preferences"] == {"x": 1} and data["mcpServers"]["other"] == {"command": "a"}
    assert data["mcpServers"]["ecoscribe"] == {"command": r"C:\Apps\Ecoscribe.exe", "args": ["--mcp"]}
    assert (store / "claude_desktop_config.json.bak").exists() and claude_link.is_connected(files)


@_windows_layout
def test_connect_without_any_claude_creates_the_classic_file(tmp_path):
    from ecoscribe import claude_link
    files = claude_link.config_files(tmp_path / "roaming", tmp_path / "local")
    assert files == [tmp_path / "roaming" / "Claude" / "claude_desktop_config.json"]
    claude_link.connect(files, claude_link.server_entry("D.exe"))
    assert claude_link.is_connected(files)


def test_old_dictado_entry_is_renamed(tmp_path):
    """dictado-c9u: the link from before the rename counts as connected and becomes `ecoscribe` at start."""
    from ecoscribe import claude_link
    old, other = tmp_path / "a" / "claude_desktop_config.json", tmp_path / "b" / "claude_desktop_config.json"
    for f, servers in ((old, {"dictado": {"command": "Dictado.exe", "args": ["--mcp"]}, "x": {"command": "x"}}),
                       (other, {"x": {"command": "x"}})):
        f.parent.mkdir()
        f.write_text(json.dumps({"mcpServers": servers}))
    assert claude_link.is_connected([old]) and not claude_link.is_connected([other])
    assert claude_link.relink_old([old, other], claude_link.server_entry("Ecoscribe.exe")) == [old]
    assert json.loads(old.read_text())["mcpServers"] == {"x": {"command": "x"},
                                                        "ecoscribe": {"command": "Ecoscribe.exe", "args": ["--mcp"]}}
    assert json.loads(other.read_text())["mcpServers"] == {"x": {"command": "x"}}  # never linked: untouched


def test_broken_config_is_never_overwritten(tmp_path):
    import pytest
    from ecoscribe import claude_link
    f = tmp_path / "Claude" / "claude_desktop_config.json"
    f.parent.mkdir()
    f.write_text("{not json")
    with pytest.raises(ValueError):
        claude_link.connect([f], claude_link.server_entry("D.exe"))
    assert f.read_text() == "{not json"


def test_window_api_connect(tmp_path, monkeypatch):
    from ecoscribe import claude_link
    from ecoscribe.window import Api
    f = tmp_path / "Claude" / "claude_desktop_config.json"
    monkeypatch.setattr(claude_link, "config_files", lambda *a: [f])
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    assert api.claude_app()["connected"] is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert api.connect_claude_app()["ok"] and api.claude_app()["connected"] is True


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS")
def test_mac_claude_config(tmp_path):
    from ecoscribe import claude_link
    files = claude_link.config_files(tmp_path)
    assert files == [tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
    files[0].parent.mkdir(parents=True)
    files[0].write_text(json.dumps({"mcpServers": {"other": {"command": "a"}}}))
    claude_link.connect(files, claude_link.server_entry("/Applications/Dictado.app/Contents/MacOS/Dictado"))
    data = json.loads(files[0].read_text())
    assert data["mcpServers"]["other"] == {"command": "a"}
    assert data["mcpServers"]["ecoscribe"] == {"command": "/Applications/Dictado.app/Contents/MacOS/Dictado",
                                             "args": ["--mcp"]}
    assert claude_link.is_connected(files)


def test_calls_with_person_by_speaker_guest_and_title(tmp_path):
    """dictado-igs: a named voice, a calendar guest or the title finds the call; unnamed voices never do."""
    make(tmp_path, "Retro", 5, speaker_names={"Speaker 1": "Ána María"})
    make(tmp_path, "Planering", 6, calendar={"title": "Planering", "attendees": ["Tom Berg", "Ana Lund"],
                                             "emails": ["tom@example.com", "ana.lund@example.com"]})
    make(tmp_path, "Fika med Ana", 7)
    make(tmp_path, "Mariana sync", 8)  # "ana" starts no word of it
    make(tmp_path, "Unnamed", 9)  # Others / Speaker N only
    make(tmp_path, "prueba Ana", 10)  # Ecoscribe's own tests stay out
    rows = json.loads(call(tmp_path, "calls_with_person", name="ana")["content"][0]["text"])
    assert [r["title"] for r in rows] == ["Fika med Ana", "Planering", "Retro"]
    assert rows[0]["matched"] == {"title": ["Fika med Ana"]}
    assert rows[1]["matched"] == {"guest": ["Ana Lund", "ana.lund@example.com"]}
    assert rows[1]["guests"] == ["Tom Berg", "Ana Lund"]
    assert rows[2]["matched"] == {"speaker": ["Ána María"]} and rows[2]["speakers"] == {"Speaker 1": "Ána María"}
    two = json.loads(call(tmp_path, "calls_with_person", name="ANA mar")["content"][0]["text"])
    assert [r["title"] for r in two] == ["Retro"]  # every word starts a word of the name
    assert [r["title"] for r in json.loads(call(tmp_path, "calls_with_person", name="ana", since="2026-10-07")
                                           ["content"][0]["text"])] == ["Fika med Ana"]
    assert len(json.loads(call(tmp_path, "calls_with_person", name="ana", limit=1)["content"][0]["text"])) == 1


def test_calls_with_person_nothing_found_points_at_search(tmp_path):
    make(tmp_path, "Retro", 5)
    r = call(tmp_path, "calls_with_person", name="Tom")
    assert not r.get("isError") and "search_meetings" in r["content"][0]["text"]
    assert call(tmp_path, "calls_with_person", name="  ")["isError"] is True
def _get(root, **params):
    return rpc(root, {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": params})[0]


def test_debrief_my_call_prompt(tmp_path):
    """dictado-2mu: the Claude app's 'Debrief my call': to-dos as proposed tickets made only after the user's OK,
    a follow-up to paste, no mailbox or calendar; the call itself comes with it, its checked summary first."""
    r = rpc(tmp_path, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})
    assert "prompts" in r[0]["result"]["capabilities"]
    (p,) = r[1]["result"]["prompts"]
    assert p["name"] == "debrief_call" and p["title"] == "Debrief my call" and not p["arguments"][0]["required"]
    old = make(tmp_path, "Planering", 3)
    new = make(tmp_path, "Retro", 5, speaker_names={"Speaker 1": "Ana"})
    (new / "summary.md").write_text("## To-dos\n- fix the budget", encoding="utf-8")
    make(tmp_path, "Still going", 6, status="recording")  # not finished: never the default
    make(tmp_path, "prueba e2e", 7)
    res = _get(tmp_path, name="debrief_call")["result"]
    text = res["messages"][0]["content"]["text"]
    assert res["messages"][0]["role"] == "user" and new.name in res["description"]
    assert "one ticket per to-do" in text and "Create nothing yet" in text and "ready to paste" in text
    assert "Never open my mailbox or calendar" in text
    assert text.index("Create nothing yet") < text.index("## To-dos") < text.index("releasen")
    other = _get(tmp_path, name="debrief_call", arguments={"id": old.name})["result"]
    assert "Planering" in other["messages"][0]["content"]["text"]


def test_debrief_errors(tmp_path):
    assert _get(tmp_path, name="debrief_call")["error"]["code"] == -32602  # no call yet
    make(tmp_path, "Retro", 5)
    assert _get(tmp_path, name="debrief_call", arguments={"id": "nope"})["error"]["code"] == -32602
    assert _get(tmp_path, name="other")["error"]["code"] == -32602
