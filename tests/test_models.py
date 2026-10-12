import pytest
import os
from pathlib import Path

from ecoscribe import models


def make_src(tmp_path):
    blobs = tmp_path / "hf" / "blobs"
    snap = tmp_path / "hf" / "snapshots" / "abc"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    for name, data in {"model.bin": b"M" * 1000, "config.json": b"{}", "tokenizer.json": b"[]"}.items():
        (blobs / f"blob-{name}").write_bytes(data)
        try:
            os.symlink(blobs / f"blob-{name}", snap / name)  # how the HF cache looks (dev mode)
        except OSError:
            (snap / name).write_bytes(data)  # no symlink privilege: plain files
    return snap


def test_local_copy_has_real_files(tmp_path):
    src = make_src(tmp_path)
    out = models.ensure_local("large-v3-turbo", root=tmp_path / "models", download=lambda name: str(src))
    assert (out / "model.bin").read_bytes() == b"M" * 1000
    assert not (out / "model.bin").is_symlink()
    assert {p.name for p in out.iterdir()} - {models.DONE} == {"model.bin", "config.json", "tokenizer.json"}


def test_second_call_does_not_redownload(tmp_path):
    src = make_src(tmp_path)
    calls = []
    dl = lambda name: calls.append(name) or str(src)  # noqa: E731
    a = models.ensure_local("m", root=tmp_path / "models", download=dl)
    b = models.ensure_local("m", root=tmp_path / "models", download=dl)
    assert a == b and calls == ["m"]


def test_half_written_copy_is_redone(tmp_path):
    src = make_src(tmp_path)
    root = tmp_path / "models"
    (root / "m").mkdir(parents=True)
    (root / "m" / "config.json").write_text("{}")  # no model.bin + no done marker
    out = models.ensure_local("m", root=root, download=lambda n: str(src))
    assert (out / "model.bin").exists()


def test_path_names_pass_through(tmp_path):
    d = tmp_path / "custom"
    d.mkdir()
    assert models.ensure_local(str(d), root=tmp_path / "models", download=None) == d


def test_copy_fallback_when_hard_links_fail(tmp_path, monkeypatch):
    src = make_src(tmp_path)
    def no_link(*a):
        raise OSError("cross-device")
    monkeypatch.setattr(models.os, "link", no_link)
    out = models.ensure_local("m", root=tmp_path / "models", download=lambda n: str(src))
    assert (out / "model.bin").read_bytes() == b"M" * 1000


def test_concurrent_callers_both_get_a_complete_copy(tmp_path):
    import threading
    src = make_src(tmp_path)
    got, errs = [], []

    def go():
        try:
            got.append(models.ensure_local("m", root=tmp_path / "models", download=lambda n: str(src)))
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs and len(got) == 4
    assert all((g / "model.bin").read_bytes() == b"M" * 1000 for g in got)


def test_repo_id_mirrors_to_safe_dir(tmp_path):
    src = make_src(tmp_path)
    out = models.ensure_local("KBLab/kb-whisper-large", root=tmp_path / "models", download=lambda n: str(src))
    assert out.name == "KBLab--kb-whisper-large"
    assert out.parent == tmp_path / "models"
    assert (out / models.DONE).exists() and (out / "model.bin").exists()


def test_is_local_false_then_true(tmp_path):
    src = make_src(tmp_path)
    root = tmp_path / "models"
    assert not models.is_local("KBLab/kb-whisper-large", root=root)
    models.ensure_local("KBLab/kb-whisper-large", root=root, download=lambda n: str(src))
    assert models.is_local("KBLab/kb-whisper-large", root=root)


def test_is_local_true_for_existing_path(tmp_path):
    assert models.is_local(str(tmp_path), root=tmp_path / "models")


def test_progress_callback_called_with_final_total(tmp_path):
    src = make_src(tmp_path)
    seen = []

    def dl(name, progress=None):
        progress(10, 1000)
        progress(1000, 1000)
        return str(src)
    models.ensure_local("KBLab/kb-whisper-large", root=tmp_path / "models", download=dl,
                        progress=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1][0] == seen[-1][1]
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_progress_reported_when_already_local(tmp_path):
    src = make_src(tmp_path)
    root = tmp_path / "models"
    models.ensure_local("m", root=root, download=lambda n: str(src))
    seen = []
    models.ensure_local("m", root=root, download=None, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1][0] == seen[-1][1] > 0


def test_hf_progress_counts_blobs(tmp_path):
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    (blobs / "a").write_bytes(b"x" * 300)
    (blobs / "b.incomplete").write_bytes(b"x" * 200)
    assert models._dir_bytes(blobs) == 500


