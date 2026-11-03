"""The release step (tools/release.py) and the install record (tools/record_install.py), dictado-trtz.3:
the commands each computer runs, checked with --dry-run and fake shells. Nothing here calls gh or bd."""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


release = _load("release")
record_install = _load("record_install")


class FakeShell(release.Shell):
    """Records commands; answers from a table keyed by the command's first words."""

    def __init__(self, answers=None):
        self.dry_run = False
        self.env = {}
        self.answers = answers or {}
        self.cmds = []

    def execute(self, cmd):
        self.cmds.append(cmd)
        for key, answer in self.answers.items():
            if cmd[:len(key)] == list(key) or (key[0] == "privacy" and "tools/privacy_guard.py" in cmd):
                return answer
        return 0, ""


def _windows_args(tmp_path, *extra):
    notes = tmp_path / "notes.md"
    notes.write_text("What's new: an invented change.\n", encoding="utf-8")
    exe = tmp_path / "Ecoscribe-Setup-1.25.2.exe"
    exe.write_bytes(b"MZ")
    return ["1.25.2", "--platform", "windows", "--notes", str(notes), "--asset", str(exe), *extra]


def test_windows_dry_run_prints_guard_then_release_and_nothing_for_the_mac(capsys):
    assert release.main(["1.25.2", "--platform", "windows", "--asset", "Ecoscribe-Setup-1.25.2.exe", "--dry-run"]) == 0
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l.startswith("+ ")]
    assert "tools/privacy_guard.py text --file" in lines[0]
    assert lines[1].startswith("+ gh release create v1.25.2 Ecoscribe-Setup-1.25.2.exe -R ErikBros/ecoscribe "
                               "--target main --latest --title 'Ecoscribe 1.25.2' --notes-file")
    assert len(lines) == 2  # the Mac download is GitHub's mac-release run, no ticket (dictado-trtz.5)
    assert "(dry run)" in out and "mac-release" in out


def test_mac_dry_run_uploads_the_dmg_and_closes_the_ticket(capsys):
    assert release.main(["1.25.2", "--platform", "mac", "--asset", "Ecoscribe-1.25.2.dmg", "--dry-run"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("+ ")]
    assert lines[0].startswith("+ gh release view v1.25.2 -R ErikBros/ecoscribe")
    assert lines[1] == "+ gh release upload v1.25.2 Ecoscribe-1.25.2.dmg -R ErikBros/ecoscribe --clobber"
    assert any(l.startswith("+ bd close") and "v1.25.2" in l for l in lines)
    assert lines[-1] == "+ bd sync"
    assert not any("release create" in l for l in lines)


def test_the_download_must_have_the_name_the_apps_look_for(capsys):
    assert release.main(["1.25.2", "--platform", "mac", "--asset", "Ecoscribe.dmg", "--dry-run"]) == 1
    assert "Ecoscribe-1.25.2.dmg" in capsys.readouterr().out


def test_windows_release_makes_no_mac_ticket(tmp_path):
    sh = FakeShell()
    assert release.main(_windows_args(tmp_path), shell=sh) == 0
    assert [c[:3] for c in sh.cmds][1] == ["gh", "release", "create"]
    assert not any(c[0] == "bd" for c in sh.cmds)


def test_privacy_guard_failure_stops_the_release(tmp_path):
    sh = FakeShell({("privacy",): (1, "")})
    assert release.main(_windows_args(tmp_path), shell=sh) == 1
    assert not any(c[:2] == ["gh", "release"] for c in sh.cmds)


def test_privacy_guard_usage_error_also_stops_the_release(tmp_path):
    sh = FakeShell({("privacy",): (2, "")})
    assert release.main(_windows_args(tmp_path), shell=sh) == 1
    assert not any(c[:2] == ["gh", "release"] for c in sh.cmds)


def test_mac_without_a_release_stops_before_uploading(tmp_path):
    dmg = tmp_path / "Ecoscribe-1.25.2.dmg"
    dmg.write_bytes(b"x")
    sh = FakeShell({("gh", "release", "view"): (1, "")})
    assert release.main(["1.25.2", "--platform", "mac", "--asset", str(dmg)], shell=sh) == 1
    assert not any(c[:3] == ["gh", "release", "upload"] for c in sh.cmds)


def test_mac_closes_the_open_ticket(tmp_path):
    dmg = tmp_path / "Ecoscribe-1.25.2.dmg"
    dmg.write_bytes(b"x")
    found = json.dumps([{"id": "dictado-x1", "title": "Mac download for v1.25.2"},
                        {"id": "dictado-x2", "title": "Mac download for v1.25.20"}])
    sh = FakeShell({("bd", "list"): (0, found)})
    assert release.main(["1.25.2", "--platform", "mac", "--asset", str(dmg)], shell=sh) == 0
    closes = [c for c in sh.cmds if c[:2] == ["bd", "close"]]
    assert [c[2] for c in closes] == ["dictado-x1"]


def test_a_real_run_needs_the_file_and_the_notes(tmp_path, capsys):
    assert release.main(["1.25.2", "--platform", "windows",
                         "--asset", str(tmp_path / "Ecoscribe-Setup-1.25.2.exe")], shell=FakeShell()) == 1
    exe = tmp_path / "Ecoscribe-Setup-1.25.2.exe"
    exe.write_bytes(b"MZ")
    assert release.main(["1.25.2", "--platform", "windows", "--asset", str(exe)], shell=FakeShell()) == 1
    assert "--notes" in capsys.readouterr().out


def test_record_install_dry_run(capsys):
    assert record_install.record("mac", "1.25.2", dry_run=True, when="2026-11-03T08:02")
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith("remember --key installed-mac '1.25.2 2026-11-03T08:02'")
    assert out[1].endswith("dolt push")


def test_record_install_failure_only_warns(monkeypatch, capsys):
    monkeypatch.setattr(record_install, "run", lambda cmd, timeout=60: (False, "offline"))
    assert record_install.record("windows", "1.25.2") is False
    out = capsys.readouterr().out
    assert "warning" in out and "record_install.py windows --version 1.25.2" in out
    assert record_install.record("windows", "not-a-version") is False


def test_bd_from_windows_python_runs_in_wsl():
    repo = "\\\\wsl.localhost\\Ubuntu\\src\\ecoscribe"
    cmd = record_install.bd_cmd(["dolt", "push"], repo=repo, platform="win32")
    assert cmd[:5] == ["wsl.exe", "-d", "Ubuntu", "--cd", "/src/ecoscribe"]
    assert cmd[-3:] == ["bd", "dolt", "push"]
    assert record_install.bd_cmd(["dolt", "push"], platform="darwin") == ["bd", "dolt", "push"]
