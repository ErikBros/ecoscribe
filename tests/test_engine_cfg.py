"""The GPU timing tests' engine worker reads a pinned config, not the user's dictation languages (dictado-i8bw).

A worker started by EngineProxy loads config.toml itself; with a language turbo handles poorly (Swedish, say) among the
dictation languages it ran large-v3 instead of turbo: the latency test's base was ~0.7 s, not ~250 ms."""
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
    p.parent.mkdir(exist_ok=True)
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


def test_latency_runs_the_default_model_unless_asked_for_the_users(tmp_path):
    from tests.engine_cfg import latency_whisper
    assert latency_whisper({}, src=_user(tmp_path)) is None  # pinned_config's default: turbo
    mine = latency_whisper({"ECOSCRIBE_LATENCY_USER_MODEL": "1"}, src=_user(tmp_path))
    assert dictation_model(mine)[0] == "Systran/faster-whisper-large-v3"


def test_the_200_ms_limit_is_for_the_default_model_only():
    from tests.engine_cfg import latency_limit_ms
    assert latency_limit_ms(WhisperCfg()) == 200
    assert latency_limit_ms(WhisperCfg(languages=["en", "sv"])) is None  # the big model: no fixed limit (dictado-fgdc)
