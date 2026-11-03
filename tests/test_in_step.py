"""The start check (tools/in_step.py, dictado-trtz.3): the words it prints for each situation, from invented
inputs. Nothing here calls bd, gh or the network."""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("in_step", REPO / "tools" / "in_step.py")
in_step = importlib.util.module_from_spec(spec)
sys.modules["in_step"] = in_step  # dataclasses look their module up here
spec.loader.exec_module(in_step)

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


def rel(version, exe=True, dmg=True, tag=None):
    assets = ([f"Ecoscribe-Setup-{version}.exe"] if exe else []) + ([f"Ecoscribe-{version}.dmg"] if dmg else [])
    return {"tag": tag or f"v{version}", "assets": assets, "draft": False, "prerelease": False}


def releases():
    return [rel("1.25.2"), rel("1.25.1"), {"tag": "gpu-runtime-3", "assets": ["x.zip"]}, rel("1.25.0")]


def green_check(name="unit (macos-14)"):
    return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}


def pr(number, hours_old=2, checks=None, draft=False):
    return {"number": number, "isDraft": draft, "createdAt": (NOW - timedelta(hours=hours_old)).isoformat(),
            "statusCheckRollup": checks if checks is not None else []}


def facts(**kw):
    base = dict(computer="windows", now=NOW, pull_error=None, prs=[], releases=releases(),
                installed={"installed-windows": "1.25.2 2026-11-03T08:02", "installed-mac": "1.25.2 2026-11-03T08:40",
                           "some-other-memory": "unrelated"})
    base.update(kw)
    return in_step.Facts(**base)


def test_all_green_is_one_line():
    assert in_step.lines(facts()) == ["Windows and Mac in step: 1.25.2 on both, tickets synced, nothing waiting."]


def test_missing_mac_download_names_the_releases_since_the_last_one_that_had_it():
    rs = [rel("1.25.2", dmg=False), rel("1.25.1", dmg=False), rel("1.25.0"), rel("1.24.4", dmg=False)]
    out = in_step.lines(facts(releases=rs))
    assert "2 releases have no Mac download: v1.25.1, v1.25.2. GitHub builds the Mac one: re-run Actions > mac-release" \
        " if it failed." in out
    assert not any("1.24.4" in line for line in out)  # older gaps don't matter: updates go to the newest


def test_missing_windows_download_and_one_release_wording():
    out = in_step.lines(facts(releases=[rel("1.25.2", exe=False), rel("1.25.1")]))
    assert "1 release has no Windows download: v1.25.2." in out


def test_a_computer_behind_the_newest_release():
    inst = {"installed-windows": "1.25.2 2026-11-03T08:02", "installed-mac": "1.25.0 2026-10-30T10:00"}
    out = in_step.lines(facts(installed=inst, computer="mac"))
    assert out == ["Mac (this computer): 1.25.0; newest release 1.25.2."]


def test_unrecorded_and_unreleased_versions():
    out = in_step.lines(facts(installed={"installed-windows": "1.25.3 2026-11-03T08:02"}))
    assert len(out) == 1
    assert "Windows (this computer): 1.25.3, not released" in out[0]
    assert "Mac: no install recorded" in out[0] and "record_install.py" in out[0]


def test_green_and_old_prs():
    prs = [pr(226, checks=[green_check(), green_check("pr-shape")]), pr(227, hours_old=30, checks=[green_check()]),
           pr(228, hours_old=50, checks=[{"status": "IN_PROGRESS", "conclusion": ""}]),
           pr(229, checks=[green_check()], draft=True), pr(230, checks=[])]
    out = in_step.lines(facts(prs=prs))
    assert out == ["2 green PRs waiting to merge: #226, #227; 2 PRs open over a day: #227, #228."]


def test_a_failed_check_or_a_commit_status_is_not_green():
    assert not in_step.is_green(pr(1, checks=[green_check(), {"status": "COMPLETED", "conclusion": "FAILURE"}]))
    assert in_step.is_green(pr(1, checks=[{"__typename": "StatusContext", "state": "SUCCESS"}]))
    assert not in_step.is_green(pr(1, checks=[{"__typename": "StatusContext", "state": "PENDING"}]))


def test_stop_lines_come_first_and_name_the_fix():
    out = in_step.lines(facts(stop=["git hooks are off (git config core.hooksPath .beads/hooks)",
                                    "gitleaks is not installed"]))
    assert out[0].startswith("STOP: ")
    assert "core.hooksPath" in out[0] and "gitleaks" in out[0]
    assert len(out) == 1


def test_ticket_pull_failure_says_run_bd_sync():
    out = in_step.lines(facts(pull_error="error: merge conflict in issues"))
    assert out == ["Tickets didn't sync on this computer (a conflict): run bd sync before any ticket work."]
    out = in_step.lines(facts(pull_error="ssh: Could not resolve hostname github-personal"))
    assert "offline" in out[0] and "bd sync" in out[0]


