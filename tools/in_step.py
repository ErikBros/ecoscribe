#!/usr/bin/env python3
"""Start check (dictado-trtz.3): are the Windows and the Mac computers in step?

    python3 tools/in_step.py

Runs first thing in every Claude session (the SessionStart hook in .claude/settings.json), on Windows
(from WSL) and on the Mac. It prints at most 5 short lines; when everything is fine, one line:
"Windows and Mac in step: 1.25.2 on both, tickets synced, nothing waiting."

What it checks:
1. Tickets: `bd dolt pull` works (else: run `bd sync` before any ticket work).
2. Work waiting: open PRs with every check green, and PRs open more than a day.
3. Downloads: recent releases without the Mac .dmg or the Windows .exe.
4. Versions: the bd memories installed-windows and installed-mac ("1.25.2 2026-11-03T08:02", written by
   tools/record_install.py after an install) against the newest release.
5. Tickets left open: an open ticket named in a merged PR's title, with nothing done on it since the merge
   (dictado-0agh): close it if the work is finished.
6. Safety: git hooks on (.beads/hooks), gitleaks installed, the local names file for the privacy guard,
   the mass-delete guard of ticket sync, the tickets repo still private. A failure is a "STOP:" line.

Every command has a short timeout and the checks run side by side (the whole run stays under 15 s).
A check that can't run says "couldn't check"; the exit code is always 0, so it never blocks a session.
Only the standard library: it runs under any python3.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GH_REPO = "ErikBros/ecoscribe"
TICKETS_REPO = "ErikBros/ecoscribe-tickets"
GH_USER = "ErikBros"
LOCAL_RULES = Path(os.environ.get("ECOSCRIBE_PRIVACY_RULES")
                   or Path.home() / ".config" / "ecoscribe" / "privacy-rules.toml")
MASS_DELETE_KEY = "sync.require_confirmation_on_mass_delete"
PLATFORMS = ("windows", "mac")
NAMES = {"windows": "Windows", "mac": "Mac"}
MAX_LINES = 5
RELEASES_LOOKED_AT = 10
VTAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
TICKET_ID = re.compile(r"\bdictado-[a-z0-9]+(?:\.\d+)*\b")
MERGED_LOOKED_AT = 30


@dataclass
class Result:
    ok: bool  # ran and exited 0
    out: str
    err: str  # stderr, or why it couldn't run ("timed out", "bd not found")


def run(cmd: list[str], timeout: float, env: dict | None = None) -> Result:
    """One command with a timeout; never raises."""
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return Result(False, "", f"{cmd[0]} not found")
    except subprocess.TimeoutExpired:
        return Result(False, "", "timed out")
    except OSError as e:
        return Result(False, "", str(e))
    err = r.stderr.strip()
    return Result(r.returncode == 0, r.stdout, err if err or r.returncode == 0 else f"exit {r.returncode}")


def this_computer() -> str:
    if sys.platform == "darwin":
        return "mac"
    if sys.platform == "win32":
        return "windows"
    try:
        if "microsoft" in Path("/proc/version").read_text(errors="ignore").lower():
            return "windows"  # WSL: the Windows session
    except OSError:
        pass
    return "linux"


# ---- what the checks found (gather fills it; lines() words it) ----

@dataclass
class Facts:
    computer: str = "linux"
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pull_error: str | None = None  # None: tickets pulled fine
    prs: list[dict] | None = None  # gh pr list --json rows; None: couldn't check
    releases: list[dict] | None = None  # [{"tag", "assets": [names], "draft", "prerelease"}]; None: couldn't check
    installed: dict | None = None  # {"windows": "1.25.2 2026-...", "mac": ...}; None: couldn't check
    tickets: list[dict] | None = None  # open + in-progress tickets (bd list --json rows); None: couldn't check
    merged: list[dict] | None = None  # recently merged PRs: {"number", "title", "mergedAt"}; None: couldn't check
    stop: list[str] = field(default_factory=list)  # safety problems, each naming its fix
    unchecked: list[str] = field(default_factory=list)  # "open PRs (timed out)"


def first_line(text: str, n: int = 70) -> str:
    line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return line[:n]


def pull_reason(err: str) -> str:
    e = err.lower()
    if "conflict" in e:
        return "a conflict"
    if "timed out" in e:
        return "timed out, offline?"
    if "bd not found" in e:
        return "bd is not installed"
    if any(w in e for w in ("could not resolve", "network", "connection", "unreachable", "no route",
                            "permission denied", "ssh")):
        return "offline or no access to the tickets repo"
    return first_line(err) or "unknown error"


def vtuple(v: str) -> tuple[int, int, int] | None:
    m = VTAG.fullmatch(v if v.startswith("v") else "v" + v)
    return tuple(int(x) for x in m.groups()) if m else None


def app_releases(releases: list[dict]) -> list[dict]:
    """The app's own releases (vX.Y.Z, not drafts, not pre-releases, not gpu-runtime-N), newest first."""
    rel = [r for r in releases if VTAG.fullmatch(r.get("tag", "")) and not r.get("draft") and not r.get("prerelease")]
    return sorted(rel, key=lambda r: vtuple(r["tag"]), reverse=True)[:RELEASES_LOOKED_AT]


