"""The GPU runtime pack (dictado-7e1): download, resume, verify, unpack, version, the DLL path, the
background fetch, the build side and the release gate's checks. All with fakes: no network, no CUDA."""
import hashlib
import importlib.util
import io
import json
import sys
import threading
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from ecoscribe import gpu, gpu_runtime as rt
from ecoscribe.config import TextCfg, TranscribeCfg, WhisperCfg

REPO = Path(__file__).resolve().parent.parent
URL = "https://example.invalid/ecoscribe-gpu-runtime-1.zip"


def _tool(name):
    sys.path.insert(0, str(REPO / "tools"))
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pack = _tool("runtime_pack")
gate = _tool("release_gate")

DLLS = {"nvidia/cublas/bin/cublas64_12.dll": b"cublas " * 5000, "nvidia/cublas/bin/cublasLt64_12.dll": b"lt " * 9000,
        "nvidia/cudnn/bin/cudnn64_9.dll": b"cudnn " * 300}


def make_pack(tmp_path, version=1, dlls=DLLS):
    """A site-packages with fake DLLs, the pack zip and its manifest, as tools/build.py makes them."""
    site = tmp_path / f"site{version}"
    for name, data in dlls.items():
        (site / name).parent.mkdir(parents=True, exist_ok=True)
        (site / name).write_bytes(data)
    lst = tmp_path / "list.txt"
    lst.write_text("# test\n" + "\n".join(Path(n).name for n in dlls) + "\n", encoding="utf-8")
    mpath = tmp_path / "gpu_runtime.json"
    if version > 1 and not mpath.exists():
        mpath.write_text(json.dumps({"version": version - 1, "files": {}}), encoding="utf-8")
    out = tmp_path / f"out{version}"
    out.mkdir(exist_ok=True)
    zp, m = pack.build(site, out, new=True, manifest_path=mpath, list_path=lst, say=lambda *a: None)
    return zp, m


