#!/usr/bin/env python3
"""Privacy guard (dictado-05h, dictado-trtz.1): the repo is public, so nothing personal leaves this computer.

Runs from the git hooks in .beads/hooks (pre-commit and pre-push), from the Claude Code hook
.claude/hooks/public_gate.py (before `gh pr create`, `gh release create`, ...) and by hand:

    python3 tools/privacy_guard.py pre-commit             # the staged changes
    python3 tools/privacy_guard.py pre-push [--refs F]    # every commit not on a remote yet, messages and branch names
    python3 tools/privacy_guard.py history                # the whole git history, once
    python3 tools/privacy_guard.py text [--file F]        # a text about to go public (stdin by default)

The checks:
1. gitleaks with .gitleaks.toml: keys, home folders, calendar links, the app's own data files,
   recordings. Words that are personal (names, places) go in a local file that is never committed,
   ~/.config/ecoscribe/privacy-rules.toml (or $ECOSCRIBE_PRIVACY_RULES), which starts with
       [extend]
       path = "<this repo>/.gitleaks.toml"
   and adds its own [[rules]].
2. Every 6-word piece of the user's own dictations and meeting transcripts on this computer, the same
   check as tests/test_no_personal_data.py, against the added lines and commit messages.
3. `text` (and branch names on pre-push) also: every 6-word piece of the private tickets' free text
   (description, design, acceptance criteria, notes, comments; not titles), read with `bd export`
   ($ECOSCRIBE_GATE_TICKETS_FILE: a JSONL export to use instead). Pieces that are already in the
   repo's own files are public anyway and pass.

`text` fails closed: no gitleaks, no ticket store or no speech data folder is a failure, not a pass.
ECOSCRIBE_GATE_CI=1 (CI only: it has neither) skips the speech and ticket checks; gitleaks still runs.
Hits are reported by where they are (check, ticket id, line), never with the private text.
Only standard library: it runs under any python3 on Windows (WSL), macOS and Linux.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RULES = REPO / ".gitleaks.toml"
LOCAL_RULES = Path(os.environ.get("ECOSCRIBE_PRIVACY_RULES") or Path.home() / ".config" / "ecoscribe" / "privacy-rules.toml")
N = 6  # words per piece, as in tests/test_no_personal_data.py
TICKET_FIELDS = ("description", "design", "acceptance_criteria", "notes")  # free text; the title is public


class Unavailable(Exception):
    """A check that can't run: the gate fails closed and says what's missing."""


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                          errors="ignore", check=True).stdout


def gate_ci() -> bool:
    return os.environ.get("ECOSCRIBE_GATE_CI") == "1"


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


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def pieces(text: str) -> set[str]:
    w = words(text)
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


def hint(piece: str) -> str:
    """Enough to find a piece in your own text, not enough to read it."""
    return " ".join(piece.split()[:2]) + " ..."


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


# --- gitleaks -------------------------------------------------------------------------------------

def gitleaks_exe() -> str:
    exe = shutil.which("gitleaks")
    if not exe:
        raise Unavailable("gitleaks is not installed, so nothing checks for keys or personal paths. Install it "
                          "(macOS: brew install gitleaks; Linux/WSL: the release binary from "
                          "https://github.com/gitleaks/gitleaks/releases into ~/.local/bin) and try again.")
    return exe


def gitleaks_config() -> Path:
    return LOCAL_RULES if LOCAL_RULES.is_file() else RULES


def run_gitleaks(mode: str, log_opts: str) -> int:
    try:
        exe = gitleaks_exe()
    except Unavailable as e:
        print(f"privacy guard: {e}", file=sys.stderr)
        return 1
    cmd = [exe, "git", "--no-banner", "--redact=40", "-c", str(gitleaks_config()), "--exit-code", "1"]
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


def gitleaks_findings(cmd: list[str], **kw) -> list[dict]:
    """Run a gitleaks scan with a JSON report to stdout; its findings (secrets redacted)."""
    r = subprocess.run([*cmd, "--no-banner", "--redact", "-l", "error", "-c", str(gitleaks_config()),
                        "--exit-code", "0", "-f", "json", "-r", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore", **kw)
    try:
        found = json.loads(r.stdout or "[]")
    except ValueError:
        raise Unavailable(f"gitleaks didn't run (exit {r.returncode}): {r.stderr.strip()[:300]}")
    return found if isinstance(found, list) else []


def gitleaks_text(text: str) -> list[str]:
    found = gitleaks_findings([gitleaks_exe(), "stdin"], input=text)
    return [f"gitleaks rule {f.get('RuleID')} on line {f.get('StartLine')}" for f in found]


# --- the private texts: speech and tickets --------------------------------------------------------

_cache: dict[str, object] = {}


def speech_pieces() -> set[str]:
    if "speech" not in _cache:
        dirs = data_dirs()
        if not any(d.is_dir() for d in dirs):
            looked = ", ".join(str(d) for d in dirs) or "nowhere (this computer has no known app folder)"
            raise Unavailable(f"the app's data folder isn't here, so nothing checks for your own dictations "
                              f"(looked in {looked}). Set ECOSCRIBE_PERSONAL_DIR to it; ECOSCRIBE_GATE_CI=1 is for CI only.")
        _cache["speech"] = set().union(*(pieces(t) for t in personal_texts(dirs))) - allowed_pieces()
    return _cache["speech"]  # type: ignore[return-value]


def ticket_records() -> list[dict]:
    """Every ticket, from $ECOSCRIBE_GATE_TICKETS_FILE or a fresh `bd export` (into a temp file, then gone)."""
    src = os.environ.get("ECOSCRIBE_GATE_TICKETS_FILE")
    if src:
        try:
            raw = Path(src).read_text(encoding="utf-8")
        except OSError as e:
            raise Unavailable(f"the ticket file {src} can't be read ({e.strerror}).")
    else:
        bd = shutil.which("bd")
        if not bd:
            raise Unavailable("bd isn't installed, so the private tickets can't be read to check for copied text.")
        fd, tmp = tempfile.mkstemp(prefix="ecoscribe-gate-", suffix=".jsonl")
        os.close(fd)
        try:
            r = subprocess.run([bd, "export", "-o", tmp], cwd=REPO, capture_output=True, text=True,
                               encoding="utf-8", errors="ignore", timeout=120)
            if r.returncode != 0:
                raise Unavailable(f"`bd export` failed (exit {r.returncode}), so the private tickets can't be "
                                  f"checked: {r.stderr.strip()[-300:]}")
            raw = Path(tmp).read_text(encoding="utf-8")
        except subprocess.TimeoutExpired:
            raise Unavailable("`bd export` took over 2 minutes, so the private tickets can't be checked.")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    out = []
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("id"):
            out.append(rec)
    if not out:
        raise Unavailable("the ticket store came back empty, so nothing checks for copied ticket text.")
    return out


def ticket_pieces() -> dict[str, str]:
    """6-word piece -> 'ticket-id field' for the private free text of every ticket (titles stay out)."""
    if "tickets" not in _cache:
        where: dict[str, str] = {}
        for rec in ticket_records():
            texts = [(f, rec.get(f)) for f in TICKET_FIELDS]
            texts += [("comment", c.get("text")) for c in rec.get("comments") or [] if isinstance(c, dict)]
            for field, t in texts:
                if isinstance(t, str) and t.strip():
                    for p in pieces(t):
                        where.setdefault(p, f"{rec['id']} {field}")
        _cache["tickets"] = where
    return _cache["tickets"]  # type: ignore[return-value]


def public_words() -> str:
    """The repo's own tracked files (not the ticket export) as one word stream: already public."""
    if "public" not in _cache:
        try:
            files = _git("ls-files", "-z").split("\0")
        except (OSError, subprocess.CalledProcessError):
            files = []
        chunks = []
        for name in files:
            if not name or name.startswith(".beads/"):
                continue
            f = REPO / name
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                chunks.append(" ".join(words(f.read_text(encoding="utf-8", errors="ignore"))))
            except OSError:
                pass
        _cache["public"] = " " + " \n ".join(chunks) + " "
    return _cache["public"]  # type: ignore[return-value]


