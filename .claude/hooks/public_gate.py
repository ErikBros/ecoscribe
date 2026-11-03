#!/usr/bin/env python3
"""Public gate (dictado-trtz.1): a Claude Code PreToolUse hook on Bash. The repo is public, and so is
every PR, comment, review, issue and release note: before a command publishes text, the text gets the
same privacy check as a commit (tools/privacy_guard.py text: gitleaks, the user's own dictations,
copies of private ticket text).

- `gh pr create|edit|comment|review`, `gh issue create|edit|comment`, `gh release create|edit`, and
  `gh api` with a body/title/notes field or --input: the whole command (inline --body, heredocs) plus
  every file it names with --body-file/--notes-file/-F/--input/field=@file is checked. A body from
  stdin (`-`) can't be checked, so it's blocked: write the text to a file first.
- `git commit|push --no-verify` (or `git commit -n`, or `git -c core.hooksPath=...`) skips the git
  hooks that run the same guard: blocked.
- The tickets are private: `bd dolt remote add|set-url`, `bd config set sync.remote`, `bd init --remote`
  with any URL but the private ErikBros/ecoscribe-tickets repo, and `bd bootstrap` while sync.remote
  isn't that repo (it would wire this public repo's origin), are blocked.
- Anything else passes at once (no heavy imports, nothing runs).

Reads the hook JSON on stdin ({"tool_input": {"command": ...}, "cwd": ...}); exit 2 with the reason on
stderr blocks the command and shows the reason to Claude, exit 0 lets it run.
"""
from __future__ import annotations

import json
import os
import re
import sys

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "tools", "privacy_guard.py")

PUBLISH = re.compile(r"\bgh(?:\.exe)?\s+(?:(?:-R|--repo)(?:\s+|=)\S+\s+)?(?:pr\s+(?:create|edit|comment|review|(?P<merge>merge))"
                     r"|issue\s+(?:create|edit|comment)|release\s+(?:create|edit)|(?P<api>api))\b")
MERGE_TEXT = re.compile(r"\s(?:--body|-b|--subject|-t|--body-file|-F)(?:\s|=)")
GIT_HINT = re.compile(r"\bgit\b")
API_FIELDS = re.compile(r"(?:^|\s)(?:-[fF]|--field|--raw-field)(?:\s+|=)['\"]?(?:body|title|notes|name|message)=|"
                        r"(?:^|\s)--input\b|\b(?:body|title)\s*:")
HEREDOC = re.compile(r"(<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\2)([^\n]*)\n.*?\n[ \t]*\3[ \t]*(?=\n|$)", re.S)
BD_HINT = re.compile(r"\bbd\b")
TICKET_REMOTE_HINT = re.compile(r"\bbd\b.*\b(remote|bootstrap|sync\.remote)\b", re.S)
PRIVATE_TICKETS = re.compile(r"[/:]ErikBros/ecoscribe-tickets(?:\.git)?/?$", re.I)
BD_VALUE_FLAGS = {"--actor", "--db", "--database", "-C", "--directory", "--dolt-auto-commit"}
SEP = set("();<>|&")
BODY_FILE_FLAGS = {"--body-file", "--notes-file", "-F", "--input"}
STDIN = {"-", "/dev/stdin"}


