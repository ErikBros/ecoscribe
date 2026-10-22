"""The GPU runtime pack (dictado-7e1): NVIDIA's CUDA libraries, fetched once instead of in every installer.

cuBLAS alone is 85 % of a full installer. The Windows app ships without the CUDA DLLs; they come as a
versioned zip (a GitHub release asset) that the background app downloads on its first start into
%LOCALAPPDATA%\\ecoscribe\\runtime\\<version>, verifies file by file and puts on the DLL search path
(platform/windows/sysutil.add_cuda_dll_dirs) before CTranslate2 loads. Until it is there, dictation and
meetings run on the CPU, as with an old driver (gpu.py), and the status says why.

ecoscribe/gpu_runtime.json (the manifest, written by tools/build.py --new-runtime) says which version
this app needs, where it lives, and the size and sha256 of the zip and of every DLL in it. A runtime of
another version, a half-written folder or a file with the wrong size is not used. An update installer
leaves the runtime alone; an app that needs a newer one fetches it and removes the old one.

Nothing here runs on the Mac (mlx on Metal, no CUDA) or from source (the pip nvidia-* DLLs load there).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

MANIFEST = Path(__file__).with_name("gpu_runtime.json")
ENV_DIR = "ECOSCRIBE_GPU_RUNTIME"  # a ready runtime folder: the release gate's selftest, a PC without internet
DONE = ".complete"  # written last, after every file checked: a folder without it is never used
MISSING = "the GPU runtime is not downloaded yet"  # the CPU reason while it is fetched (gpu.notice knows it)
MIN_DRIVER = 12000  # the driver must run CUDA 12.0 (gpu.driver_cuda): an older one gets no download, a notice
CHUNK = 1 << 20
WAITS = (60, 300, 900, 3600)  # seconds between tries after a failed download; the last one repeats


class DownloadError(Exception):
    """A download or unpack that failed; the message is for the user (status.json, a notice)."""


# ---------------- the manifest ----------------
def manifest(path: Path | None = None) -> dict | None:
    """The runtime this app needs, or None (a Mac build, a source checkout without the file)."""
    try:
        m = json.loads(Path(path or MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return m if isinstance(m.get("files"), dict) and m.get("version") else None


def unpacked_bytes(m: dict) -> int:
    return sum(int(f["size"]) for f in m["files"].values())


def _safe(name: str) -> bool:
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and ":" not in name and "\\" not in name


# ---------------- what is on disk ----------------
def runtime_root(data: Path) -> Path:
    return Path(data) / "runtime"


def folder(data: Path, m: dict) -> Path:
    return runtime_root(data) / str(m["version"])


def check(root: Path, m: dict, full: bool = False) -> str | None:
    """None when `root` holds this runtime; else what is wrong. Every start checks the marker and the
    sizes (a few stat calls); full=True also hashes every file (after an unpack, the gate)."""
    root = Path(root)
    try:
        mark = json.loads((root / DONE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "not unpacked"
    if str(mark.get("version")) != str(m["version"]) or mark.get("sha256") != m.get("sha256"):
        return f"version {mark.get('version')}, this app needs {m['version']}"
    for name, f in m["files"].items():
        p = root / name
        try:
            size = p.stat().st_size
        except OSError:
            return f"{name} is missing"
        if size != int(f["size"]):
            return f"{name} has {size} bytes, expected {f['size']}"
        if full and _sha256(p) != f["sha256"]:
            return f"{name} is damaged (checksum)"
    return None


def installed(data: Path, m: dict | None) -> Path | None:
    """The runtime folder for this app, ready to load; None when it isn't (yet)."""
    if not m:
        return None
    p = folder(data, m)
    return p if check(p, m) is None else None


def needed(m: dict | None = None, frozen: bool | None = None, platform: str | None = None) -> bool:
    """True when this app loads CUDA from the runtime pack: the installed Windows app. A source run loads
    the pip nvidia-* DLLs from site-packages; the Mac has no CUDA."""
    m = manifest() if m is None else m
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    return bool(m) and bool(frozen) and (platform or sys.platform) == "win32"


def dll_root(data: Path | None = None, m: dict | None = None) -> Path | None:
    """The folder whose nvidia/*/bin go on the DLL search path: ECOSCRIBE_GPU_RUNTIME if it holds the
    runtime, else the downloaded one; None when there is none."""
    m = manifest() if m is None else m
    if not m:
        return None
    env = os.environ.get(ENV_DIR)
    if env and check(Path(env), m) is None:
        return Path(env)
    if data is None:
        from . import paths
        data = paths.data_dir()
    return installed(data, m)