def speech_hits(text: str) -> list[str]:
    """The 6-word pieces of a text that are the user's own dictations or meetings. Raises Unavailable."""
    return sorted(pieces(text) & speech_pieces())


def ticket_copies(text: str) -> dict[str, list[str]]:
    """'ticket-id field' -> the pieces of a text copied from it (and not public in the repo's files anyway)."""
    tickets = ticket_pieces()
    copied = sorted(p for p in pieces(text) if p in tickets)
    if copied:
        public = public_words()
        copied = [p for p in copied if f" {p} " not in public]
    out: dict[str, list[str]] = {}
    for p in copied:
        out.setdefault(tickets[p], []).append(p)
    return out


def private_hits(text: str) -> list[str]:
    """Speech and ticket-copy hits in a text, by where they come from. Raises Unavailable."""
    if gate_ci():
        return []
    out = []
    speech = speech_hits(text)
    if speech:
        out.append(f"speech check: {len(speech)} piece(s) of your own dictations or meetings "
                   f"(first starts '{hint(speech[0])}')")
    for where, ps in sorted(ticket_copies(text).items()):
        out.append(f"ticket-copy check: {len(ps)} piece(s) copied from the private text of {where}")
    return out


def check_text(text: str) -> list[str]:
    """Every check on a text about to go public; the hits by where. Raises Unavailable (fail closed)."""
    return gitleaks_text(text) + private_hits(text)


