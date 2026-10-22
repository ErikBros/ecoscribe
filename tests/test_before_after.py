"""The before/after page for look changes (tools/before_after.py, dictado-yql): pixel diff and the page."""
import importlib.util
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("before_after", REPO / "tools" / "before_after.py")
ba = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ba)


def _png(path: Path, box=None, shade=0) -> Path:
    im = Image.new("RGB", (200, 100), (246 - shade, 245, 241))
    if box:
        ImageDraw.Draw(im).rectangle(box, fill=(35, 85, 122))
    im.save(path)
    return path


def test_font_smoothing_noise_is_not_a_change(tmp_path):
    frac, picture = ba.diff(_png(tmp_path / "a.png"), _png(tmp_path / "b.png", shade=6))
    assert frac == 0 and picture is None


def test_a_real_change_is_measured_and_drawn(tmp_path):
    frac, picture = ba.diff(_png(tmp_path / "a.png"), _png(tmp_path / "b.png", box=(0, 0, 19, 9)))
    assert abs(frac - 200 / 20000) < 1e-9 and picture.exists()


def _data(page: str) -> dict:
    return json.loads(re.search(r"const D = (.*);\n</script>", page).group(1).replace("<\\/", "</"))


def test_page_keeps_only_changed_screens_and_has_decision_markers(tmp_path):
    shots = {("inicio", 980): {"before": _png(tmp_path / "1.png"), "after": _png(tmp_path / "2.png", box=(0, 0, 50, 50))},
             ("ajustes", 980): {"before": _png(tmp_path / "3.png"), "after": _png(tmp_path / "4.png")}}
    page = ba.build("Ecoscribe: test", "look-test", ["before", "after"], shots, [980], variants=False)
    d = _data(page)
    assert [s["page"] for s in d["screens"]] == ["inicio"] and d["same"] == ["ajustes @ 980"]
    assert d["screens"][0]["imgs"]["after"].startswith("data:image/png;base64,")
    assert 'const ROUND = "look-test";' in page and 'kind: "Look", date: "' in page
    assert re.search(r'^\s*\{ id: "this-change",', page, re.M)  # one line per choice, for a page server's round list


def test_variants_page_offers_each_look(tmp_path):
    shots = {("inicio", 1470): {"Calm": _png(tmp_path / "1.png"), "Bold": _png(tmp_path / "2.png", box=(0, 0, 9, 9))}}
    page = ba.build("Pill", "look-pill", ["Calm", "Bold"], shots, [1470], variants=True)
    assert len(_data(page)["screens"]) == 1
    assert re.findall(r'^\s*\{ id: "([a-z-]+)",', page, re.M) == ["calm", "bold"]


def test_a_folder_source_is_found_in_a_checkout(tmp_path):
    (tmp_path / "ecoscribe" / "web").mkdir(parents=True)
    (tmp_path / "ecoscribe" / "web" / "index.html").write_text("<html></html>")
    assert ba.web_dir(str(tmp_path), tmp_path / "t") == tmp_path / "ecoscribe" / "web"
