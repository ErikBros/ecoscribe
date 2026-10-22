"""The week's own to-dos from call summaries, by person (dictado-xuu). Invented text only."""
import json
from datetime import date, datetime

import pytest

from ecoscribe import meetui, sessions, todos
from ecoscribe.config import Config
from ecoscribe.window import Api

MON = date(2026, 10, 19)  # a Monday


def _cfg(enabled=True):
    c = Config()
    c.summaries.enabled = enabled
    return c


def _call(root, title, when, todo_list, app="signal", **meta):
    d = sessions.create(title, "en", "meeting", root, now=when)
    sessions.write_meta(d, status="done", app=app, summary="done", **meta)
    (d / "summary.json").write_text(json.dumps({"kind": "family or friends", "todos": todo_list}), encoding="utf-8")
    return d


def T(text, who=None, checked=True):
    i = {"text": text, "at": "00:01:10", "quote": "words from the call", "checked": checked}
    if who:
        i["who"] = who
    return i


def test_person_is_the_guests_else_the_named_speakers_else_the_title():
    assert todos.person_of({"calendar": {"attendees": ["Ana"]}, "speaker_names": {"Speaker 1": "Bo"}}) == "Ana"
    assert todos.person_of({"speaker_names": {"Speaker 2": "Leo", "Speaker 1": "Mia"}}) == "Leo and Mia"
    assert todos.person_of({"speaker_names": {"Me": "Sam"}, "title": "Lesson 3"}, me="Sam") == "Lesson 3"
    assert todos.person_of({"calendar": {"attendees": ["A1", "B2", "C3", "D4"]}}) == "A1, B2 and 2 more"
    assert todos.person_of({}) == "A call"


def test_week_takes_your_own_todos_of_personal_calls_in_that_week_grouped(tmp_path):
    root = tmp_path / "t"
    _call(root, "Catch-up", datetime(2026, 10, 20, 18, 0), [T("Book the table"), T("Send the photos", who="Ana")],
          speaker_names={"Speaker 1": "Ana"})
    _call(root, "Catch-up again", datetime(2026, 10, 23, 18, 0), [T("Buy the tickets", checked=False)],
          speaker_names={"Speaker 1": "Ana"})
    _call(root, "Lesson", datetime(2026, 10, 25, 23, 0), [T("Read chapter 4")])
    _call(root, "Last week", datetime(2026, 10, 18, 22, 0), [T("Too early")])
    _call(root, "Next week", datetime(2026, 10, 26, 0, 30), [T("Too late")])
    _call(root, "Work sync", datetime(2026, 10, 21, 9, 0), [T("A work to-do")], app="ms-teams")
    w = todos.week(root, _cfg(), date(2026, 10, 22))  # any day of the week finds its Monday
    assert (w["start"], w["end"]) == ("2026-10-19", "2026-10-25")
    assert [g["person"] for g in w["people"]] == ["Ana", "Lesson"]
    ana = w["people"][0]["items"]
    assert [i["text"] for i in ana] == ["Book the table", "Buy the tickets"]  # someone else's to-do left out
    assert ana[1]["checked"] is False and ana[0]["day"] == "2026-10-20"
    assert (w["count"], w["open"], w["calls"]) == (3, 3, 3)


def test_a_tick_is_kept_and_counted(tmp_path):
    root, folder = tmp_path / "t", tmp_path / "data" / "todos"
    d = _call(root, "Catch-up", datetime(2026, 10, 20, 18, 0), [T("Book the table"), T("Buy the tickets")])
    todos.set_done(folder, todos.key(d.name, "Book  the TABLE"), True)
    w = todos.week(root, _cfg(), MON, folder)
    assert [i["done"] for i in w["people"][0]["items"]] == [True, False] and w["open"] == 1
    todos.set_done(folder, todos.key(d.name, "Book the table"), False)
    assert todos.week(root, _cfg(), MON, folder)["open"] == 2


