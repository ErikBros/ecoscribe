// The look checklist (docs/look-checklist.md, dictado-6vv), the parts a test can judge, on every demo page.
// A failure listed in KNOWN is reported but doesn't fail (each has a ticket: fixing it is a look change that
// needs Erik's OK); a new failure fails; a KNOWN one that no longer happens says so, so the list only shrinks.
// Run from WSL: node tests/ui/look.mjs
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(here, "../../ecoscribe/web");
async function loadJsdom() {  // same lookup as smoke.mjs
  if (process.env.ECOSCRIBE_JSDOM) return import(pathToFileURL(process.env.ECOSCRIBE_JSDOM).href);
  const { createRequire } = await import("module");
  for (const base of [import.meta.url, pathToFileURL(path.join(process.env.NODE_PATH || "", "x")).href]) {
    try { return import(pathToFileURL(createRequire(base).resolve("jsdom")).href); } catch {}
  }
  const { execSync } = await import("child_process");
  const root = execSync("npm root -g").toString().trim();
  return import(pathToFileURL(createRequire(path.join(root, "x")).resolve("jsdom")).href);
}
const { JSDOM } = await loadJsdom();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// the same pages tools/shoot.py photographs
const PAGES = {
  inicio: "page=inicio", historial: "page=historial", ajustes: "page=ajustes", bienvenida: "page=bienvenida&welcome=1",
  "setup-models": "page=bienvenida&welcome=1&sstep=models", "setup-mic": "page=bienvenida&welcome=1&sstep=mic",
  "setup-shortcut": "page=bienvenida&welcome=1&sstep=shortcut", "setup-try": "page=bienvenida&welcome=1&sstep=try",
  "setup-done": "page=bienvenida&welcome=1&sstep=done", detenido: "page=inicio&state=stopped",
  cargando: "page=inicio&state=loading", "inicio-version": "page=inicio&update=1", "inicio-version-descarga": "page=inicio&update=dl",
  "inicio-version-lista": "page=inicio&update=ready", "inicio-version-fallo": "page=inicio&update=failed", reuniones: "page=reuniones", "reuniones-vacia": "page=reuniones&rec=0",
  "reunion-directo": "page=reuniones/2026-10-05_1400_retro", "reunion-lista": "page=reuniones/2026-10-05_0915_planering",
  "reunion-cola": "page=reuniones/2026-10-05_1130_podcast",
  "reunion-reemplazar": "page=reuniones/2026-10-04_1600_kund&replace=1", "reunion-reemplazado": "page=reuniones/2026-10-04_1600_kund&replace=1&replaced=1", "reunion-sin-invitados": "page=reuniones/2026-10-05_0915_planering&noguests=1&email=1",
  insights: "page=insights&insights=1",
};

async function load(query) {
  const html = fs.readFileSync(path.join(web, "index.html"), "utf8").replace('<script src="app.js"></script>', "");
  const dom = new JSDOM(html, { url: `file:///x/index.html?demo=1&${query}`, runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.eval(fs.readFileSync(path.join(web, "app.js"), "utf8"));
  for (let i = 0; i < 50 && dom.window.document.body.dataset.ready !== "1"; i++) await sleep(20);
  await sleep(300);
  return dom.window;
}
function visible(el) {
  for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
    if (e.hidden || e.getAttribute("aria-hidden") === "true" || e.style.display === "none") return false;
  }
  return true;
}
function where(el) {
  const id = el.id || el.closest("[id]")?.id;
  return `${el.tagName.toLowerCase()}${el.className ? "." + String(el.className).split(" ")[0] : ""}${id ? " in #" + id : ""}`;
}
const leaves = (doc) => [...doc.body.querySelectorAll("*")].filter((e) => !e.children.length && visible(e)
  && !["SCRIPT", "STYLE", "OPTION", "TEXTAREA"].includes(e.tagName) && !e.closest("svg") && e.textContent.trim());
// elements with their own words (text right inside them, not only in children): "Tap <kbd>Right Ctrl</kbd>, talk"
const own = (e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ").trim();
const speaking = (doc, re) => [...doc.body.querySelectorAll("*")].filter((e) => visible(e) && !e.closest("svg")
  && !["SCRIPT", "STYLE", "OPTION"].includes(e.tagName) && re.test(own(e)));

const CHECKS = {
  // 1. every number says what it counts: a lone number needs a label next to it (its card has words)
  "number-has-unit": (doc) => leaves(doc).filter((e) => /^[\d][\d.,\s]*$/.test(e.textContent.trim()))
    .filter((e) => !/[A-Za-zÀ-ÿ]{2,}/.test((e.parentElement.parentElement || e.parentElement).textContent.replace(e.textContent, "")))
    .map((e) => `bare number "${e.textContent.trim()}" (${where(e)})`),
  // 2. no dash placeholders: say what's missing instead
  "no-dash-placeholder": (doc) => leaves(doc).filter((e) => /^[—–-]$/.test(e.textContent.trim()))
    .map((e) => `"${e.textContent.trim()}" placeholder (${where(e)})`),
};
const tapWhile = (state) => (doc) => speaking(doc, /\btap\b/i)
  .map((e) => `${state}, but says "${e.textContent.trim().replace(/\s+/g, " ").slice(0, 50)}" (${where(e)})`);
const STATE = {
  // 3. the words match the state: no "tap the key" while the app is stopped or loading
  detenido: { "copy-matches-state": tapWhile("stopped") },
  cargando: { "copy-matches-state": tapWhile("loading") },
  // 4. status shows once per screen
  inicio: { "status-once": (doc) => { const s = speaking(doc, /\b(ready|running)\b/i);
    return s.length > 1 ? [`status shown ${s.length} times: ${s.map((e) => `"${own(e)}"`).join(", ")}`] : []; } },
};

// 5. one colour set: colours written outside :root may only go down (a ratchet towards one token file, dictado-u9h)
const STRAY_COLOURS_MAX = 85;
// found on 2026-10-22, each a look change waiting for Erik's OK (dictado-9jf); delete a line once it's fixed
const KNOWN = [];

const found = [];
for (const [name, q] of Object.entries(PAGES)) {
  const window = await load(q);
  const doc = window.document;
  for (const [check, fn] of Object.entries({ ...CHECKS, ...(STATE[name] || {}) })) {
    for (const f of fn(doc)) found.push(`${name}: ${check}: ${f}`);
  }
  window.close();
}
const css = fs.readFileSync(path.join(web, "app.css"), "utf8");
const outsideRoot = css.replace(/:root\s*\{[^}]*\}/g, "");
const stray = (outsideRoot.match(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g) || []).length;
let failed = 0;
for (const f of found) {
  const known = KNOWN.some((k) => f.startsWith(k));
  console.log(`${known ? "known" : "FAIL "} ${f}`);
  failed += !known;
}
for (const k of KNOWN) if (!found.some((f) => f.startsWith(k))) console.log(`fixed ${k} (take it off KNOWN in tests/ui/look.mjs)`);
const colours = stray <= STRAY_COLOURS_MAX;
console.log(`${colours ? "ok   " : "FAIL "} colours written outside :root: ${stray} (at most ${STRAY_COLOURS_MAX}; use a token)`);
failed += !colours;
console.log(failed ? `\n${failed} FAILED` : "\nlook checklist ok");
process.exit(failed ? 1 : 0);
