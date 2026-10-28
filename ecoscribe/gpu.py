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


# The speech models peak at ~2.3 GB of graphics memory (turbo float16 2.3, large-v3 int8_float16 2.1; RTX 3070 Ti,
# 2026-10-28) and Windows keeps some for the screen: a smaller card runs out at the first dictation (dictado-5d6y)
MIN_CARD_MB = 2800
SMALL = "the graphics card has too little memory for the speech models"  # the CPU reason (notice knows it)
_card: list = []


def card_mb() -> int | None:
    """Total memory of the first NVIDIA card in MB, None without one. Asks nvcuda.dll (no CUDA context); once."""
    if not _card:
        mb = None
        if sys.platform == "win32":
            try:
                cu = ctypes.WinDLL("nvcuda.dll")
                dev, total = ctypes.c_int(0), ctypes.c_size_t(0)
                if (cu.cuInit(0) == 0 and cu.cuDeviceGet(ctypes.byref(dev), 0) == 0
                        and cu.cuDeviceTotalMem_v2(ctypes.byref(total), dev) == 0):
                    mb = total.value // 2**20
            except (OSError, AttributeError):
                pass
        _card.append(mb)
    return _card[0]


def too_small() -> int | None:
    """The card's memory in MB when it can't hold the speech models, else None (no card counts as None)."""
    mb = card_mb()
    return mb if mb and mb < MIN_CARD_MB else None


def _gb(mb: int) -> str:
    return f"{max(1, round(mb / 1024))} GB"


def small_why(mb: int) -> str:
    """Why dictation runs on the processor on a too-small card, for setup and Settings."""
    return f"this computer's graphics card has {_gb(mb)} of memory and the big models need {_gb(MIN_CARD_MB + 300)}"


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
    from .gpu_runtime import MIN_DRIVER, MISSING
    if reason == MISSING and driver and driver < MIN_DRIVER:
        reason = "CUDA driver version is insufficient for CUDA runtime version"
    elif reason == MISSING and driver:  # dictado-7e1: the CUDA libraries are being downloaded, once
        return "Getting Ecoscribe's GPU part (one download). Dictating on the CPU, slower, until it's there."
    if reason and "driver version is insufficient" in reason.lower():
        have = f" (it supports CUDA {_version(driver)})" if driver else ""
        return (f"Your NVIDIA driver is too old for Ecoscribe{have}: update it from nvidia.com/drivers. "
                "Dictating on the CPU, slower, until then.")
    if reason == SMALL:
        have = f" ({_gb(mb)})" if (mb := card_mb()) else ""
        return f"Your graphics card has too little memory for Ecoscribe{have}: dictating on the CPU, slower."
    return "No GPU: dictating on the CPU, slower. Details in Settings > Troubleshooting."
