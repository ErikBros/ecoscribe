"""Download progress for the Mac's mlx models (dictado-kuu): the same contract as models.ensure_local."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="mlx models are the Mac's")

REPO = "mlx-community/whisper-test"


def fake_download(cache, sizes, delay=0.0):
    """Writes the files the way huggingface_hub does: blobs (via .incomplete), then the snapshot links."""
    calls = []

    def download(repo, cache_dir=None, on_bytes=None):
        calls.append(repo)
        base = cache / f"models--{repo.replace('/', '--')}"
        blobs, snap = base / "blobs", base / "snapshots" / "abc"
        blobs.mkdir(parents=True, exist_ok=True)
        snap.mkdir(parents=True, exist_ok=True)
        (base / "refs").mkdir(exist_ok=True)
        (base / "refs" / "main").write_text("abc")
        for name, n in sizes.items():
            part = blobs / f"{name}.incomplete"
            part.write_bytes(b"x" * (n // 2))
            time.sleep(delay)
            part.write_bytes(b"x" * n)
            if name.startswith("weights"):  # huggingface_hub 1.x: big files go to the shared store + a link
                shared = cache / "blobs" / "ab"
                shared.mkdir(parents=True, exist_ok=True)
                part.rename(shared / name)
                if not (blobs / name).is_symlink():
                    (blobs / name).symlink_to(shared / name)
            else:
                part.rename(blobs / name)
            if not (snap / name).is_symlink():
                (snap / name).symlink_to(blobs / name)
        return str(snap)
    return download, calls


SIZES = {"config.json": 100, "weights.safetensors": 5000}


def test_progress_ends_at_total_and_never_goes_down(tmp_path):
    from ecoscribe.platform.macos import mlx_engine
    dl, calls = fake_download(tmp_path, SIZES, delay=1.2)
    seen = []
    path = mlx_engine.ensure_mlx(REPO, progress=lambda d, t: seen.append((d, t)), download=dl,
                                 total=lambda r: 5100, cache_dir=str(tmp_path))
    assert calls == [REPO]
    assert path.endswith("abc")
    assert seen[-1] == (5100, 5100)
    done = [d for d, _ in seen]
    assert done == sorted(done)
    assert any(0 < d < 5100 for d in done)  # the poller saw a file being written
    assert all(t == 5100 for _, t in seen)


def test_cached_reports_done_at_once_and_does_not_download(tmp_path):
    from ecoscribe.platform.macos import mlx_engine
    dl, calls = fake_download(tmp_path, SIZES)
    dl(REPO)
    calls.clear()
    seen = []
    mlx_engine.ensure_mlx(REPO, progress=lambda d, t: seen.append((d, t)), download=dl,
                          total=lambda r: pytest.fail("no size lookup when cached"), cache_dir=str(tmp_path))
    assert calls == []
    assert seen == [(5100, 5100)]


def test_unknown_total_still_finishes_with_done_equal_total(tmp_path):
    from ecoscribe.platform.macos import mlx_engine
    dl, _ = fake_download(tmp_path, SIZES)
    seen = []
    mlx_engine.ensure_mlx(REPO, progress=lambda d, t: seen.append((d, t)), download=dl,
                          total=lambda r: None, cache_dir=str(tmp_path))
    assert seen[0][1] is None
    assert seen[-1] == (5100, 5100)


def test_no_progress_downloads_without_size_lookup(tmp_path):
    from ecoscribe.platform.macos import mlx_engine
    dl, calls = fake_download(tmp_path, SIZES)
    mlx_engine.ensure_mlx(REPO, download=dl, total=lambda r: pytest.fail("not needed"), cache_dir=str(tmp_path))
    assert calls == [REPO]


def test_is_cached_mlx_needs_the_weights_not_just_the_ref(tmp_path):
    from ecoscribe.platform.macos import mlx_engine
    assert not mlx_engine.is_cached_mlx(REPO, cache_dir=str(tmp_path))
    dl, _ = fake_download(tmp_path, {"config.json": 100})  # interrupted: ref + config, no weights
    dl(REPO)
    assert not mlx_engine.is_cached_mlx(REPO, cache_dir=str(tmp_path))
    dl, _ = fake_download(tmp_path, SIZES)
    dl(REPO)
    assert mlx_engine.is_cached_mlx(REPO, cache_dir=str(tmp_path))


def test_half_cached_repo_downloads_again(tmp_path):
    from ecoscribe.platform.macos import mlx_engine
    fake_download(tmp_path, {"config.json": 100})[0](REPO)
    dl, calls = fake_download(tmp_path, SIZES)
    mlx_engine.ensure_mlx(REPO, download=dl, cache_dir=str(tmp_path))
    assert calls == [REPO]


def test_network_bytes_move_the_bar_before_anything_is_on_disk(tmp_path):
    """Xet keeps a file off disk until it's rebuilt: the network counter is what moves the bar."""
    from ecoscribe.platform.macos import mlx_engine
    inner, _ = fake_download(tmp_path, SIZES)

    def dl(repo, cache_dir=None, on_bytes=None):
        for n in (1000, 2500, 4000):
            on_bytes("huggingface_hub.snapshot_download.transfer", n)
            time.sleep(1.1)
        return inner(repo)
    seen = []
    mlx_engine.ensure_mlx(REPO, progress=lambda d, t: seen.append((d, t)), download=dl,
                          total=lambda r: 5100, cache_dir=str(tmp_path))
    mid = [d for d, _ in seen[:-1]]
    assert any(1000 <= d <= 4000 for d in mid) and max(mid) < 5100
    assert seen[-1] == (5100, 5100)


def test_byte_counter_reports_only_the_byte_bars():
    from ecoscribe.platform.macos import mlx_engine
    got = []
    cls = mlx_engine._byte_counter(lambda bar, n: got.append((bar, n)))
    files = cls(total=3, unit="it", name="huggingface_hub.snapshot_download.files")
    files.update(1)
    net = cls(total=0, unit="B", name="huggingface_hub.snapshot_download.transfer")
    net.update(300)
    net.update(200)
    assert got == [("huggingface_hub.snapshot_download.transfer", 300), ("huggingface_hub.snapshot_download.transfer", 500)]
