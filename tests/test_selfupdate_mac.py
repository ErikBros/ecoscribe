"""dictado-6gr: self-update on the Mac. The release's .dmg, only announced when there is one; the install
script swaps Ecoscribe.app only for an app signed like this one. The real-script test runs on a throwaway
app and .dmg in tmp_path (darwin only); the installed app is never touched."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ecoscribe import selfupdate, updates
from ecoscribe.platform.macos import selfinstall

_spec = importlib.util.spec_from_file_location("build_mac", Path(__file__).resolve().parent.parent / "tools" / "build_mac.py")
build_mac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_mac)

TAG = "v1.19.0"
DMG = "Ecoscribe-1.19.0.dmg"
EXE = "Ecoscribe-Setup-1.19.0.exe"
SIZE = 4 * 1024 ** 2


def asset(name):
    return {"name": name, "size": SIZE, "state": "uploaded", "digest": "sha256:" + "a" * 64,
            "browser_download_url": f"https://github.com/ErikBros/ecoscribe/releases/download/{TAG}/{name}"}


def release(*names):
    return {"tag_name": TAG, "draft": False, "prerelease": False, "assets": [asset(n) for n in names]}


@pytest.fixture(autouse=True)
def mac(monkeypatch):
    monkeypatch.setattr(selfupdate, "MAC", True)
    monkeypatch.setattr(updates, "NEED_INSTALLER", True)


def test_the_mac_picks_the_dmg():
    a = selfupdate.pick_asset(release(EXE, DMG))
    assert a["name"] == DMG and a["version"] == "1.19.0" and a["sha256"] == "a" * 64
    assert selfupdate.pick_asset(release(EXE)) is None  # a Windows-only release: nothing for the Mac
    assert selfupdate.pick_asset(release(EXE), mac=False)["name"] == EXE


def test_a_release_without_a_dmg_is_not_announced_on_the_mac():
    with_dmg = {"latest": TAG, "asset": selfupdate.pick_asset(release(EXE, DMG))}
    assert updates.notice(with_dmg, "1.18.0")["version"] == "1.19.0"
    assert updates.notice({"latest": TAG, "asset": None}, "1.18.0") is None
    stale = {"latest": TAG, "asset": selfupdate.pick_asset(release(EXE), mac=False)}  # saved by an older build
    assert updates.notice(stale, "1.18.0") is None
    assert updates.notice({"latest": TAG, "asset": None}, "1.18.0", need_installer=False)["version"] == "1.19.0"


def test_after_start_also_tidies_dmgs(tmp_path):
    d = selfupdate.folder(tmp_path)
    d.mkdir()
    (d / "Ecoscribe-1.18.0.dmg").write_bytes(b"x")
    (d / "Ecoscribe-1.19.0.dmg.part").write_bytes(b"x")
    selfupdate.after_start(tmp_path, "1.18.0")
    assert sorted(p.name for p in d.iterdir()) == ["Ecoscribe-1.19.0.dmg.part"]


def test_app_bundle_only_from_an_app():
    assert selfinstall.app_bundle("/Applications/Ecoscribe.app/Contents/MacOS/Ecoscribe") == Path(
        "/Applications/Ecoscribe.app").resolve()
    assert selfinstall.app_bundle("/usr/bin/python3") is None


def test_run_installer_starts_the_swap_script(tmp_path, monkeypatch):
    monkeypatch.setattr(selfinstall, "requirement", lambda app: 'identifier "x" and certificate leaf = H"ab"')
    monkeypatch.setattr(selfinstall, "app_bundle", lambda exe=None: Path("/Applications/Ecoscribe.app"))
    a = {"tag": TAG, "version": "1.19.0", "name": DMG, "size": 3}
    p = selfupdate.folder(tmp_path) / DMG
    p.parent.mkdir()
    p.write_bytes(b"abc")
    started = []
    assert selfupdate.run_installer(tmp_path, p, a, relaunch=True, popen=started.append, now=5.0)
    [args] = started
    s = Path(args[1]).read_text()
    assert args[0] == "/bin/sh" and str(Path("/Applications/Ecoscribe.app")) in s and str(p) in s  # Windows CI: backslashes
    assert "-R=\"$req\"" in s and 'open "$app"' in s
    assert selfupdate.run_installer(tmp_path, p, a, relaunch=False, popen=started.append)
    assert 'open "$app"' not in Path(started[1][1]).read_text()  # at Quit: stays closed


def test_a_copy_that_cant_be_replaced_offers_the_download(tmp_path, monkeypatch):
    monkeypatch.setattr(selfinstall, "app_bundle", lambda exe=None: None)  # run from source, not an .app
    a = {"tag": TAG, "version": "1.19.0", "name": DMG, "size": 3}
    p = selfupdate.folder(tmp_path) / DMG
    p.parent.mkdir()
    p.write_bytes(b"abc")
    started = []
    assert not selfupdate.run_installer(tmp_path, p, a, relaunch=True, popen=started.append)
    st = updates.load(tmp_path)
    assert started == [] and st["install_failed"] == "1.19.0"


# ---------------- the real script on a throwaway app (darwin) ----------------
def _app(where: Path, text: str) -> Path:
    app = where / "Ecoscribe.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        "<key>CFBundleIdentifier</key><string>test.ecoscribe.selfinstall</string>"
        "<key>CFBundleExecutable</key><string>Ecoscribe</string></dict></plist>")
    exe = app / "Contents" / "MacOS" / "Ecoscribe"
    exe.write_text(f"#!/bin/sh\necho {text}\n")
    exe.chmod(0o755)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True, capture_output=True)
    return app


def _dmg(app: Path, out: Path) -> Path:
    build_mac.hdiutil_create(["-volname", "Ecoscribe", "-srcfolder", app, "-ov", "-format", "UDZO", out],
                             capture_output=True)
    return out


def test_hdiutil_create_tries_again_after_a_failure():
    calls, waits = [], []

    def runner(cmd, check, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    r = build_mac.hdiutil_create(["-ov", Path("x.dmg")], runner=runner, sleep=waits.append)
    assert r.returncode == 0
    assert calls == [["hdiutil", "create", "-ov", "x.dmg"]] * 2
    assert waits == [3.0]


def test_hdiutil_create_gives_up_after_its_tries():
    calls = []

    def runner(cmd, check, **kw):
        calls.append(cmd)
        raise subprocess.CalledProcessError(1, cmd)

    with pytest.raises(subprocess.CalledProcessError):
        build_mac.hdiutil_create(["x.dmg"], tries=3, runner=runner, sleep=lambda s: None)
    assert len(calls) == 3


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("hdiutil"), reason="the Mac's hdiutil and codesign")
@pytest.mark.parametrize("same_signature", [True, False])
def test_the_script_swaps_only_an_app_signed_like_this_one(tmp_path, same_signature):
    installed = _app(tmp_path / "installed", "old")
    req = selfinstall.requirement(installed)
    assert req
    src = tmp_path / "src"
    if same_signature:  # ad hoc signing pins the exact code: an identical copy is "signed like this one"
        src.mkdir()
        subprocess.run(["ditto", str(installed), str(src / "Ecoscribe.app")], check=True)
    else:  # someone else's (here: different code, so a different requirement)
        _app(src, "evil")
    dmg = _dmg(src / "Ecoscribe.app", tmp_path / DMG)
    upd = tmp_path / "updates"
    upd.mkdir()
    s = upd / "install.sh"
    s.write_text(selfinstall.script(dmg, installed, req, upd / "install.log", relaunch=False))
    before = (installed / "Contents" / "MacOS" / "Ecoscribe").stat().st_ino
    subprocess.run(["/bin/sh", str(s)], check=True, timeout=120)
    log = (upd / "install.log").read_text()
    exe = installed / "Contents" / "MacOS" / "Ecoscribe"
    swapped = exe.stat().st_ino != before
    assert not (installed.parent / "Ecoscribe.app.old").exists() and not (installed.parent / "Ecoscribe.app.new").exists()
    if same_signature:
        assert log.splitlines()[-1] == "installed" and swapped
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(installed)], check=True)
    else:
        assert "not installed" in log and not swapped and "echo old" in exe.read_text()


# ---------------- Install now: the swap runs behind the window's Installing screen (dictado-9zeo.1) ----------------
def _text(relaunch):
    return selfinstall.script(Path("/x/Ecoscribe-1.19.0.dmg"), Path("/Applications/Ecoscribe.app"), 'identifier "x"',
                              Path("/x/install.log"), relaunch)


def test_install_now_script_does_not_wait_for_the_window_and_opens_home():
    s = _text(True)
    assert 'busy() { pgrep -lf "$app/Contents/MacOS/" | grep -v -e " --ui" >/dev/null; }' in s  # the window may stay
    lines = s.splitlines()
    swap = lines.index('    if ditto "$new" "$app.new" && mv "$app" "$app.old" && mv "$app.new" "$app"; then')
    end, reopen = lines.index("end_window"), lines.index('open "$app" --args --after-update')
    assert swap < end < reopen  # swapped, then the old window ended, then the new app opened on Home
    assert selfinstall.AFTER_UPDATE == selfupdate.AFTER_UPDATE == "--after-update"


def test_quit_script_waits_for_every_process_and_stays_closed():
    s = _text(False)
    assert 'busy() { pgrep -f "$app/Contents/MacOS/" >/dev/null; }' in s
    assert "end_window\n" not in s.split("}\n", 2)[-1] and "--after-update" not in s and 'open "$app"' not in s


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("hdiutil"), reason="the Mac's hdiutil and codesign")
@pytest.mark.parametrize("same_signature", [True, False])
def test_install_now_swaps_behind_the_open_window_then_opens_home(tmp_path, same_signature):
    """The real script on a throwaway app, a stand-in window process still running (`... --ui`) and a stand-in for
    `open`: the swap doesn't wait for the window (seconds, not WAIT_S), the window is ended, the app is opened with
    the Home flag; with a wrong signature the old window is ended too and the old app opened again."""
    import time
    installed = _app(tmp_path / "installed", "old")
    req = selfinstall.requirement(installed)
    src = tmp_path / "src"
    if same_signature:
        src.mkdir()
        subprocess.run(["ditto", str(installed), str(src / "Ecoscribe.app")], check=True)
    else:
        _app(src, "evil")
    dmg = _dmg(src / "Ecoscribe.app", tmp_path / DMG)
    upd = tmp_path / "updates"
    upd.mkdir()
    opened = tmp_path / "opened.txt"
    fake_open = tmp_path / "fake-open.sh"
    fake_open.write_text(f'#!/bin/sh\necho "$@" >> "{opened}"\n')
    fake_open.chmod(0o755)
    window = subprocess.Popen(["/bin/sh", "-c", "sleep 60; :", str(installed / "Contents" / "MacOS" / "Ecoscribe"), "--ui"])
    try:
        s = upd / "install.sh"
        s.write_text(selfinstall.script(dmg, installed, req, upd / "install.log", relaunch=True, open_cmd=str(fake_open)))
        before = (installed / "Contents" / "MacOS" / "Ecoscribe").stat().st_ino
        t0 = time.monotonic()
        subprocess.run(["/bin/sh", str(s)], check=True, timeout=90)
        took = time.monotonic() - t0
        assert took < 30, took  # not after WAIT_S: the window doesn't hold the swap
        window.wait(timeout=10)  # ended by the script
        log = (upd / "install.log").read_text()
        swapped = (installed / "Contents" / "MacOS" / "Ecoscribe").stat().st_ino != before
        assert opened.read_text().split() == [str(installed), "--args", "--after-update"]
        assert not (installed.parent / "Ecoscribe.app.old").exists() and not (installed.parent / "Ecoscribe.app.new").exists()
        if same_signature:
            assert "installed" in log.splitlines() and swapped
        else:
            assert "not installed" in log and not swapped
    finally:
        if window.poll() is None:
            window.kill()


def test_install_now_script_still_reopens_when_no_temp_folder():
    """No temporary folder for the .dmg: the script goes on to the end step (old window ended, app reopened)."""
    s = selfinstall.script(Path("/u/Ecoscribe-1.19.0.dmg"), Path("/Applications/Ecoscribe.app"), "req", Path("/u/l"), True)
    assert "|| exit 1" not in s and '[ -n "$mnt" ] && hdiutil attach' in s
    assert s.index("end_window\n") > s.index("mktemp")
