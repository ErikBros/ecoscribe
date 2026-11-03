#!/usr/bin/env python3
"""The release step both computers use (dictado-trtz.3): no release goes out without its two downloads
being tracked, and the Mac download never gets forgotten again.

    python3 tools/release.py [X.Y.Z] --notes FILE [--asset PATH] [--platform windows|mac] [--dry-run]

X.Y.Z defaults to ecoscribe/__init__.py, the platform to this computer (WSL counts as Windows).

Windows (makes the release, after tools/build.py --installer --install):
  1. python3 tools/privacy_guard.py text --file NOTES     the notes are public: no names, quotes, paths
  2. gh release create vX.Y.Z Ecoscribe-Setup-X.Y.Z.exe --target main --latest
        --title "Ecoscribe X.Y.Z" --notes-file NOTES
  3. bd create "Mac download for vX.Y.Z" (P1) and bd sync: the Mac session's start check sees it
Mac (adds its download, after tools/build_mac.py):
  1. gh release view vX.Y.Z                                 the Windows session makes the release
  2. gh release upload vX.Y.Z Ecoscribe-X.Y.Z.dmg --clobber
  3. bd close the open "Mac download for vX.Y.Z" ticket and bd sync

--dry-run prints every command and runs none. The installer is looked for in the Windows build folder
(%USERPROFILE%\\ecoscribe-build), the .dmg in build/mac; --asset names another file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GH_REPO = "ErikBros/ecoscribe"
GH_USER = "ErikBros"
VERSION = re.compile(r"\d+\.\d+\.\d+")
UNKNOWN_MODE = 2  # privacy_guard.py's exit code for a mode it doesn't have


def tree_version() -> str:
    ns: dict = {}
    exec((REPO / "ecoscribe" / "__init__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def this_computer() -> str:
    if sys.platform == "darwin":
        return "mac"
    return "windows"  # Windows Python, or WSL (the Windows session); a plain Linux box says --platform


def mac_ticket_title(version: str) -> str:
    return f"Mac download for v{version}"


def windows_build_dir() -> Path | None:
    """%USERPROFILE%\\ecoscribe-build, seen from this Python (Windows, or WSL through wslpath)."""
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE", Path.home())) / "ecoscribe-build"
    try:
        win = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"], capture_output=True, text=True,
                             timeout=10, cwd="/mnt/c").stdout.strip()
        unix = subprocess.run(["wslpath", "-u", win], capture_output=True, text=True, timeout=10).stdout.strip()
        return Path(unix) / "ecoscribe-build" if win and unix else None
    except (OSError, subprocess.SubprocessError):
        return None


def default_asset(platform: str, version: str) -> Path:
    if platform == "mac":
        return REPO / "build" / "mac" / f"Ecoscribe-{version}.dmg"
    folder = windows_build_dir() or Path("%USERPROFILE%") / "ecoscribe-build"
    return folder / f"Ecoscribe-Setup-{version}.exe"


class Shell:
    """Runs commands (or only prints them, with dry_run). Tests replace `execute`."""

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.env = None if dry_run else self._gh_env()

    @staticmethod
    def _gh_env() -> dict:
        env = dict(os.environ)
        try:
            tok = subprocess.run(["gh", "auth", "token", "--user", GH_USER], capture_output=True, text=True,
                                 timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            tok = ""
        if tok:
            env["GH_TOKEN"] = tok
        return env

    def execute(self, cmd: list[str]) -> tuple[int, str]:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env, stdin=subprocess.DEVNULL)
        if r.stderr.strip():
            print(r.stderr.strip(), file=sys.stderr)
        return r.returncode, r.stdout

    def __call__(self, cmd: list[str], note: str = "") -> tuple[int, str]:
        print("+ " + shlex.join(cmd) + (f"    # {note}" if note else ""), flush=True)
        if self.dry_run:
            return 0, ""
        return self.execute(cmd)


def loud(msg: str) -> None:
    bar = "!" * 72
    print(f"\n{bar}\n{msg}\n{bar}\n", flush=True)


def open_tickets(sh: Shell, title: str) -> list[str]:
    code, out = sh(["bd", "list", "--status", "open,in_progress", "--title", title, "--json", "--brief"],
                   note="find the ticket")
    try:
        rows = json.loads(out) if code == 0 and out.strip() else []
    except ValueError:
        rows = []
    return [r["id"] for r in rows if isinstance(r, dict) and r.get("title") == title]


def release_windows(sh: Shell, version: str, asset: Path, notes: Path | None) -> int:
    tag = f"v{version}"
    notes_arg = str(notes) if notes else "NOTES.md"
    code, _ = sh([sys.executable, "tools/privacy_guard.py", "text", "--file", notes_arg],
                 note="the notes are public")
    if code == UNKNOWN_MODE:
        loud("WARNING: tools/privacy_guard.py has no 'text' mode in this tree, so the release notes were NOT\n"
             "checked. Read them yourself now: no names, no quotes of what the user said, no personal paths.")
    elif code != 0:
        print("release: the privacy guard stopped the release notes (above). Fix them and run again.")
        return 1
    code, _ = sh(["gh", "release", "create", tag, str(asset), "-R", GH_REPO, "--target", "main", "--latest",
                  "--title", f"Ecoscribe {version}", "--notes-file", notes_arg])
    if code != 0:
        print(f"release: gh release create {tag} failed (above).")
        return 1
    title = mac_ticket_title(version)
    if open_tickets(sh, title):
        print(f"release: the ticket '{title}' is already open.")
    else:
        code, _ = sh(["bd", "create", title, "-p", "1", "-t", "task", "-l", "mac,release", "-d",
                      f"Release {tag} has the Windows installer and no Mac download. On the Mac: tools/build_mac.py, "
                      f"install it, python3 tools/record_install.py mac, then python3 tools/release.py {version} "
                      "(uploads the .dmg and closes this ticket)."])
        if code != 0:
            print(f"release: warning: the ticket '{title}' was not created; create it by hand.")
    if sh(["bd", "sync"])[0] != 0:
        print("release: warning: bd sync failed; run it before ending the session.")
    print(f"{'(dry run) ' if sh.dry_run else ''}Released {tag} with the Windows installer; the Mac download is ticket '{title}'.")
    return 0


def release_mac(sh: Shell, version: str, asset: Path) -> int:
    tag = f"v{version}"
    code, _ = sh(["gh", "release", "view", tag, "-R", GH_REPO, "--json", "tagName"], note="the Windows session makes it")
    if code != 0:
        print(f"release: there is no release {tag} yet. The Windows session makes it (tools/release.py there); "
              "upload the .dmg after that.")
        return 1
    code, _ = sh(["gh", "release", "upload", tag, str(asset), "-R", GH_REPO, "--clobber"])
    if code != 0:
        print(f"release: the upload to {tag} failed (above).")
        return 1
    title = mac_ticket_title(version)
    ids = open_tickets(sh, title) or (["<its id>"] if sh.dry_run else [])
    for i in ids:
        sh(["bd", "close", i, "--reason", f"{asset.name} uploaded to release {tag}"])
    if not ids:
        print(f"release: no open ticket '{title}' to close (fine if there never was one).")
    if sh(["bd", "sync"])[0] != 0:
        print("release: warning: bd sync failed; run it before ending the session.")
    print(f"{'(dry run) ' if sh.dry_run else ''}Release {tag} has the Mac download.")
    return 0


def main(argv: list[str] | None = None, shell: Shell | None = None) -> int:
    ap = argparse.ArgumentParser(description="Release step for Windows (creates) and Mac (adds the .dmg).")
    ap.add_argument("version", nargs="?", help="X.Y.Z (default: ecoscribe/__init__.py)")
    ap.add_argument("--platform", choices=("windows", "mac"), help="default: this computer")
    ap.add_argument("--notes", type=Path, help="release notes file (Windows; required unless --dry-run)")
    ap.add_argument("--asset", type=Path, help="the installer or .dmg (default: the build folder)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, run none")
    a = ap.parse_args(argv)
    version = (a.version or tree_version()).lstrip("v")
    if not VERSION.fullmatch(version):
        ap.error(f"version {version!r} is not X.Y.Z")
    platform = a.platform or this_computer()
    asset = a.asset or default_asset(platform, version)
    want = f"Ecoscribe-Setup-{version}.exe" if platform == "windows" else f"Ecoscribe-{version}.dmg"
    if asset.name != want:  # the apps' self-update and tools/in_step.py look for exactly this name
        print(f"release: the {platform} download must be named {want}, not {asset.name}.")
        return 1
    if not a.dry_run:
        if not asset.is_file():
            print(f"release: {asset} doesn't exist; build it first or pass --asset.")
            return 1
        if platform == "windows" and not (a.notes and a.notes.is_file()):
            print("release: --notes FILE is needed: what's new in this version, in plain words.")
            return 1
    sh = shell or Shell(a.dry_run)
    if platform == "windows":
        return release_windows(sh, version, asset, a.notes)
    return release_mac(sh, version, asset)


if __name__ == "__main__":
    sys.exit(main())
