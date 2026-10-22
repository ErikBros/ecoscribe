"""A GPU that can't run the model (dictado-kux): noted once, every later worker on the CPU, the user told."""
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ecoscribe import crash, gpu
from ecoscribe.config import TextCfg, WhisperCfg
from ecoscribe.engine import Engine

HERE = Path(__file__).resolve().parent
OLD = "RuntimeError: CUDA failed with error CUDA driver version is insufficient for CUDA runtime version"


def test_the_note_holds_until_the_app_or_the_driver_changes(tmp_path):
    assert gpu.known_bad(tmp_path, "1.0.0", 11040) is None
    gpu.remember_bad(tmp_path, "1.0.0", 11040, OLD)
    assert gpu.known_bad(tmp_path, "1.0.0", 11040) == OLD
    assert gpu.known_bad(tmp_path, "1.0.1", 11040) is None  # a new Ecoscribe tries the GPU again
    assert gpu.known_bad(tmp_path, "1.0.0", 12040) is None  # so does an updated driver
    (tmp_path / gpu.FILE).write_text("{broken", encoding="utf-8")
    assert gpu.known_bad(tmp_path, "1.0.0", 11040) is None


def test_the_notice_says_what_to_do():
    msg = gpu.notice(OLD, 11040)
    assert "too old" in msg and "nvidia.com/drivers" in msg and "CUDA 11.4" in msg and "CPU" in msg
    assert "too old" not in gpu.notice("RuntimeError: CUDA failed with error out of memory")


class Model:
    def __init__(self, name, device, warm_error=None):
        self.name, self.device, self.warm_error = name, device, warm_error

    def detect_language(self, audio, vad_filter=False):
        if self.warm_error:
            raise self.warm_error
        return "en", 0.9, [("en", 0.9)]

    def transcribe(self, audio, **kw):
        return iter([SimpleNamespace(text=" hello", no_speech_prob=0.0)]), SimpleNamespace(duration=1.0)


def engine(made, cuda_error=None, warm_error=None):
    def factory(name, device, compute_type, local_files_only=False):
        if device == "cuda" and cuda_error:
            raise cuda_error
        m = Model(name, device, warm_error if device == "cuda" else None)
        made.append(m)
        return m
    return Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory, resolve=lambda n: n)


def test_a_gpu_known_to_fail_is_not_tried():
    made = []
    e = engine(made, cuda_error=AssertionError("must not try CUDA"))
    e.skip_gpu = OLD
    e.load()
    assert [m.device for m in made] == ["cpu"] and e.device == "cpu" and e.fallback_reason == OLD


def test_the_worker_load_raises_a_gpu_error_instead_of_falling_back():
    made = []
    with pytest.raises(RuntimeError, match="insufficient"):
        engine(made, cuda_error=RuntimeError(OLD)).load(fallback=False)
    assert made == []
    e = engine(made, cuda_error=OSError("model files missing"))
    e.load(fallback=False)  # not a GPU error: small/cpu as before
    assert e.device == "cpu"


def test_a_model_that_failed_its_warmup_is_retired_never_destroyed():
    made = []
    e = engine(made, warm_error=RuntimeError("CUDA failed with error unspecified launch failure"))
    e.load()
    assert e.device == "cpu" and made[0] in e._retired


def spawner(*modes):
    """Each spawn runs the fake worker in the next mode (the last one repeats)."""
    procs, modes = [], list(modes)

    def spawn():
        mode = modes.pop(0) if len(modes) > 1 else modes[0]
        procs.append(subprocess.Popen([sys.executable, str(HERE / "fake_engine_worker.py"), mode],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE))
        return procs[-1]
    return spawn, procs


def audio(n=16000):
    return np.zeros(n, np.float32)


def proxy(spawn, seen=None):
    from ecoscribe.engine_proc import EngineProxy
    return EngineProxy(WhisperCfg(on_demand=True), TextCfg(), spawn=spawn, check_s=None,
                       on_device=lambda d, f: seen.append((d, f)) if seen is not None else None)


def test_a_worker_that_found_the_gpu_unusable_is_replaced_without_losing_the_dictation():
    spawn, procs = spawner("gpu_failed", "cpu")
    seen = []
    e = proxy(spawn, seen)
    r = e.transcribe(audio())
    assert r.text and len(procs) == 2 and procs[0].returncode == gpu.FAILED_RC
    assert e.device == "cpu" and seen == [("cpu", "RuntimeError: CUDA failed with error CUDA driver version is insufficient")]
    e.close()


def test_a_worker_that_keeps_failing_the_gpu_does_not_loop():
    spawn, procs = spawner("gpu_failed")
    e = proxy(spawn)
    with pytest.raises(RuntimeError, match="failed twice"):
        e.transcribe(audio())
    assert len(procs) == 3
    e.close()


def test_the_cpu_gets_a_longer_reply_timeout():
    e = proxy(lambda: None)
    assert e._reply_timeout(16000 * 10) == 30.0
    e.device = "cpu"
    assert e._reply_timeout(16000 * 10) == 100.0 and e._reply_timeout(16000) == 60.0
    e.close()


def test_the_freeze_watch_counts_only_awake_time():
    clock = crash.awake_clock()
    a = clock()
    time.sleep(0.05)
    assert 0.03 < clock() - a < 1.0
    if sys.platform == "win32":
        assert clock is not time.monotonic  # Windows' monotonic counts sleep: a night read as a freeze


@pytest.mark.skipif(sys.platform != "win32", reason="nvcuda.dll is Windows")
def test_the_driver_version_is_read_without_cuda():
    v = gpu.driver_cuda()
    assert v is None or v >= 10000


def test_the_worker_notes_a_gpu_failure_and_exits_and_the_next_one_skips_the_gpu(tmp_path, monkeypatch):
    from ecoscribe import __version__, engine, engine_proc, paths, winutil
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr(winutil, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(engine_proc, "fault_log", lambda data: None)
    monkeypatch.setattr(engine_proc, "serve", lambda e, *pipes: None)
    monkeypatch.setattr(engine_proc, "std_pipes", lambda: (None, None))
    monkeypatch.setattr(gpu, "driver_cuda", lambda: 11040)
    loads = []

    def load(self, fallback=True):
        loads.append(self.skip_gpu)
        if not self.skip_gpu:
            raise RuntimeError(OLD.split(": ", 1)[1])
        self.device, self.fallback_reason = "cpu", self.skip_gpu
    monkeypatch.setattr(engine.Engine, "load", load)
    assert engine_proc.worker_main() == gpu.FAILED_RC
    assert gpu.known_bad(tmp_path, __version__, 11040) == OLD
    assert engine_proc.worker_main() == 0 and loads == [None, OLD]


def test_debug_info_names_the_gpu_and_the_note(tmp_path):
    from ecoscribe import window
    assert window._gpu()
    gpu.remember_bad(tmp_path, "1.0.0", 11040, OLD)
    api = window.Api.__new__(window.Api)
    api._data_dir, api._config_path = tmp_path, tmp_path / "config.toml"
    info = api.debug_info()
    assert "GPU: " in info and "## gpu-failed.json" in info and "insufficient" in info
