"""Meetings > Apply the Replace list to a saved transcript, with one Undo (dictado-9lo). Invented text only."""
import json

from ecoscribe import meetings, sessions
from ecoscribe.text import replace_counted
from ecoscribe.window import REPLACE_BACKUP
from tests.test_window_sessions import env, make  # noqa: F401  (env is a fixture)

SEGS = [{"t0": 0, "t1": 2, "text": "Open a poll request for the eco scribe build.", "speaker": "Me"},
        {"t0": 3, "t1": 5, "text": "The Poll  Request is ready, and so is Ecoscribe.", "speaker": "Others"},
        {"t0": 6, "t1": 8, "text": "Nothing to change here.", "speaker": "Others"}]
PAIRS = [{"heard": "poll request", "write": "pull request"}, {"heard": "eco scribe", "write": "Ecoscribe"}]


def segs_of(d):
    return json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]


def setup(env, pairs=PAIRS, **kw):
    api, root, *_ = env
    if pairs is not None:
        assert api.save_settings({"replacements": pairs})["ok"]
    d = make(root, "Planning", 1, segs=[dict(s) for s in SEGS], **kw)
    (d / "audio" / "mic.flac").write_bytes(b"not really audio")
    return api, d


def test_counts_only_real_changes():
    texts, counts = replace_counted(["a poll request", "Ecoscribe and eco scribe", ""],
                                    {"poll request": "pull request", "eco scribe": "Ecoscribe", "ecoscribe": "Ecoscribe"})
    assert texts == ["a pull request", "Ecoscribe and Ecoscribe", ""]
    assert counts == {"poll request": 1, "eco scribe": 1}  # "Ecoscribe" already written that way: not a change


def test_preview_counts_the_places_per_pair(env):
    api, d = setup(env)
    p = api.replace_preview(d.name)
    assert p["ok"] and p["places"] == 3 and not p["empty"] and not p["undo"]
    assert p["pairs"] == [{"heard": "poll request", "write": "pull request", "n": 2},
                          {"heard": "eco scribe", "write": "Ecoscribe", "n": 1}]
    assert segs_of(d) == SEGS  # a preview writes nothing


def test_apply_rewrites_the_transcript_and_exports_never_the_audio(env):
    api, d = setup(env)
    audio = (d / "audio" / "mic.flac").read_bytes()
    out = api.apply_replacements(d.name)
    assert out == {"ok": True, "places": 3}
    assert [s["text"] for s in segs_of(d)] == ["Open a pull request for the Ecoscribe build.",
                                               "The pull request is ready, and so is Ecoscribe.",
                                               "Nothing to change here."]
    assert [s["speaker"] for s in segs_of(d)] == ["Me", "Others", "Others"] and segs_of(d)[1]["t0"] == 3
    assert "pull request" in (d / "transcript.txt").read_text(encoding="utf-8")
    assert "poll request" not in (d / "transcript.md").read_text(encoding="utf-8").lower()
    assert "Ecoscribe build" in (d / "transcript.srt").read_text(encoding="utf-8")
    assert json.loads((d / REPLACE_BACKUP).read_text(encoding="utf-8"))["segments"] == SEGS
    assert (d / "audio" / "mic.flac").read_bytes() == audio
    assert api.get_session(d.name)["segments"][0]["text"].startswith("Open a pull request")
    p = api.replace_preview(d.name)
    assert p["places"] == 0 and p["undo"]


def test_undo_puts_the_transcript_back(env):
    api, d = setup(env)
    before = (d / "transcript.json").read_bytes()
    api.apply_replacements(d.name)
    assert api.undo_replacements(d.name) == {"ok": True}
    assert (d / "transcript.json").read_bytes() == before and not (d / REPLACE_BACKUP).exists()
    assert "poll request" in (d / "transcript.txt").read_text(encoding="utf-8")
    assert not api.undo_replacements(d.name)["ok"]  # one step only
    assert api.replace_preview(d.name)["places"] == 3


def test_undo_refuses_after_the_transcript_changed(env):
    api, d = setup(env)
    api.apply_replacements(d.name)
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    tr["segments"][2]["speaker"] = "Me"  # e.g. two speakers merged since
    sessions._write_json(d / "transcript.json", tr)
    out = api.undo_replacements(d.name)
    assert not out["ok"] and "changed" in out["error"]
    assert segs_of(d)[2]["speaker"] == "Me"


def test_an_empty_list_changes_nothing(env):
    api, d = setup(env, pairs=None)
    p = api.replace_preview(d.name)
    assert p["ok"] and p["places"] == 0 and p["empty"] and p["pairs"] == []
    out = api.apply_replacements(d.name)
    assert not out["ok"] and "empty" in out["error"]
    assert segs_of(d) == SEGS and not (d / REPLACE_BACKUP).exists()


def test_nothing_to_replace_writes_nothing(env):
    api, d = setup(env, pairs=[{"heard": "flux capacitor", "write": "Flux Capacitor"}])
    assert api.apply_replacements(d.name) == {"ok": True, "places": 0}
    assert not (d / REPLACE_BACKUP).exists() and not (d / "transcript.txt").exists()


def test_refuses_a_transcript_still_being_written(env):
    api, root, _, _, data = env
    api.save_settings({"replacements": PAIRS})
    running = make(root, "Running", 2, status="running", segs=[dict(s) for s in SEGS])
    queued = make(root, "Queued", 3, segs=[dict(s) for s in SEGS])
    speakers = make(root, "Speakers", 4, segs=[dict(s) for s in SEGS])
    sessions.write_meta(speakers, speakers="running")  # the speakers pass rewrites transcript.json
    (data / meetings.STATE).write_text(json.dumps({"meeting": None, "job": None, "queue": [str(queued)]}), encoding="utf-8")
    for d in (running, queued, speakers):
        for call in (api.replace_preview, api.apply_replacements, api.undo_replacements):
            out = call(d.name)
            assert not out["ok"] and "still being written" in out["error"], (d.name, call.__name__)
        assert segs_of(d) == SEGS and not (d / REPLACE_BACKUP).exists()
