#!/usr/bin/env python3
"""Record which Ecoscribe version is installed on this computer (dictado-trtz.3), for tools/in_step.py on
both computers.

    python3 tools/record_install.py windows|mac [--version X.Y.Z] [--dry-run]

Stores the bd memory installed-<platform> = "<version> <local time, YYYY-MM-DDTHH:MM>" (memories travel
with the tickets) and pushes it with `bd dolt push`. The version defaults to ecoscribe/__init__.py.

Windows: tools/release_gate.py calls record() after a passing install (tools/build.py --installer --install),
under Windows Python, so bd runs in WSL. Mac: tools/build_mac.py only builds, so the Mac session runs this
by hand after it installs the .app. A failure only warns: the install happened either way.
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLATFORMS = ("windows", "mac")
VERSION = re.compile(r"\d+\.\d+\.\d+")
WSL_UNC = re.compile(r"^\\\\wsl(?:\.localhost|\$)\\([^\\]+)\\(.*)$", re.IGNORECASE)


def tree_version() -> str:
    ns: dict = {}
    exec((REPO / "ecoscribe" / "__init__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def bd_cmd(args: list[str], repo: Path = REPO, platform: str = sys.platform) -> list[str]:
    """bd with these args. Under Windows Python with the checkout in WSL, bd is a WSL program: run it there,
    in the checkout, through a login shell (bd lives in ~/.local/bin)."""
    if platform == "win32":
        m = WSL_UNC.match(str(repo))
        if m:
            distro, rest = m.groups()
            return ["wsl.exe", "-d", distro, "--cd", "/" + rest.replace("\\", "/"), "--exec",
                    "bash", "-lc", 'bd "$@"', "bd", *args]
    return ["bd", *args]


def run(cmd: list[str], timeout: float = 60) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def record(platform: str, version: str | None = None, dry_run: bool = False, when: str | None = None) -> bool:
    """True when the memory was stored and pushed; prints a warning (never raises) otherwise."""
    version = version or tree_version()
    if platform not in PLATFORMS or not VERSION.fullmatch(version or ""):
        print(f"warning: install not recorded: platform {platform!r}, version {version!r}")
        return False
    value = f"{version} {when or time.strftime('%Y-%m-%dT%H:%M')}"
    steps = [("bd remember", ["remember", "--key", f"installed-{platform}", value]), ("bd dolt push", ["dolt", "push"])]
    for name, args in steps:
        cmd = bd_cmd(args)
        if dry_run:
            print("+ " + shlex.join(cmd))
            continue
        ok, msg = run(cmd)
        if not ok:
            why = msg.splitlines()[0][:120] if msg else "no message"
            print(f"warning: install not recorded for the other computer ({name} failed: {why}); "
                  f"run: python3 tools/record_install.py {platform} --version {version}")
            return False
    if not dry_run:
        print(f"Recorded: {platform} has {version} (bd memory installed-{platform}, pushed)")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("platform", choices=PLATFORMS)
    ap.add_argument("--version", help="default: ecoscribe/__init__.py")
    ap.add_argument("--dry-run", action="store_true", help="print the bd commands, run nothing")
    a = ap.parse_args(argv)
    record(a.platform, a.version, dry_run=a.dry_run)
    return 0  # an install that isn't recorded is a warning, not a failure


if __name__ == "__main__":
    sys.exit(main())