# --- branch names (pre-push) -----------------------------------------------------------------------

def pushed_names(refs: str) -> list[str]:
    """Branch and tag names in git's pre-push lines `<local ref> <local sha> <remote ref> <remote sha>`."""
    names = []
    for line in refs.splitlines():
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"}:  # a delete publishes no new name
            continue
        for ref in (parts[0], parts[2]):
            name = re.sub(r"^refs/(heads|tags)/", "", ref)
            if name and name != "HEAD" and name not in names:
                names.append(name)
    return names


def check_names(names: list[str]) -> list[str]:
    """A branch name goes public too: as it is (gitleaks) and as words split on - _ / . (pieces)."""
    if not names:
        return []
    text = "\n".join(names) + "\n\n" + "\n".join(re.sub(r"[-_/.]+", " ", n) for n in names)
    return [f"branch name: {h}" for h in check_text(text)]


def current_branch() -> list[str]:
    try:
        name = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError):
        return []
    return [name] if name and name != "HEAD" else []


def _arg(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        return argv[i + 1] if i + 1 < len(argv) else ""
    return None


def main_text(argv: list[str]) -> int:
    path = _arg(argv, "--file")
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore") if path else sys.stdin.read()
    except OSError as e:
        print(f"privacy guard: can't read {path} ({e.strerror}).", file=sys.stderr)
        return 1
    try:
        found = check_text(text)
    except Unavailable as e:
        print(f"privacy guard: blocked, a check can't run: {e}", file=sys.stderr)
        return 1
    if found:
        print("privacy guard: this text can't go public (the repo, its PRs, issues and releases are public):\n  - "
              + "\n  - ".join(found) + "\nRewrite it in your own words: describe the change and what the user wants, "
              "never copy dictations, meetings or private ticket text.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "pre-commit"
    if mode not in ("pre-commit", "pre-push", "history", "text"):
        print(__doc__)
        return 2
    if mode == "text":
        return main_text(argv)
    bad = 0
    if mode == "pre-push":
        refs_file = _arg(argv, "--refs")
        try:
            refs = Path(refs_file).read_text(encoding="utf-8", errors="ignore") if refs_file else ""
        except OSError:
            refs = ""
        names = pushed_names(refs) if refs.strip() else ([] if refs_file else current_branch())
        try:
            hits = check_names(names)
        except Unavailable as e:
            print(f"privacy guard: blocked, the branch-name check can't run: {e}", file=sys.stderr)
            return 1
        if hits:
            print("privacy guard: a branch or tag name you're pushing can't go public:\n  - " + "\n  - ".join(hits)
                  + "\nRename it (git branch -m <new-name>) and push again.", file=sys.stderr)
            bad = 1
    text, log_opts = outgoing(mode)
    if mode == "pre-push" and not text.strip():
        return bad  # no new commits leave this computer
    bad = run_gitleaks(mode, log_opts) or bad
    found = leaked(personal_texts(data_dirs()), text, allowed_pieces())
    if found:
        print(f"privacy guard: {len(found)} piece(s) of your own dictations or meetings are in what you're "
              f"about to {'commit' if mode == 'pre-commit' else 'push'} (first starts '{hint(found[0])}'). "
              "Take them out; tests and docs use invented text.", file=sys.stderr)
        bad = 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
