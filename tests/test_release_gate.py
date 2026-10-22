"""The release gate (tools/release_gate.py, dictado-n5r): nothing is installed while a call records or a
meeting is processed, or without disk room; a crashed meetings.json doesn't block."""
import importlib.util
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release_gate", REPO / "tools" / "release_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def _meetings(tmp_path, **st):
    p = tmp_path / "meetings.json"
    p.write_text(json.dumps({"meeting": None, "job": None, "queue": [], "next_meeting": None, **st}), encoding="utf-8")
    return p


def test_idle_meetings_pass(tmp_path):
    assert gate.check_no_meeting(_meetings(tmp_path))[0]
    assert gate.check_no_meeting(tmp_path / "missing.json")[0]


def test_a_live_call_or_a_running_job_blocks(tmp_path):
    alive = lambda pid: pid == 42  # noqa: E731
    ok, why = gate.check_no_meeting(_meetings(tmp_path, meeting={"pid": 42}), alive)
    assert not ok and "recorded" in why
    ok, why = gate.check_no_meeting(_meetings(tmp_path, job={"pid": 42, "kind": "speakers"}), alive)
    assert not ok and "speakers" in why


def test_a_queued_meeting_blocks(tmp_path):
    ok, why = gate.check_no_meeting(_meetings(tmp_path, queue=["a", "b"]), lambda pid: False)
    assert not ok and "2 meeting" in why


def test_a_crashed_meeting_left_behind_does_not_block(tmp_path):
    p = _meetings(tmp_path, meeting={"pid": 42}, job={"pid": 43})
    assert gate.check_no_meeting(p, lambda pid: False)[0]


def test_pid_alive_sees_this_process_only():
    assert gate.pid_alive(os.getpid())
    assert not gate.pid_alive(None)


def test_disk_needs_three_times_the_installer(tmp_path):
    setup = tmp_path / "Ecoscribe-Setup-9.9.9.exe"
    setup.write_bytes(b"x" * 1000)
    assert gate.check_disk(setup, free=3000)[0]
    assert not gate.check_disk(setup, free=2999)[0]


def test_version_is_read_from_the_installer_name(tmp_path):
    assert gate.setup_version(Path("Ecoscribe-Setup-1.15.2.exe")) == "1.15.2"
    assert gate.setup_version(Path("Ecoscribe-Speakers-Setup-1.2.0.exe")) is None
    setup = tmp_path / f"Ecoscribe-Setup-{gate.app_version()}.exe"
    assert gate.check_version(setup)[0]
    assert not gate.check_version(tmp_path / "Ecoscribe-Setup-0.0.1.exe")[0]


def test_a_failed_check_means_not_installed(tmp_path, monkeypatch, capsys):
    setup = tmp_path / f"Ecoscribe-Setup-{gate.app_version()}.exe"
    setup.write_bytes(b"x")
    installed = []
    monkeypatch.setattr(gate, "check_tests", lambda: (False, "1 failed"))
    monkeypatch.setattr(gate, "check_selftest", lambda: (True, "cuda"))
    monkeypatch.setattr(gate, "check_no_meeting", lambda: (True, "idle"))
    monkeypatch.setattr(gate, "install", lambda *a: installed.append(a) or (True, {}))
    monkeypatch.setattr(gate, "OUT", tmp_path)
    monkeypatch.setattr(gate, "DOWNLOADS", tmp_path / "none")
    assert gate.run(setup, do_install=True) == 1
    out = capsys.readouterr().out
    assert "FAIL  unit tests" in out and "Installed: no" in out and not installed


def test_old_installers_are_listed_never_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "OUT", tmp_path)
    monkeypatch.setattr(gate, "DOWNLOADS", tmp_path / "none")
    for v in ("1.0.0", "1.1.0", "1.2.0"):
        (tmp_path / f"Ecoscribe-Setup-{v}.exe").write_bytes(b"x")
    old = gate.old_installers(tmp_path / "Ecoscribe-Setup-1.2.0.exe")
    assert [p.name for p in old] == ["Ecoscribe-Setup-1.0.0.exe", "Ecoscribe-Setup-1.1.0.exe"]
    assert all(p.exists() for p in old)
