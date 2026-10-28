"""Ecoscribe's own copy of the Whisper model, as plain files.

The Hugging Face cache stores model files as symlinks into a blobs folder. The
copy of Ecoscribe started by the installer could not open them ("Unable to open
file 'model.bin'", 2026-10-02) while the same exe launched otherwise could. So
the model is mirrored into %LOCALAPPDATA%\\ecoscribe\\models\\<name> with hard links
to the real blobs (no extra disk space, nothing to resolve at load time); copies
if hard links are impossible.

Repo ids (`KBLab/kb-whisper-large`) mirror to `models/KBLab--kb-whisper-large` and
download with huggingface_hub.snapshot_download; short names (`large-v3-turbo`)
go through faster-whisper's own download_model as before.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from fnmatch import fnmatch
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)
DONE = ".complete"
_lock = threading.Lock()


CT2_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def safe_name(name: str) -> str:
    return name.replace("/", "--")


def _dir_bytes(d: Path) -> int:
    total = 0
    for f in Path(d).rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _tree_bytes(d: Path) -> int:
    """Bytes under `d` while a download runs, following links once per real file: huggingface_hub 1.x
    moves a finished file to a shared store and leaves a link, which _dir_bytes would stop counting."""
    total, seen = 0, set()
    for f in Path(d).rglob("*"):
        try:
            st = f.stat()
        except OSError:
            continue
        if f.is_file() and (st.st_dev, st.st_ino) not in seen:
            seen.add((st.st_dev, st.st_ino))
            total += st.st_size
    return total


def _repo_total(repo: str) -> int | None:
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo, files_metadata=True)
        return sum(s.size or 0 for s in info.siblings if any(fnmatch(s.rfilename, p) for p in CT2_FILES)) or None
    except Exception:
        log.warning("could not read the size of %s", repo, exc_info=True)
        return None


def _snapshot(repo: str, progress=None, cache_dir=None) -> str:
    from huggingface_hub import constants, snapshot_download
    try:
        return snapshot_download(repo, allow_patterns=CT2_FILES, local_files_only=True, cache_dir=cache_dir)
    except Exception:
        log.info("model %s not in the HF cache, downloading", repo)
    if progress is None:
        return snapshot_download(repo, allow_patterns=CT2_FILES, cache_dir=cache_dir)
    total = _repo_total(repo)
    blobs = Path(cache_dir or constants.HF_HUB_CACHE) / f"models--{safe_name(repo)}" / "blobs"
    stop = threading.Event()

    def poll():  # finished blobs + the .incomplete ones being written
        while not stop.wait(1.0):
            progress(_tree_bytes(blobs) if blobs.exists() else 0, total)
    t = threading.Thread(target=poll, name="model-progress", daemon=True)
    t.start()
    try:
        return snapshot_download(repo, allow_patterns=CT2_FILES, cache_dir=cache_dir)
    finally:
        stop.set()
        t.join()


def _hf_download(name: str, progress=None, cache_dir=None) -> str:
    if "/" in name:
        return _snapshot(name, progress, cache_dir)
    from faster_whisper.utils import _MODELS, download_model
    if progress is not None and name in _MODELS:  # the same files download_model fetches, with progress
        return _snapshot(_MODELS[name], progress, cache_dir)
    try:
        return download_model(name, local_files_only=True, cache_dir=cache_dir)
    except Exception:
        log.info("model %s not in the HF cache, downloading", name)
        return download_model(name, cache_dir=cache_dir)


class _monotonic:
    """Progress hook that never reports less than before; finish() reports done == total."""

    def __init__(self, fn):
        self.fn, self.done = fn, 0

    def __call__(self, done, total):
        self.done = max(self.done, int(done))
        self.fn(self.done, total)

    def finish(self, n):
        n = max(self.done, int(n))
        self.done = n
        self.fn(n, n)


def is_local(name: str, root: Path | None = None) -> bool:
    """True when `name` is an existing path or a complete mirror (no download needed)."""
    if os.path.isdir(name):
        return True
    root = Path(root) if root else paths.data_dir() / "models"
    out = root / safe_name(name)
    return (out / DONE).exists() and (out / "model.bin").exists()


def ensure_local(name: str, root: Path | None = None, download=_hf_download, progress=None,
                 cache_dir: Path | None = None) -> Path:
    """Directory with real model files for `name` (a model name, a repo id or an existing path).

    progress(done_bytes, total_bytes | None) is called while downloading, and always once
    at the end with done == total."""
    if os.path.isdir(name):
        return Path(name)
    if progress:
        progress = _monotonic(progress)
    root = Path(root) if root else paths.data_dir() / "models"
    out = root / safe_name(name)
    if is_local(name, root):
        if progress:
            progress.finish(_dir_bytes(out))
        return out
    kw = {}
    if progress:
        kw["progress"] = progress
    if cache_dir is not None:
        kw["cache_dir"] = str(cache_dir)
    src = Path(download(name, **kw))
    tmp = root / f".{safe_name(name)}.{os.getpid()}.{threading.get_ident()}.tmp"  # per caller: no shared scratch dir
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for f in src.iterdir():
        real = Path(os.path.realpath(f))
        if not real.is_file():
            continue
        try:
            os.link(real, tmp / f.name)
        except OSError:
            shutil.copy2(real, tmp / f.name)
    (tmp / DONE).write_text(str(src), encoding="utf-8")
    with _lock:
        if (out / DONE).exists() and (out / "model.bin").exists():  # another caller finished first
            shutil.rmtree(tmp, ignore_errors=True)
            return out
        shutil.rmtree(out, ignore_errors=True)
        try:
            os.replace(tmp, out)
        except OSError:
            if (out / DONE).exists() and (out / "model.bin").exists():
                shutil.rmtree(tmp, ignore_errors=True)
                return out
            raise
    log.info("model %s mirrored to %s", name, out)
    if progress:
        progress.finish(_dir_bytes(out))
    return out


def for_transcribe(name: str, cfg, download=_hf_download, progress=None) -> Path:
    """ensure_local for a transcription model, honoring TranscribeCfg.models_root."""
    if not cfg.models_root or is_local(name):  # e.g. dictation's turbo, already in the default dir
        return ensure_local(name, download=download, progress=progress)
    root = Path(cfg.models_root)
    return ensure_local(name, root=root, download=download, progress=progress, cache_dir=root / "hf")


# ---------------- first-run setup (dictado-zpz) ----------------
# Approximate download sizes, shown before the real total is known.
CPU_MODEL = "small"  # dictation without an NVIDIA GPU (engine.py's CPU fallback); dictado-7t38
SIZES = {"large-v3-turbo": 1_620_000_000, "Systran/faster-whisper-large-v3": 3_090_000_000, CPU_MODEL: 484_000_000}


def no_gpu(wcfg) -> bool:
    """True on a Windows PC with no NVIDIA driver: dictation runs on CPU_MODEL there (engine.py), so setup and the
    app fetch that one. The Mac always has its GPU (mlx). dictado-7t38"""
    if sys.platform != "win32" or wcfg.device != "cuda":
        return False
    from . import gpu
    return gpu.driver_cuda() is None


def setup_models(wcfg, languages, cpu: bool = False) -> list[dict]:
    """The two speech models Ecoscribe uses, fast first. `required`: the one dictation in
    `languages` runs on; the other is recommended (meetings and files use both).
    cpu (no_gpu): dictation runs on CPU_MODEL, listed first and needed; the GPU two are left unticked (dictado-7t38)."""
    from .languages import ALL, TURBO_OK, needs_big_model
    big = needs_big_model(languages)
    # dictado-607: named with the user's own languages, never a fixed "Swedish, Greek" for everyone
    names = lambda cs: " and ".join(filter(None, [", ".join(ALL.get(c, c) for c in cs[:-1]), ALL.get(cs[-1], cs[-1])]))  # noqa: E731
    fast = [c for c in languages or [] if c in TURBO_OK]
    slow = [c for c in languages or [] if c not in TURBO_OK]
    rows = [
        {"name": wcfg.model, "label": "Fast", "use": (f"For your {names(fast)}" if fast else "English, Spanish and similar")
         + "; finds the language in meetings and files",
         "size": SIZES.get(wcfg.model, 1_620_000_000), "required": not big},
        {"name": wcfg.sv_model, "label": "Most accurate", "use": (f"For your {names(slow)}" if slow else "Languages the fast one isn't good at")
         + "; meetings and files in them",
         "size": SIZES.get(wcfg.sv_model, 3_090_000_000), "required": big},
    ]
    if not cpu:
        return rows
    for r in rows:
        r.update(required=False, checked=False, use=r["use"] + "; slow without a graphics card")
    return [{"name": CPU_MODEL, "label": "For this computer", "tag": "Needed on this computer",
             "use": "Dictation on the processor: this computer has no NVIDIA graphics card",
             "size": SIZES[CPU_MODEL], "required": True}] + rows


def _mlx():
    from .platform.macos import mlx_engine
    return mlx_engine


def is_ready(name: str, root: Path | None = None) -> bool:
    """True when `name` needs no download on this platform."""
    repo = _mlx().mlx_repo(name) if sys.platform == "darwin" else None
    if repo:  # Mac: the mlx conversion; a model without one runs faster-whisper there too (mlx_engine.factory)
        return bool(_mlx().is_cached_mlx(repo))
    return is_local(name, root)


def prepare(name: str, progress=None, root: Path | None = None, download=_hf_download) -> Path:
    """Download `name` for this platform (once), calling progress(done_bytes, total_bytes | None)."""
    repo = _mlx().mlx_repo(name) if sys.platform == "darwin" else None
    if repo:
        return Path(_mlx().ensure_mlx(repo, progress=progress))
    return ensure_local(name, root=root, download=download, progress=progress)


# ---------------- Settings > Speech models (dictado-z4q) ----------------
def _hf_cache_dir(name: str) -> Path | None:
    """The Hugging Face cache folder that holds `name`'s download on this platform."""
    from huggingface_hub import constants
    repo = None
    if sys.platform == "darwin":
        repo = _mlx().mlx_repo(name)
    if repo is None:
        if "/" in name:
            repo = name
        else:
            from faster_whisper.utils import _MODELS
            repo = _MODELS.get(name)
    return Path(constants.HF_HUB_CACHE) / f"models--{safe_name(repo)}" if repo else None


