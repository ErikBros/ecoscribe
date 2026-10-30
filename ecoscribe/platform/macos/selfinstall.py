"""The Mac's installer for selfupdate.py: the new Ecoscribe.app from the release's .dmg, swapped in for this one.

command() writes a small sh script next to the download and returns how to start it. Started detached as
the app quits, the script:

1. waits for every process of this app (the window, a worker) to end, at most WAIT_S;
2. mounts the .dmg read-only, hidden from Finder;
3. checks the new app against this one's designated requirement (same bundle id, same certificate): macOS
   keeps the permission grants (mic, Accessibility, Input Monitoring, System Audio) only for that, and a
   file signed by anyone else is never installed;
4. copies it next to this one and swaps the two with renames, so a failure leaves the old app in place;
5. unmounts and, unless the install ran at Quit, opens Ecoscribe again.

The new copy's start tells selfupdate.after_start whether it worked (the old version again = it didn't).
A download by urllib has no quarantine flag, so Gatekeeper doesn't stop the self-signed app.
"""
from __future__ import annotations

import logging
import re
import shlex
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
WAIT_S = 120


def app_bundle(exe: str | None = None) -> Path | None:
    """This Ecoscribe.app (from .../Ecoscribe.app/Contents/MacOS/Ecoscribe), or None when not run from one."""
    p = Path(exe or sys.executable).resolve()
    app = p.parents[2] if len(p.parents) > 2 else None
    if app is None or app.suffix != ".app" or p.parent.name != "MacOS":
        return None
    return app


def requirement(app: Path) -> str | None:
    """The app's designated requirement (`identifier "..." and certificate leaf = H"..."`), or None if unsigned."""
    try:
        out = subprocess.run(["codesign", "-d", "-r-", str(app)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^(?:# )?designated => (.+)$", out.stdout + out.stderr, re.M)  # "# ": ad hoc, implicit (cdhash)
    return m.group(1).strip() if m else None


def script(dmg: Path, app: Path, req: str, log_path: Path, relaunch: bool) -> str:
    q = shlex.quote
    return f"""#!/bin/sh
# Ecoscribe self-update (selfinstall.py). Runs after the app quits.
dmg={q(str(dmg))}
app={q(str(app))}
req={q(req)}
exec >>{q(str(log_path))} 2>&1
echo "$(date '+%F %T') installing $dmg into $app"
i=0
while pgrep -f "$app/Contents/MacOS/" >/dev/null && [ $i -lt {WAIT_S} ]; do sleep 1; i=$((i+1)); done
if pgrep -f "$app/Contents/MacOS/" >/dev/null; then echo "Ecoscribe still running after {WAIT_S} s: not installed"; exit 1; fi
mnt=$(mktemp -d /tmp/ecoscribe-update.XXXXXX) || exit 1
ok=0
if hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$mnt" "$dmg"; then
  new="$mnt/Ecoscribe.app"
  if codesign --verify --deep --strict -R="$req" "$new"; then
    rm -rf "$app.new" "$app.old"
    if ditto "$new" "$app.new" && mv "$app" "$app.old" && mv "$app.new" "$app"; then
      rm -rf "$app.old"; ok=1
    fi
  else
    echo "the new app isn't signed like this one: not installed"
  fi
  hdiutil detach "$mnt" -quiet || hdiutil detach "$mnt" -force -quiet
fi
rmdir "$mnt" 2>/dev/null
if [ $ok = 1 ]; then echo "installed"; else
  echo "not installed"; [ -d "$app" ] || mv "$app.old" "$app"; rm -rf "$app.new"
fi
{'open "$app"' if relaunch else ': # installed at Quit: stays closed'}
"""


def command(dmg: Path, updates_dir: Path, relaunch: bool, exe: str | None = None) -> list[str] | None:
    """["/bin/sh", <script>] to start detached, or None when this copy can't be replaced (not an .app, unsigned)."""
    app = app_bundle(exe)
    req = requirement(app) if app else None
    if not app or not req:
        log.warning("self-update: not an installed, signed Ecoscribe.app (%s)", app)
        return None
    s = Path(updates_dir) / "install.sh"
    s.write_text(script(Path(dmg), app, req, Path(updates_dir) / "install.log", relaunch), encoding="utf-8")
    return ["/bin/sh", str(s)]
