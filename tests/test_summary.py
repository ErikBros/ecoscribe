"""Call summaries (dictado-crf) and their quote check (dictado-xu2). Invented text only."""
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

from ecoscribe import claude_cli, mcp_server, sessions, summary
from ecoscribe.config import Config

SEGS = [
    {"t0": 5.0, "t1": 9.0, "text": "Hola, ¿qué tal la semana?", "speaker": "Others"},
    {"t0": 60.0, "t1": 66.0, "text": "Quedamos el sábado a las diez en la estación del norte.", "speaker": "Others"},
    {"t0": 70.0, "t1": 75.0, "text": "Vale, yo compro las entradas del museo esta noche.", "speaker": "Me"},
    {"t0": 400.0, "t1": 405.0, "text": "Θα φέρω το βιβλίο την Τρίτη.", "speaker": "Others"},
]

ANSWER = {"kind": "family or friends", "summary": "Plans for Saturday.",
          "decisions": [{"text": "Meet Saturday at ten", "at": "00:01:00", "quote": "el sábado a las diez en la estación"}],
          "todos": [{"text": "Buy the museum tickets tonight", "at": "00:01:10", "quote": "yo compro las entradas del museo"},
                    {"text": "Book a table", "at": "00:02:00", "quote": "reservo una mesa para cuatro personas"}],
          "open_questions": []}


def _cfg(**summaries):
    c = Config()
    c.summaries.enabled = True
    for k, v in summaries.items():
        setattr(c.summaries, k, v)
    return c


def _session(tmp_path, title="Call", app="signal", created=None, **meta) -> Path:
    d = sessions.create(title, "es", "meeting", tmp_path, now=created or datetime.now())
    sessions.write_meta(d, status="done", app=app, duration_s=420, **meta)
    (d / "transcript.json").write_text(json.dumps({"segments": SEGS}, ensure_ascii=False), encoding="utf-8")
    return d


def test_fold_drops_case_accents_and_punctuation_also_in_greek():
    assert summary._fold("¿Qué TAL, Señor?") == "que tal senor"
    assert summary._fold("Θα φέρω το βιβλίο") == summary._fold("θα φερω το βιβλιο")


def test_a_quote_is_found_only_near_its_time():
    assert summary.found("las entradas del museo", "00:01:10", SEGS)
    assert not summary.found("las entradas del museo", "00:30:00", SEGS)
    assert summary.found("las entradas del museo", "sometime", SEGS)  # unreadable time: looked for anywhere


def test_whisper_misspellings_still_match_but_made_up_lines_do_not():
    assert summary.found("yo compro las entrdas del musseo", "00:01:10", SEGS)
    assert summary.found("θα φερω το βιβλιο την τριτη", "00:06:41", SEGS)  # no accents, still Greek
    assert not summary.found("reservo una mesa para cuatro", "00:01:10", SEGS)
    assert not summary.found("vale", "00:01:10", SEGS)  # one word proves nothing


def test_check_marks_items_and_counts():
    r = summary.check(json.loads(json.dumps(ANSWER)), SEGS)
    assert (r["checked"], r["total"]) == (2, 3)
    assert [i["checked"] for i in r["todos"]] == [True, False]


def test_parse_takes_json_out_of_a_code_fence():
    assert summary.parse("```json\n" + json.dumps(ANSWER) + "\n```")["kind"] == "family or friends"
    with pytest.raises(ValueError):
        summary.parse("no json here")


def test_summarize_writes_json_and_markdown_with_the_check(tmp_path):
    d = _session(tmp_path, title="Weekend plans")
    asked = {}

    def ask(text, system, model, timeout, command):
        asked.update(text=text, model=model)
        return json.dumps(ANSWER, ensure_ascii=False)
    summary.summarize(d, _cfg(), ask=ask)
    assert "estación del norte" in asked["text"] and asked["model"] == "sonnet"
    md = (d / summary.MD).read_text(encoding="utf-8")
    assert "2 of 3 items checked against the call." in md
    assert "Book a table [00:02:00]" in md and md.count("(not found in the call)") == 1
    assert json.loads((d / summary.JSON).read_text(encoding="utf-8"))["total"] == 3


