"""Search by meaning (dictado-2i1): a word search that finds nothing is counted (never what was looked
for); from the first miss on, the calls closest in meaning answer instead. The model is faked here,
except in the last test, which runs the real one when it is on this machine."""
import json
import os
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest

from ecoscribe import config, mcp_server, meaning, sessions

TOPICS = [("money", "budget presupuesto pengar money dinero cost"), ("travel", "trip resa viaje flight flyg"),
          ("health", "knee doctor läkare médico pain")]


class FakeEmbedder:
    """One dimension per topic word list, plus a little of everything: enough to rank like a model would."""
    calls = 0

    def embed(self, texts, kind="passage"):
        FakeEmbedder.calls += 1
        out = []
        for t in texts:
            words = t.lower().split()
            v = np.array([sum(w.strip(".,?") in ws.split() for w in words) for _, ws in TOPICS] + [0.1], np.float32)
            out.append(v / np.linalg.norm(v))
        return np.vstack(out)


def make(root, title, day, lines, status="done", **meta):
    d = sessions.create(title, "sv", "meeting", root, now=datetime(2026, 10, day, 14, 0))
    sessions.write_meta(d, status=status, duration_s=60.0, app="signal", **meta)
    segs = [{"t0": float(i * 10), "t1": float(i * 10 + 5), "text": t, "speaker": "Speaker 1" if i % 2 else "Me"}
            for i, t in enumerate(lines)]
    (d / "transcript.json").write_text(json.dumps({"segments": segs}), encoding="utf-8")
    return d


def search(root, **args):
    r = mcp_server._call(root, "search_meetings", args)
    return r, r["content"][0]["text"]


@pytest.fixture
def ready(monkeypatch, tmp_path):
    """Meaning search on, the model 'downloaded' (faked)."""
    monkeypatch.setattr(mcp_server, "MEANING", {"mode": "auto", "models_root": str(tmp_path / "models")})
    monkeypatch.setattr(mcp_server, "_EMBEDDER", {})
    monkeypatch.setattr(meaning, "model_ready", lambda models_root="": True)
    monkeypatch.setattr(meaning, "Embedder", lambda d: FakeEmbedder())


def test_a_miss_is_counted_without_the_words(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "MEANING", {"mode": "auto", "models_root": str(tmp_path / "models")})
    root = tmp_path / "t"
    make(root, "Retro", 5, ["Vi flyttar releasen till fredag."])
    assert meaning.misses(root) == 0 and not meaning.switched_on(root, "auto")
    r, text = search(root, text="releasen")
    assert "Retro" in text and meaning.misses(root) == 0  # found: no miss
    r, text = search(root, text="zebrafinkar")
    assert not r.get("isError") and json.loads(text) == []  # not ready yet: the empty answer stands
    r, text = search(root, text="okapi")
    saved = (root / meaning.MISSES).read_text(encoding="utf-8")
    assert json.loads(saved) == {"misses": 2, "last": date.today().isoformat()}
    assert "zebra" not in saved and "okapi" not in saved
    assert meaning.switched_on(root, "auto") and not meaning.switched_on(root, "off")
    assert sessions.list_sessions(root)[0]["title"] == "Retro"  # the log file is no session


def test_modes(tmp_path):
    assert meaning.switched_on(tmp_path, "on") and not meaning.switched_on(tmp_path, "auto")
    meaning.log_miss(tmp_path, today=date(2026, 10, 1))
    assert meaning.switched_on(tmp_path, "AUTO") and meaning.switched_on(tmp_path, "nonsense")  # unknown = auto
    assert not meaning.switched_on(tmp_path, "off")
    assert config.Config().search.meaning == "auto"
    cfg = tmp_path / "config.toml"
    cfg.write_text('[search]\nmeaning = "off"\n', encoding="utf-8")
    assert config.load(cfg).search.meaning == "off"