class Resp(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status, self.headers = status, headers or {}

    def getcode(self):
        return self.status


class Server:
    """A fake release download: serves `body`, honours Range unless told not to, can cut off or be offline."""

    def __init__(self, body, ranges=True, cut_at=None, offline=False, http=None):
        self.body, self.ranges, self.cut_at, self.offline, self.http = body, ranges, cut_at, offline, http
        self.requests = []

    def __call__(self, req, timeout):
        rng = req.headers.get("Range")
        self.requests.append(rng)
        if self.offline:
            raise urllib.error.URLError("getaddrinfo failed")
        if self.http:
            raise urllib.error.HTTPError(req.full_url, self.http, "Not Found", {}, None)
        start = int(rng.split("=")[1].rstrip("-")) if rng and self.ranges else 0
        body = self.body[start:]
        if self.cut_at is not None:
            cut, self.cut_at = self.cut_at, None
            return Cut(body[:cut - start])
        return Resp(body, 206 if start else 200)


class Cut(Resp):
    """Sends some bytes, then the connection drops."""

    def read(self, n=-1):
        data = super().read(n)
        if not data:
            raise ConnectionResetError("connection reset")
        return data


# ---------------- download ----------------
def test_download_verify_and_progress(tmp_path):
    zp, m = make_pack(tmp_path)
    body, seen = zp.read_bytes(), []
    part = tmp_path / "dl" / "x.part"
    rt.fetch("https://x/y.zip", part, len(body), m["sha256"], progress=lambda d, t: seen.append(d), opener=Server(body))
    assert part.read_bytes() == body and seen[0] == 0 and seen[-1] == len(body)


def test_a_cut_download_keeps_its_bytes_and_resumes(tmp_path):
    zp, m = make_pack(tmp_path)
    body = zp.read_bytes()
    srv, part = Server(body, cut_at=len(body) // 2), tmp_path / "x.part"
    with pytest.raises(rt.DownloadError, match="no connection"):
        rt.fetch(URL, part, len(body), m["sha256"], opener=srv)
    assert 0 < part.stat().st_size < len(body)
    rt.fetch(URL, part, len(body), m["sha256"], opener=srv)
    assert srv.requests[-1] == f"bytes={len(body) // 2}-" and part.read_bytes() == body


def test_a_server_that_ignores_the_range_starts_over(tmp_path):
    zp, m = make_pack(tmp_path)
    body = zp.read_bytes()
    part = tmp_path / "x.part"
    part.write_bytes(body[:100])
    rt.fetch(URL, part, len(body), m["sha256"], opener=Server(body, ranges=False))
    assert part.read_bytes() == body


def test_a_wrong_checksum_removes_the_download(tmp_path):
    zp, m = make_pack(tmp_path)
    body = bytearray(zp.read_bytes())
    body[50] ^= 0xFF
    part = tmp_path / "x.part"
    with pytest.raises(rt.DownloadError, match="damaged"):
        rt.fetch(URL, part, len(body), m["sha256"], opener=Server(bytes(body)))
    assert not part.exists()


def test_a_damaged_partial_file_is_not_kept_forever(tmp_path):
    zp, m = make_pack(tmp_path)
    body = zp.read_bytes()
    part = tmp_path / "x.part"
    part.write_bytes(b"\0" * 100)  # garbage from some earlier try: the checksum catches it, then a clean try
    with pytest.raises(rt.DownloadError, match="damaged"):
        rt.fetch(URL, part, len(body), m["sha256"], opener=Server(body))
    rt.fetch(URL, part, len(body), m["sha256"], opener=Server(body))
    assert part.read_bytes() == body


def test_offline_and_http_errors_say_so(tmp_path):
    with pytest.raises(rt.DownloadError, match="no connection"):
        rt.fetch(URL, tmp_path / "a.part", 10, "0" * 64, opener=Server(b"", offline=True))
    with pytest.raises(rt.DownloadError, match="404"):
        rt.fetch(URL, tmp_path / "b.part", 10, "0" * 64, opener=Server(b"", http=404))


# ---------------- unpack, version, check ----------------
def test_unpack_checks_every_file_and_marks_the_folder(tmp_path):
    zp, m = make_pack(tmp_path)
    data = tmp_path / "data"
    p = rt.unpack(zp, data, m)
    assert p == data / "runtime" / "1" and rt.check(p, m, full=True) is None and rt.installed(data, m) == p
    (p / "nvidia/cudnn/bin/cudnn64_9.dll").write_bytes(b"short")
    assert "bytes" in rt.check(p, m) and rt.installed(data, m) is None


def test_a_damaged_file_in_the_pack_leaves_nothing_half_done(tmp_path):
    zp, m = make_pack(tmp_path)
    bad = json.loads(json.dumps(m))
    bad["files"]["nvidia/cublas/bin/cublas64_12.dll"]["sha256"] = "0" * 64
    data = tmp_path / "data"
    with pytest.raises(rt.DownloadError, match="damaged"):
        rt.unpack(zp, data, bad)
    assert not (data / "runtime" / "1").exists() and not (data / "runtime" / "1.partial").exists()


def test_a_runtime_of_another_version_is_not_used(tmp_path):
    zp, m = make_pack(tmp_path)
    data = tmp_path / "data"
    rt.unpack(zp, data, m)
    newer = {**m, "version": 2, "sha256": "f" * 64}
    assert rt.installed(data, newer) is None
    assert "version 1" in rt.check(rt.runtime_root(data) / "1", newer)


def test_ensure_downloads_once_then_uses_what_it_has(tmp_path):
    zp, m = make_pack(tmp_path)
    srv, data = Server(zp.read_bytes()), tmp_path / "data"
    m = {**m, "url": "https://example.invalid/pack.zip"}
    p = rt.ensure(data, m, opener=srv, free=10**12)
    assert rt.installed(data, m) == p and not list(rt.runtime_root(data).glob("*.part"))
    assert rt.ensure(data, m, opener=Server(b"", offline=True)) == p and len(srv.requests) == 1


def test_a_newer_app_fetches_its_runtime_and_drops_the_old_one(tmp_path):
    zp1, m1 = make_pack(tmp_path)
    data = tmp_path / "data"
    rt.unpack(zp1, data, m1)
    zp2, m2 = make_pack(tmp_path, 2, {**DLLS, "nvidia/cublas/bin/cublas64_12.dll": b"cublas v2 " * 5000})
    p = rt.ensure(data, m2, opener=Server(zp2.read_bytes()), free=10**12)
    assert p.name == "2" and not (rt.runtime_root(data) / "1").exists()


def test_ensure_offline_installs_nothing_and_needs_room(tmp_path):
    zp, m = make_pack(tmp_path)
    data = tmp_path / "data"
    with pytest.raises(rt.DownloadError, match="no connection"):
        rt.ensure(data, m, opener=Server(b"", offline=True), free=10**12)
    assert rt.installed(data, m) is None
    with pytest.raises(rt.DownloadError, match="disk space"):
        rt.ensure(data, m, opener=Server(zp.read_bytes()), free=1000)


def test_an_old_install_s_own_dlls_are_moved_not_downloaded(tmp_path):
    zp, m = make_pack(tmp_path)
    legacy, data = tmp_path / "app" / "_internal", tmp_path / "data"
    for name, body in DLLS.items():
        (legacy / name).parent.mkdir(parents=True, exist_ok=True)
        (legacy / name).write_bytes(body)
    p = rt.ensure(data, m, opener=Server(b"", offline=True), free=10**12, legacy=legacy)
    assert rt.check(p, m, full=True) is None and not (legacy / "nvidia").exists()


def test_other_dlls_in_an_old_install_are_replaced_by_a_download(tmp_path):
    zp, m = make_pack(tmp_path)
    legacy, data = tmp_path / "app" / "_internal", tmp_path / "data"
    for name, body in DLLS.items():
        (legacy / name).parent.mkdir(parents=True, exist_ok=True)
        (legacy / name).write_bytes(bytes(reversed(body)))  # same sizes, other files
    p = rt.ensure(data, m, opener=Server(zp.read_bytes()), free=10**12, legacy=legacy)
    assert rt.check(p, m, full=True) is None and not (legacy / "nvidia").exists()


# ---------------- who needs it, the DLL path ----------------
def test_only_the_installed_windows_app_needs_the_pack(tmp_path):
    zp, m = make_pack(tmp_path)
    assert not rt.needed(m, frozen=False, platform="win32")  # a source run: the pip DLLs
    assert not rt.needed(m, frozen=True, platform="darwin")  # the Mac: no CUDA
    assert not rt.needed({}, frozen=True, platform="win32")  # no manifest
    assert rt.needed(m, frozen=True, platform="win32")
    data = tmp_path / "data"
    assert rt.missing(data, m, frozen=True, platform="win32") == rt.MISSING
    assert rt.missing(data, m, frozen=False, platform="win32") is None
    rt.unpack(zp, data, m)
    assert rt.missing(data, m, frozen=True, platform="win32") is None


def test_dll_root_prefers_a_ready_folder_named_in_the_environment(tmp_path, monkeypatch):
    zp, m = make_pack(tmp_path)
    ready = rt.unpack(zp, tmp_path / "gate", m)
    data = tmp_path / "data"
    monkeypatch.setenv(rt.ENV_DIR, str(ready))
    assert rt.dll_root(data, m) == ready
    monkeypatch.setenv(rt.ENV_DIR, str(tmp_path / "nothing"))
    assert rt.dll_root(data, m) is None


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows DLL search path")
def test_the_runtime_folder_goes_first_on_the_dll_path(tmp_path, monkeypatch):
    from ecoscribe.platform.windows import sysutil
    zp, m = make_pack(tmp_path)
    ready = rt.unpack(zp, tmp_path / "data", m)
    monkeypatch.setattr(rt, "dll_root", lambda *a, **k: ready)
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    assert sysutil.cuda_roots()[0] == str(ready)
    added = sysutil.add_cuda_dll_dirs()
    assert str(ready / "nvidia" / "cublas" / "bin") in added
    assert sysutil.add_cuda_dll_dirs() == []  # a second call adds nothing twice
    assert __import__("os").environ["PATH"].split(";")[0].startswith(str(ready))


def test_the_manifest_in_the_repo_is_complete():
    m = rt.manifest()
    assert m and m["url"].endswith(m["asset"]) and len(m["sha256"]) == 64 and m["size"] > 0
    assert {Path(n).name for n in m["files"]} == set(pack.names())
    assert all(rt._safe(n) and len(f["sha256"]) == 64 for n, f in m["files"].items())


# ---------------- the background fetch ----------------
def test_the_fetcher_reports_progress_failure_retry_and_ready(tmp_path):
    zp, m = make_pack(tmp_path)
    body, states = zp.read_bytes(), []
    calls = {"n": 0}

    def opener(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("offline")
        return Server(body)(req, timeout)
    f = rt.Fetcher(tmp_path / "data", m, lambda s, **i: states.append((s, i)), opener=opener, waits=(0,), free=10**12)
    p = f.run()
    names = [s for s, _ in states]
    assert names[0] == "downloading" and "failed" in names and names[-1] == "ready"
    failed = dict(states)["failed"]
    assert "no connection" in failed["error"] and failed["retry_s"] == 0
    assert rt.installed(tmp_path / "data", m) == p


def test_a_stopped_fetcher_gives_up_quietly(tmp_path):
    zp, m = make_pack(tmp_path)
    f = rt.Fetcher(tmp_path / "data", m, lambda *a, **k: None, opener=Server(b"", offline=True), waits=(60,),
                   free=10**12)
    f.stop.set()
    assert f.run() is None


# ---------------- the app while it fetches ----------------
def test_the_notice_says_the_gpu_part_is_coming():
    assert "GPU part" in gpu.notice(rt.MISSING, 12040)
    assert "too old" in gpu.notice(rt.MISSING, 11040)
    assert gpu.notice(rt.MISSING, None).startswith("No GPU")


def test_meetings_go_to_the_cpu_while_it_is_missing():
    from ecoscribe import transcribe
    assert transcribe.steps(TranscribeCfg(), runtime_missing=lambda: rt.MISSING) == [("cpu", "int8")]
    assert transcribe.steps(TranscribeCfg(), runtime_missing=lambda: None)[0][0] == "cuda"


def test_dictation_goes_to_the_cpu_without_a_failure_note(monkeypatch):
    from ecoscribe.engine import Engine
    made = []

    def factory(name, device, compute_type, local_files_only=False):
        assert device == "cpu", "must not try CUDA without the runtime"
        made.append(device)
        return SimpleNamespace(detect_language=lambda a, vad_filter=False: ("en", 0.9, [("en", 0.9)]),
                               transcribe=lambda a, **k: (iter([]), SimpleNamespace(duration=1.0)))
    monkeypatch.setattr(Engine, "runtime_missing", staticmethod(lambda: rt.MISSING))
    e = Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory, resolve=lambda n: n)
    e.load(fallback=False)  # the worker's load: no exception, so no gpu-failed.json
    assert e.device == "cpu" and e.fallback_reason == rt.MISSING and made == ["cpu"]


def test_dictation_on_a_card_too_small_goes_straight_to_the_cpu(monkeypatch):
    """dictado-5d6y: no doomed CUDA load, no failure note; the pill says why."""
    from ecoscribe.engine import Engine
    made = []

    def factory(name, device, compute_type, local_files_only=False):
        made.append((name, device))
        return SimpleNamespace(detect_language=lambda a, vad_filter=False: ("en", 0.9, [("en", 0.9)]),
                               transcribe=lambda a, **k: (iter([]), SimpleNamespace(duration=1.0)))
    monkeypatch.setattr(Engine, "runtime_missing", staticmethod(lambda: None))
    monkeypatch.setattr(gpu, "card_mb", lambda: 2048)
    e = Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory, resolve=lambda n: n)
    e.load(fallback=False)
    assert e.device == "cpu" and e.fallback_reason == gpu.SMALL and made == [("small", "cpu")]
    assert "too little memory" in gpu.notice(gpu.SMALL, 12040) and "2 GB" in gpu.notice(gpu.SMALL, 12040)
    monkeypatch.setattr(gpu, "card_mb", lambda: 8192)
    made.clear()
    Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory, resolve=lambda n: n).load(fallback=False)
    assert made[0][1] == "cuda"


