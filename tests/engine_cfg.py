"""A config.toml for the engine worker of a GPU timing test (dictado-i8bw).

The worker EngineProxy starts reads config.toml itself, never the WhisperCfg the test passed. With a
language turbo handles poorly among the user's dictation languages (Swedish, say: languages.TURBO_OK)
it ran large-v3: a base of ~0.7 s where turbo takes ~250 ms (and ~1.15 s later on the same PC, with no
code change behind it). The pinned file keeps
the run's config (models_root, the meeting and file side) and sets [whisper] and [text] to the test's
own, so the number is the same on every PC, whatever languages its user dictates in.
"""
from __future__ import annotations

from pathlib import Path

from ecoscribe import config, paths, tomlw
from ecoscribe.config import TextCfg, WhisperCfg


def pinned_config(dst: Path, src: Path | None = None, whisper: WhisperCfg | None = None,
                  text: TextCfg | None = None) -> Path:
    """Write the run's config (or `src`) with the given [whisper] and [text] (default: the defaults) to dst."""
    cfg = config.load(src or paths.config_path())
    cfg.whisper = whisper or WhisperCfg(on_demand=True)
    cfg.text = text or TextCfg()
    tomlw.save(cfg, dst)
    return Path(dst)


def pinned_proxy(tmp_path: Path, src: Path | None = None, whisper: WhisperCfg | None = None,
                 text: TextCfg | None = None, spawn_with=None, **kw):
    """An EngineProxy whose worker reads a pinned config in tmp_path (spawn_with(path): the worker starter)."""
    from ecoscribe.engine_proc import EngineProxy, spawn_worker
    path = pinned_config(Path(tmp_path) / "engine-config.toml", src, whisper, text)
    cfg = config.load(path)
    start = spawn_with or spawn_worker
    kw.setdefault("check_s", None)
    return EngineProxy(cfg.whisper, cfg.text, spawn=lambda: start(path), **kw)


USER_MODEL = "ECOSCRIBE_LATENCY_USER_MODEL"  # =1: the latency test times the user's own dictation model


def latency_whisper(env, src: Path | None = None) -> WhisperCfg | None:
    """The [whisper] the latency test runs: None (pinned_config's default, turbo), or with USER_MODEL=1 the
    user's own, so one idle run can time both models (dictado-i8bw)."""
    if env.get(USER_MODEL) != "1":
        return None
    return config.load(src or paths.config_path()).whisper


LIMIT_MS = 200  # criterion 6, amended by the user 2026-10-02, set for turbo


def latency_limit_ms(whisper: WhisperCfg) -> int | None:
    """The +200 ms limit next to a file job holds for the default dictation model; the big model
    (large-v3, for languages turbo handles poorly) has no fixed limit: the user's call, dictado-fgdc."""
    from ecoscribe.engine import dictation_model
    return LIMIT_MS if dictation_model(whisper) == dictation_model(WhisperCfg()) else None