def test_only_finished_recent_personal_calls_are_wanted(tmp_path):
    cfg, now = _cfg(), time.time()
    assert summary.wanted(sessions.read_meta(_session(tmp_path)), cfg, now)
    assert not summary.wanted(sessions.read_meta(_session(tmp_path, app="msteams")), cfg, now)  # a work call
    assert not summary.wanted(sessions.read_meta(_session(tmp_path, speakers="pending")), cfg, now)
    assert not summary.wanted(sessions.read_meta(_session(tmp_path, summary="done")), cfg, now)
    assert not summary.wanted(sessions.read_meta(_session(tmp_path, summary="failed", summary_tries=2)), cfg, now)
    old = _session(tmp_path, created=datetime(2020, 1, 1))
    assert not summary.wanted(sessions.read_meta(old), cfg, now)


class _Proc:
    def __init__(self):
        self.rc = None
        self.pid = 4242

    def poll(self):
        return self.rc


def test_sweeper_runs_one_summary_at_a_time_and_reports_it(tmp_path):
    a, b = _session(tmp_path, title="One"), _session(tmp_path, title="Two")
    started, clock = [], [1000.0]

    def spawn(args):
        started.append(Path(args[1]))
        return _Proc()
    sw = summary.Sweeper(_cfg(), tmp_path, spawn, clock=lambda: clock[0])
    assert sw.tick() == [] and len(started) == 1
    clock[0] += 3600
    assert sw.tick() == [] and len(started) == 1  # one worker at a time
    first = started[0]
    assert sessions.read_meta(first)["summary"] == "running"
    sessions.write_meta(first, summary="done")
    sw.proc.rc = 0
    assert sw.tick() == [first]
    assert set(started) == {a, b}


def test_sweeper_skips_busy_sessions_and_does_nothing_when_off(tmp_path):
    d = _session(tmp_path)
    started = []
    spawn = lambda args: started.append(args) or _Proc()  # noqa: E731
    summary.Sweeper(_cfg(enabled=False), tmp_path, spawn).tick()
    summary.Sweeper(_cfg(), tmp_path, spawn).tick(busy={str(d)})
    assert started == []


def test_a_worker_that_died_counts_as_a_failed_try(tmp_path):
    d = _session(tmp_path)
    sw = summary.Sweeper(_cfg(), tmp_path, lambda args: _Proc(), clock=lambda: 1000.0)
    sw.tick()
    sw.proc.rc = 1
    sw.tick()
    m = sessions.read_meta(d)
    assert m["summary"] == "failed" and m["summary_tries"] == 1


def _run(stdout: dict | str, rc=0):
    def run(cmd, input, capture_output, timeout, **kw):
        run.cmd, run.input = cmd, input
        out = stdout if isinstance(stdout, str) else json.dumps(stdout)
        return subprocess.CompletedProcess(cmd, rc, out.encode(), b"boom")
    return run


def test_claude_cli_sends_text_on_stdin_with_lean_flags():
    run = _run({"result": "ok", "is_error": False})
    assert claude_cli.ask("texto", "be short", model="haiku", command=["claude"], run=run) == "ok"
    assert run.cmd[:2] == ["claude", "-p"] and "--strict-mcp-config" in run.cmd
    assert run.cmd[-4:] == ["--model", "haiku", "--system-prompt", "be short"] and run.input == "texto".encode()


def test_claude_cli_errors_say_why():
    with pytest.raises(claude_cli.ClaudeError, match="Not logged in"):
        claude_cli.ask("x", "y", command=["claude"], run=_run({"result": "Not logged in", "is_error": True}))
    with pytest.raises(claude_cli.ClaudeError, match="boom"):
        claude_cli.ask("x", "y", command=["claude"], run=_run("", rc=1))

    def missing(*a, **k):
        raise FileNotFoundError(2, "no such file", "wsl.exe")
    with pytest.raises(claude_cli.ClaudeError, match="isn't reachable"):
        claude_cli.ask("x", "y", command=["wsl.exe"], run=missing)


def test_the_claude_app_gets_the_summary_first(tmp_path):
    d = _session(tmp_path, title="Weekend plans")
    assert mcp_server.list_meetings(tmp_path)[0]["summary"] is False
    (d / summary.MD).write_text("# Summary: Weekend plans\n\n1 of 1 items checked against the call.", encoding="utf-8")
    out = mcp_server.read_meeting(tmp_path, d.name)
    assert out.startswith("# Summary: Weekend plans") and "estación del norte" in out
    assert mcp_server.list_meetings(tmp_path)[0]["summary"] is True
