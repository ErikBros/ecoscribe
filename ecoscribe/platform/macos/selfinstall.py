"""The Mac's installer for selfupdate.py: the new Ecoscribe.app from the release's .dmg, swapped in for this one.

command() writes a small sh script next to the download and returns how to start it. Started detached as
the app quits, the script:

1. waits for the processes of this app to end, at most WAIT_S: after an Install now (relaunch) every one but the
   window (`--ui`), which shows the Installing screen meanwhile (dictado-9zeo.1); at Quit every one;
2. mounts the .dmg read-only, hidden from Finder;
3. checks the new app against this one's designated requirement (same bundle id, same certificate): macOS
   keeps the permission grants (mic, Accessibility, Input Monitoring, System Audio) only for that, and a
   file signed by anyone else is never installed;
4. copies it next to this one and swaps the two with renames, so a failure leaves the old app in place
   (a rename works while the old window still runs from it);
5. unmounts and, unless the install ran at Quit, ends the old window and opens Ecoscribe again with
   --after-update, so it opens on Home (installed or not: the user is never left without the app).

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
AFTER_UPDATE = "--after-update"  # selfupdate.AFTER_UPDATE: the new app's first start opens Home


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


def script(dmg: Path, app: Path, req: str, log_path: Path, relaunch: bool, open_cmd: str = "open") -> str:
    """The install script. relaunch: after an Install now (the window, `--ui`, stays up with the Installing screen
    until the swap is done, then it is ended and the app opened on Home); not: at Quit. open_cmd: what opens the
    app again (tests pass a stand-in for macOS's `open`)."""
    q = shlex.quote
    if relaunch:  # every process but the window
        busy = 'pgrep -lf "$app/Contents/MacOS/" | grep -v -e " --ui" >/dev/null'
        end = f"""end_window
rm -rf "$app.old"
{open_cmd} "$app" --args {AFTER_UPDATE}"""
    else:
        busy = 'pgrep -f "$app/Contents/MacOS/" >/dev/null'
        end = """rm -rf "$app.old"
: # installed at Quit: stays closed"""
    return f"""#!/bin/sh
# Ecoscribe self-update (selfinstall.py). Runs after the app quits.
dmg={q(str(dmg))}
app={q(str(app))}
req={q(req)}
exec >>{q(str(log_path))} 2>&1
echo "$(date '+%F %T') installing $dmg into $app"
busy() {{ {busy}; }}
end_window() {{  # the old window (--ui), which showed the Installing screen
  for p in $(pgrep -lf "$app/Contents/MacOS/" | grep -e " --ui" | cut -d' ' -f1); do kill "$p"; done
  j=0
  while pgrep -lf "$app/Contents/MacOS/" | grep -q -e " --ui" && [ $j -lt 10 ]; do sleep 0.5; j=$((j+1)); done
  for p in $(pgrep -lf "$app/Contents/MacOS/" | grep -e " --ui" | cut -d' ' -f1); do kill -9 "$p"; done
}}
i=0
while busy && [ $i -lt {WAIT_S} ]; do sleep 1; i=$((i+1)); done
ok=0
if busy; then echo "Ecoscribe still running after {WAIT_S} s: not installed"; else
mnt=$(mktemp -d /tmp/ecoscribe-update.XXXXXX) || {{ echo "no temporary folder for the .dmg"; mnt=""; }}
if [ -n "$mnt" ] && hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$mnt" "$dmg"; then
  new="$mnt/Ecoscribe.app"
  if codesign --verify --deep --strict -R="$req" "$new"; then
    rm -rf "$app.new" "$app.old"
    if ditto "$new" "$app.new" && mv "$app" "$app.old" && mv "$app.new" "$app"; then
      ok=1
    fi
  else
    echo "the new app isn't signed like this one: not installed"
  fi
  hdiutil detach "$mnt" -quiet || hdiutil detach "$mnt" -force -quiet
fi
[ -n "$mnt" ] && rmdir "$mnt" 2>/dev/null
fi
if [ $ok = 1 ]; then echo "installed"; else
  echo "not installed"; [ -d "$app" ] || mv "$app.old" "$app"; rm -rf "$app.new"
fi
{end}
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
