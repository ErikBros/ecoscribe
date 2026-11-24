"""A config.toml for the engine worker of a GPU timing test (dictado-i8bw).

The worker EngineProxy starts reads config.toml itself, never the WhisperCfg the test passed. With a
language turbo handles poorly among the user's dictation languages (Swedish, say: languages.TURBO_OK)
it ran large-v3 and the latency test measured ~1.15 s where turbo takes ~250 ms. The pinned file keeps
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