def test_renew_retires_an_idle_worker_and_waits_for_a_busy_one():
    from ecoscribe.engine_proc import EngineProxy
    killed = []
    e = EngineProxy(WhisperCfg(on_demand=True), TextCfg(), spawn=None, check_s=None)
    e._w = SimpleNamespace(kill=lambda: killed.append(1))
    held, done = threading.Event(), threading.Event()

    def dictation():  # a transcription in flight holds the request lock on another thread
        with e._lock:
            held.set()
            done.wait(5)
    t = threading.Thread(target=dictation)
    t.start()
    held.wait(5)
    e.renew()
    assert not killed and e._w is not None
    done.set()
    t.join(5)
    e.check_idle()  # the next idle check
    assert killed == [1] and e._w is None


# ---------------- the build side ----------------
def test_the_pack_zip_is_the_same_bytes_every_build(tmp_path):
    files = {}
    for name, body in DLLS.items():
        p = tmp_path / "src" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        files[name] = p
    a, b = pack.write_zip(files, tmp_path / "a.zip"), pack.write_zip(files, tmp_path / "b.zip")
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def test_build_checks_the_dlls_against_the_manifest(tmp_path):
    zp, m = make_pack(tmp_path)
    assert m["version"] == 1 and m["url"].endswith("/gpu-runtime-1/ecoscribe-gpu-runtime-1.zip")
    mpath, lst = tmp_path / "gpu_runtime.json", tmp_path / "list.txt"
    zp.unlink()
    again, m2 = pack.build(tmp_path / "site1", zp.parent, manifest_path=mpath, list_path=lst, say=lambda *a: None)
    assert m2 == m and hashlib.sha256(again.read_bytes()).hexdigest() == m["sha256"]  # rebuilt, same bytes
    (tmp_path / "site1" / "nvidia/cudnn/bin/cudnn64_9.dll").write_bytes(b"changed")
    with pytest.raises(SystemExit, match="new-runtime"):
        pack.build(tmp_path / "site1", zp.parent, manifest_path=mpath, list_path=lst, say=lambda *a: None)
    _, m3 = pack.build(tmp_path / "site1", zp.parent, new=True, manifest_path=mpath, list_path=lst, say=lambda *a: None)
    assert m3["version"] == 2 and json.loads(mpath.read_text())["version"] == 2


