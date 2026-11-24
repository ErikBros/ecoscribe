"""The GPU timing tests' engine worker reads a pinned config, not the user's dictation languages (dictado-i8bw).

A worker started by EngineProxy loads config.toml itself; with a language turbo handles poorly (Swedish, say) among the
dictation languages it ran large-v3 instead of turbo and the latency test measured ~1.15 s instead of ~250 ms."""
from ecoscribe import config
from ecoscribe.config import WhisperCfg
from ecoscribe.engine import dictation_model
from tests.engine_cfg import pinned_config, pinned_proxy

USER = """[whisper]
languages = ["en", "sv"]

[transcribe]
models_root = "D:/models"
"""


def _user(tmp_path):
    p = tmp_path / "user" / "config.toml"
    p.parent.mkdir()
    p.write_text(USER, encoding="utf-8")
    return p


def test_the_users_big_model_languages_pick_large_v3(tmp_path):
    assert dictation_model(config.load(_user(tmp_path)).whisper)[0] == "Systran/faster-whisper-large-v3"


def test_pinned_config_runs_turbo_and_keeps_the_rest(tmp_path):
    out = pinned_config(tmp_path / "pinned.toml", src=_user(tmp_path))
    cfg = config.load(out)
    assert dictation_model(cfg.whisper) == ("large-v3-turbo", "float16")
    assert cfg.whisper.languages == ["en"]
    assert cfg.transcribe.models_root == "D:/models"  # the meeting/file side stays the user's


def test_pinned_config_takes_a_given_whisper(tmp_path):
    out = pinned_config(tmp_path / "pinned.toml", src=_user(tmp_path), whisper=WhisperCfg(idle_exit_s=5.0))
    assert config.load(out).whisper.idle_exit_s == 5.0


def test_pinned_proxy_starts_its_worker_on_the_pinned_config(tmp_path):
    seen = []
    e = pinned_proxy(tmp_path, src=_user(tmp_path), spawn_with=lambda path: seen.append(path))
    try:
        e.spawn()
        assert len(seen) == 1
        assert dictation_model(config.load(seen[0]).whisper)[0] == "large-v3-turbo"
        assert e.cfg.languages == ["en"]
    finally:
        e._closed.set()
