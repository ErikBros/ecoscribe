"""Meetings > Share in Slack (dictado-pnuy): the transcript .md on the clipboard as a file, named with the
meeting, who spoke and how long; no notes, no summary; Slack opens. Invented demo text only."""
import json
from datetime import datetime

from ecoscribe import export, sessions
from ecoscribe.window import SLACK_APP, SLACK_WEB, Api

SEGS = [{"t0": 0, "t1": 2, "text": "Shall we start with the demo?", "speaker": "Speaker 1"},
        {"t0": 3, "t1": 5, "text": "Yes, after lunch works.", "speaker": "Me"},
        {"t0": 6, "t1": 8, "text": "I'll bring the slides.", "speaker": "Speaker 2"}]


def test_the_name_is_meeting_people_and_minutes():
    meta = {"title": "Weekly planning", "duration_s": 3480, "speaker_names": {"Speaker 1": "Ana"}}
    assert export.share_name(meta, SEGS, "Sam") == "Weekly planning · Ana, Sam · 58 min.md"


def test_unnamed_voices_fall_back_to_the_invite_and_hours_read_as_hours():
    meta = {"title": "Retro", "recorded_s": 4380, "calendar": {"attendees": ["Ana", "Bo"]}}
    assert export.share_name(meta, SEGS, "") == "Retro · Ana, Bo · 1 h 13 min.md"
    assert export.share_name({"duration_s": 7200}, [], "") == "Transcript · 2 h.md"


def test_characters_windows_refuses_are_dropped_and_long_names_cut():
    name = export.share_name({"title": 'Q3: plan/budget "v2"?', "duration_s": 60}, [], "")
    assert name == "Q3 plan budget v2 · 1 min.md"
    assert len(export.share_name({"title": "x" * 400}, [], "")) <= export.SHARE_MAX + 3


def _api(tmp_path, opened, files, fail_app=False):
    root = tmp_path / "transcripts"
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[transcribe]\nroot = "{root.as_posix()}"\n[meetings]\nmy_name = "Sam"\n', encoding="utf-8")

    def open_url(u):
        if fail_app and u == SLACK_APP:
            raise OSError("no handler")
        opened.append(u)
    (tmp_path / "data").mkdir()
    return Api(data_dir=tmp_path / "data", config_path=cfg, copy=lambda t: None, open_url=open_url,
               copy_files=files.extend), root


def _meeting(root, segs=SEGS):
    d = sessions.create("Weekly planning", "en", "meeting", root, now=datetime(2026, 10, 5, 9, 15))
    sessions.write_meta(d, status="done", duration_s=2520.0, speaker_names={"Speaker 1": "Ana", "Speaker 2": "Bo"})
    (d / "transcript.json").write_text(json.dumps({"segments": segs}), encoding="utf-8")
    (d / export.NOTES).write_text("private: ask about the budget", encoding="utf-8")
    return d


def test_share_copies_the_md_as_a_file_and_opens_slack(tmp_path):
    opened, files = [], []
    api, root = _api(tmp_path, opened, files)
    d = _meeting(root)
    r = api.share_slack(d.name)
    assert r["ok"] and r["file"] == "Weekly planning · Ana, Sam, Bo · 42 min.md" and r["people"] == ["Ana", "Sam", "Bo"]
    assert len(files) == 1 and files[0].name == r["file"]
    text = files[0].read_text(encoding="utf-8")
    assert "**[00:00:00] Ana:** Shall we start with the demo?" in text and "Sam:" in text
    assert "private" not in text and "My notes" not in text  # the user's notes stay theirs
    assert opened == [SLACK_APP]
    api.share_slack(d.name)
    assert len(list((tmp_path / "data" / "share").glob("*.md"))) == 1  # only the last shared file is kept


def test_no_slack_app_opens_slack_in_the_browser(tmp_path):
    opened, files = [], []
    api, root = _api(tmp_path, opened, files, fail_app=True)
    assert api.share_slack(_meeting(root).name)["ok"] and opened == [SLACK_WEB]


def test_nothing_to_share_before_the_transcript_exists(tmp_path):
    opened, files = [], []
    api, root = _api(tmp_path, opened, files)
    d = sessions.create("Live", "en", "meeting", root, now=datetime(2026, 10, 5, 9, 15))
    r = api.share_slack(d.name)
    assert not r["ok"] and "no transcript" in r["error"] and not files and not opened