def test_network_failure_wording():
    out = in_step.lines(facts(prs=None, releases=None, unchecked=["open PRs (offline?)", "releases (offline?)"]))
    assert out == ["Couldn't check open PRs (offline?), releases (offline?)."]


def test_never_more_than_five_lines():
    out = in_step.lines(facts(
        stop=["gitleaks is not installed"], pull_error="timed out",
        installed={"installed-mac": "1.25.0 x"},
        releases=[rel("1.25.2", dmg=False, exe=False), rel("1.25.1")],
        prs=[pr(5, checks=[green_check()])], unchecked=["the mass-delete guard (timed out)"]))
    assert len(out) == 5
    assert out[0].startswith("STOP:")
    assert "Couldn't check" in out[-1]  # the overflow joins the last line, nothing is dropped


def test_the_whole_run_offline_prints_lines_not_a_traceback(monkeypatch, tmp_path, capsys):
    rules = tmp_path / "privacy-rules.toml"
    rules.write_text("[extend]\n", encoding="utf-8")
    monkeypatch.setattr(in_step, "LOCAL_RULES", rules)
    monkeypatch.setattr(in_step.shutil, "which", lambda name: "/fake/" + name)

    def fake_run(cmd, timeout, env=None):
        if cmd[:2] == ["git", "config"]:
            return in_step.Result(True, ".beads/hooks\n", "")
        return in_step.Result(False, "", "timed out")

    monkeypatch.setattr(in_step, "run", fake_run)
    assert in_step.main() == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert 1 <= len(out) <= 5
    assert not any("Traceback" in line or line.startswith("STOP") for line in out)
    assert any("bd sync" in line for line in out)
    assert any(line.startswith("Couldn't check") and "open PRs" in line for line in out)


def test_safety_failures_found_locally(monkeypatch, tmp_path):
    monkeypatch.setattr(in_step, "LOCAL_RULES", tmp_path / "missing.toml")
    monkeypatch.setattr(in_step.shutil, "which", lambda name: None)
    monkeypatch.setattr(in_step, "run", lambda cmd, timeout, env=None: in_step.Result(False, "", "exit 1"))
    f = in_step.Facts()
    in_step.check_local(f)
    text = " ".join(f.stop)
    assert "core.hooksPath .beads/hooks" in text and "gitleaks" in text and "privacy-rules.toml" in text


def test_hooks_path_may_be_absolute(monkeypatch, tmp_path):
    rules = tmp_path / "r.toml"
    rules.write_text("", encoding="utf-8")
    monkeypatch.setattr(in_step, "LOCAL_RULES", rules)
    monkeypatch.setattr(in_step.shutil, "which", lambda name: "/fake/gitleaks")
    monkeypatch.setattr(in_step, "run", lambda cmd, timeout, env=None: in_step.Result(True, "/src/app/.beads/hooks\n", ""))
    f = in_step.Facts()
    in_step.check_local(f)
    assert f.stop == []


def test_mass_delete_guard_off_is_a_stop(monkeypatch):
    answers = {"pull": in_step.Result(True, "", ""), "memories": in_step.Result(True, "{}", ""),
               "config": in_step.Result(True, "false\n", "")}

    def fake_run(cmd, timeout, env=None):
        return answers[cmd[2] if cmd[1] == "dolt" else cmd[1]]

    monkeypatch.setattr(in_step, "run", fake_run)
    f = in_step.Facts()
    in_step.check_bd(f)
    assert any("mass-delete" in s and "bd config set" in s for s in f.stop)
    assert f.pull_error is None and f.installed == {}


def test_a_public_tickets_repo_is_a_stop(monkeypatch):
    monkeypatch.setattr(in_step, "gh_env", lambda: {})
    monkeypatch.setattr(in_step, "check_bd", lambda f: None)
    monkeypatch.setattr(in_step, "check_local", lambda f: None)
    monkeypatch.setattr(in_step, "check_prs", lambda env: ([], ""))
    monkeypatch.setattr(in_step, "check_releases", lambda env: (releases(), ""))
    monkeypatch.setattr(in_step, "check_private", lambda env: (False, ""))
    f = in_step.gather()
    assert any("PUBLIC" in s for s in f.stop)
    assert in_step.lines(f)[0].startswith("STOP:")


def test_a_crash_inside_is_one_line_and_exit_zero(monkeypatch, capsys):
    def boom():
        raise RuntimeError("something odd")
    monkeypatch.setattr(in_step, "gather", boom)
    assert in_step.main() == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "RuntimeError" in out[0]