def test_passages_overlap_and_keep_time_and_speaker():
    segs = [{"t0": 0.0, "t1": 30.0, "text": " ".join(f"a{i}" for i in range(90)), "speaker": "Me"},
            {"t0": 40.0, "t1": 60.0, "text": " ".join(f"b{i}" for i in range(60)), "speaker": "Speaker 2"}]
    ps = meaning.passages(segs)
    assert [len(p["text"].split()) for p in ps] == [100, 75]
    assert ps[0]["t0"] == 0.0 and ps[0]["speaker"] == "Me" and ps[0]["text"].endswith("b9")
    assert ps[1]["t0"] == 0.0 and ps[1]["speaker"] == "Me" and ps[1]["text"].startswith("a75 ")  # a quarter overlaps
    assert ps[1]["text"].endswith("b59")
    assert meaning.passages([]) == []


def test_index_catches_up_forgets_and_ranks(tmp_path):
    a = make(tmp_path, "Plata", 3, ["El presupuesto no alcanza.", "Hay que pedir más dinero."])
    b = make(tmp_path, "Resa", 4, ["Vi bokar flyg till Kreta.", "Resa i augusti."], speaker_names={"Speaker 1": "Ana"})
    make(tmp_path, "Knä", 5, ["Mitt knä gör ont, läkare på måndag."])
    idx = meaning.Index(tmp_path)
    try:
        assert len(idx.stale()) == 3
        loads = []
        assert idx.refresh(lambda: loads.append(1) or FakeEmbedder()) == 0 and loads == [1] and idx.stale() == []
        assert idx.refresh(lambda: loads.append(1) or FakeEmbedder()) == 0 and loads == [1]  # nothing new: no model load
        top = idx.search("the trip in summer", FakeEmbedder(), limit=2)
        assert [r["title"] for r in top] == ["Resa", top[1]["title"]] and len(top) == 2
        assert top[0]["found_by"] == "meaning" and top[0]["score"] > top[1]["score"]
        assert top[0]["hits"][0]["at"] == "00:00:00" and "Kreta" in top[0]["hits"][0]["text"]
        assert idx.search("money", FakeEmbedder(), keep=lambda m: m["title"] != "Plata")[0]["title"] != "Plata"
        sessions.delete(b)
        (a / "transcript.json").write_text(json.dumps({"segments": [{"t0": 0, "t1": 1, "text": "flyg resa", "speaker": "Me"}]}))
        os.utime(a / "transcript.json", (1, 1))
        assert idx.stale() == [a.name]
        idx.refresh(FakeEmbedder())
        assert idx.search("trip", FakeEmbedder(), limit=1)[0]["title"] == "Plata"  # re-read, and Resa is gone
        assert "Resa" not in [r["title"] for r in idx.search("trip", FakeEmbedder())]
    finally:
        idx.close()


def test_index_time_budget(tmp_path):
    for day in (3, 4, 5):
        make(tmp_path, f"Call {day}", day, ["presupuesto"])
    ticks = iter(range(100))
    idx = meaning.Index(tmp_path)
    try:
        assert idx.refresh(FakeEmbedder(), budget_s=2.5, clock=lambda: next(ticks)) == 1
        assert len(idx.stale()) == 1
    finally:
        idx.close()


def test_broken_index_is_rebuilt(tmp_path):
    (tmp_path / meaning.FILE).write_bytes(b"not a database at all" * 100)
    idx = meaning.Index(tmp_path)
    idx.close()
    idx = meaning.Index(tmp_path)  # opens the rebuilt one as it is
    idx.close()


def test_claude_search_falls_back_to_meaning_after_a_miss(tmp_path, ready):
    make(tmp_path, "Plata", 3, ["El presupuesto no alcanza, hay que pedir más dinero."])
    make(tmp_path, "Resa", 4, ["Vi bokar flyg till Kreta i augusti."])
    make(tmp_path, "prueba resa", 5, ["flyg resa viaje"])  # Ecoscribe's own tests stay out
    assert not meaning.switched_on(tmp_path, "auto")
    r, text = search(tmp_path, text="our trip")  # no call has "our": the miss switches meaning on, and it answers
    rows = json.loads(text)
    assert rows[0]["title"] == "Resa" and rows[0]["found_by"] == "meaning" and "prueba resa" not in text
    assert meaning.misses(tmp_path) == 1
    r, text = search(tmp_path, text="dinero")  # found by its words: no meaning search, no miss
    assert json.loads(text)[0]["title"] == "Plata" and "found_by" not in text and meaning.misses(tmp_path) == 1
    r, text = search(tmp_path, text="money worries", by_meaning=True)
    assert json.loads(text)[0]["title"] == "Plata"
    assert json.loads(search(tmp_path, text="trip", by_meaning=True, since="2026-10-04")[1])[0]["title"] == "Resa"


