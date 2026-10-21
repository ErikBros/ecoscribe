"""The privacy guard (tools/privacy_guard.py, dictado-05h) blocks personal text and paths before a commit
or push. Invented text only: never a real dictation here."""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("privacy_guard", REPO / "tools" / "privacy_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SAID = "the purple walrus ordered seven lemon cakes for the harbour party tonight"


def test_a_quote_of_six_words_is_caught():
    assert guard.leaked([SAID], 'label = "walrus ordered seven lemon cakes for"', set())


def test_unrelated_text_and_allowed_test_sentences_pass():
    assert not guard.leaked([SAID], "the purple button opens settings", set())
    quote = "walrus ordered seven lemon cakes for"
    assert not guard.leaked([SAID], quote, guard.pieces(quote))


def test_only_added_lines_and_messages_count():
    diff = "--- a/x.py\n+++ b/x.py\n-old removed line\n+new added line\n    commit message line\n"
    assert guard.added_text(diff).splitlines() == ["new added line", "    commit message line"]


@pytest.mark.parametrize("hook", ["pre-commit", "pre-push"])
def test_the_git_hooks_run_the_guard(hook):
    text = (REPO / ".beads" / "hooks" / hook).read_text(encoding="utf-8")
    assert f"tools/privacy_guard.py\" {hook}" in text


def _gitleaks(tmp_path: Path, files: dict[str, str]) -> set[str]:
    if not shutil.which("gitleaks") or not shutil.which("git"):
        pytest.skip("gitleaks not installed here (CI runs it in pr-shape)")
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body, encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.hooksPath=/dev/null"]
    subprocess.run([*git, "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-qm", "t"], cwd=tmp_path, check=True)
    report = tmp_path.parent / f"{tmp_path.name}-report.json"
    subprocess.run(["gitleaks", "git", "--no-banner", "-c", str(guard.RULES), "-r", str(report), str(tmp_path)],
                   capture_output=True)
    import json
    return {f["RuleID"] for f in json.loads(report.read_text(encoding="utf-8") or "[]")}


def test_gitleaks_rules_catch_personal_paths_and_files(tmp_path):
    found = _gitleaks(tmp_path, {
        "a.py": 'p = r"C:\\Users\\Jdoe\\AppData\\Local"\nq = "/home/jdoe/notes"\n',
        "data/history.jsonl": '{"text": "x"}\n',
        "clip.flac": "not really audio\n",
        "notes.local.md": "x\n",
    })
    assert found >= {"personal-home-path", "personal-data-file", "recording-outside-fixtures", "private-local-file"}


def test_gitleaks_rules_let_placeholders_and_fixtures_through(tmp_path):
    found = _gitleaks(tmp_path, {
        "a.md": "Put it in /Users/me/Library or C:\\Users\\you\\Downloads.\n",
        "tests/fixtures/hello.wav": "scripted test recording\n",
    })
    assert not found, found