def test_a_cuda_dll_in_the_app_is_caught(tmp_path):
    zp, m = make_pack(tmp_path)
    dist = tmp_path / "dist"
    (dist / "_internal").mkdir(parents=True)
    (dist / "_internal" / "ctranslate2").mkdir()
    (dist / "_internal" / "ctranslate2" / "ctranslate2.dll").write_bytes(b"x")
    (dist / "_internal" / "ctranslate2" / "cudnn64_9.dll").write_bytes(b"x")  # the ctranslate2 wheel's own
    assert pack.bundled(dist, m) == [] and gate.check_split(dist, m)[0]
    (dist / "_internal" / "cublasLt64_12.dll").write_bytes(b"x")
    assert not gate.check_split(dist, m)[0]
    (dist / "_internal" / "cublasLt64_12.dll").unlink()
    (dist / "_internal" / "nvidia" / "cublas" / "bin").mkdir(parents=True)
    (dist / "_internal" / "nvidia" / "cublas" / "bin" / "nvblas64_12.dll").write_bytes(b"x")
    assert pack.bundled(dist, m) == [str(Path("_internal/nvidia/cublas/bin/nvblas64_12.dll"))]


# ---------------- the release gate ----------------
def test_gate_checks_the_pack_and_that_it_is_published(tmp_path, monkeypatch):
    zp, m = make_pack(tmp_path)
    monkeypatch.setattr(gate, "OUT", zp.parent)
    assert gate.check_runtime_pack(m)[0]
    zp.write_bytes(zp.read_bytes()[:-1] + b"!")
    assert not gate.check_runtime_pack(m)[0]

    def live(req, timeout):
        return Resp(b"x", 206, {"Content-Range": f"bytes 0-0/{m['size']}"})
    assert gate.check_runtime_published(m, opener=live)[0]
    ok, why = gate.check_runtime_published(m, opener=Server(b"", http=404))
    assert not ok and "upload it once" in why