def missing(data: Path | None = None, m: dict | None = None, frozen: bool | None = None,
            platform: str | None = None) -> str | None:
    """MISSING when this app needs the runtime and it isn't there: the GPU is skipped (no doomed CUDA
    load, no gpu-failed note) until the background app has fetched it."""
    m = manifest() if m is None else m
    if not needed(m, frozen, platform):
        return None
    if dll_root(data, m) or _sizes_match(legacy_dir(), m):  # an old install's own DLLs load until moved
        return None
    return MISSING


def _sizes_match(root: Path | None, m: dict) -> bool:
    if root is None:
        return False
    try:
        return all((Path(root) / n).stat().st_size == int(f["size"]) for n, f in m["files"].items())
    except OSError:
        return False


# ---------------- download ----------------
def _sha256(path: Path, h=None) -> str:
    h = h or hashlib.sha256()
    with open(path, "rb") as f:
        while buf := f.read(CHUNK):
            h.update(buf)
    return h.hexdigest()


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 (our own https release URL)


def fetch(url: str, part: Path, size: int, sha256: str, progress=None, opener=_open, timeout: float = 30) -> Path:
    """Download `url` into `part`, going on from a partial file left by an earlier try. Raises
    DownloadError: offline or cut off (the part is kept to resume), or a wrong size or checksum (the
    part is removed: it can't be resumed)."""
    part = Path(part)
    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    h = hashlib.sha256()
    if have:
        _sha256(part, h)
    if have < size:
        if progress:
            progress(have, size)
        headers = {"User-Agent": "Ecoscribe"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with opener(urllib.request.Request(url, headers=headers), timeout) as r:
                code = getattr(r, "status", None) or r.getcode()
                if have and code != 206:  # the server sent the whole file: start over
                    log.info("GPU runtime: the server can't resume, downloading from the start")
                    have, h = 0, hashlib.sha256()
                with open(part, "ab" if have else "wb") as f:
                    while buf := r.read(CHUNK):
                        f.write(buf)
                        h.update(buf)
                        have += len(buf)
                        if progress:
                            progress(have, size)
                        if have > size:
                            break
        except urllib.error.HTTPError as e:
            raise DownloadError(f"the download server said {e.code} {e.reason}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:  # offline, DNS, cut off mid-way
            why = getattr(e, "reason", None) or e
            raise DownloadError(f"no connection ({why}); {have // 2**20} of {size // 2**20} MB kept") from e
    if have < size:
        raise DownloadError(f"the download stopped at {have // 2**20} of {size // 2**20} MB")
    if have > size or h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise DownloadError("the download was damaged (wrong size or checksum); it starts over next time")
    return part


def unpack(zip_path: Path, data: Path, m: dict) -> Path:
    """Unpack the pack into runtime/<version>, checking every DLL's size and sha256 against the
    manifest; the folder only gets its name (and the marker) once all of it checks out."""
    root = runtime_root(data)
    root.mkdir(parents=True, exist_ok=True)
    final = folder(data, m)
    tmp = root / f"{m['version']}.partial"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            members = set(z.namelist())
            for name, f in m["files"].items():
                if not _safe(name) or name not in members:
                    raise DownloadError(f"the GPU runtime pack has no {name}")
                out = tmp / name
                out.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with z.open(name) as src, open(out, "wb") as dst:
                    while buf := src.read(CHUNK):
                        dst.write(buf)
                        h.update(buf)
                if out.stat().st_size != int(f["size"]) or h.hexdigest() != f["sha256"]:
                    raise DownloadError(f"{name} in the GPU runtime pack is damaged")
    except zipfile.BadZipFile as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise DownloadError("the GPU runtime pack is not a zip") from e
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    (tmp / DONE).write_text(json.dumps({"version": m["version"], "sha256": m.get("sha256")}), encoding="utf-8")
    if final.exists():  # an older or broken copy of this version
        shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)
    return final


def prune(data: Path, m: dict) -> list[str]:
    """Remove runtimes of other versions and leftovers (best effort: a file in use stays for next time)."""
    gone, root = [], runtime_root(data)
    keep = {str(m["version"]), f"{m['asset']}.part"}
    for p in root.iterdir() if root.is_dir() else []:
        if p.name in keep:
            continue
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            gone.append(p.name)
        except OSError:
            log.info("GPU runtime: %s still in use, removed another time", p)
    return gone


def adopt(data: Path, m: dict, legacy: Path) -> Path | None:
    """An app updated from an installer that still carried the CUDA DLLs (<= 1.17) has them in its own
    folder: move them into runtime/<version> when they are exactly this runtime, so the update downloads
    nothing. None when they aren't there or don't match."""
    legacy = Path(legacy)
    if not _sizes_match(legacy, m):
        return None
    if any(_sha256(legacy / n) != f["sha256"] for n, f in m["files"].items()):
        return None
    root = runtime_root(data)
    tmp = root / f"{m['version']}.partial"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        for name in m["files"]:
            (tmp / name).parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(legacy / name, tmp / name)  # same drive: instant
            except OSError:
                shutil.copy2(legacy / name, tmp / name)  # another drive, or in use
    except OSError:
        log.exception("GPU runtime: could not take the DLLs from %s", legacy)
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    (tmp / DONE).write_text(json.dumps({"version": m["version"], "sha256": m.get("sha256")}), encoding="utf-8")
    final = folder(data, m)
    if final.exists():
        shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)
    shutil.rmtree(legacy / "nvidia", ignore_errors=True)
    return final


