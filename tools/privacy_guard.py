#!/usr/bin/env python3
"""Privacy guard (dictado-05h): the repo is public, so nothing personal gets committed or pushed.

Runs from the git hooks in .beads/hooks (pre-commit and pre-push) and by hand:

    python3 tools/privacy_guard.py pre-commit   # the staged changes
    python3 tools/privacy_guard.py pre-push     # every commit not on a remote yet, messages included
    python3 tools/privacy_guard.py history      # the whole git history, once

Two checks:
1. gitleaks with .gitleaks.toml: keys, home folders, calendar links, the app's own data files,
   recordings. Words that are personal (names, places) go in a local file that is never committed,
   ~/.config/ecoscribe/privacy-rules.toml (or $ECOSCRIBE_PRIVACY_RULES), which starts with
       [extend]
       path = "<this repo>/.gitleaks.toml"
   and adds its own [[rules]].
2. Every 6-word piece of the user's own dictations and meeting transcripts on this computer, the same
   check as tests/test_no_personal_data.py, against the added lines and commit messages.
Only standard library: it runs under any python3 on Windows (WSL), macOS and Linux.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RULES = REPO / ".gitleaks.toml"
LOCAL_RULES = Path(os.environ.get("ECOSCRIBE_PRIVACY_RULES") or Path.home() / ".config" / "ecoscribe" / "privacy-rules.toml")
N = 6  # words per piece, as in tests/test_no_personal_data.py


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                          errors="ignore", check=True).stdout


def data_dirs() -> list[Path]:
    """Where the app keeps dictations and transcripts on this computer (the Windows one too, from WSL)."""
    if os.environ.get("ECOSCRIBE_PERSONAL_DIR"):
        return [Path(os.environ["ECOSCRIBE_PERSONAL_DIR"])]
    if sys.platform == "darwin":
        sup = Path.home() / "Library" / "Application Support"
        return [sup / "Ecoscribe", sup / "Dictado"]
    if os.environ.get("LOCALAPPDATA"):
        return [Path(os.environ["LOCALAPPDATA"]) / "ecoscribe"]
    try:
        wsl = "microsoft" in Path("/proc/version").read_text(errors="ignore").lower()
    except OSError:
        wsl = False
    if wsl:
        try:
            win = subprocess.run(["cmd.exe", "/c", "echo %LOCALAPPDATA%"], capture_output=True, text=True,
                                 timeout=10, cwd="/mnt/c").stdout.strip()
            local = subprocess.run(["wslpath", "-u", win], capture_output=True, text=True, timeout=10).stdout.strip()
            if local:
                return [Path(local) / "ecoscribe"]
        except (OSError, subprocess.SubprocessError):
            pass
    return []


def personal_texts(dirs: list[Path]) -> list[str]:
    texts = []
    for d in dirs:
        for f in [d / "history.jsonl", *d.glob("history*.bak")]:
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    try:
                        texts.append(str(json.loads(line).get("text", "")))
                    except (ValueError, AttributeError):
                        pass
            except OSError:
                pass
        for f in d.glob("transcripts/*/transcript.json"):
            try:
                segs = json.loads(f.read_text(encoding="utf-8")).get("segments", [])
                texts.append(" ".join(str(x.get("text", "")) for x in segs))
            except (OSError, ValueError, AttributeError):
                pass
    return [t for t in texts if t.strip()]


def pieces(text: str) -> set[str]:
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + N]) for i in range(0, max(0, len(w) - N + 1))}


def allowed_pieces() -> set[str]:
    """The scripted sentences of the test recordings: test runs dictate them, so they are in the history."""
    out: set[str] = set()
    for f in [REPO / "tools" / "make_fixtures.py", *(REPO / "tests" / "fixtures").glob("*.txt")]:
        out |= pieces(f.read_text(encoding="utf-8", errors="ignore"))
    return out


def leaked(personal: list[str], outgoing: str, allowed: set[str]) -> list[str]:
    mine = set().union(*(pieces(t) for t in personal))
    return sorted((pieces(outgoing) & mine) - allowed)


def added_text(diff: str) -> str:
    """Lines a diff adds (and commit messages, which `git log -p` indents), not the ones it removes."""
    return "\n".join(line[1:] if line.startswith("+") else line for line in diff.splitlines()
                     if (line.startswith("+") and not line.startswith("+++")) or line.startswith("    "))


def outgoing(mode: str) -> tuple[str, str]:
    """(text to check, gitleaks --log-opts) for a mode; log opts empty for staged changes."""
    if mode == "pre-commit":
        return added_text(_git("diff", "--cached", "-U0", "--no-color")), ""
    rng = "--branches --tags --not --remotes" if mode == "pre-push" else "--all"
    return added_text(_git("log", "-p", "-U0", "--no-color", *rng.split())), rng


def run_gitleaks(mode: str, log_opts: str) -> int:
    exe = shutil.which("gitleaks")
    if not exe:
        print("privacy guard: gitleaks is not installed, so nothing checks for keys or personal paths.\n"
              "  Install it (macOS: brew install gitleaks; Linux/WSL: the release binary from\n"
              "  https://github.com/gitleaks/gitleaks/releases into ~/.local/bin) and try again.", file=sys.stderr)
        return 1
    cfg = LOCAL_RULES if LOCAL_RULES.is_file() else RULES
    cmd = [exe, "git", "--no-banner", "--redact=40", "-c", str(cfg), "--exit-code", "1"]
    if mode == "pre-commit":
        cmd.append("--staged")
    else:
        cmd.append(f"--log-opts={log_opts}")
    r = subprocess.run([*cmd, str(REPO)], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        print("privacy guard: gitleaks found something personal or secret (above). Take it out; the repo is public.",
              file=sys.stderr)
    return r.returncode


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "pre-commit"
    if mode not in ("pre-commit", "pre-push", "history"):
        print(__doc__)
        return 2
    text, log_opts = outgoing(mode)
    if mode == "pre-push" and not text.strip():
        return 0  # nothing new leaves this computer
    bad = run_gitleaks(mode, log_opts)
    found = leaked(personal_texts(data_dirs()), text, allowed_pieces())
    if found:
        print(f"privacy guard: {len(found)} piece(s) of your own dictations or meetings are in what you're "
              f"about to {'commit' if mode == 'pre-commit' else 'push'} (first: {found[0]!r}). Take them out; "
              "tests and docs use invented text.", file=sys.stderr)
        bad = 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