def tokens(cmd: str) -> list[str] | None:
    import shlex
    try:
        lex = shlex.shlex(HEREDOC.sub(r"\1\4", cmd), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return None


def segments(toks: list[str]) -> list[list[str]]:
    """Simple commands: tokens between shell operators (&& ; | ( ) and the like)."""
    out, cur = [], []
    for t in toks:
        if t and set(t) <= SEP:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def _is(tok: str, name: str) -> bool:
    return tok == name or tok.endswith("/" + name) or tok in (name + ".exe",)


def skips_hooks(toks: list[str]) -> str | None:
    """Why a git commit/push in these tokens skips the privacy hooks, or None."""
    for seg in segments(toks):
        for i, t in enumerate(seg):
            if not _is(t, "git"):
                continue
            j, sub = i + 1, None
            while j < len(seg):
                a = seg[j]
                if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and j + 1 < len(seg):
                    if a == "-c" and seg[j + 1].lower().startswith("core.hookspath"):
                        return "it points git's core.hooksPath somewhere else, which skips the privacy hooks"
                    j += 2
                elif a.startswith("-"):
                    if a.lower().startswith("--config-env") and "hookspath" in a.lower():
                        return "it points git's core.hooksPath somewhere else, which skips the privacy hooks"
                    j += 1
                else:
                    sub = a
                    break
            if sub not in ("commit", "push"):
                continue
            args = seg[j + 1:]
            if "--no-verify" in args:
                return f"`git {sub} --no-verify` skips the privacy hooks"
            if sub == "commit":
                k = 0
                while k < len(args):
                    a = args[k]
                    if a == "--":
                        break
                    if re.fullmatch(r"-[A-Za-z]+", a):
                        for ch in a[1:]:
                            if ch == "n":
                                return "`git commit -n` (--no-verify) skips the privacy hooks"
                            if ch in "mFcCtuS":
                                if a.endswith(ch) and ch in "mFcCt":
                                    k += 1  # the next token is this option's value
                                break
                    elif a in ("--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author",
                               "--date", "--fixup", "--squash", "--trailer"):
                        k += 1
                    k += 1
    return None


def body_files(toks: list[str], cwd: str) -> list[str]:
    """Files a publishing gh command reads its text from (absolute paths); '-' for stdin."""
    out = []
    base = cwd
    for seg in segments(toks):
        if len(seg) >= 2 and seg[0] == "cd":
            base = os.path.normpath(os.path.join(base, os.path.expanduser(seg[1])))
            continue
        for i, t in enumerate(seg):
            if not _is(t, "gh"):
                continue
            rest = seg[i + 1:]
            words = [w for w in rest[:4] if not w.startswith("-")]
            api = bool(words) and words[0] == "api"
            for k, a in enumerate(rest):
                val = None
                if a in BODY_FILE_FLAGS and k + 1 < len(rest):
                    val = rest[k + 1]
                elif "=" in a and a.split("=", 1)[0] in BODY_FILE_FLAGS:
                    val = a.split("=", 1)[1]
                if api and a in ("-F", "--field") and k + 1 < len(rest):
                    # gh api -F key=@file reads the value from a file; key=value is inline (in the command)
                    field = rest[k + 1]
                    val = field.split("=@", 1)[1] if "=@" in field else None
                if val is None:
                    continue
                if val in STDIN:
                    out.append("-")
                else:
                    out.append(os.path.normpath(os.path.join(base, os.path.expanduser(val))))
    return out


def scrub(cmd: str, files: list[str]) -> str:
    """The command without the paths it names (folders aren't text that goes public; the files are read)."""
    cmd = re.sub(r"(^|[;&|(\n]\s*)cd\s+(\"[^\"]*\"|'[^']*'|\S+)", r"\1cd <dir>", cmd)
    for f in files:
        for v in {f, os.path.basename(f)}:
            if len(v) > 2:
                cmd = cmd.replace(v, "<file>")
    return cmd


def is_private_tickets(url: str) -> bool:
    return bool(PRIVATE_TICKETS.search(url or ""))


def configured_sync_remote(cwd: str) -> str:
    """beads' sync.remote here ('' if unset or unreadable): where `bd bootstrap` would clone and push."""
    import subprocess
    try:
        r = subprocess.run(["bd", "config", "get", "sync.remote"], cwd=cwd, capture_output=True, text=True,
                           timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"\S*ecoscribe-tickets\S*", r.stdout)
    return m.group(0) if m and r.returncode == 0 else ""


def ticket_remote_risk(toks: list[str], sync_remote) -> str | None:
    """Why a bd command would point the private tickets at a remote other than the private tickets repo."""
    for seg in segments(toks):
        for i, t in enumerate(seg):
            if not _is(t, "bd"):
                continue
            args, pos, k = seg[i + 1:], [], 0
            while k < len(args):
                a = args[k]
                if a in BD_VALUE_FLAGS:
                    k += 2
                    continue
                if not a.startswith("-"):
                    pos.append(a)
                k += 1
            if pos[:3] in (["dolt", "remote", "add"], ["dolt", "remote", "set-url"]):
                url = pos[4] if len(pos) > 4 else ""
                if not is_private_tickets(url):
                    return f"`bd dolt remote {pos[2]}` with {url or 'no URL'} would push the private tickets there"
            elif pos[:3] == ["config", "set", "sync.remote"]:
                url = pos[3] if len(pos) > 3 else ""
                if not is_private_tickets(url):
                    return f"`bd config set sync.remote {url}` would sync the private tickets there"
            elif pos[:1] == ["init"]:
                url = next((args[j + 1] for j, a in enumerate(args[:-1]) if a == "--remote"), None)
                url = next((a.split("=", 1)[1] for a in args if a.startswith("--remote=")), url)
                if url is not None and not is_private_tickets(url):
                    return f"`bd init --remote {url}` would sync the private tickets there"
            elif pos[:1] == ["bootstrap"] and "--dry-run" not in args:
                if not is_private_tickets(sync_remote()):
                    return ("`bd bootstrap` without sync.remote set to the private tickets repo wires the code "
                            "repo's origin (public) for push. First: bd config set sync.remote "
                            "<the ErikBros/ecoscribe-tickets URL>")
    return None


def block(reason: str) -> int:
    print(f"public gate: blocked. {reason}", file=sys.stderr)
    return 2


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    cmd = ((event.get("tool_input") or {}).get("command")) or ""
    if not isinstance(cmd, str) or not cmd:
        return 0
    publish = [m for m in PUBLISH.finditer(cmd)
               if not (m.group("api") and not API_FIELDS.search(cmd[m.end():]))
               and not (m.group("merge") and not MERGE_TEXT.search(cmd[m.end():]))]
    if not publish and not GIT_HINT.search(cmd) and not BD_HINT.search(cmd):
        return 0
    toks = tokens(cmd)
    if BD_HINT.search(cmd):
        cwd = event.get("cwd") or os.getcwd()
        why = ticket_remote_risk(toks, lambda: configured_sync_remote(cwd)) if toks is not None else (
            "the command can't be read reliably" if TICKET_REMOTE_HINT.search(cmd) else None)
        if why:
            return block(f"{why}. The tickets are private and this code repo is public: their Dolt remote must be "
                         "the private ErikBros/ecoscribe-tickets repo, never the code repo (ignore beads' "
                         "'repair: bd dolt remote add origin ...' hint, it points at the public repo).")
    if GIT_HINT.search(cmd):
        if toks is None:
            if re.search(r"\bgit\b[^\n;&|]*\b(commit|push)\b[^\n;&|]*\s--no-verify\b", cmd):
                return block("`--no-verify` skips the privacy hooks, which check every commit and push of this "
                             "public repo. Fix what the hook found instead and commit again.")
        else:
            why = skips_hooks(toks)
            if why:
                return block(f"{why}. The hooks check every commit and push of this public repo for personal "
                             "text and secrets; fix what they find instead of skipping them.")
    if not publish:
        return 0
    cwd = event.get("cwd") or os.getcwd()
    files = body_files(toks or [], cwd)
    if toks is None:
        files += [os.path.normpath(os.path.join(cwd, m.group(2))) for m in
                  re.finditer(r"(--body-file|--notes-file|--input|-F)[ =]['\"]?([^\s'\"]+)", cmd)]
    parts = [scrub(cmd, [f for f in files if f != "-"])]
    for f in files:
        if f == "-":
            return block("the text comes from stdin (`-`), which this check can't read. Write it to a file in "
                         "one command, then pass it with --body-file/--notes-file <file> in the next.")
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                parts.append(fh.read())
        except OSError:
            return block(f"can't read {f} to check it before it goes public. Write the text to that file in "
                         "one command, then run the gh command in the next one.")
    import subprocess
    try:
        r = subprocess.run([sys.executable, GUARD, "text"], input="\n\n".join(parts), capture_output=True,
                           text=True, encoding="utf-8", errors="ignore", timeout=110)
    except subprocess.TimeoutExpired:
        return block("the privacy check took too long, so nothing was checked. Try again.")
    except OSError as e:
        return block(f"the privacy check couldn't start ({e}).")
    if r.returncode != 0:
        return block("this text goes public (the repo's PRs, comments, issues and releases are public) and the "
                     "privacy check stopped it:\n" + (r.stderr.strip() or r.stdout.strip()) +
                     "\nRewrite the text in your own words (Ticket / What changed / Why: 'the user wants...' / "
                     "Tests / docs line); never paste dictations, meetings or private ticket text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