def test_models_root_puts_cache_and_mirror_on_root(tmp_path):
    from ecoscribe.config import TranscribeCfg
    src = make_src(tmp_path)
    seen = {}

    def dl(name, cache_dir=None):
        seen["cache_dir"] = cache_dir
        return str(src)
    root = tmp_path / "E" / "ecoscribe-models"
    # a repo id that is never in the default dir (KB-Whisper may be, on the user's PC)
    out = models.for_transcribe("Test/never-local", TranscribeCfg(models_root=str(root)), download=dl)
    assert out == root / "Test--never-local"
    assert Path(seen["cache_dir"]) == root / "hf"


def test_empty_models_root_uses_default_dir(tmp_path, monkeypatch):
    from ecoscribe.config import TranscribeCfg
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.setenv("ECOSCRIBE_DATA_DIR", str(tmp_path / "lad" / "ecoscribe"))  # macOS data dir
    src = make_src(tmp_path)
    calls = []
    out = models.for_transcribe("m", TranscribeCfg(), download=lambda n: calls.append(n) or str(src))
    assert out == tmp_path / "lad" / "ecoscribe" / "models" / "m"
    assert calls == ["m"]  # no cache_dir passed: the default HF cache


def test_models_root_round_trips_in_config(tmp_path):
    from ecoscribe import tomlw
    from ecoscribe.config import Config, load
    c = Config()
    c.transcribe.models_root = "E:\\ecoscribe-models"
    p = tmp_path / "c.toml"
    tomlw.save(c, p)
    assert load(p).transcribe.models_root == "E:\\ecoscribe-models"


def test_models_root_reuses_existing_default_mirror(tmp_path, monkeypatch):
    """Dictation's turbo already lives in the default dir: don't download it again to E:."""
    from ecoscribe.config import TranscribeCfg
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.setenv("ECOSCRIBE_DATA_DIR", str(tmp_path / "lad" / "ecoscribe"))  # macOS data dir
    src = make_src(tmp_path)
    default = models.ensure_local("large-v3-turbo", download=lambda n: str(src))
    out = models.for_transcribe("large-v3-turbo", TranscribeCfg(models_root=str(tmp_path / "E")),
                                download=lambda n, cache_dir=None: pytest.fail("downloaded again"))
    assert out == default


def test_setup_models_needed_one_is_required_by_the_languages():
    from ecoscribe.config import WhisperCfg
    w = WhisperCfg()
    fast, big = models.setup_models(w, ["en"])
    assert (fast["name"], fast["required"]) == (w.model, True)
    assert (big["name"], big["required"]) == (w.sv_model, False)
    fast, big = models.setup_models(w, ["en", "sv"])  # Swedish runs dictation on large-v3
    assert (fast["required"], big["required"]) == (False, True)
    assert fast["size"] < big["size"]


def test_prepare_reports_progress_and_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(models.sys, "platform", "win32")
    src = make_src(tmp_path)
    seen = []
    out = models.prepare("large-v3-turbo", progress=lambda d, t: seen.append((d, t)),
                         root=tmp_path / "models", download=lambda name, **kw: str(src))
    assert (out / "model.bin").exists()
    assert seen[-1][0] == seen[-1][1] > 0
    assert models.is_ready("large-v3-turbo", root=tmp_path / "models")
    assert not models.is_ready("Systran/faster-whisper-large-v3", root=tmp_path / "models")


def test_short_names_download_with_progress_through_the_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(models, "_snapshot", lambda repo, progress=None, cache_dir=None: calls.append(repo) or "/x")
    assert models._hf_download("large-v3-turbo", progress=lambda d, t: None) == "/x"
    assert calls and "turbo" in calls[0]


def test_tree_bytes_follows_links_once(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "big").write_bytes(b"x" * 500)
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    (blobs / "small").write_bytes(b"y" * 20)
    try:
        (blobs / "big").symlink_to(shared / "big")  # huggingface_hub 1.x: a finished file moves, a link stays
        (blobs / "big2").symlink_to(shared / "big")
    except OSError:
        pytest.skip("no symlink privilege")
    assert models._tree_bytes(blobs) == 520


def test_mac_model_without_mlx_conversion_uses_the_ct2_mirror(tmp_path, monkeypatch):
    import types
    monkeypatch.setattr(models.sys, "platform", "darwin")
    fake = types.SimpleNamespace(mlx_repo=lambda name: None, ensure_mlx=lambda *a, **k: pytest.fail("no mlx path"))
    monkeypatch.setattr(models, "_mlx", lambda: fake)
    src = make_src(tmp_path)
    out = models.prepare("KBLab/kb-whisper-large", root=tmp_path / "models", download=lambda name, **kw: str(src))
    assert (out / "model.bin").exists()
    assert models.is_ready("KBLab/kb-whisper-large", root=tmp_path / "models")
