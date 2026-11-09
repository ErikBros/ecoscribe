"""The meeting worker: `ecoscribe --meeting DIR`.

Records mic + system audio (session_rec), transcribes pause-cut chunks as they
come into live.jsonl (what the pill and the Reuniones page show), and when the
meeting stops (a `stop` file in DIR or the named event) finishes the FLACs, runs
the full-quality pass on mix.flac with the same, already loaded model, labels
each segment Yo / Otros and writes the transcript. One process per meeting:
its VRAM is freed when it exits (hard exit, models are never destroyed).
"""
from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import export, models, segclean, sessions, speakers, transcribe
from .config import TranscribeCfg
from .routing import mixed_langs, model_for

log = logging.getLogger(__name__)
SR = 16000
STOP_EVENT = "Local\\EcoscribeMeetingStop"
MAX_S = 4 * 3600  # a forgotten recording stops itself after 4 h
# dictado-9z99: the call is in another of the user's languages than the one it records in. Two live chunks in a row
# (each >= HINT_MIN_S of audio with words in it) must say the same other language with >= HINT_P, within the first
# HINT_UNTIL_S of the call; then meta "heard_lang" is written once and the pill offers the switch.
HINT_P = 0.8
HINT_MIN_S = 5.0
HINT_UNTIL_S = 240.0
HINT_SAME_DONE = 3


class LangHint:
    """Watches the first live chunks of a one-language meeting for another of the user's languages."""

    def __init__(self, mine, p_min: float = HINT_P, in_a_row: int = 2):
        self.mine = {str(c) for c in mine or []}
        self.p_min, self.in_a_row = p_min, in_a_row
        self.run: tuple[str | None, int] = (None, 0)
        self.done = False
        self.same = 0  # clear chunks of the set language: after HINT_SAME_DONE the call is what it says, stop checking

    def other(self, probs, current: str) -> str | None:
        """The language a chunk is clearly in, when it is another of the user's; else None."""
        p = dict(probs or [])
        if not p:
            return None
        top = max(p, key=p.get)
        return top if top != current and top in self.mine and p[top] >= self.p_min else None

    def feed(self, probs, current: str, t0: float, seconds: float, has_words: bool) -> str | None:
        """One live chunk. Returns the language to suggest, once; None otherwise."""
        if self.done or not current or current == "auto" or mixed_langs(current) or t0 > HINT_UNTIL_S:
            return None
        if seconds < HINT_MIN_S or not has_words:
            return None  # too little to go on: neither counts nor breaks a run
        lang = self.other(probs, current)
        p = dict(probs or [])
        if lang is None and p and max(p, key=p.get) == current and p[current] >= self.p_min:
            self.same += 1
            if self.same >= HINT_SAME_DONE:
                self.done = True  # each check costs a detector pass: no more once the language is confirmed
        n = self.run[1] + 1 if lang is not None and lang == self.run[0] else (1 if lang else 0)
        self.run = (lang, n)
        if lang is not None and n >= self.in_a_row:
            self.done = True
            return lang
        return None


def _probs(model, audio):
    """The detector's [(lang, p)] for a piece of audio; [] when it can't say."""
    try:
        _, _, probs = model.detect_language(audio)
        return list(probs or [])
    except Exception:
        log.debug("language check of a live chunk failed", exc_info=True)
        return []


def stop_checker(d: Path, event_name: str | None = STOP_EVENT):
    """True once DIR/stop exists or the named event is set (macOS: the file only)."""
    handle = None
    if event_name and sys.platform != "darwin":
        try:
            import win32event
            handle = win32event.CreateEvent(None, True, False, event_name)
        except Exception:
            log.warning("no stop event, the stop file still works", exc_info=True)

    def check() -> bool:
        if (Path(d) / "stop").exists():
            return True
        if handle is not None:
            import win32event
            return win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_OBJECT_0
        return False
    return check


def _default_recorder(d: Path, on_chunk):
    from . import config, paths
    if sys.platform == "darwin":  # a Core Audio process tap instead of WASAPI loopback
        from .platform.macos.systap import Loopback
    else:
        from .loopback import Loopback
    from .micgate import MicGate
    from .session_rec import MicSource, SessionRecorder
    audio_cfg = config.load(paths.config_path()).audio
    gate = MicGate(audio_cfg.device, audio_cfg.unmute_volume, enabled=audio_cfg.unmute_while_recording)
    return SessionRecorder(d, mic_factory=lambda: MicSource(audio_cfg), loop_factory=Loopback, gate=gate,
                           on_chunk=on_chunk)


def _current_lang(d: Path, fallback):
    """The meeting's language now: meta lang (changed from the live view) or the start one.
    The loaded model stays (large-v3 and turbo speak every language); the final pass routes
    on meta lang, so a switch also picks the right model for the whole recording."""
    try:
        lang = sessions.read_meta(d).get("lang")
    except Exception:
        return fallback
    return None if lang == "auto" else (lang or fallback)


