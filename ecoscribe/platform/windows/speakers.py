"""Where the speaker add-on lives on Windows (diarize.addon_exe; macOS: platform/macos/speakers.py).

Its own installer puts EcoscribeSpeakers.exe in %LOCALAPPDATA%\\Programs\\Ecoscribe Speakers. Before
the rename (dictado-jtv) it was Dictado Speakers\\DictadoSpeakers.exe: still found when the new one
isn't there, so an installed 1.1.0 add-on keeps working.
"""
from __future__ import annotations

import os
from pathlib import Path

NEW = ("Ecoscribe Speakers", "EcoscribeSpeakers.exe")
OLD = ("Dictado Speakers", "DictadoSpeakers.exe")


def addon_exe(localappdata: Path | None = None) -> Path:
    progs = Path(localappdata or os.environ.get("LOCALAPPDATA", "")) / "Programs"
    for folder, exe in (NEW, OLD):
        if (progs / folder / exe).is_file():
            return progs / folder / exe
    return progs / NEW[0] / NEW[1]  # not installed: where it will be


MIN_FREE_MB = 3000  # the add-on peaks ~2.6 GB on CUDA next to a live meeting (measured dictado-ngp)


def gpu_room(min_free_mb: int = MIN_FREE_MB, run=None) -> bool:
    """True when the NVIDIA GPU has room for the speakers pass next to a recording call (dictado-ngp).
    No NVIDIA GPU, or nvidia-smi fails: False, and the pass waits for the call to end."""
    import subprocess
    run = run or subprocess.run
    try:
        out = run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                  capture_output=True, text=True, timeout=5,
                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return int(out.strip().splitlines()[0]) >= min_free_mb
    except Exception:
        return False