def test_a_broken_summary_is_skipped(tmp_path):
    root = tmp_path / "t"
    d = _call(root, "Catch-up", datetime(2026, 10, 20, 18, 0), [T("Book the table")])
    (d / "summary.json").write_text("{half", encoding="utf-8")
    assert todos.week(root, _cfg(), MON)["count"] == 0


@pytest.mark.parametrize("now, week, since", [
    (datetime(2026, 10, 25, 17, 59), "2026-10-12", datetime(2026, 10, 18, 18, 0)),  # Sunday before 18:00: last week
    (datetime(2026, 10, 25, 18, 0), "2026-10-19", datetime(2026, 10, 25, 18, 0)),
    (datetime(2026, 10, 27, 9, 0), "2026-10-19", datetime(2026, 10, 25, 18, 0)),  # Tuesday: the week just gone
])
def test_due_is_the_week_that_ended_on_the_last_sunday_evening(now, week, since):
    start, at = todos.due(now)
    assert start.isoformat() == week and at == since


def test_collector_writes_the_week_once_on_sunday_evening_with_one_notice(tmp_path):
    root, folder = tmp_path / "t", tmp_path / "data" / "todos"
    _call(root, "Catch-up", datetime(2026, 10, 20, 18, 0), [T("Book the table")], speaker_names={"Speaker 1": "Ana"})
    t = [datetime(2026, 10, 25, 19, 0).timestamp()]
    c = todos.Collector(_cfg(), root, folder, clock=lambda: t[0])
    w = c.tick()
    assert w and w["count"] == 1 and todos.count_line(w) == "1 to-do from 1 call"
    md = (folder / "2026-10-19.md").read_text(encoding="utf-8")
    assert "## Ana" in md and "- [ ] Book the table (Tue, Catch-up)" in md
    assert json.loads((folder / "2026-10-19.json").read_text(encoding="utf-8"))["count"] == 1
    t[0] += todos.EVERY_S
    assert c.tick() is None  # written already: no second notice


def test_collector_waits_between_looks_and_stays_quiet_when_late_or_off(tmp_path):
    root, folder = tmp_path / "t", tmp_path / "data" / "todos"
    _call(root, "Catch-up", datetime(2026, 10, 20, 18, 0), [T("Book the table")])
    t = [datetime(2026, 10, 28, 9, 0).timestamp()]  # Wednesday: more than 36 h late
    c = todos.Collector(_cfg(), root, folder, clock=lambda: t[0])
    assert c.tick() is None and (folder / "2026-10-19.md").exists()  # written, no notice
    off = todos.Collector(_cfg(enabled=False), root, tmp_path / "other", clock=lambda: t[0])
    assert off.tick() is None and not (tmp_path / "other").exists()


def test_the_notice_says_how_many_and_opens_home():
    p = meetui.Prompt("todos", "7 to-dos from 4 calls", None, 0.0)
    assert p.title == "Your to-dos for the week" and p.question == "7 to-dos from 4 calls"
    assert ("Open", "todos") in p.buttons and p.timeout_choice == "hide"


def test_window_api_week_and_tick(tmp_path):
    root = tmp_path / "transcripts"
    cfg_path = tmp_path / "cfg" / "config.toml"
    cfg_path.parent.mkdir()
    cfg_path.write_text(f'[transcribe]\nroot = "{root.as_posix()}"\n[summaries]\nenabled = true\n', encoding="utf-8")
    api = Api(data_dir=tmp_path / "data", config_path=cfg_path, copy=lambda s: None, signal_reload=lambda: True)
    (tmp_path / "data").mkdir()
    _call(root, "Catch-up", datetime.now(), [T("Book the table")])
    w = api.week_todos()
    assert w["enabled"] is True and w["back"] == 0 and w["count"] == 1
    k = w["people"][0]["items"][0]["key"]
    assert api.todo_done(k, True)["ok"] and api.week_todos()["open"] == 0
    assert api.week_todos(1)["count"] == 0
    assert not api.todo_done("", True)["ok"]
