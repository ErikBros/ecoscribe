"""A before/after page for every look change (dictado-yql). Run with Windows Python.

    python before_after.py --before origin/main --out page.html
    python before_after.py --before origin/main --variant "Calm=../try-a" --variant "Bold=../try-b" --out page.html

Shoots every window page (tools/shoot.py, headless Edge with the demo API, nothing on screen) from the
old and the new web folder at 980 (the window), 1470 and 1920 px, compares the pixels and writes ONE
self-contained HTML page: only the screens that changed, each as side by side, a slider, old, new or
the difference; the unchanged ones listed. With --variant, 2-3 looks side by side to pick from.

A source is a git ref (its ecoscribe/web is taken with `git archive`) or a folder (a web folder, or a
checkout that has ecoscribe/web). --after defaults to this working tree.

Served by a page server that has /api/picks/<round> and /api/send/<round> (--round sets the id),
Approve / Not this / a note and "Send to Claude" are saved there; opened as a file, the buttons
copy the answer to paste into the chat instead.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shoot import APP, SHOTS, TALL, shot  # noqa: E402

PAGES = {**SHOTS, **TALL}  # a tall page shows what's below the fold (only when named in --pages)
TALL_H = 2300

SIZES = {980: 690, 1470: 920, 1920: 1080}
NOISE = 16  # a channel difference below this is font smoothing, not a change
CHANGED = 0.0005  # more than 0.05 % of the pixels changed = a changed screen


def web_dir(src: str, tmp: Path) -> Path:
    """A folder with index.html for a git ref or a path."""
    p = Path(src)
    if p.exists():
        for cand in (p, p / "ecoscribe" / "web"):
            if (cand / "index.html").exists():
                return cand
        raise SystemExit(f"{src}: no index.html in it or in ecoscribe/web")
    out = tmp / src.replace("/", "_")
    out.mkdir(parents=True, exist_ok=True)
    data = subprocess.run(["git", "-C", str(APP), "archive", src, "ecoscribe/web"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(out, filter="data")
    return out / "ecoscribe" / "web"


def diff(a: Path, b: Path) -> tuple[float, Path | None]:
    """Fraction of pixels changed, and a picture of where (changed pixels red over a faded new screen)."""
    from PIL import Image, ImageChops
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return 1.0, None
    mask = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > NOISE else 0)
    n = sum(mask.histogram()[255:])
    frac = n / (ia.size[0] * ia.size[1])
    if not n:
        return 0.0, None
    faded = Image.blend(ib, Image.new("RGB", ib.size, (255, 255, 255)), 0.7)
    out = b.with_name(b.stem + "-diff.png")
    Image.composite(Image.new("RGB", ib.size, (230, 30, 60)), faded, mask).save(out)
    return frac, out


def b64(p: Path | None) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode() if p else ""


def shoot_all(sources: dict[str, Path], out: Path, pages: list[str], widths: list[int]) -> dict:
    """{(page, width): {source: png}}, four Edge processes at a time."""
    jobs = [(name, src, page, w) for name, src in sources.items() for page in pages for w in widths]

    def one(job):
        name, src, page, w = job
        png = out / f"{name}-{page}-{w}.png"
        shot(src, PAGES[page], png, size=(w, TALL_H if page in TALL else SIZES.get(w, 900)))
        return job, png
    res: dict = {}
    with ThreadPoolExecutor(4) as ex:
        for (name, _, page, w), png in ex.map(one, jobs):
            res.setdefault((page, w), {})[name] = png
    return res


def build(title: str, round_id: str, sources: list[str], shots: dict, widths: list[int], variants: bool) -> str:
    screens, same = [], []
    for (page, w), pngs in sorted(shots.items(), key=lambda kv: (kv[0][1], list(PAGES).index(kv[0][0]))):
        if variants:
            screens.append({"page": page, "w": w, "imgs": {s: b64(pngs[s]) for s in sources}})
            continue
        frac, d = diff(pngs[sources[0]], pngs[sources[1]])
        if frac > CHANGED:
            screens.append({"page": page, "w": w, "pct": round(frac * 100, 2),
                            "imgs": {s: b64(pngs[s]) for s in sources}, "diff": b64(d)})
        else:
            same.append(f"{page} @ {w}")
    proposals = sources if variants else ["This change"]
    data = {"title": title, "round": round_id, "variants": variants, "sources": sources, "widths": widths,
            "screens": screens, "same": same, "made": time.strftime("%Y-%m-%d %H:%M")}
    ids = "\n".join(f'  {{ id: "{_slug(p)}", title: {json.dumps(p)} }},' for p in proposals)
    return (PAGE.replace("__TITLE__", html.escape(title))
                .replace("__ROUND__", round_id)
                .replace("__DATE__", time.strftime("%d %B"))
                .replace("__PROPOSALS__", ids)
                .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "look"


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root { --bg:#f4f2ee; --panel:#fff; --ink:#1c1b19; --mute:#6b675f; --line:#e2ded6; --accent:#2d5bd7; --ok:#1f7a4d; --no:#b4322f; --chip:#ece8e0; }
@media (prefers-color-scheme: dark) { :root { --bg:#16171a; --panel:#1f2125; --ink:#ecebe8; --mute:#9a978f; --line:#2e3036; --accent:#7c9cff; --ok:#4cc38a; --no:#ff7a70; --chip:#2a2c31; } }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 "IBM Plex Sans", "Segoe UI", system-ui, sans-serif; }
header { position:sticky; top:0; z-index:5; background:color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line); padding:18px 40px 14px; display:flex; gap:28px; align-items:flex-end; flex-wrap:wrap }
h1 { font-size:22px; font-weight:600; margin:0 0 2px; letter-spacing:-.01em }
.sub { color:var(--mute); font-size:13.5px }
.seg { display:inline-flex; background:var(--chip); border-radius:9px; padding:3px; gap:2px }
.seg button { border:0; background:none; color:var(--mute); font:500 13px "IBM Plex Sans", sans-serif; padding:6px 12px; border-radius:7px; cursor:pointer }
.seg button.on { background:var(--panel); color:var(--ink); box-shadow:0 1px 2px rgba(0,0,0,.12) }
.ctl { display:flex; gap:14px; align-items:center; margin-left:auto }
.lab { font-size:11.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--mute); margin-right:4px }
main { padding:26px 40px 140px; max-width:2400px; margin:0 auto }
.card { background:var(--panel); border:1px solid var(--line); border-radius:14px; margin:0 0 26px; overflow:hidden }
.card h2 { margin:0; font-size:15px; font-weight:600; padding:13px 18px; border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:baseline }
.card h2 .m { font:400 12.5px "IBM Plex Mono", monospace; color:var(--mute) }
.card h2 .pct { margin-left:auto; font:500 12.5px "IBM Plex Mono", monospace; color:var(--accent) }
.view { padding:18px; display:grid; gap:18px }
.view.two { grid-template-columns:1fr 1fr }
.view.three { grid-template-columns:repeat(3, 1fr) }
figure { margin:0 }
figcaption { font-size:12px; color:var(--mute); text-transform:uppercase; letter-spacing:.06em; margin:0 0 6px }
img { display:block; width:100%; height:auto; border-radius:8px; border:1px solid var(--line); background:#fff }
.slider { position:relative; user-select:none; border-radius:8px; overflow:hidden; border:1px solid var(--line); cursor:ew-resize }
.slider img { border:0; border-radius:0 }
.slider .top { position:absolute; inset:0; overflow:hidden; width:50% }
.slider .top img { width:auto; height:100%; max-width:none }
.slider .bar { position:absolute; top:0; bottom:0; width:2px; background:var(--accent); left:50%; transform:translateX(-1px) }
.slider .bar::after { content:"⟷"; position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); background:var(--accent); color:#fff;
  border-radius:20px; padding:3px 8px; font-size:13px }
.tag { position:absolute; bottom:10px; padding:2px 8px; border-radius:6px; background:rgba(0,0,0,.55); color:#fff; font-size:12px }
.same { color:var(--mute); font-size:13.5px }
.same summary { cursor:pointer }
.empty { padding:60px; text-align:center; color:var(--mute) }
.decide { position:fixed; left:0; right:0; bottom:0; z-index:6; background:var(--panel); border-top:1px solid var(--line);
  padding:14px 40px; display:flex; gap:14px; align-items:center; box-shadow:0 -6px 24px rgba(0,0,0,.06) }
.decide .q { font-weight:600; min-width:220px }
.opt { display:flex; gap:6px; align-items:center; padding:4px 10px; border:1px solid var(--line); border-radius:10px }
.opt span { font-size:13.5px; margin-right:4px }
.btn { border:1px solid var(--line); background:var(--panel); color:var(--ink); font:500 13.5px "IBM Plex Sans", sans-serif; padding:7px 13px; border-radius:8px; cursor:pointer }
.btn.yes.on { background:var(--ok); border-color:var(--ok); color:#fff }
.btn.no.on { background:var(--no); border-color:var(--no); color:#fff }
.btn.send { background:var(--accent); border-color:var(--accent); color:#fff; margin-left:auto }
.note { flex:1; min-width:200px; border:1px solid var(--line); background:var(--bg); color:var(--ink); border-radius:8px; padding:8px 10px; font:14px "IBM Plex Sans", sans-serif }
.status { font-size:13px; color:var(--mute) }
/* the viewer: a picture full size; arrows swap the looks of the same screen in place */
.card h2 .open { margin-left:auto; border:1px solid var(--line); background:var(--panel); color:var(--ink); font:500 12.5px "IBM Plex Sans", sans-serif;
  padding:4px 11px; border-radius:7px; cursor:pointer }
.card h2 .pct + .open { margin-left:12px }
figure img { cursor:zoom-in }
.lb { position:fixed; inset:0; z-index:20; background:#0e0f11; color:#ecebe8; display:flex; flex-direction:column }
.lb[hidden] { display:none }
.lb-top { display:flex; align-items:center; gap:18px; padding:10px 18px; border-bottom:1px solid #2a2c31; flex-wrap:wrap }
.lb-where { font:500 13px "IBM Plex Mono", monospace; color:#9a978f }
.lb-tabs { display:inline-flex; gap:6px }
.lb-tabs button { border:1px solid #3a3d44; background:none; color:#c9c6bf; font:500 14px "IBM Plex Sans", sans-serif; padding:7px 14px; border-radius:8px; cursor:pointer }
.lb-tabs button .k { font:500 11.5px "IBM Plex Mono", monospace; color:#7d7a73; margin-right:7px }
.lb-tabs button.on { background:#ecebe8; border-color:#ecebe8; color:#16171a }
.lb-tabs button.on .k { color:#6b675f }
.lb-tools { margin-left:auto; display:flex; gap:8px; align-items:center }
.lb-tools button { border:1px solid #3a3d44; background:none; color:#c9c6bf; font:500 13px "IBM Plex Sans", sans-serif; padding:6px 11px; border-radius:8px; cursor:pointer }
.lb-tools button:hover, .lb-tabs button:not(.on):hover { border-color:#6b6e76; color:#fff }
.lb-hint { color:#7d7a73; font-size:12.5px; padding:0 18px 8px }
.lb-hint kbd { font:500 11.5px "IBM Plex Mono", monospace; border:1px solid #3a3d44; border-radius:4px; padding:0 5px; color:#c9c6bf }
.lb-stage { flex:1; overflow:auto }
.lb-stage img { display:block; margin:0 auto; width:auto; max-width:100%; height:auto; border:0; border-radius:0; background:#fff; cursor:zoom-in }
.lb-stage.actual img { max-width:none; cursor:zoom-out }
.lb-side { position:fixed; top:50%; transform:translateY(-50%); width:52px; height:92px; border:0; border-radius:12px; background:rgba(14,15,17,.62);
  color:#fff; font-size:30px; cursor:pointer; z-index:21; box-shadow:0 2px 10px rgba(0,0,0,.25) }
.lb-side:hover { background:rgba(14,15,17,.88) }
.lb-prev { left:14px } .lb-next { right:14px }
</style>
</head>
<body>
<script>
// Decision-page markers for a page server's round list: ROUND, META (kind, date) and one `  { id: "...",` line per choice.
const ROUND = "__ROUND__";
const META = { kind: "Look", date: "__DATE__" };
const P = [
__PROPOSALS__
];
const D = __DATA__;
</script>
<header>
  <div><h1></h1><div class="sub" id="sub"></div></div>
  <div class="ctl">
    <span class="lab">Width</span><div class="seg" id="widths"></div>
    <span class="lab" id="modelab">Show</span><div class="seg" id="modes"></div>
  </div>
</header>
<main id="main"></main>
<div class="decide" id="decide"></div>
<div class="lb" id="lb" hidden>
  <div class="lb-top"><span class="lb-where" id="lb-where"></span><div class="lb-tabs" id="lb-tabs"></div>
    <div class="lb-tools"><button id="lb-up">Previous screen</button><button id="lb-down">Next screen</button><button id="lb-size">Actual size</button><button id="lb-x">Close (Esc)</button></div></div>
  <div class="lb-hint"><kbd>←</kbd> <kbd>→</kbd> or <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> swap the look in the same spot, so what changed jumps out · <kbd>Shift</kbd>+<kbd>←</kbd> <kbd>→</kbd> another screen · click the picture for actual size · <kbd>Esc</kbd> closes</div>
  <div class="lb-stage" id="lb-stage"><img id="lb-img" alt=""></div>
  <button class="lb-side lb-prev" id="lb-prev" title="Previous look (←)">‹</button><button class="lb-side lb-next" id="lb-next" title="Next look (→)">›</button>
</div>
<script>
const $ = (s) => document.querySelector(s);
const served = location.protocol.startsWith("http");
let width = D.widths[D.widths.length - 1], mode = D.variants ? "all" : "slider";
const MODES = D.variants ? [["all", "All"]] : [["slider", "Slider"], ["side", "Side by side"], ["before", "Before"], ["after", "After"], ["diff", "Difference"]];
document.title = D.title; $("h1").textContent = D.title;
const shown = D.screens.length, total = shown + D.same.length;
$("#sub").textContent = D.variants
  ? `${D.sources.length} looks to pick from · ${shown} screens · made ${D.made}`
  : `${new Set(D.screens.map(s => s.page)).size} screens changed (${shown} of ${total} shots) · ${D.sources[0]} → ${D.sources[1]} · made ${D.made}`;
function seg(el, items, cur, set) {
  el.innerHTML = "";
  for (const [k, label] of items) {
    const b = document.createElement("button"); b.textContent = label; b.className = k === cur ? "on" : "";
    b.onclick = () => { set(k); draw(); }; el.append(b);
  }
}
function fig(caption, src) { return `<figure><figcaption>${caption}</figcaption><img src="${src}" alt="${caption}"></figure>`; }
function slider(a, b) {
  return `<div class="slider"><img src="${b}" alt="after"><div class="top"><img src="${a}" alt="before"></div>
    <div class="bar"></div><span class="tag" style="left:10px">${D.sources[0]}</span><span class="tag" style="right:10px">${D.sources[1]}</span></div>`;
}
function draw() {
  seg($("#widths"), D.widths.map(w => [w, w === 980 ? "980 · window" : String(w)]), width, (w) => width = w);
  seg($("#modes"), MODES, mode, (m) => mode = m);
  $("#modes").hidden = $("#modelab").hidden = D.variants;
  const list = D.screens.filter(s => s.w === width), main = $("#main");
  main.innerHTML = list.length ? "" : `<div class="empty">No screen changed at ${width} px.</div>`;
  for (const s of list) {
    const c = document.createElement("section"); c.className = "card";
    const [a, b] = D.sources;
    let body;
    if (D.variants) body = `<div class="view ${D.sources.length === 2 ? "two" : "three"}">${D.sources.map(v => fig(v, s.imgs[v])).join("")}</div>`;
    else if (mode === "side") body = `<div class="view two">${fig("Before · " + a, s.imgs[a])}${fig("After · " + b, s.imgs[b])}</div>`;
    else if (mode === "before") body = `<div class="view">${fig("Before · " + a, s.imgs[a])}</div>`;
    else if (mode === "after") body = `<div class="view">${fig("After · " + b, s.imgs[b])}</div>`;
    else if (mode === "diff") body = `<div class="view">${fig("What changed (red)", s.diff)}</div>`;
    else body = `<div class="view">${slider(s.imgs[a], s.imgs[b])}</div>`;
    c.innerHTML = `<h2>${s.page}<span class="m">${s.w} px</span>${s.pct != null ? `<span class="pct">${s.pct}% of pixels changed</span>` : ""}<button class="open">Open large</button></h2>${body}`;
    c.querySelector(".open").onclick = () => openLb(s, 0);
    // a figure's place in lbItems(s): the looks in order; Before 0, After 1, Difference 2
    const at = D.variants || mode === "side" ? null : { before: 0, after: 1, diff: 2 }[mode];
    c.querySelectorAll("figure img").forEach((im, j) => { im.onclick = () => openLb(s, at ?? j); });
    main.append(c);
  }
  if (D.same.length && !D.variants) {
    const d = document.createElement("details"); d.className = "same";
    d.innerHTML = `<summary>${D.same.length} shots unchanged</summary><p>${D.same.join(" · ")}</p>`; main.append(d);
  }
  for (const sl of document.querySelectorAll(".slider")) {
    const top = sl.querySelector(".top"), bar = sl.querySelector(".bar"), img = top.querySelector("img");
    const fit = () => { img.style.width = sl.clientWidth + "px"; };
    const move = (x) => { const r = sl.getBoundingClientRect(), p = Math.max(0, Math.min(1, (x - r.left) / r.width)) * 100;
      top.style.width = p + "%"; bar.style.left = p + "%"; };
    fit(); new ResizeObserver(fit).observe(sl);
    sl.onpointerdown = (e) => { sl.setPointerCapture(e.pointerId); move(e.clientX); sl.onpointermove = (ev) => move(ev.clientX); };
    sl.onpointerup = () => { sl.onpointermove = null; };
  }
}
let picks = {};
async function save(id, body) {
  picks[id] = { ...(picks[id] || {}), ...body };
  if (served) {
    try { const r = await fetch(`/api/picks/${ROUND}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal: id, ...body }) }); picks = await r.json(); } catch (e) {}
  }
  decide();
}
function answer() {
  return P.map(p => `${p.title}: ${({ yes: "approve", no: "not this", later: "later" })[(picks[p.id] || {}).choice] || "no answer"}` +
    ((picks[p.id] || {}).note ? ` (${picks[p.id].note})` : "")).join("; ");
}
function decide() {
  const el = $("#decide");
  el.innerHTML = `<span class="q">${D.variants ? "Which look?" : "Ship this look?"}</span>`;
  for (const p of P) {
    const cur = (picks[p.id] || {}).choice, o = document.createElement("div"); o.className = "opt";
    o.innerHTML = `${D.variants ? `<span>${p.title}</span>` : ""}<button class="btn yes ${cur === "yes" ? "on" : ""}">${D.variants ? "This one" : "Approve"}</button>` +
      `<button class="btn no ${cur === "no" ? "on" : ""}">Not this</button>`;
    o.querySelector(".yes").onclick = () => save(p.id, { choice: "yes" });
    o.querySelector(".no").onclick = () => save(p.id, { choice: "no" });
    el.append(o);
  }
  const note = document.createElement("input"); note.className = "note"; note.placeholder = "What to change (optional)";
  note.value = (picks[P[0].id] || {}).note || "";
  note.onchange = () => save(P[0].id, { note: note.value });
  const send = document.createElement("button"); send.className = "btn send"; send.textContent = served ? "Send to Claude" : "Copy answer";
  const st = document.createElement("span"); st.className = "status";
  send.onclick = async () => {
    if (served) { try { await fetch(`/api/send/${ROUND}`, { method: "POST" }); st.textContent = "Sent."; } catch (e) { st.textContent = "Not sent."; } }
    else { await navigator.clipboard.writeText(`Look review ${ROUND}: ${answer()}`); st.textContent = "Copied: paste it in the chat."; }
  };
  el.append(note, send, st);
}
if (served) fetch(`/api/picks/${ROUND}`, { cache: "no-store" }).then(r => r.json()).then(p => { picks = p; decide(); }).catch(() => {});
draw(); decide();
// the viewer (Erik 2026-10-23: "too small to see anything... cycle through pictures to compare")
const lb = { list: [], k: 0, i: 0 };
function lbItems(s) {
  if (D.variants) return D.sources.map(v => [v, s.imgs[v]]);
  const [a, b] = D.sources;
  return [["Before · " + a, s.imgs[a]], ["After · " + b, s.imgs[b]], ...(s.diff ? [["What changed (red)", s.diff]] : [])];
}
function openLb(s, i) {
  lb.list = D.screens.filter(x => x.w === s.w); lb.k = Math.max(0, lb.list.indexOf(s)); lb.i = i;
  $("#lb").hidden = false; document.body.style.overflow = "hidden"; showLb(true);
}
function closeLb() { $("#lb").hidden = true; document.body.style.overflow = ""; }
function showLb(top) {
  const s = lb.list[lb.k], items = lbItems(s), stage = $("#lb-stage"), img = $("#lb-img");
  lb.i = (lb.i + items.length) % items.length;
  const y = top ? 0 : stage.scrollTop, x = top ? 0 : stage.scrollLeft;
  img.onload = () => { stage.scrollTop = y; stage.scrollLeft = x; };
  img.src = items[lb.i][1]; img.alt = items[lb.i][0];
  $("#lb-where").textContent = `${s.page} · ${s.w} px · screen ${lb.k + 1} of ${lb.list.length}`;
  const tabs = $("#lb-tabs"); tabs.innerHTML = "";
  items.forEach(([label], j) => {
    const b = document.createElement("button"); b.className = j === lb.i ? "on" : "";
    b.innerHTML = `<span class="k">${j + 1}</span>`; b.append(label);
    b.onclick = () => { lb.i = j; showLb(); }; tabs.append(b);
  });
  $("#lb-up").disabled = lb.k === 0; $("#lb-down").disabled = lb.k === lb.list.length - 1;
}
function lbScreen(d) { const k = lb.k + d; if (k < 0 || k >= lb.list.length) return; lb.k = k; showLb(true); }
$("#lb-x").onclick = closeLb;
$("#lb-prev").onclick = () => { lb.i--; showLb(); };
$("#lb-next").onclick = () => { lb.i++; showLb(); };
$("#lb-up").onclick = () => lbScreen(-1);
$("#lb-down").onclick = () => lbScreen(1);
$("#lb-size").onclick = $("#lb-img").onclick = () => {
  const st = $("#lb-stage"), on = st.classList.toggle("actual"); $("#lb-size").textContent = on ? "Fit to window" : "Actual size";
};
addEventListener("keydown", (e) => {
  if ($("#lb").hidden) return;
  if (e.key === "Escape") closeLb();
  else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    const d = e.key === "ArrowLeft" ? -1 : 1;
    if (e.shiftKey) lbScreen(d); else { lb.i += d; showLb(); }
  } else if (/^[1-9]$/.test(e.key) && +e.key <= lbItems(lb.list[lb.k]).length) { lb.i = +e.key - 1; showLb(); }
  else return;
  e.preventDefault(); e.stopImmediatePropagation();
}, true);
addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  const i = D.widths.indexOf(width);
  if (e.key === "ArrowRight" && i < D.widths.length - 1) { width = D.widths[i + 1]; draw(); }
  if (e.key === "ArrowLeft" && i > 0) { width = D.widths[i - 1]; draw(); }
});
</script>
</body>
</html>
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--before", help="git ref or folder of the current look (default origin/main)", default="origin/main")
    ap.add_argument("--after", help="git ref or folder of the new look (default: this working tree)", default=str(APP))
    ap.add_argument("--variant", action="append", default=[], metavar="NAME=SRC", help="a look to pick from (2-3)")
    ap.add_argument("--out", required=True, help="the HTML page to write")
    ap.add_argument("--round", help="decision id for a page server (default from the out file name)")
    ap.add_argument("--title", default="Ecoscribe: look change")
    ap.add_argument("--pages", help="comma list of pages (default all but the tall ones): " + ",".join(PAGES))
    ap.add_argument("--widths", default="980,1470,1920")
    a = ap.parse_args(argv)
    out = Path(a.out)
    widths = [int(w) for w in a.widths.split(",")]
    pages = a.pages.split(",") if a.pages else list(SHOTS)
    with tempfile.TemporaryDirectory(prefix="ecoscribe-look-") as t:
        tmp = Path(t)
        if a.variant:
            named = dict(v.split("=", 1) for v in a.variant)
            sources = {name: web_dir(src, tmp) for name, src in named.items()}
        else:
            sources = {"before": web_dir(a.before, tmp), "after": web_dir(a.after, tmp)}
        shots = shoot_all(sources, tmp, pages, widths)
        page = build(a.title, a.round or _slug(out.stem), list(sources), shots, widths, bool(a.variant))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"{out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
