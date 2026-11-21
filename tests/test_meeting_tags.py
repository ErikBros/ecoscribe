"""Tags on meetings (dictado-4vms): the user's own labels, e.g. a customer or a recurring meeting.
Kept in meta.json; the Meetings list filters by one, the search box and Claude (MCP) see them. Invented data only."""
import io
import json
from datetime import datetime

import pytest

from ecoscribe import mcp_server, sessions
from ecoscribe.window import Api


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "transcripts"
    cfg_path = tmp_path / "cfg" / "config.toml"
    cfg_path.parent.mkdir()
    cfg_path.write_text(f'[transcribe]\nroot = "{root.as_posix()}"\n', encoding="utf-8")
    (tmp_path / "data").mkdir()
    api = Api(data_dir=tmp_path / "data", config_path=cfg_path, copy=lambda t: None, signal_reload=lambda: True,
              send_command=lambda d, cmd, args=None: {"ok": True})
    return api, root


def make(root, title, minute, tags=None, segs=None):
    d = sessions.create(title, "en", "meeting", root, now=datetime(2026, 10, 5, 14, minute))
    sessions.write_meta(d, status="done", duration_s=60.0, **({"tags": tags} if tags is not None else {}))
    if segs is not None:
        (d / "transcript.json").write_text(json.dumps({"segments": segs}), encoding="utf-8")
    return d


# ---------- normalising ----------

def test_a_tag_is_trimmed_collapsed_and_cut_at_40():
    assert sessions.normalize_tags(["  Customer   A  ", "Weekly\tops", "x" * 50]) == ["Customer A", "Weekly ops", "x" * 40]


def test_control_characters_and_empty_tags_go():
    assert sessions.normalize_tags(["Hir\x00ing", "\n", "", "   ", None, "Ops​"]) == ["Hir ing", "Ops"]


def test_duplicates_ignore_case_and_the_first_spelling_stays():
    assert sessions.normalize_tags(["Hiring", "HIRING", "hiring ", "Ops"]) == ["Hiring", "Ops"]


def test_another_meetings_spelling_wins():
    assert sessions.normalize_tags(["customer a", "New"], known=["Customer A", "customer A"]) == ["Customer A", "New"]


def test_at_most_ten_and_a_single_string_is_one_tag():
    assert sessions.normalize_tags([f"t{i}" for i in range(15)]) == [f"t{i}" for i in range(10)]
    assert sessions.normalize_tags("Weekly ops") == ["Weekly ops"]


def test_tags_of_survives_a_hand_edited_meta():
    assert sessions.tags_of({"tags": "oops"}) == [] and sessions.tags_of({}) == []
    assert sessions.tags_of({"tags": ["A", 3, None, " ", "B"]}) == ["A", "B"]


# ---------- the window ----------

def test_set_and_get_tags(env):
    api, root = env
    d = make(root, "Client call", 1)
    out = api.set_tags(d.name, ["Customer A", " customer a ", "Weekly ops"])
    assert out == {"ok": True, "tags": ["Customer A", "Weekly ops"], "offer": None}  # no calendar event: nothing to offer (dictado-fnnr)
    assert sessions.read_meta(d)["tags"] == ["Customer A", "Weekly ops"]
    assert api.get_session(d.name)["session"]["tags"] == ["Customer A", "Weekly ops"]
    assert api.list_sessions()["items"][0]["tags"] == ["Customer A", "Weekly ops"]
    assert api.set_tags(d.name, [])["tags"] == [] and sessions.read_meta(d)["tags"] == []


def test_set_tags_reuses_the_spelling_on_another_meeting(env):
    api, root = env
    make(root, "Ops sync", 1, tags=["Weekly Ops"])
    d = make(root, "Ops sync 2", 2)
    assert api.set_tags(d.name, ["weekly ops"])["tags"] == ["Weekly Ops"]


def test_set_tags_on_a_missing_meeting_fails(env):
    api, _ = env
    with pytest.raises(FileNotFoundError):
        api.set_tags("../nope", ["A"])


def test_tag_counts_sorted_by_count_then_name(env):
    api, root = env
    make(root, "One", 1, tags=["Hiring", "Customer A"])
    make(root, "Two", 2, tags=["customer a"])
    make(root, "Three", 3, tags=["Budget", "Weekly ops"])
    make(root, "Four", 4)
    tags = api.list_sessions()["tags"]
    assert [(t["name"], t["count"]) for t in tags] == [("customer a", 2), ("Budget", 1), ("Hiring", 1), ("Weekly ops", 1)]


def test_no_tags_no_chips(env):
    api, root = env
    make(root, "Plain", 1)
    assert api.list_sessions()["tags"] == []


def test_filter_by_tag_ignores_case_and_works_with_the_search_box(env):
    api, root = env
    make(root, "Retro", 1, tags=["Weekly ops"])
    make(root, "Planning", 2, tags=["Weekly ops", "Hiring"])
    make(root, "Client call", 3, tags=["Customer A"])
    out = api.list_sessions(tag="WEEKLY OPS")
    assert [r["title"] for r in out["items"]] == ["Planning", "Retro"]
    assert len(out["tags"]) == 3  # the chips always count every meeting
    assert [r["title"] for r in api.list_sessions("retro", tag="Weekly ops")["items"]] == ["Retro"]
    assert api.list_sessions("client", tag="Weekly ops")["items"] == []
    assert api.list_sessions(tag="Nobody has this")["items"] == []


def test_the_search_box_matches_a_tag_without_accents(env):
    api, root = env
    make(root, "Monday call", 1, tags=["Café Norte"])
    make(root, "Other call", 2)
    assert [r["title"] for r in api.list_sessions("cafe nor")["items"]] == ["Monday call"]
    assert [r["title"] for r in api.list_sessions("CAFÉ")["items"]] == ["Monday call"]


# ---------- Claude (MCP) ----------

def _call(root, tool, **args):
    inp = io.BytesIO((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": tool, "arguments": args}}) + "\n").encode())
    out = io.BytesIO()
    mcp_server.serve(inp, out, root)
    return json.loads(json.loads(out.getvalue().decode())["result"]["content"][0]["text"])


def test_mcp_list_meetings_filters_by_tag_and_shows_tags(tmp_path):
    make(tmp_path, "Retro", 1, tags=["Weekly ops"])
    make(tmp_path, "Client call", 2, tags=["Customer A"])
    make(tmp_path, "Plain", 3)
    rows = _call(tmp_path, "list_meetings")
    assert [r["tags"] for r in rows] == [[], ["Customer A"], ["Weekly ops"]]
    assert [r["title"] for r in _call(tmp_path, "list_meetings", tag="customer a")] == ["Client call"]
    assert _call(tmp_path, "list_meetings", tag="Customer") == []  # the whole tag, not a piece of it


def test_mcp_search_and_person_rows_carry_tags(tmp_path):
    segs = [{"t0": 1.0, "t1": 3.0, "text": "We move the release to Friday.", "speaker": "Speaker 1"}]
    make(tmp_path, "Release sync with Ana", 1, tags=["Weekly ops"], segs=segs)
    assert _call(tmp_path, "search_meetings", text="release")[0]["tags"] == ["Weekly ops"]
    assert _call(tmp_path, "calls_with_person", name="ana")[0]["tags"] == ["Weekly ops"]


def test_mcp_schema_offers_the_tag_filter():
    tool = next(t for t in mcp_server.TOOLS if t["name"] == "list_meetings")
    assert "tag" in tool["inputSchema"]["properties"] and "tag" in tool["description"]