def _append_live(d: Path, line: dict) -> None:
    with open(Path(d) / "live.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _label(d: Path) -> None:
    from faster_whisper import decode_audio
    audio = Path(d) / "audio"
    mic = decode_audio(str(audio / "mic.flac"), sampling_rate=SR)
    system = decode_audio(str(audio / "system.flac"), sampling_rate=SR)
    path = Path(d) / "transcript.json"
    tr = json.loads(path.read_text(encoding="utf-8"))
    tr["segments"] = segclean.drop_silent(tr["segments"], mic, system)
    speakers.label(tr["segments"], mic, system)
    transcribe._write_json(path, tr)
    export.write_all(d)


def run(session_dir: Path, cfg: TranscribeCfg, recorder_factory=_default_recorder, stop_check=None,
        poll_s: float = 0.25, factory=transcribe._default_factory, resolve=None,
        clock=time.monotonic, prompt: str | None = None, speech=transcribe._speech,
        replacements: dict | None = None, call_devices=None, my_langs=None) -> int:
    d = Path(session_dir)
    stop_check = stop_check or stop_checker(d)
    cache: dict = {}
    try:
        meta = sessions.write_meta(d, source="meeting", status="recording", error=None)
        lang = meta["lang"]
        live_lang = None if lang == "auto" else lang  # auto: each chunk detects; the final pass routes
        name = cfg.detector_model if lang == "auto" else model_for(lang, cfg)
        resolve = resolve or transcribe._resolve_for(factory)
        model, _ = transcribe._load(name, cfg, 0, factory, resolve, d, cache)
        sessions.write_meta(d, status="recording")
        chunks: queue.Queue = queue.Queue()
        dropping = threading.Event()
        last_lang = [None]  # a mixed meeting's last live language: short unsure chunks keep it
        hint = LangHint(my_langs)  # dictado-9z99
        t_start = clock()

        def on_chunk(t0, audio):
            chunks.put((t0, audio))

        def live():
            while True:
                item = chunks.get()
                if item is None:
                    return
                if dropping.is_set():
                    continue
                t0, audio = item
                try:
                    lang_now = _current_lang(d, live_lang)  # the user can switch it mid-meeting (meta lang)
                    if mixed_langs(lang_now):  # Greek + Spanish: each chunk is one or the other (t0u.34)
                        lang_now = transcribe.pick_mixed(model, audio, mixed_langs(lang_now), last_lang[0])
                        last_lang[0] = lang_now
                    gen, _ = model.transcribe(audio, language=lang_now, beam_size=cfg.beam_size, vad_filter=True,
                                              condition_on_previous_text=False, initial_prompt=prompt)
                    text = " ".join(s["text"] for s in segclean.clean_segments(
                        [{"text": s.text} for s in gen]))
                    if not hint.done and not mixed_langs(lang_now) and t0 <= HINT_UNTIL_S and len(audio) / SR >= HINT_MIN_S:
                        heard = hint.feed(_probs(model, audio), lang_now, t0, len(audio) / SR, bool(text.strip()))
                        if heard:
                            sessions.write_meta(d, heard_lang=heard)
                            log.info("meeting sounds like %s, not %s: offering the switch", heard, lang_now)
                except Exception:
                    log.exception("live chunk at %.1f s failed", t0)
                    continue
                t1 = round(t0 + len(audio) / SR, 2)
                lag = round(clock() - t_start - t1, 2)
                if text:
                    _append_live(d, {"t0": round(t0, 2), "t1": t1, "text": text, "lag_s": lag})
                log.info("live chunk t0=%.1f t1=%.1f live_lag_s=%.2f chars=%d", t0, t1, lag, len(text))

        worker = threading.Thread(target=live, name="ecoscribe-live", daemon=True)
        worker.start()
        rec = recorder_factory(d, on_chunk)
        try:
            rec.start()
            log.info("meeting recording lang=%s model=%s", lang, name)
            from .meet_sources import Sources
            sources = Sources(d, rec, app=meta.get("app"), call_devices=call_devices, clock=clock)
            last_lv = None
            while not stop_check() and clock() - t_start < MAX_S:
                if last_lv is None or clock() - last_lv >= 1.0:  # the page and the background app's silence backup read it
                    last_lv = clock()
                    sources.tick()
                time.sleep(poll_s)
            log.info("meeting stop after %.0f s", clock() - t_start)
        finally:  # whatever happened: finish the FLACs and give the mic back
            durations = rec.stop()
            dropping.set()  # chunks still queued are covered by the final pass
            chunks.put(None)
        worker.join(timeout=120)  # at most one chunk (<= 20 s of audio) still in flight
        if worker.is_alive():
            log.warning("live chunk still running after 120 s; final pass waits for it")
            worker.join()
        sessions.write_meta(d, status="finalizing", recorded_s=durations.get("mix"))
        rc = transcribe.run(d, cfg, factory=factory, resolve=resolve, cache=cache, prompt=prompt, speech=speech,
                            replacements=replacements)
        if rc == 0:
            _label(d)
            from .after_hook import launch
            launch(cfg.after_transcribe, d)
        return rc
    except Exception as e:
        log.exception("meeting failed")
        try:
            sessions.write_meta(d, status="failed", error=f"{type(e).__name__}: {e}")
        except Exception:
            log.exception("could not mark %s failed", d)
        return 1


def main(session_dir: str) -> int:
    """`ecoscribe --meeting DIR`: called from __main__, which hard-exits with the result."""
    from . import config, paths, winutil
    d = Path(session_dir)
    winutil.setup_logging(d / "worker.log", logging.INFO)
    for noisy in ("faster_whisper", "httpx", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    winutil.add_cuda_dll_dirs()
    full = config.load(paths.config_path())
    from .calendar_ics import session_words
    from .text import vocab_prompt
    if sys.platform == "darwin":  # dictado-7bw: Core Audio's process objects
        from .platform.macos.audio_route import call_devices
    else:
        from .platform.windows.audio_route import call_devices
    from .languages import user_langs
    return run(d, full.transcribe, prompt=vocab_prompt(session_words(d, full.text.vocabulary)),
               replacements=dict(full.text.replacements), call_devices=call_devices,
               my_langs=user_langs(full.whisper.languages, full.whisper.extra_languages, full.meetings.default_lang))