def download_name(platform: str, version: str) -> str:
    return f"Ecoscribe-Setup-{version}.exe" if platform == "windows" else f"Ecoscribe-{version}.dmg"


def missing_downloads(releases: list[dict]) -> dict[str, list[str]]:
    """Per platform, the releases newer than the newest one that has its download (older gaps don't matter:
    the app only ever updates to the newest)."""
    out = {}
    for p in PLATFORMS:
        out[p] = []
        for r in app_releases(releases):
            if download_name(p, r["tag"][1:]) in r.get("assets", []):
                break
            out[p].append(r["tag"])
        out[p].reverse()  # oldest first reads naturally: v1.25.1, v1.25.2
    return out


def newest_version(releases: list[dict]) -> str | None:
    rel = app_releases(releases)
    return rel[0]["tag"][1:] if rel else None


def is_green(pr: dict) -> bool:
    checks = pr.get("statusCheckRollup") or []
    if not checks:
        return False
    for c in checks:
        if "state" in c and "conclusion" not in c:  # a commit status, not a check run
            if c.get("state") != "SUCCESS":
                return False
        elif c.get("status") != "COMPLETED" or c.get("conclusion") not in GREEN:
            return False
    return True


def age_days(pr: dict, now: datetime) -> float:
    try:
        created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return 0.0
    return (now - created).total_seconds() / 86400


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def pr_line(prs: list[dict], now: datetime) -> str | None:
    green = sorted(p["number"] for p in prs if not p.get("isDraft") and is_green(p))
    old = sorted(p["number"] for p in prs if age_days(p, now) >= 1)
    parts = []
    if green:
        parts.append(f"{plural(len(green), 'green PR', 'green PRs')} waiting to merge: "
                     + ", ".join(f"#{n}" for n in green))
    if old:
        parts.append(f"{plural(len(old), 'PR', 'PRs')} open over a day: " + ", ".join(f"#{n}" for n in old))
    return "; ".join(parts) + "." if parts else None


def downloads_line(releases: list[dict]) -> str | None:
    miss = missing_downloads(releases)
    parts = []
    for p in ("mac", "windows"):
        if miss[p]:
            has = "has" if len(miss[p]) == 1 else "have"
            parts.append(f"{plural(len(miss[p]), 'release', 'releases')} {has} no {NAMES[p]} download: "
                         + ", ".join(miss[p]))
    if not parts:
        return None
    hint = " GitHub builds the Mac one: re-run Actions > mac-release if it failed." if miss["mac"] else ""
    return "; ".join(parts) + "." + hint


def installed_version(installed: dict, platform: str) -> str | None:
    words = str(installed.get(f"installed-{platform}") or installed.get(platform) or "").split()
    return words[0] if words else None


def versions_line(installed: dict, releases: list[dict], computer: str) -> str | None:
    newest = newest_version(releases)
    if newest is None:
        return None
    parts, unrecorded = [], False
    for p in PLATFORMS:
        who = NAMES[p] + (" (this computer)" if p == computer else "")
        v = installed_version(installed, p)
        if v is None:
            parts.append(f"{who}: no install recorded")
            unrecorded = True
        elif vtuple(v) is None:
            parts.append(f"{who}: {v}?")
        elif vtuple(v) < vtuple(newest):
            parts.append(f"{who}: {v}")
        elif vtuple(v) > vtuple(newest):
            parts.append(f"{who}: {v}, not released")
    if not parts:
        return None
    return (", ".join(parts) + f"; newest release {newest}."
            + (" After an install: tools/record_install.py." if unrecorded else ""))


