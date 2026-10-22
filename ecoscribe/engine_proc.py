"""Dictation engine on demand: the model lives in a worker process that leaves when idle.

With `[whisper] on_demand = true` the background app never loads Whisper itself.
The tap that starts a recording also starts the worker (`ecoscribe --engine-worker`),
which loads the model while the user talks (~3 s from disk, measured); the worker is
terminated after `idle_exit_s` without dictation, which frees all of its GPU
memory and RAM. A dead worker is respawned; a hung one is killed after a reply
timeout; in both cases the utterance is retried once.

Wire protocol (worker stdin/stdout), every message = 4-byte little-endian length +
payload. Request: JSON header {"n": samples}, then the float32 audio bytes.
Reply / ready: JSON.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import struct
import subprocess
import sys
import threading
import time

import numpy as np

from . import gpu
from .crash import exit_name
from .engine import Result

log = logging.getLogger(__name__)
SR = 16000


# ---------- framing ----------
def _send(f, data: bytes) -> None:
    f.write(struct.pack("<I", len(data)) + data)
    f.flush()


def _recv(f) -> bytes | None:
    head = _read_n(f, 4)
    if head is None:
        return None
    return _read_n(f, struct.unpack("<I", head)[0])


def _read_n(f, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        part = f.read(n - len(buf))
        if not part:
            return None
        buf += part
    return buf


# ---------- worker side ----------
def std_pipes():
    """Binary stdin + a private copy of stdout for the protocol.

    fd 1 itself is then pointed at stderr (or nowhere), so a stray print or a native
    library banner can never land in the protocol stream. Works in a windowed (frozen)
    exe too, where sys.stdin / sys.stdout may be None."""
    inp = sys.stdin.buffer if sys.stdin else os.fdopen(0, "rb", buffering=0)
    if sys.stdout:
        sys.stdout.flush()
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    try:
        os.dup2(2, 1)
    except OSError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    sys.stdout = sys.stderr
    return inp, out


def serve(engine, inp, out) -> None:
    _send(out, json.dumps({"ready": True, "device": engine.device, "fallback": engine.fallback_reason}).encode())
    while True:
        head = _recv(inp)
        if head is None:
            return  # the app closed our stdin (it quit, or retired us)
        req = json.loads(head)
        n, words = req["n"], req.get("words")
        kw = {k: req[k] for k in ("lang", "prefer") if req.get(k)}  # dictation-languages
        raw = _recv(inp)
        if raw is None:
            return
        audio = np.frombuffer(raw, dtype=np.float32, count=n)
        try:
            if words:
                kw["words"] = words
            if req.get("confidence"):  # dictado-9jc.1: the clarity pass after the paste
                wp = engine.word_confidence(audio, req.get("lang"), words)
                _send(out, json.dumps({"words_p": wp}).encode())
                continue
            if req.get("preview"):  # the live transcript's quick pass: may be skipped (dictado-live)
                r = engine.preview(audio, **{k: v for k, v in kw.items() if k != "words"})
                if r is None:
                    _send(out, json.dumps({"skipped": True}).encode())
                    continue
            else:
                r = engine.transcribe(audio, **kw)
            reply = {"text": r.text, "lang": r.lang, "speech_s": r.speech_s, "ms": r.ms,
                     "device": engine.device, "fallback": engine.fallback_reason}
        except Exception as e:
            log.exception("worker transcription failed")
            reply = {"error": f"{type(e).__name__}: {e}"}
        _send(out, json.dumps(reply).encode())


def worker_main(config_path: str | None = None) -> int:
    """`ecoscribe --engine-worker [--config X]`: load the dictation model, serve until stdin closes."""
    from pathlib import Path

    from . import __version__, config, gpu, paths, winutil
    data = paths.data_dir()
    winutil.setup_logging(data / "engine-worker.log", logging.INFO)
    fault_log(data)
    winutil.add_cuda_dll_dirs()
    from .engine import Engine
    cfg = config.load(Path(config_path) if config_path else paths.config_path())
    engine = Engine(cfg.whisper, cfg.text)
    driver = gpu.driver_cuda()
    engine.skip_gpu = gpu.known_bad(data, __version__, driver)
    t0 = time.monotonic()
    try:
        engine.load(fallback=False)
    except Exception as e:  # a GPU error: note it and leave, the next worker starts on the CPU (dictado-kux)
        reason = f"{type(e).__name__}: {e}"
        gpu.remember_bad(data, __version__, driver, reason)
        log.error("whisper on %s failed (%s; driver supports CUDA %s): noted, the next worker runs on the CPU",
                  cfg.whisper.device, reason, driver)
        return gpu.FAILED_RC
    log.info("engine worker ready pid=%d device=%s load_s=%.1f", os.getpid(), engine.device, time.monotonic() - t0)
    serve(engine, *std_pipes())
    return 0


FAULT_LOG = "engine-worker-fault.log"
_fault_file = None  # open for the life of the worker: faulthandler writes to its fd


def fault_log(data, keep: int = 256_000) -> None:
    """A native crash in the worker (CTranslate2, CUDA) leaves every thread's stack in
    engine-worker-fault.log instead of vanishing (the app only sees the pipe close)."""
    global _fault_file
    import faulthandler
    from pathlib import Path
    p = Path(data) / FAULT_LOG
    try:
        mode = "w" if p.exists() and p.stat().st_size > keep else "a"
        _fault_file = open(p, mode, encoding="utf-8")  # noqa: SIM115 (must stay open)
        _fault_file.write(f"--- engine worker pid={os.getpid()} started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        _fault_file.flush()
        faulthandler.enable(_fault_file, all_threads=True)
    except OSError:
        log.exception("no fault log for the engine worker")


def spawn_worker(config_path: str | None = None):
    frozen = getattr(sys, "frozen", False)
    argv = [sys.executable] if frozen else [sys.executable, "-m", "ecoscribe"]
    cwd = None if frozen else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # -m needs the app dir
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    extra = ["--config", str(config_path)] if config_path else []
    return subprocess.Popen(argv + ["--engine-worker", *extra], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            cwd=cwd, creationflags=flags)


# ---------- app side ----------
def _exit_code(w) -> int | None:
    """The worker's exit code once its pipe closed (None while it runs: it hung)."""
    try:
        return w.proc.wait(1.0)
    except subprocess.TimeoutExpired:
        return None


