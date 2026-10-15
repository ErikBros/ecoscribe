"""[transcribe] after_transcribe: the user's own command, started once a transcript is done.

A list like ["C:/Python312/python.exe", "C:/me/after.py"]; the session folder is added as the
last argument. It runs on its own (detached), so the transcription worker exits and frees the
GPU; its output goes to after_transcribe.log in the session folder. Empty: nothing runs.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
LOG = "after_transcribe.log"


def launch(cmd, session_dir: Path, popen=subprocess.Popen):
    if not cmd:
        return None
    d = Path(session_dir)
    args = [str(x) for x in ([cmd] if isinstance(cmd, str) else cmd)] + [str(d)]
    if sys.platform == "win32":
        kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
              | subprocess.CREATE_NO_WINDOW}
    else:
        kw = {"start_new_session": True}
    try:
        with open(d / LOG, "ab") as out:
            p = popen(args, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, close_fds=True, **kw)
        log.info("after_transcribe started: %s", args[0])
        return p
    except OSError:
        log.exception("after_transcribe could not start")
        return None