def _when(stamp) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def done_tickets(tickets: list[dict], merged: list[dict]) -> list[tuple[str, int]]:
    """(ticket id, PR number): open tickets a merged PR names in its title, untouched since that merge.
    A ticket updated after the merge (a note, more work on a second PR) is still being worked on."""
    by_id = {t.get("id"): t for t in tickets if t.get("id")}
    out = {}
    for pr in sorted(merged, key=lambda p: str(p.get("mergedAt") or "")):
        at = _when(pr.get("mergedAt"))
        if at is None:
            continue
        for tid in TICKET_ID.findall(pr.get("title") or ""):
            t = by_id.get(tid)
            upd = _when(t.get("updated_at")) if t else None
            if t is not None and (upd is None or upd <= at):
                out[tid] = pr.get("number")  # merges come oldest first: the newest PR naming it wins
    return sorted(out.items())


def done_line(tickets: list[dict], merged: list[dict]) -> str | None:
    done = done_tickets(tickets, merged)
    if not done:
        return None
    names = ", ".join(f"{tid} (#{n})" for tid, n in done)
    word = "ticket is" if len(done) == 1 else "tickets are"
    return f"{len(done)} open {word} named in a merged PR: {names}. Close if finished (bd close)."


def lines(f: Facts) -> list[str]:
    """The report: at most MAX_LINES lines; all fine is one line."""
    out = []
    if f.stop:
        out.append("STOP: " + "; ".join(f.stop) + ".")
    if f.pull_error is not None:
        where = " on this computer" if f.computer in PLATFORMS else ""
        out.append(f"Tickets didn't sync{where} ({pull_reason(f.pull_error)}): run bd sync before any ticket work.")
    if f.installed is not None and f.releases is not None:
        line = versions_line(f.installed, f.releases, f.computer)
        if line:
            out.append(line)
    if f.releases is not None:
        line = downloads_line(f.releases)
        if line:
            out.append(line)
    if f.prs is not None:
        line = pr_line(f.prs, f.now)
        if line:
            out.append(line)
    if f.tickets is not None and f.merged is not None:
        line = done_line(f.tickets, f.merged)
        if line:
            out.append(line)
    if f.unchecked:
        out.append("Couldn't check " + ", ".join(f.unchecked) + ".")
    if not out:
        newest = newest_version(f.releases or []) or "?"
        return [f"Windows and Mac in step: {newest} on both, tickets synced, nothing waiting."]
    if len(out) > MAX_LINES:
        out = out[:MAX_LINES - 1] + [" | ".join(out[MAX_LINES - 1:])]
    return out


# ---- gathering (each piece behind a small function, so tests swap them) ----

def gh_env() -> dict:
    """gh as the repo's account (other sessions on this computer may use another one)."""
    env = dict(os.environ)
    r = run(["gh", "auth", "token", "--user", GH_USER], 5)
    if r.ok and r.out.strip():
        env["GH_TOKEN"] = r.out.strip()
    return env


def check_bd(f: Facts) -> None:
    """Pull, then read the memories and the mass-delete guard: one after another (one Dolt database)."""
    r = run(["bd", "dolt", "pull"], 7)
    f.pull_error = None if r.ok else (r.err or "unknown error")
    if r.err == "bd not found":
        f.unchecked.append("installed versions (bd not found)")
        return
    r = run(["bd", "memories", "--json"], 3)
    try:
        f.installed = json.loads(r.out) if r.ok else None
    except ValueError:
        f.installed = None
    if not isinstance(f.installed, dict):
        f.installed = None
        f.unchecked.append(f"installed versions (bd memories: {first_line(r.err, 40) or 'no answer'})")
    r = run(["bd", "list", "--status", "open,in_progress", "--limit", "0", "--json"], 5)
    try:
        f.tickets = json.loads(r.out) if r.ok else None
    except ValueError:
        f.tickets = None
    if not isinstance(f.tickets, list):
        f.tickets = None
        f.unchecked.append(f"open tickets (bd list: {first_line(r.err, 40) or 'no answer'})")
    r = run(["bd", "config", "get", MASS_DELETE_KEY], 3)
    if not r.ok:
        f.unchecked.append(f"the mass-delete guard ({first_line(r.err, 40)})")
    elif r.out.strip().lower() != "true":
        f.stop.append(f"ticket sync may mass-delete without asking (bd config set {MASS_DELETE_KEY} true)")