def legacy_dir() -> Path | None:
    """Where an installer <= 1.17 put the CUDA DLLs: the frozen app's own folder."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def ensure(data: Path, m: dict, progress=None, opener=_open, free=None, legacy: Path | None = None) -> Path:
    """The runtime folder, fetched if needed: from an old install's own folder, else downloaded. Raises
    DownloadError with a message for the user."""
    p = installed(data, m)
    if p:
        return p
    if legacy is not None:
        p = adopt(data, m, legacy)
        if p:
            log.info("GPU runtime %s taken from the old install folder", m["version"])
            prune(data, m)
            return p
    root = runtime_root(data)
    root.mkdir(parents=True, exist_ok=True)
    part = root / f"{m['asset']}.part"
    have = part.stat().st_size if part.exists() else 0
    need = int(m["size"]) - have + unpacked_bytes(m) + 200 * 2**20
    room = shutil.disk_usage(root).free if free is None else free
    if room < need:
        raise DownloadError(f"not enough disk space: it needs {need / 1e9:.1f} GB free, there is {room / 1e9:.1f} GB")
    fetch(m["url"], part, int(m["size"]), m["sha256"], progress=progress, opener=opener)
    p = unpack(part, data, m)
    part.unlink(missing_ok=True)
    prune(data, m)
    if legacy is not None:  # an old install's DLLs that weren't this runtime: the pack replaces them
        shutil.rmtree(Path(legacy) / "nvidia", ignore_errors=True)
    return p


# ---------------- the background app's fetch ----------------
class Fetcher:
    """Runs ensure() on a thread with retries, reporting through on_state(state, **info):
    "downloading" (done, total; at most once a second), "ready" (path), "failed" (error, retry_s).
    A failed try waits WAITS[i] and goes on from the bytes it has."""

    def __init__(self, data: Path, m: dict, on_state, opener=_open, waits=WAITS, clock=time.monotonic,
                 legacy: Path | None = None, free=None):
        self.data, self.m, self.on_state, self.opener = Path(data), m, on_state, opener
        self.waits, self.clock, self.legacy, self.free = tuple(waits), clock, legacy, free
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self._last = None

    def _progress(self, done: int, total: int) -> None:
        now = self.clock()
        if self._last is None or now - self._last >= 1.0 or done >= total:
            self._last = now
            self.on_state("downloading", done=done, total=total)

    def run(self) -> Path | None:
        tries = 0
        while not self.stop.is_set():
            try:
                p = ensure(self.data, self.m, progress=self._progress, opener=self.opener, free=self.free,
                           legacy=self.legacy)
            except Exception as e:  # never kill the app over the runtime: say why, try again later
                wait = self.waits[min(tries, len(self.waits) - 1)]
                tries += 1
                msg = str(e) if isinstance(e, DownloadError) else f"{type(e).__name__}: {e}"
                log.warning("GPU runtime %s: try %d failed (%s); next try in %d s", self.m["version"], tries, msg, wait)
                self.on_state("failed", error=msg, retry_s=wait, tries=tries)
                if self.stop.wait(wait):
                    return None
                continue
            log.info("GPU runtime %s ready in %s", self.m["version"], p)
            self.on_state("ready", path=str(p))
            return p
        return None

    def start(self) -> Fetcher:
        self.thread = threading.Thread(target=self.run, name="ecoscribe-gpu-runtime", daemon=True)
        self.thread.start()
        return self
