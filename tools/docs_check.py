#!/usr/bin/env python3
"""Docs check (dictado-xr3v): a PR that changes what the user sees also changes the user guides in docs/,
or says why not in its body, on a line of its own: "docs: not needed, because <reason>".

Run by the pr-shape workflow, and by hand:

    git diff --name-only origin/main...HEAD | PR_BODY="..." python3 tools/docs_check.py
"""
from __future__ import annotations
import os
import re
import sys

# What the user sees: the window, the pill, the tray, the prompt box and the notices.
UI = ("ecoscribe/web/", "ecoscribe/notice.py", "ecoscribe/meetui.py",
      "ecoscribe/platform/windows/pillart.py", "ecoscribe/platform/windows/trayicon.py",
      "ecoscribe/platform/windows/shell.py", "ecoscribe/platform/macos/shell.py")
NOT_GUIDES = {"docs/look-checklist.md"}  # in docs/ but for whoever changes the look, not for users
REASON = re.compile(r"^\W*docs:\s*not needed,?\s*because\s+\S", re.IGNORECASE | re.MULTILINE)


def check(files: list[str], body: str) -> str | None:
    """None when the PR is fine, else what's wrong."""
    ui = [f for f in files if f.startswith(UI)]
    if not ui:
        return None
    if any(f.startswith("docs/") and f not in NOT_GUIDES for f in files):
        return None
    if REASON.search(body or ""):
        return None
    shown = ", ".join(ui[:3]) + (f" and {len(ui) - 3} more" if len(ui) > 3 else "")
    return (f"This PR changes what the user sees ({shown}) but no user guide in docs/. "
            "Update the guide, or add a line to the PR body: 'docs: not needed, because <reason>'.")


def main() -> int:
    files = [line.strip() for line in sys.stdin if line.strip()]
    err = check(files, os.environ.get("PR_BODY", ""))
    if err:
        print(f"::error::{err}")
        return 1
    print("docs check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
