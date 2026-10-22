"""Remembering a GPU that can't run Ecoscribe's model (dictado-kux).

A PC whose NVIDIA driver is older than the CUDA runtime Ecoscribe ships fails every CUDA load
("CUDA driver version is insufficient for CUDA runtime version"). The engine worker that hits it
writes gpu-failed.json and exits; every later worker reads it and goes straight to the CPU, so no
dictation waits for a doomed CUDA load and no process carries on after a failed one. The note
holds the app version and the driver's CUDA version: a new Ecoscribe or a driver update tries the
GPU again.
"""
from __future__ import annotations

import ctypes
import json
import sys
import time
from pathlib import Path

FILE = "gpu-failed.json"
FAILED_RC = 75  # the worker's exit code after writing the note: start the next one, it runs on the CPU


def driver_cuda() -> int | None:
    """The newest CUDA version the installed NVIDIA driver supports (12040 = 12.4), None without one.
    Asks nvcuda.dll directly: no CUDA context, a millisecond."""
    if sys.platform != "win32":
        return None
    try:
        v = ctypes.c_int(0)
        if ctypes.WinDLL("nvcuda.dll").cuDriverGetVersion(ctypes.byref(v)) != 0:
            return None
        return v.value
    except (OSError, AttributeError):
        return None


def _version(v: int | None) -> str:
    return f"{v // 1000}.{v % 1000 // 10}" if v else "?"


def known_bad(data: Path, app_version: str, driver: int | None) -> str | None:
    """The reason this GPU failed before, if nothing changed since (same app, same driver)."""
    try:
        note = json.loads((Path(data) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if note.get("app") != app_version or note.get("driver") != driver:
        return None
    return str(note.get("reason") or "the GPU failed before")


def remember_bad(data: Path, app_version: str, driver: int | None, reason: str) -> None:
    (Path(data) / FILE).write_text(json.dumps({"app": app_version, "driver": driver, "reason": reason,
                                               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")


def notice(reason: str | None, driver: int | None = None) -> str:
    """One line for the user about dictating on the CPU."""
    if reason and "driver version is insufficient" in reason.lower():
        have = f" (it supports CUDA {_version(driver)})" if driver else ""
        return (f"Your NVIDIA driver is too old for Ecoscribe{have}: update it from nvidia.com/drivers. "
                "Dictating on the CPU, slower, until then.")
    return "No GPU: dictating on the CPU, slower. Details in Settings > Troubleshooting."