def check_prs(env: dict) -> tuple[list[dict] | None, str]:
    r = run(["gh", "pr", "list", "-R", GH_REPO, "--state", "open",
             "--json", "number,createdAt,isDraft,statusCheckRollup"], 10, env)
    try:
        return (json.loads(r.out), "") if r.ok else (None, r.err)
    except ValueError:
        return None, "unreadable answer"


def check_merged(env: dict) -> tuple[list[dict] | None, str]:
    r = run(["gh", "pr", "list", "-R", GH_REPO, "--state", "merged", "--limit", str(MERGED_LOOKED_AT),
             "--json", "number,title,mergedAt"], 10, env)
    try:
        return (json.loads(r.out), "") if r.ok else (None, r.err)
    except ValueError:
        return None, "unreadable answer"


def check_releases(env: dict) -> tuple[list[dict] | None, str]:
    r = run(["gh", "api", f"repos/{GH_REPO}/releases?per_page=20"], 10, env)
    try:
        rows = json.loads(r.out) if r.ok else None
    except ValueError:
        return None, "unreadable answer"
    if rows is None:
        return None, r.err
    return [{"tag": x.get("tag_name", ""), "draft": x.get("draft"), "prerelease": x.get("prerelease"),
             "assets": [a.get("name", "") for a in x.get("assets", [])]} for x in rows], ""


def check_private(env: dict) -> tuple[bool | None, str]:
    r = run(["gh", "api", f"repos/{TICKETS_REPO}", "--jq", ".private"], 10, env)
    if not r.ok:
        return None, r.err
    return r.out.strip() == "true", ""


def check_local(f: Facts) -> None:
    """Safety checks that need no network."""
    r = run(["git", "config", "core.hooksPath"], 5)
    hooks = r.out.strip().replace("\\", "/").rstrip("/")
    if not (hooks == ".beads/hooks" or hooks.endswith("/.beads/hooks")):
        f.stop.append("git hooks are off, so the privacy guard doesn't run (git config core.hooksPath .beads/hooks)")
    if not shutil.which("gitleaks"):
        f.stop.append("gitleaks is not installed (macOS: brew install gitleaks; WSL: its release binary in ~/.local/bin)")
    if not LOCAL_RULES.is_file():
        f.stop.append("the privacy guard's local names file is missing (~/.config/ecoscribe/privacy-rules.toml, "
                      "see tools/privacy_guard.py)")


def short(err: str) -> str:
    e = first_line(err, 40)
    if "timed out" in e or "could not resolve" in e.lower() or "connect" in e.lower():
        return "offline?"
    return e or "no answer"


def gather() -> Facts:
    f = Facts(computer=this_computer())
    with ThreadPoolExecutor(max_workers=6) as pool:
        bd = pool.submit(check_bd, f)
        env = gh_env()
        prs = pool.submit(check_prs, env)
        rel = pool.submit(check_releases, env)
        priv = pool.submit(check_private, env)
        merged = pool.submit(check_merged, env)
        check_local(f)
        f.prs, err = prs.result()
        if f.prs is None:
            f.unchecked.append(f"open PRs ({short(err)})")
        f.releases, err = rel.result()
        if f.releases is None:
            f.unchecked.append(f"releases ({short(err)})")
        private, err = priv.result()
        if private is None:
            f.unchecked.append(f"that the tickets repo is private ({short(err)})")
        elif not private:
            f.stop.append(f"the tickets repo {TICKETS_REPO} is PUBLIC: make it private on GitHub now")
        f.merged, err = merged.result()
        if f.merged is None:
            f.unchecked.append(f"merged PRs ({short(err)})")
        bd.result()
    return f


def main() -> int:
    try:
        out = lines(gather())
    except Exception as e:  # informs, never blocks: no traceback at session start
        out = [f"In-step check failed ({type(e).__name__}: {first_line(str(e))}); run python3 tools/in_step.py."]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
