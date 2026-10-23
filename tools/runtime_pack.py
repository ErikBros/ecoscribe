"""The GPU runtime pack (dictado-7e1): the CUDA DLLs as one versioned zip, built from site-packages.

Used by tools/build.py (--runtime, --new-runtime) and tools/release_gate.py. The app side (download,
check, DLL path) is ecoscribe/gpu_runtime.py; this side writes the zip and ecoscribe/gpu_runtime.json.

The zip is deterministic (sorted names, fixed dates and attributes), so the same DLLs give the same
bytes and the same sha256 on any rebuild: the published asset and a local rebuild can be compared.
A new runtime version is made only on purpose (--new-runtime), when the DLLs change: an app pinned to
version N keeps downloading exactly the N it was tested with.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
LIST = APP / "packaging" / "windows" / "cuda_dlls.txt"
MANIFEST = APP / "ecoscribe" / "gpu_runtime.json"
REPO = "ErikBros/ecoscribe"
MIN_DRIVER = 12000  # CUDA 12.0: what cuBLAS 12 needs from the NVIDIA driver
DATE = (1980, 1, 1, 0, 0, 0)  # the oldest a zip can say: no build time in the bytes


def names(list_path: Path = LIST) -> list[str]:
    return [line.strip() for line in Path(list_path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def find(site: Path, wanted: list[str]) -> dict[str, Path]:
    """{"nvidia/<pkg>/bin/<dll>": path} for every DLL in `wanted`, from site-packages' nvidia-* wheels."""
    found = {}
    for dll in sorted(Path(site).glob("nvidia/*/bin/*.dll")):
        if dll.name in wanted:
            found[f"nvidia/{dll.parent.parent.name}/bin/{dll.name}"] = dll
    lost = sorted(set(wanted) - {Path(k).name for k in found})
    if lost:
        raise SystemExit(f"CUDA DLLs not in {site}: {', '.join(lost)} (pip install the nvidia-*-cu12 wheels)")
    return found


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while buf := f.read(1 << 20):
            h.update(buf)
    return h.hexdigest()


def entries(files: dict[str, Path]) -> dict[str, dict]:
    return {k: {"size": p.stat().st_size, "sha256": sha256(p)} for k, p in sorted(files.items())}


def write_zip(files: dict[str, Path], dest: Path) -> Path:
    """The pack, byte for byte the same for the same files."""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_LZMA) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, DATE)
            info.compress_type = zipfile.ZIP_LZMA  # 20 % smaller than deflate on these DLLs; zipfile reads it
            info.create_system = 0
            info.external_attr = 0
            with open(files[name], "rb") as src, z.open(info, "w", force_zip64=True) as dst:
                while buf := src.read(1 << 20):
                    dst.write(buf)
    tmp.replace(dest)
    return dest


def asset(version: int) -> str:
    return f"ecoscribe-gpu-runtime-{version}.zip"


def tag(version: int) -> str:
    return f"gpu-runtime-{version}"


def url(version: int) -> str:
    return f"https://github.com/{REPO}/releases/download/{tag(version)}/{asset(version)}"


def load(path: Path = MANIFEST) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build(site: Path, out: Path, new: bool = False, manifest_path: Path = MANIFEST, list_path: Path = LIST,
          say=print) -> tuple[Path, dict]:
    """The pack for this app in `out`, checked against the manifest. new=True (the DLLs changed on
    purpose): the next version, and a new manifest written. Raises SystemExit with what to do."""
    cur = load(manifest_path)
    files = find(Path(site), names(list_path))
    ent = entries(files)
    if cur and not new:
        if ent != cur.get("files"):
            raise SystemExit(f"the CUDA DLLs in {site} differ from GPU runtime {cur['version']} (the one this app "
                             "downloads): run tools/build.py --new-runtime to make the next version, or reinstall the "
                             "wheels it was made from")
        zp = Path(out) / cur["asset"]
        if zp.exists() and zp.stat().st_size == cur["size"] and sha256(zp) == cur["sha256"]:
            say(f"GPU runtime {cur['version']}: {zp} matches the manifest")
            return zp, cur
        write_zip(files, zp)
        if zp.stat().st_size != cur["size"] or sha256(zp) != cur["sha256"]:
            raise SystemExit(f"rebuilt {zp.name} differs from the published one (another zlib?): download the "
                             f"published asset from {cur['url']} into {out} instead")
        say(f"GPU runtime {cur['version']}: rebuilt {zp}, same bytes as the manifest")
        return zp, cur
    version = int(cur["version"]) + 1 if cur else 1
    zp = write_zip(files, Path(out) / asset(version))
    m = {"version": version, "asset": asset(version), "url": url(version), "size": zp.stat().st_size,
         "sha256": sha256(zp), "min_driver": MIN_DRIVER, "files": ent,
         "made_by": "tools/build.py --new-runtime; upload the zip once as release " + tag(version)}
    Path(manifest_path).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    say(f"GPU runtime {version}: {zp} ({m['size'] / 1e6:.0f} MB) and {manifest_path.name} written")
    return zp, m


def bundled(dist: Path, m: dict) -> list[str]:
    """CUDA DLLs of the pack found inside the frozen app (should be none: they come from the pack).
    The ctranslate2 wheel's own small cudnn64_9.dll is part of ctranslate2, not of the pack."""
    want = {Path(k).name.lower() for k in m["files"]}
    out = []
    for p in Path(dist).rglob("*.dll"):
        parts = [x.lower() for x in p.relative_to(dist).parts]
        if "nvidia" in parts or (p.name.lower() in want and "ctranslate2" not in parts):
            out.append(str(p.relative_to(dist)))
    return sorted(out)
