"""History > Delete (dictado-vfo): the line and its kept audio go; nothing else changes."""
import json

from ecoscribe import commands, histfile


def _hist(tmp_path, rows):
    p = tmp_path / "history.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n", encoding="utf-8")
    (tmp_path / "recent").mkdir()
    return p


def test_delete_by_id_drops_the_line_and_its_audio(tmp_path):
    p = _hist(tmp_path, [{"id": "a", "ts": "2026-01-01T10:00:00", "text": "first"},
                         {"id": "b", "ts": "2026-01-01T10:01:00", "text": "second"}])
    (tmp_path / "recent" / "a.wav").write_bytes(b"x")
    (tmp_path / "recent" / "b.wav").write_bytes(b"x")
    assert histfile.delete(p, "a") is True
    lines = p.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["id"] for x in lines[:-1]] == ["b"] and lines[-1] == "not json"
    assert not (tmp_path / "recent" / "a.wav").exists() and (tmp_path / "recent" / "b.wav").exists()
    assert histfile.delete(p, "a") is False  # already gone


def test_an_old_line_without_an_id_deletes_by_its_time(tmp_path):
    p = _hist(tmp_path, [{"ts": "2026-01-01T10:00:00", "text": "old"}, {"id": "c", "ts": "2026-01-01T10:00:00", "text": "new"}])
    assert histfile.delete(p, None, "2026-01-01T10:00:00") is True
    assert [json.loads(x).get("id") for x in p.read_text(encoding="utf-8").splitlines()[:-1]] == ["c"]
    assert histfile.delete(p) is False and histfile.delete(tmp_path / "missing.jsonl", "a") is False


def test_the_command_reaches_the_dictation_app():
    calls = []

    class App:
        def delete_dictation(self, rid, ts=None):
            calls.append((rid, ts))
            return {"ok": True, "gone": True}
    h = commands.handler_for(object(), None, app=App())
    assert h("delete_dictation", {"id": "a"}) == {"ok": True, "gone": True} and calls == [("a", None)]
    h("delete_dictation", {"ts": "2026-01-01T10:00:00"})
    assert calls[-1] == ("", "2026-01-01T10:00:00")
    assert commands.handler_for(object(), None)("delete_dictation", {"id": "a"})["ok"] is False