def test_gate_selftest_must_take_cublas_from_the_pack(tmp_path):
    good = {"ok": True, "device": "cuda", "text": "after the climbing session", "ms": 300,
            "gpu_runtime": str(tmp_path), "nvidia_dlls": ["cublas64_12.dll", "cublasLt64_12.dll"]}
    assert gate.judge_selftest(good, tmp_path)[0]
    assert not gate.judge_selftest({**good, "gpu_runtime": None}, tmp_path)[0]
    assert not gate.judge_selftest({**good, "device": "cpu"}, tmp_path)[0]
    assert not gate.judge_selftest({**good, "nvidia_dlls": []}, None)[0]
    assert not gate.judge_selftest({}, tmp_path)[0]


def test_gate_waits_for_the_installed_app_to_have_the_runtime(tmp_path, monkeypatch):
    zp, m = make_pack(tmp_path)
    data, t = tmp_path / "data", [0.0]
    monkeypatch.setattr(gate, "status", lambda: {"gpu_runtime": {"state": "downloading"}})

    def sleep(s):
        t[0] += s
        if t[0] >= 30:
            rt.unpack(zp, data, m)  # the app finished its download
    ok, why = gate.wait_runtime(m, minutes=5, data=data, clock=lambda: t[0], sleep=sleep)
    assert ok and "runtime 1" in why
    ok, why = gate.wait_runtime(m, minutes=1, data=tmp_path / "none", clock=lambda: t[0], sleep=sleep)
    assert not ok and "no runtime after" in why


def test_gate_counts_the_runtime_in_the_disk_room(tmp_path):
    zp, m = make_pack(tmp_path)
    setup = tmp_path / "Ecoscribe-Setup-9.9.9.exe"
    setup.write_bytes(b"x" * 1000)
    need = gate.runtime_need(m, tmp_path / "data")
    assert need == m["size"] + rt.unpacked_bytes(m)
    assert not gate.check_disk(setup, free=3000, runtime=need)[0] and gate.check_disk(setup, free=3000 + need, runtime=need)[0]
    rt.unpack(zp, tmp_path / "data", m)
    assert gate.runtime_need(m, tmp_path / "data") == 0
