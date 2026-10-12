"""Speakers pass: `ecoscribe --speakers DIR` (t0u.22). Tells the remote voices apart.

Runs after the transcript is done, as its own job (meetings.Controller), so the
add-on's model never shares the GPU with a Whisper model. The add-on is a separate
install (PyTorch + pyannote, a few GB): `EcoscribeSpeakers.exe <audio> <out.json>`
writes [[t0, t1, "SPEAKER_00"], ...]. A meeting diarizes only system.flac (the user is
the mic track, labelled Me already); an import diarizes the file. With one remote
voice nothing changes, so a 1:1 call reads as before; with several, the remote
segments become Speaker 1..N in order of first appearance. The transcript stays
usable (status done) throughout; a failed pass leaves it untouched.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

from . import export, sessions

log = logging.getLogger(__name__)
NEAREST_S = 2.0  # a segment no turn overlaps takes the closest turn this near
TIMEOUT_S = 3 * 3600


if sys.platform == "darwin":  # /Applications/Ecoscribe Speakers.app (ecoscribe/platform/macos/speakers.py)
    from .platform.macos.speakers import addon_exe
else:  # %LOCALAPPDATA%\\Programs\\Ecoscribe Speakers (ecoscribe/platform/windows/speakers.py)
    from .platform.windows.speakers import addon_exe


def available(cfg, exe: Path | None = None) -> bool:
    return bool(cfg.meetings.speakers) and (exe or addon_exe()).is_file()


def track(d: Path) -> Path:
    if sessions.read_meta(d).get("source") == "meeting":
        return Path(d) / "audio" / "system.flac"
    from .transcribe import audio_file
    return audio_file(d)


def _who(s: dict, turns: list) -> str | None:
    best, best_ov = None, 0.0
    for t0, t1, spk in turns:
        ov = min(t1, s["t1"]) - max(t0, s["t0"])
        if ov > best_ov:
            best, best_ov = spk, ov
    if best is not None:
        return best
    gap, near = NEAREST_S, None
    for t0, t1, spk in turns:
        g = max(t0 - s["t1"], s["t0"] - t1)
        if g <= gap:
            gap, near = g, spk
    return near


ONE_ON_ONE = re.compile(r"\b1\s*[:/]\s*1\b|\b1[- ]on[- ]1\b|\bone[- ]on[- ]one\b", re.I)


def other_side_cap(meta: dict) -> int | None:
    """How many people the other side of a call can be (dictado-gk9): 1 for a meeting named as a 1:1,
    else the calendar invite's guests minus the user; None when nothing says."""
    if meta.get("source") != "meeting":
        return None
    if ONE_ON_ONE.search(str(meta.get("title") or "")):
        return 1
    att = (meta.get("calendar") or {}).get("attendees") or []
    return max(1, len(att) - 1) if len(att) >= 2 else None


def cap_turns(turns: list, cap: int | None, voices_by_spk: dict | None = None) -> list:
    """Fold the add-on's speakers beyond `cap` into the ones kept (the ones who talked most): each
    into the kept voice it sounds most like when the add-on gave voices, else into the main one."""
    talk: dict = {}
    for t0, t1, spk in turns:
        talk[spk] = talk.get(spk, 0.0) + (t1 - t0)
    if not cap or len(talk) <= cap:
        return turns
    keep = sorted(talk, key=talk.get, reverse=True)[:cap]
    vs = voices_by_spk or {}

    def home(spk):
        if spk in keep:
            return spk
        if spk in vs and all(k in vs for k in keep):
            from .voices import cosine
            return max(keep, key=lambda k: cosine(vs[spk], vs[k]))
        return keep[0]
    to = {spk: home(spk) for spk in talk}
    log.info("speakers capped at %d: %d voices folded", cap, len(talk) - cap)
    return [[t0, t1, to[spk]] for t0, t1, spk in turns]


def assign(segments: list[dict], turns: list, target) -> int:
    """Relabel the segments whose speaker is `target` ("Others" for a meeting, None for an
    import). Returns how many remote voices were found; with fewer than two nothing changes."""
    return _assign(segments, turns, target)[1]


def _assign(segments: list[dict], turns: list, target) -> tuple[dict, int]:
    """assign(), also returning {add-on label: label in the transcript} ("SPEAKER_01" -> "Speaker 2")."""
    picks = [(s, _who(s, turns)) for s in sorted(segments, key=lambda s: s["t0"]) if s.get("speaker") == target]
    order: list[str] = []
    for _, spk in picks:
        if spk is not None and spk not in order:
            order.append(spk)
    if len(order) == 1:
        return ({order[0]: target} if target else {}), 1
    if len(order) >= 2:
        for s, spk in picks:
            if spk is not None:
                s["speaker"] = f"Speaker {order.index(spk) + 1}"
        return {spk: f"Speaker {i + 1}" for i, spk in enumerate(order)}, len(order)
    return {}, 0


