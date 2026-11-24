"""The real --engine-worker on the GPU (criterion 0c, model part)."""
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ecoscribe.audio import read_wav
from ecoscribe.config import WhisperCfg
from tests.engine_cfg import pinned_proxy

pytestmark = pytest.mark.gpu
FIX = Path(__file__).parent / "fixtures"


def _worker_mem_mb() -> int:
    """macOS: unified memory, so "VRAM" is the Ecoscribe worker processes' own footprint (MB)."""
    out = subprocess.run(["pgrep", "-f", "ecoscribe --(engine-worker|transcribe|meeting)"], capture_output=True, text=True).stdout
    total = 0
    for pid in out.split():
        fp = subprocess.run(["footprint", "-p", pid], capture_output=True, text=True).stdout
        for line in fp.splitlines():
            if "phys_footprint:" in line:
                n, unit = line.split("phys_footprint:")[1].split()[:2]
                total += float(n) * {"KB": 1 / 1024, "MB": 1, "GB": 1024}.get(unit, 1)
    return int(total)


def vram_mb():
    if sys.platform == "darwin":
        return _worker_mem_mb()
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout
    return int(out.strip().splitlines()[0])


def test_cold_start_dictation_then_idle_exit_frees_vram(tmp_path):
    before = vram_mb()
    t = [0.0]
    # the default dictation model, whatever the user's languages pick (tests/engine_cfg.py, dictado-i8bw)
    e = pinned_proxy(tmp_path, whisper=WhisperCfg(on_demand=True, idle_exit_s=600), clock=lambda: t[0])
    t0 = time.monotonic()
    e.warm()  # the tap
    time.sleep(1.5)  # the user talks
    r = e.transcribe(read_wav(FIX / "en_fox.wav"))
    cold_s = time.monotonic() - t0
    assert "fox" in r.text.lower() and e.device == ("mlx" if sys.platform == "darwin" else "cuda")
    loaded = vram_mb()
    t1 = time.monotonic()
    r2 = e.transcribe(read_wav(FIX / "en_fox.wav"))
    warm_ms = (time.monotonic() - t1) * 1000
    t[0] = 601
    e.check_idle()
    time.sleep(3)
    after = vram_mb()
    print(f"ENGINE cold_s={cold_s:.1f} warm_ms={warm_ms:.0f} vram before/loaded/after={before}/{loaded}/{after}")
    assert loaded - before > 500  # the model really was on the GPU
    assert after - before < 300  # and is gone after the idle exit
