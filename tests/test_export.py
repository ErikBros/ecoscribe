import json
import re

from ecoscribe import export

META = {"title": "Planering", "lang": "sv", "created": "2026-10-02T14:05:00", "duration_s": 3725.0,
        "source": "meeting", "app": "msteams"}
SEGS = [
    {"t0": 0.0, "t1": 2.5, "text": " Hej allihopa.", "speaker": "Me"},
    {"t0": 3.0, "t1": 6.0, "text": "Tack.", "speaker": "Others"},
    {"t0": 3661.5, "t1": 3663.25, "text": "Hejdå.", "speaker": None},
]


def test_txt_one_line_per_turn():
    assert export.to_txt(SEGS) == "Hej allihopa.\nTack.\nHejdå.\n"


def test_srt_timestamps():
    srt = export.to_srt(SEGS)
    assert "01:01:01,500 --> 01:01:03,250" in srt
    assert "00:00:00,000 --> 00:00:02,500" in srt


def test_srt_is_parseable():
    blocks = export.to_srt(SEGS).strip("\n").split("\n\n")
    assert len(blocks) == 3
    for i, b in enumerate(blocks, 1):
        lines = b.split("\n")
        assert lines[0] == str(i)
        assert re.fullmatch(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", lines[1])
        assert lines[2].strip()
    assert export.to_srt(SEGS).endswith("\n\n")


def test_md_has_speaker_labels():
    md = export.to_md(META, SEGS)
    assert md.startswith("# Planering\n")
    assert "**[00:00:00] Me:** Hej allihopa." in md
    assert "**[00:00:03] Others:** Tack." in md
    assert "**[01:01:01]** Hejdå." in md
    assert "2026-10-02 14:05 · Swedish · 1:02:05" in md
    assert "\u2014" not in md


def test_for_claude_header():
    out = export.for_claude(META, SEGS)
    lines = out.split("\n")
    assert lines[0] == "Transcript: Planering"
    assert "Date: 2026-10-02 14:05" in lines
    assert "App: msteams" in lines
    assert "Duration: 1:02:05" in lines
    assert "Language: Swedish" in lines
    assert "# Planering" not in out
    assert "**[00:00:00] Me:** Hej allihopa." in out


def test_write_all(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps(META), encoding="utf-8")
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": SEGS, "lang": "sv"}), encoding="utf-8")
    written = export.write_all(tmp_path)
    assert {p.name for p in written} == {"transcript.txt", "transcript.md", "transcript.srt"}
    assert (tmp_path / "transcript.md").read_text(encoding="utf-8").startswith("# Planering")


CHOPPED = [  # invented: how Whisper chops one sentence into timestamped lines
    {"t0": 29.0, "t1": 30.5, "text": "so the", "speaker": "Others"},
    {"t0": 31.0, "t1": 33.0, "text": "blue bicycle", "speaker": "Others"},
    {"t0": 34.0, "t1": 36.0, "text": "is mine", "speaker": "Others"},
    {"t0": 38.0, "t1": 39.5, "text": "the train leaves", "speaker": "Me"},
    {"t0": 40.0, "t1": 41.0, "text": "at nine tomorrow", "speaker": "Me"},
    {"t0": 50.0, "t1": 52.0, "text": "okay", "speaker": "Me"},  # 9 s later: a new turn
]


def test_turns_join_same_speaker_lines_close_together():
    t = export.turns(CHOPPED)
    assert [(x["t0"], x["t1"], x["speaker"], x["text"]) for x in t] == [
        (29.0, 36.0, "Others", "so the blue bicycle is mine"),
        (38.0, 41.0, "Me", "the train leaves at nine tomorrow"),
        (50.0, 52.0, "Me", "okay")]
    assert CHOPPED[0]["text"] == "so the"  # the input is not changed


def test_turns_cap_a_monologue():
    segs = [{"t0": i * 10.0, "t1": i * 10.0 + 9.5, "text": f"s{i}", "speaker": None} for i in range(20)]
    t = export.turns(segs)
    assert len(t) > 1 and all(x["t1"] - x["t0"] <= export.TURN_MAX_S for x in t)


def test_md_and_txt_read_in_turns_srt_keeps_every_line():
    md = export.to_md(META, CHOPPED)
    assert "**[00:00:29] Others:** so the blue bicycle is mine" in md
    assert export.to_txt(CHOPPED).count("\n") == 3
    assert export.to_srt(CHOPPED).count("-->") == 6


def test_your_name_replaces_me_but_a_rename_wins():
    segs = [{"t0": 0.0, "t1": 1.0, "text": "Hello there.", "speaker": "Me"}]
    assert "Alex Doe:** Hello there." in export.to_md(META, segs, me="Alex Doe")
    assert "Alex Doe:** Hello there." in export.for_claude(META, segs, me="Alex Doe")
    assert "Me:** Hello there." in export.to_md(META, segs)  # no name set: "Me" as before
    renamed = {**META, "speaker_names": {"Me": "Host"}}
    assert "Host:** Hello there." in export.to_md(renamed, segs, me="Alex Doe")