def test_by_meaning_says_why_it_cannot(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "MEANING", {"mode": "auto", "models_root": str(tmp_path / "models")})
    make(tmp_path, "Plata", 3, ["presupuesto"])
    r, text = search(tmp_path, text="money", by_meaning=True)
    assert r["isError"] and "off" in text
    monkeypatch.setattr(mcp_server, "MEANING", {"mode": "on", "models_root": str(tmp_path / "models")})
    r, text = search(tmp_path, text="money", by_meaning=True)
    assert r["isError"] and "getting ready" in text


def test_tool_list_offers_by_meaning(tmp_path):
    (tool,) = [t for t in mcp_server.TOOLS if t["name"] == "search_meetings"]
    assert tool["inputSchema"]["properties"]["by_meaning"]["type"] == "boolean"


class Proc:
    def __init__(self):
        self.rc = None

    def poll(self):
        return self.rc


def test_sweeper_waits_for_a_miss_and_a_quiet_moment(tmp_path, monkeypatch):
    cfg = config.Config()
    now = [1000.0]
    spawned = []
    sw = meaning.Sweeper(cfg, tmp_path, lambda args: spawned.append(args) or Proc(), clock=lambda: now[0])
    make(tmp_path, "Plata", 3, ["presupuesto"])
    assert not sw.tick(set()) and spawned == []  # auto, no miss yet
    meaning.log_miss(tmp_path)
    now[0] += meaning.EVERY_S
    assert not sw.tick({"some/meeting"})  # something records: later
    assert sw.tick(set()) and spawned == [["--meaning-index"]]  # the model is missing: the worker fetches it
    now[0] += meaning.EVERY_S
    assert not sw.tick(set())  # still running
    sw.proc.rc = 0
    monkeypatch.setattr(meaning, "model_ready", lambda models_root="": True)
    idx = meaning.Index(tmp_path)
    idx.refresh(FakeEmbedder())
    idx.close()
    now[0] += meaning.EVERY_S
    assert not sw.tick(set()) and len(spawned) == 1  # model there, every call indexed: nothing to do
    make(tmp_path, "Resa", 4, ["flyg"])
    now[0] += meaning.EVERY_S
    assert sw.tick(set()) and len(spawned) == 2  # a new call
    cfg.search.meaning = "off"
    sw.proc.rc = 0
    now[0] += meaning.EVERY_S
    assert not sw.tick(set()) and len(spawned) == 2


def _real_model() -> Path | None:
    d = os.environ.get("ECOSCRIBE_MEANING_MODEL")
    if d and (Path(d) / meaning.ONNX).is_file():
        return Path(d)
    return meaning.model_dir() if meaning.model_ready() else None


@pytest.mark.skipif(_real_model() is None, reason="the meaning model is not on this machine")
def test_real_model_finds_a_topic_across_languages(tmp_path):
    emb = meaning.Embedder(_real_model())
    make(tmp_path, "A", 3, ["El presupuesto del proyecto se ha quedado corto, hay que pedir más dinero al comité."])
    make(tmp_path, "B", 4, ["Τον Αύγουστο θα πάμε διακοπές στην Κρήτη με τους φίλους μου."])
    make(tmp_path, "C", 5, ["Mitt knä gör ont sedan klättringen, fysioterapeuten sa vila en vecka."])
    make(tmp_path, "D", 6, ["The landlord said the rent goes up five percent from January."])
    idx = meaning.Index(tmp_path)
    try:
        idx.refresh(emb)
        for q, want in (("the project ran out of money", "A"), ("summer holiday on a Greek island", "B"),
                        ("injury from climbing", "C"), ("el alquiler sube", "D")):
            assert idx.search(q, emb, limit=1)[0]["title"] == want, q
    finally:
        idx.close()
