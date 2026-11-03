"""Where the speaker add-on lives on macOS (diarize.addon_exe for the Mac).

"Ecoscribe Speakers.app" (PyTorch + pyannote, a separate download like on Windows), dragged to
/Applications or ~/Applications. Its binary takes the same arguments as EcoscribeSpeakers.exe:
<audio> <out.json>, plus the <out>.voices.json sidecar. Before the rename (dictado-c9u) it was
"Dictado Speakers.app": still found when the new one isn't there.
"""
from __future__ import annotations

from pathlib import Path

BINARY = Path("Ecoscribe Speakers.app") / "Contents" / "MacOS" / "EcoscribeSpeakers"
OLD_BINARY = Path("Dictado Speakers.app") / "Contents" / "MacOS" / "DictadoSpeakers"


def addon_exe(home: Path | None = None) -> Path:
    places = [Path("/Applications"), Path(home or Path.home()) / "Applications"]
    for b in (BINARY, OLD_BINARY):
        for p in places:
            if (p / b).is_file():
                return p / b
    return places[0] / BINARY  # not installed: where it will be


MIN_FREE_MB = 6000  # the add-on took about 3.5 GB next to live mlx-whisper (dictado-692); the rest is margin


def _sysctl(name: str) -> int | None:
    import subprocess
    try:
        return int(subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception:
        return None


def free_mb(read=_sysctl) -> int | None:
    """Memory free for new work, in MB: the kernel's free percentage (what Activity Monitor's pressure
    follows) of the computer's memory. The Apple GPU shares it, so this is the GPU's room too."""
    level, total = read("kern.memorystatus_level"), read("hw.memsize")
    if level is None or total is None:
        return None
    return int(total * level / 100 / 2**20)


def gpu_room(min_free_mb: int = MIN_FREE_MB, read=_sysctl) -> bool:
    """Room for the speakers pass next to a recording call (dictado-692, as dictado-ngp on Windows)?
    Measured on an M2 Pro: next to live large-v3 on mlx, a 30 s live chunk took 2.7 s alone and at most
    7.6 s while the pass ran (still far ahead of the call), memory never swapped. So: True when enough
    memory is free; unknown or tight: False, and the pass waits for the call to end."""
    free = free_mb(read)
    return free is not None and free >= min_free_mb