class _Worker:
    def __init__(self, proc):
        self.proc = proc
        self.replies: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.info: dict = {}
        threading.Thread(target=self._read, name="ecoscribe-engine-reader", daemon=True).start()

    def _read(self) -> None:
        first = True
        while True:
            data = _recv(self.proc.stdout)
            if data is None:
                self.replies.put(None)
                self.ready.set()  # unblock waiters; alive() says it's dead
                return
            try:
                msg = json.loads(data)
            except ValueError:  # garbage on the pipe: treat the worker as gone
                log.error("engine worker sent garbage, dropping it")
                self.replies.put(None)
                self.ready.set()
                return
            if first:
                first = False
                self.info = msg
                self.ready.set()
            else:
                self.replies.put(msg)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill(self) -> None:
        # Process first: closing stdin would block on the buffer lock while a send thread is
        # stuck writing to a worker that stopped reading; once the process is gone that write fails.
        try:
            self.proc.kill()  # TerminateProcess: no CTranslate2 teardown
        except Exception:
            pass
        try:
            self.proc.stdin.close()
        except Exception:
            pass


class EngineProxy:
    def __init__(self, cfg, text_cfg, spawn=spawn_worker, clock=time.monotonic, check_s: float | None = 30.0,
                 ready_timeout_s: float = 120.0, reply_timeout_s: float | None = None, on_device=None):
        """on_device(device, fallback_reason): called when a worker says where it runs (status.json, a notice)."""
        self.cfg, self.text_cfg, self.spawn, self.clock = cfg, text_cfg, spawn, clock
        self.on_device = on_device
        self.ready_timeout_s, self.reply_timeout_s = ready_timeout_s, reply_timeout_s
        self.device = cfg.device
        self.fallback_reason: str | None = None
        self._w: _Worker | None = None
        self._lock = threading.RLock()  # one request at a time
        self._spawn_lock = threading.Lock()  # the worker handle; never held for long
        self._last = clock()
        self._renew = False  # the GPU runtime arrived: a worker started on the CPU makes way (dictado-7e1)
        self._closed = threading.Event()
        if check_s:
            threading.Thread(target=self._watch, args=(check_s,), name="ecoscribe-engine-idle", daemon=True).start()

    def load(self) -> None:
        """Nothing to load up front: that's the point."""

    def _ensure(self) -> _Worker:
        with self._spawn_lock:
            if self._closed.is_set():
                raise RuntimeError("engine closed")  # shutting down: never spawn a new worker
            if self._w is None or not self._w.alive():
                if self._w is not None:
                    rc = self._w.proc.poll()
                    if rc == gpu.FAILED_RC:
                        log.info("the engine worker found the GPU unusable: the next one runs on the CPU")
                    elif rc is not None:
                        log.warning("engine worker ended by itself (exit %s)", exit_name(rc))
                    self._w.kill()
                log.info("starting engine worker")
                self._w = _Worker(self.spawn())
            self._last = self.clock()
            return self._w

    def warm(self) -> None:
        """Start the worker now (the tap), so the model loads while the user speaks. Runs on the key
        thread: it only takes the short spawn lock, never waits for a transcription in flight."""
        try:
            self._ensure()
        except Exception:
            log.exception("could not start the engine worker")

    def _set_device(self, device: str, fallback: str | None) -> None:
        changed = (device, fallback) != (self.device, self.fallback_reason)
        self.device, self.fallback_reason = device, fallback
        if changed and self.on_device:
            try:
                self.on_device(device, fallback)
            except Exception:
                log.exception("on_device failed")

    def _reply_timeout(self, n: int) -> float:
        """A worker on the CPU (small model, no GPU) needs far longer than one on the GPU."""
        if self.reply_timeout_s:
            return self.reply_timeout_s
        secs = n / SR
        return max(60.0, 10 * secs) if self.device == "cpu" else max(30.0, 3 * secs)

    def _ask(self, w: _Worker, audio: np.ndarray, timeout: float | None, words=None, extra=None) -> dict | None:
        """timeout None: by the audio's length and where the worker runs."""
        if not w.ready.wait(self.ready_timeout_s) or not w.alive() and w.replies.empty():
            return None
        if w.info.get("device"):
            self._set_device(w.info["device"], w.info.get("fallback"))
        if timeout is None:
            timeout = self._reply_timeout(len(audio))
        sent = threading.Event()

        def send():  # a worker that stopped reading would block this write forever
            try:
                head = {"n": len(audio), **({"words": list(words)} if words else {}), **(extra or {})}
                _send(w.proc.stdin, json.dumps(head, ensure_ascii=False).encode())
                _send(w.proc.stdin, np.ascontiguousarray(audio, np.float32).tobytes())
                sent.set()
            except (OSError, ValueError):
                pass
        t = threading.Thread(target=send, name="ecoscribe-engine-send", daemon=True)
        t.start()
        t.join(timeout)
        if not sent.is_set():
            return None
        try:
            return w.replies.get(timeout=timeout)
        except queue.Empty:
            return None

    def transcribe(self, audio: np.ndarray, words=None, lang: str | None = None, prefer: str | None = None) -> Result:
        audio = np.asarray(audio, np.float32)
        with self._lock:
            attempt, gpu_noted = 0, False
            while attempt < 2:
                w = self._ensure()
                reply = self._ask(w, audio, None, words, {k: v for k, v in (("lang", lang), ("prefer", prefer)) if v})
                if reply is not None and "error" not in reply:
                    self._last = self.clock()
                    self._set_device(reply.get("device", self.device), reply.get("fallback"))
                    return Result(text=reply["text"], lang=reply["lang"], speech_s=reply["speech_s"], ms=reply["ms"])
                rc = _exit_code(w)
                if rc == gpu.FAILED_RC and not gpu_noted:  # not a failed try: the next worker starts on the CPU
                    gpu_noted = True
                    continue
                attempt += 1
                log.error("engine worker gave no answer (attempt %d, reply=%s, exit %s): restarting it", attempt,
                          reply, exit_name(rc) if rc is not None else "none, still running")
                w.kill()
                with self._spawn_lock:
                    if self._w is w:
                        self._w = None
            raise RuntimeError("engine worker failed twice")

    def word_confidence(self, audio: np.ndarray, lang: str | None = None, words=None) -> list | None:
        """dictado-9jc.1: the clarity pass, after the paste. None (never a restart) when the worker isn't
        ready or gives no answer: it's only for Insights."""
        w = self._w
        if w is None or not w.ready.is_set():
            return None
        with self._lock:
            if self._w is not w or not w.alive():
                return None
            audio = np.asarray(audio, np.float32)
            reply = self._ask(w, audio, max(30.0, 3 * len(audio) / SR), words,
                              {"confidence": True, **({"lang": lang} if lang else {})})
            if reply is None:  # no answer: a late one would be read as the next dictation's
                log.error("engine worker gave no answer to the clarity pass: restarting it")
                w.kill()
                with self._spawn_lock:
                    if self._w is w:
                        self._w = None
                return None
            self._last = self.clock()
            wp = reply.get("words_p")
            return [(x, float(p)) for x, p in wp] if wp else None

    def preview(self, audio: np.ndarray, lang: str | None = None, prefer: str | None = None) -> Result | None:
        """The live transcript's quick pass (dictado-live). None, without waiting, while the worker
        is still loading or a dictation holds it: the paste never waits for a preview."""
        w = self._w
        if w is None or not w.ready.is_set() or not self._lock.acquire(blocking=False):
            return None
        try:
            if self._w is not w or not w.alive():
                return None
            audio = np.asarray(audio, np.float32)
            reply = self._ask(w, audio, 10.0, None, {"preview": True,
                                                     **{k: v for k, v in (("lang", lang), ("prefer", prefer)) if v}})
            if reply is None:  # no answer: a late one would be read as the next dictation's
                log.error("engine worker gave no answer to a preview: restarting it")
                w.kill()
                with self._spawn_lock:
                    if self._w is w:
                        self._w = None
                return None
            if "error" in reply or reply.get("skipped"):
                return None
            self._last = self.clock()
            return Result(text=reply["text"], lang=reply["lang"], speech_s=reply["speech_s"], ms=reply["ms"])
        finally:
            self._lock.release()

    def renew(self) -> None:
        """The GPU runtime is there now (dictado-7e1): retire the current worker as soon as no dictation
        uses it, so the next one starts on the GPU. Never cuts a transcription short."""
        self._renew = True
        self.check_idle()

    def check_idle(self) -> None:
        if not self._lock.acquire(blocking=False):
            return  # a transcription is running: not idle (a pending renew waits for the next check)
        try:
            with self._spawn_lock:
                if self._renew:
                    self._renew = False
                    if self._w is not None:
                        log.info("GPU runtime ready: retiring the engine worker, the next one starts on the GPU")
                        self._w.kill()
                        self._w = None
                    return
                if self._w is not None and self.clock() - self._last >= self.cfg.idle_exit_s:
                    log.info("engine idle %.0f s: stopping the worker to free memory", self.clock() - self._last)
                    self._w.kill()
                    self._w = None
        finally:
            self._lock.release()

    def _watch(self, every: float) -> None:
        while not self._closed.wait(every):
            try:
                self.check_idle()
            except Exception:
                log.exception("idle check failed")

    def close(self) -> None:
        """Kill the worker now, even mid-request (shutdown must not wait for a transcription)."""
        self._closed.set()
        with self._spawn_lock:
            if self._w is not None:
                self._w.kill()
                self._w = None