def _remember(d: Path, out: Path, turns: list, shown: dict, memory: Path | None) -> dict:
    """t0u.32: keep this call's voices (per transcript label) and name the ones the memory knows.
    Returns {label: name} for the speakers recognised; {} when off or the add-on is pre-1.1."""
    side = Path(str(out.with_suffix("")) + ".voices.json")
    if memory is None or not side.exists():
        side.unlink(missing_ok=True)
        return {}
    from . import voices
    raw = json.loads(side.read_text(encoding="utf-8"))
    side.unlink(missing_ok=True)
    talk: dict = {}
    for t0, t1, spk in turns:
        talk[spk] = talk.get(spk, 0.0) + (t1 - t0)
    embs = {shown[spk]: v for spk, v in raw.items()
            if spk in shown and shown[spk] and talk.get(spk, 0.0) >= voices.MIN_SPEECH_S}
    if not embs:
        return {}
    sessions._write_json(d / "voices.json", embs)  # what rename_speaker learns from
    return {label: name for label, (name, _s) in voices.match(embs, voices.load(memory)).items()}


def _run_addon(audio: Path, out: Path) -> int:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run([str(addon_exe()), str(audio), str(out)], timeout=TIMEOUT_S, creationflags=flags).returncode


READABLE = {".flac", ".wav", ".ogg", ".mp3"}  # what the add-on's soundfile opens directly


def _to_flac(src: Path, dst: Path) -> None:
    """16 kHz mono FLAC of any file Ecoscribe can decode (m4a, mp4, webm...)."""
    from faster_whisper import decode_audio
    from .flacw import FlacWriter
    w = FlacWriter(dst)
    try:
        w.write(decode_audio(str(src), sampling_rate=16000))
    finally:
        w.close()


def run(session_dir: Path, run_addon=_run_addon, convert=_to_flac, memory: Path | None = None) -> int:
    d = Path(session_dir)
    tmp = d / "speakers-input.flac"  # next to audio/, never in it: audio_file() wants one source
    try:
        meta = sessions.write_meta(d, speakers="running", speakers_error=None)
        out = d / "speakers.json"
        src = track(d)
        if src.suffix.lower() not in READABLE:
            convert(src, tmp)
            src = tmp
        rc = run_addon(src, out)
        if rc != 0:
            raise RuntimeError(f"the speaker add-on ended with code {rc}")
        turns = json.loads(out.read_text(encoding="utf-8"))
        cap = other_side_cap(meta)
        if cap:  # a 1:1 or an invite: never more voices on the other side than people (dictado-gk9)
            side = Path(str(out.with_suffix("")) + ".voices.json")
            try:
                vs = json.loads(side.read_text(encoding="utf-8")) if side.exists() else None
            except (OSError, ValueError):
                vs = None
            turns = cap_turns(turns, cap, vs)
        path = d / "transcript.json"
        tr = json.loads(path.read_text(encoding="utf-8"))
        shown, n = _assign(tr["segments"], turns, "Others" if meta.get("source") == "meeting" else None)
        if n >= 2:
            sessions._write_json(path, tr)
        known = {}
        try:
            known = _remember(d, out, turns, shown, memory)
        except Exception:
            log.exception("voice memory skipped")
        if known:
            names = dict(sessions.read_meta(d).get("speaker_names") or {})
            for label, name in known.items():
                names.setdefault(label, name)  # a name the user already typed wins
            sessions.write_meta(d, speaker_names=names, speakers_recognised=sorted(known))
        if n >= 2 or known:
            export.write_all(d)
        sessions.write_meta(d, speakers="done", speakers_n=n)
        log.info("speakers done n=%d turns=%d %s", n, len(turns), d)
        return 0
    except Exception as e:
        log.exception("speakers pass failed")
        try:
            sessions.write_meta(d, speakers="failed", speakers_error=f"{type(e).__name__}: {e}")
        except Exception:
            log.exception("could not mark %s", d)
        return 1
    finally:
        tmp.unlink(missing_ok=True)


def main(session_dir: str) -> int:
    """`ecoscribe --speakers DIR`: called from __main__, which hard-exits with the result."""
    from . import winutil
    d = Path(session_dir)
    winutil.setup_logging(d / "worker.log", logging.INFO)
    from . import config, paths
    cfg = config.load(paths.config_path())
    return run(d, memory=paths.data_dir() / "voices.json" if cfg.meetings.voice_memory else None)
