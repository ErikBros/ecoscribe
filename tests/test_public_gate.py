"""The public gate (dictado-trtz.1): text that goes public (PR bodies, comments, issues, release notes,
branch names) gets the privacy check, including copies of private ticket text, and fails closed.
Invented text only: never a real dictation or a real ticket here."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / ".claude" / "hooks" / "public_gate.py"
spec = importlib.util.spec_from_file_location("privacy_guard_gate", REPO / "tools" / "privacy_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SAID = "the purple walrus ordered seven lemon cakes for the harbour party tonight"
TICKET_DESC = "the copper kettle hums a quiet tune whenever the lighthouse keeper sleeps late"
TICKET_TITLE = "seven orange balloons drift slowly over the frozen river at dawn"
FAKE_HOME = "/" + "home/jdoe/notes"  # built at run time: gitleaks would flag the literal in this file
needs_gitleaks = pytest.mark.skipif(not shutil.which("gitleaks"), reason="gitleaks not installed here (WSL, Mac and CI have it)")


@pytest.fixture
def private(tmp_path, monkeypatch):
    """A fake app folder with one dictation, a fake ticket export, and no public repo text to excuse a copy."""
    speech = tmp_path / "app"
    speech.mkdir()
    (speech / "history.jsonl").write_text(json.dumps({"text": SAID}) + "\n", encoding="utf-8")
    tickets = tmp_path / "tickets.jsonl"
    tickets.write_text(json.dumps({"id": "demo-1a", "title": TICKET_TITLE, "description": TICKET_DESC,
                                   "notes": "", "comments": [{"text": "a comment nobody reads twice"}]}) + "\n",
                       encoding="utf-8")
    monkeypatch.setenv("ECOSCRIBE_PERSONAL_DIR", str(speech))
    monkeypatch.setenv("ECOSCRIBE_GATE_TICKETS_FILE", str(tickets))
    monkeypatch.delenv("ECOSCRIBE_GATE_CI", raising=False)
    guard._cache.clear()
    guard._cache["public"] = " "
    yield {"speech": speech, "tickets": tickets, "tmp": tmp_path}
    guard._cache.clear()


def test_clean_text_has_no_private_hits(private):
    assert guard.private_hits("Ticket: demo-1a. What changed: the settings page saves on close.") == []


def test_a_dictation_piece_is_caught_by_where_not_by_what(private):
    hits = guard.private_hits("Why: walrus ordered seven lemon cakes for the party")
    assert len(hits) == 1 and hits[0].startswith("speech check")
    assert "lemon cakes" not in hits[0]


def test_a_copy_of_a_ticket_description_is_caught(private):
    hits = guard.private_hits("What changed: kettle hums a quiet tune whenever the keeper")
    assert hits == ["ticket-copy check: 2 piece(s) copied from the private text of demo-1a description"]
    assert "kettle" not in hits[0]


def test_ticket_titles_are_not_private(private):
    assert guard.private_hits(f"Title: {TICKET_TITLE}") == []


def test_ticket_text_already_in_the_repo_is_public(private):
    guard._cache["public"] = " " + " ".join(guard.words(TICKET_DESC)) + " "
    assert guard.private_hits("kettle hums a quiet tune whenever") == []


def test_fails_closed_when_the_tickets_cant_be_read(private, monkeypatch):
    monkeypatch.setenv("ECOSCRIBE_GATE_TICKETS_FILE", str(private["tmp"] / "missing.jsonl"))
    with pytest.raises(guard.Unavailable):
        guard.private_hits("anything at all")


def test_fails_closed_when_the_speech_folder_is_missing(private, monkeypatch):
    monkeypatch.setenv("ECOSCRIBE_PERSONAL_DIR", str(private["tmp"] / "nowhere"))
    with pytest.raises(guard.Unavailable):
        guard.private_hits("anything at all")


def test_ci_mode_skips_speech_and_tickets(private, monkeypatch):
    monkeypatch.setenv("ECOSCRIBE_GATE_CI", "1")
    monkeypatch.setenv("ECOSCRIBE_PERSONAL_DIR", str(private["tmp"] / "nowhere"))
    monkeypatch.setenv("ECOSCRIBE_GATE_TICKETS_FILE", str(private["tmp"] / "missing.jsonl"))
    assert guard.private_hits(SAID) == []


def test_gitleaks_missing_fails_closed(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda name: None)
    with pytest.raises(guard.Unavailable):
        guard.check_text("hello")


@needs_gitleaks
def test_text_mode_end_to_end(private, tmp_path, capsys):
    clean, said, home = tmp_path / "clean.md", tmp_path / "said.md", tmp_path / "home.md"
    clean.write_text("Ticket: demo-1a\n\nWhat changed: the pill fades out faster.\n", encoding="utf-8")
    said.write_text("Why: the walrus ordered seven lemon cakes for the party\n", encoding="utf-8")
    home.write_text(f"Logs are in {FAKE_HOME} now\n", encoding="utf-8")
    assert guard.main(["pg", "text", "--file", str(clean)]) == 0
    assert guard.main(["pg", "text", "--file", str(said)]) == 1
    assert guard.main(["pg", "text", "--file", str(home)]) == 1
    err = capsys.readouterr().err
    assert "personal-home-path" in err and "jdoe" not in err and "lemon" not in err


@needs_gitleaks
def test_ci_mode_still_runs_gitleaks(private, monkeypatch):
    monkeypatch.setenv("ECOSCRIBE_GATE_CI", "1")
    assert guard.check_text(f"see {FAKE_HOME}") and not guard.check_text(SAID)


# --- pre-push: branch names ------------------------------------------------------------------------

def test_pushed_names_come_from_the_pre_push_lines():
    z = "0" * 40
    refs = (f"refs/heads/fix-pill abc123 refs/heads/fix-pill {z}\n"
            f"refs/heads/old {z} refs/heads/old def456\n"  # a delete publishes nothing new
            f"refs/tags/v1.2.3 fff111 refs/tags/v1.2.3 {z}\n")
    assert guard.pushed_names(refs) == ["fix-pill", "v1.2.3"]


def test_a_branch_name_with_a_dictation_piece_is_caught(private, monkeypatch):
    monkeypatch.setattr(guard, "gitleaks_text", lambda text: [])  # gitleaks has its own tests
    hits = guard.check_names(["walrus-ordered-seven-lemon-cakes-for"])
    assert hits and hits[0].startswith("branch name: speech check")
    assert guard.check_names(["fix-pill-fade"]) == []


def test_the_pre_push_hook_passes_the_refs_on():
    text = (REPO / ".beads" / "hooks" / "pre-push").read_text(encoding="utf-8")
    assert 'cat > "$_pg_refs"' in text and 'pre-push --refs "$_pg_refs"' in text
    assert text.index('cat > "$_pg_refs"') < text.index("BEGIN BEADS")  # before beads reads stdin


# --- the Claude Code hook ---------------------------------------------------------------------------

def run_hook(command: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    event = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": command, "description": "t"}, "cwd": str(cwd)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True,
                          encoding="utf-8", env={**os.environ, **(env or {})}, timeout=120)


@pytest.mark.parametrize("command", [
    "ls -la",
    "gh pr view 12",
    "gh pr checks 12 --watch",
    "gh pr merge 12 --merge --delete-branch",
    "gh release view v1.2.3",
    "gh release download v1.2.3 -p '*.exe'",
    "GH_TOKEN=$(gh auth token --user someone) gh pr list --state open",
    "gh api repos/o/r/pulls --jq '.[].title'",
    "git commit -m 'fix: the pill fades (ticket: demo-1a)'",
    "git commit -am 'not -n here'",
    "git push -u origin HEAD",
    "git log --oneline -n 5",
])
def test_harmless_commands_pass(command, tmp_path):
    r = run_hook(command, tmp_path, {"ECOSCRIBE_PERSONAL_DIR": str(tmp_path / "nowhere")})
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("command", [
    "git commit --no-verify -m x",
    "git commit -nm x",
    "git -C /repo push --no-verify origin HEAD",
    "git -c core.hooksPath=/dev/null commit -m x",
    "cd /repo && git add -A && git commit -n -m 'x'",
])
def test_skipping_the_git_hooks_is_blocked(command, tmp_path):
    r = run_hook(command, tmp_path)
    assert r.returncode == 2 and "public gate: blocked" in r.stderr


def test_a_body_from_stdin_is_blocked(tmp_path):
    r = run_hook("gh pr create --title t --body-file -", tmp_path)
    assert r.returncode == 2 and "stdin" in r.stderr


def test_a_body_file_that_doesnt_exist_is_blocked(tmp_path):
    r = run_hook("gh pr comment 12 --body-file body.md", tmp_path)
    assert r.returncode == 2 and "can't read" in r.stderr


def test_the_body_files_a_command_names():
    hook = importlib.util.spec_from_file_location("public_gate", HOOK)
    mod = importlib.util.module_from_spec(hook)
    hook.loader.exec_module(mod)
    base = os.path.abspath("/w")
    toks = mod.tokens("cd sub && gh pr create -t x -F body.md; gh release create v1 --notes-file=/n.md; "
                      "gh api repos/o/r/issues -F body=@c.md -F title=plain")
    assert mod.body_files(toks, base) == [os.path.normpath(os.path.join(base, "sub", "body.md")),
                                          os.path.normpath(os.path.join(base, "sub", "/n.md")),
                                          os.path.normpath(os.path.join(base, "sub", "c.md"))]


@needs_gitleaks
def test_a_pr_body_with_a_dictation_piece_is_blocked(private):
    env = {"ECOSCRIBE_PERSONAL_DIR": str(private["speech"]), "ECOSCRIBE_GATE_TICKETS_FILE": str(private["tickets"])}
    body = "Ticket: demo-1a\n\nWhy: the purple walrus ordered seven lemon cakes for the party\n"
    cmd = f"gh pr create --title 'Pill fades faster' --body \"$(cat <<'EOF'\n{body}EOF\n)\""
    r = run_hook(cmd, private["tmp"], env)
    assert r.returncode == 2 and "speech check" in r.stderr and "lemon" not in r.stderr
    clean = cmd.replace("the purple walrus ordered seven lemon cakes for the party", "the user wants a faster pill")
    r = run_hook(clean, private["tmp"], env)
    assert r.returncode == 0, r.stderr


@needs_gitleaks
def test_a_body_file_is_read_and_checked(private):
    env = {"ECOSCRIBE_PERSONAL_DIR": str(private["speech"]), "ECOSCRIBE_GATE_TICKETS_FILE": str(private["tickets"])}
    (private["tmp"] / "body.md").write_text("Why: walrus ordered seven lemon cakes for us\n", encoding="utf-8")
    (private["tmp"] / "ok.md").write_text("Why: the user wants a faster pill\n", encoding="utf-8")
    assert run_hook("gh pr create -t x --body-file body.md", private["tmp"], env).returncode == 2
    assert run_hook("gh issue comment 3 -F ok.md", private["tmp"], env).returncode == 0


def test_the_audit_reads_paginated_gh_output(monkeypatch):
    spec_a = importlib.util.spec_from_file_location("public_audit", REPO / "tools" / "public_audit.py")
    audit = importlib.util.module_from_spec(spec_a)
    spec_a.loader.exec_module(audit)
    pages = '[{"number": 1}]\n[{"number": 2}, {"number": 3}]{"data": {}}'
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=pages, stderr=""))
    assert [i.get("number") for i in audit.gh_list("repos/o/r/pulls", {})] == [1, 2, 3, None]


# --- the private ticket store never gets the public repo as its remote --------------------------------

PUBLIC_URL = "git+ssh://git@github-personal/ErikBros/ecoscribe.git"
PRIVATE_URL = "git+ssh://git@github-personal/ErikBros/ecoscribe-tickets.git"


@pytest.mark.parametrize("command", [
    f"bd dolt remote add origin {PUBLIC_URL} && bd dolt push",
    f"bd dolt remote set-url origin {PUBLIC_URL}",
    "bd dolt remote add origin",
    f"bd init --remote {PUBLIC_URL}",
    f"bd init --remote={PUBLIC_URL}",
    f"bd config set sync.remote {PUBLIC_URL}",
    f"bd --actor someone dolt remote add origin https://github.com/ErikBros/ecoscribe",
])
def test_a_public_ticket_remote_is_blocked(command, tmp_path):
    r = run_hook(command, tmp_path)
    assert r.returncode == 2 and "ecoscribe-tickets" in r.stderr, r.stderr


@pytest.mark.parametrize("command", [
    f"bd dolt remote add origin {PRIVATE_URL}",
    "bd dolt remote add origin https://github.com/ErikBros/ecoscribe-tickets",
    f"bd init --remote {PRIVATE_URL}",
    f"bd config set sync.remote {PRIVATE_URL}",
    "bd dolt remote list",
    "bd dolt push",
    "bd bootstrap --dry-run",
    "bd ready",
])
def test_the_private_ticket_remote_and_other_bd_commands_pass(command, tmp_path):
    r = run_hook(command, tmp_path)
    assert r.returncode == 0, r.stderr


def test_bootstrap_needs_the_private_sync_remote_first():
    hook = importlib.util.spec_from_file_location("public_gate_bd", HOOK)
    mod = importlib.util.module_from_spec(hook)
    hook.loader.exec_module(mod)
    toks = mod.tokens("bd bootstrap --yes")
    assert "sync.remote" in mod.ticket_remote_risk(toks, lambda: "")
    assert "sync.remote" in mod.ticket_remote_risk(toks, lambda: PUBLIC_URL)
    assert mod.ticket_remote_risk(toks, lambda: PRIVATE_URL) is None


# --- weekly audit (dictado-trtz.6) -----------------------------------------------------------------------

def _audit():
    spec_a = importlib.util.spec_from_file_location("public_audit_w", REPO / "tools" / "public_audit.py")
    audit = importlib.util.module_from_spec(spec_a)
    spec_a.loader.exec_module(audit)
    return audit


def test_reviewed_hits_file_is_read_without_comments(tmp_path):
    audit = _audit()
    f = tmp_path / "reviewed.txt"
    f.write_text("# header\nPR #1 body: dictado-a1  # harmless\n\nrelease v1.0.0 notes: dictado-b2\n", encoding="utf-8")
    assert audit.reviewed_keys(f) == {"PR #1 body: dictado-a1", "release v1.0.0 notes: dictado-b2"}
    assert audit.reviewed_keys(tmp_path / "missing.txt") == set()


def test_the_repo_reviewed_list_only_names_ticket_copies():
    for key in _audit().reviewed_keys():
        assert re.fullmatch(r"(PR #\d+ (body|title|branch name)|release v[\d.]+ (notes|name)|comment \S+): dictado-\S+",
                            key), key


def test_weekly_waits_seven_days():
    audit = _audit()
    import time as _t
    now = _t.mktime(_t.strptime("2026-11-10", "%Y-%m-%d"))
    assert audit.days_since_last('{"public-audit-last": "2026-11-05 clean"}', now) == pytest.approx(5, abs=0.1)
    assert audit.days_since_last('{"other": "x"}', now) is None
    assert audit.days_since_last("not json", now) is None


def test_ticket_text_once_published_still_counts_as_public():
    audit = _audit()
    raw = json.dumps({"id": "dictado-x", "description": "The user wants a calmer pill colour at night"}) + "\n"
    words = audit.exported_ticket_words(raw)
    assert " the user wants a calmer pill colour " in words


def _run_audit(monkeypatch, audit, copies, reviewed, exported=" ", weekly=False):
    monkeypatch.setattr(audit, "token", lambda: "t")
    monkeypatch.setattr(audit, "public_texts", lambda repo, env: [("PR #7 body", "invented text")])
    monkeypatch.setattr(audit, "gitleaks_all", lambda texts: [])
    monkeypatch.setattr(audit.guard, "speech_hits", lambda t: [])
    monkeypatch.setattr(audit.guard, "ticket_copies", lambda t: copies)
    monkeypatch.setattr(audit, "exported_ticket_words", lambda raw=None: exported)
    monkeypatch.setattr(audit, "reviewed_keys", lambda path=None: reviewed)
    monkeypatch.setattr(audit.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    calls = []
    monkeypatch.setattr(audit, "bd", lambda *a, **k: calls.append(a) or (0, "{}"))
    return audit.main(["public_audit.py"] + (["--weekly"] if weekly else [])), calls


def test_a_reviewed_ticket_copy_is_not_a_hit(monkeypatch, capsys):
    audit = _audit()
    code, _ = _run_audit(monkeypatch, audit, {"dictado-q1 notes": ["a b c d e f"]}, {"PR #7 body: dictado-q1"})
    assert code == 0 and "reviewed earlier" in capsys.readouterr().out


def test_an_unreviewed_ticket_copy_is_a_hit_and_weekly_opens_a_private_ticket(monkeypatch, capsys):
    audit = _audit()
    code, calls = _run_audit(monkeypatch, audit, {"dictado-q1": ["a b c d e f"]}, set(), weekly=True)
    assert code == 1 and "HIT PR #7 body" in capsys.readouterr().out
    assert any(c[0] == "remember" and c[2] == "public-audit-last" and "1 hit" in c[3] for c in calls)
    create = [c for c in calls if c[0] == "create"]
    assert create and "PR #7 body" in create[0][-1] and "a b c" not in create[0][-1]


def test_weekly_skips_when_run_recently(monkeypatch, capsys):
    audit = _audit()
    import time as _t
    today = _t.strftime("%Y-%m-%d")
    monkeypatch.setattr(audit, "bd", lambda *a, **k: (0, json.dumps({"public-audit-last": f"{today} clean"})))
    monkeypatch.setattr(audit, "public_texts", lambda *a: pytest.fail("should not download"))
    monkeypatch.setattr(audit, "token", lambda: "t")
    assert audit.main(["public_audit.py", "--weekly"]) == 0
    assert "next in" in capsys.readouterr().out
