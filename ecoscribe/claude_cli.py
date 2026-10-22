"""Claude through the user's own Claude Code login (dictado-crf; also for self-corrections and command mode).

A lean `claude -p` call: no tools, no MCP servers, no settings files, a short system prompt, the text on
stdin, JSON out. Measured 2.2-2.5 s for a short Haiku answer (radar FU5, 2026-10-21); the default
`claude -p` with its full setup takes 5-9 s, so the flags matter. Windows: Claude Code lives in WSL, so it
runs through `wsl.exe` in a login shell (PATH has ~/.local/bin). macOS: `claude` from a login shell.
[claude] command in config.toml replaces the default (a list, the claude arguments are added after it).
The text goes to Anthropic under that login, the same as pasting it into Claude.
"""
from __future__ import annotations

import json
import subprocess
import sys

LEAN = ["-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
        "--output-format", "json"]


class ClaudeError(RuntimeError):
    pass


def default_command() -> list[str]:
    if sys.platform == "win32":
        return ["wsl.exe", "-e", "bash", "-lc", 'exec claude "$@"', "claude"]
    return ["/bin/zsh" if sys.platform == "darwin" else "/bin/bash", "-lc", 'exec claude "$@"', "claude"]


def ask(text: str, system: str, model: str = "haiku", timeout: float = 60, command: list | None = None,
        run=subprocess.run) -> str:
    """Claude's answer to `text` (stdin) under `system`. Raises ClaudeError (with the reason) or
    subprocess.TimeoutExpired; callers fall back to doing nothing."""
    cmd = [str(x) for x in (command or default_command())] + LEAN + ["--model", model, "--system-prompt", system]
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        r = run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=timeout, **kw)
    except FileNotFoundError as e:
        raise ClaudeError(f"Claude Code isn't reachable ({e.filename})") from e
    out = (r.stdout or b"").decode("utf-8", "replace").strip()
    try:
        d = json.loads(out.splitlines()[-1]) if out else {}
    except ValueError:
        d = {}
    if r.returncode != 0 or d.get("is_error") or "result" not in d:
        why = d.get("result") or (r.stderr or b"").decode("utf-8", "replace").strip()[-300:] or f"exit code {r.returncode}"
        raise ClaudeError(f"Claude Code failed: {why}")
    return str(d["result"])