def disk_size(name: str, root: Path | None = None) -> int:
    """Bytes `name` takes on disk: the download (the mirror hard-links it, so it isn't counted twice)."""
    cache = _hf_cache_dir(name)
    root = Path(root) if root else paths.data_dir() / "models"
    total = _tree_bytes(cache) if cache and cache.exists() else 0
    mirror = root / safe_name(name)
    if mirror.exists():
        total = max(total, _tree_bytes(mirror))
    return total


def _drop_from_hf_cache(cache: Path) -> None:
    """Delete a cached repo with huggingface_hub's own cache API. Since huggingface_hub 1.x a big file
    lives in the cache-wide blobs/ store with only a link in the repo's folder, so removing the folder
    alone left the 1.6 GB weights on disk while Settings said 0 MB (seen on the Mac)."""
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir(cache.parent)
        revs = [r.commit_hash for repo in info.repos if repo.repo_path == cache for r in repo.revisions]
        if revs:
            info.delete_revisions(*revs).execute()
    except Exception:  # the folder itself still goes below; a shared blob may then stay behind
        log.warning("cache API delete failed for %s", cache, exc_info=True)


def delete(name: str, root: Path | None = None) -> bool:
    """Free the space: the mirror and the download. It downloads again the next time it's needed.
    False when there was nothing to delete; OSError when a file is in use (a dictation running)."""
    root = Path(root) if root else paths.data_dir() / "models"
    gone = False
    cache = _hf_cache_dir(name)
    if cache is not None and cache.exists():
        _drop_from_hf_cache(cache)
        gone = True
    for d in (root / safe_name(name), cache):
        if d is not None and d.exists():
            shutil.rmtree(d)
            gone = True
    return gone
