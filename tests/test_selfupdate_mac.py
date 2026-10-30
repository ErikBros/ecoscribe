"""dictado-6gr: self-update on the Mac. The release's .dmg, only announced when there is one; the install
script swaps Ecoscribe.app only for an app signed like this one. The real-script test runs on a throwaway
app and .dmg in tmp_path (darwin only); the installed app is never touched."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ecoscribe import selfupdate, updates
from ecoscribe.platform.macos import selfinstall

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
    subprocess.run(["hdiutil", "create", "-volname", "Ecoscribe", "-srcfolder", str(app), "-ov", "-format", "UDZO",
                    str(out)], check=True, capture_output=True)
    return out


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
