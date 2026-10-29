// jsdom smoke test of the Ecoscribe window in demo mode: every page renders and the
// main interactions work. Run from WSL: node tests/ui/smoke.mjs
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(here, "../../ecoscribe/web");
// jsdom: ECOSCRIBE_JSDOM (path to jsdom/lib/api.js) if set, else Node's normal lookup from this folder up
// (a node_modules here, in the repo, or in any parent folder), else the global install.
async function loadJsdom() {
  if (process.env.ECOSCRIBE_JSDOM) return import(pathToFileURL(process.env.ECOSCRIBE_JSDOM).href);
  const { createRequire } = await import("module");
  for (const base of [import.meta.url, pathToFileURL(path.join(process.env.NODE_PATH || "", "x")).href]) {
    try { return import(pathToFileURL(createRequire(base).resolve("jsdom")).href); } catch {}
  }
  try {
    const { execSync } = await import("child_process");
    const root = execSync("npm root -g").toString().trim();
    return import(pathToFileURL(createRequire(path.join(root, "x")).resolve("jsdom")).href);
  } catch {}
  throw new Error("jsdom not found: npm install jsdom (here or globally) or set ECOSCRIBE_JSDOM");
}
const { JSDOM } = await loadJsdom();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (cond, msg) => { if (!cond) { failed++; console.log("FAIL", msg); } else console.log("ok  ", msg); };

async function load(query) {
  const html = fs.readFileSync(path.join(web, "index.html"), "utf8").replace('<script src="app.js"></script>', "");
  const dom = new JSDOM(html, { url: `file:///x/index.html?demo=1&${query}`, runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  window.confirm = () => true;
  const errors = [];
  window.addEventListener("error", (e) => errors.push(e.message));
  window.eval(fs.readFileSync(path.join(web, "app.js"), "utf8"));
  for (let i = 0; i < 50 && window.document.body.dataset.ready !== "1"; i++) await sleep(20);
  return { window, doc: window.document, errors };
}

{ // ajustes: your words (market deep dive 2026-10-05)
  const { window, doc } = await load("page=ajustes");
  const v = doc.querySelector("#f-vocabulary");
  check(v && v.value === "Göteborg\npyannote", "Your words shows the saved list");
  check(doc.querySelector("#f-voice-commands") && !doc.querySelector("#f-voice-commands").checked, "voice commands off by default");
  check(doc.querySelector("#f-screen-names")?.checked === true, "names on your screen on by default");
  check(doc.querySelector("#f-hold") && !doc.querySelector("#f-hold").checked && !doc.querySelector("#f-hold").disabled, "hold to talk off by default, available for Right Ctrl");
  v.value = "Göteborg\npyannote\n  Kristineberg  \n"; v.dispatchEvent(new window.Event("input", { bubbles: true }));
  check(!doc.querySelector("#savebar").hidden, "typing a word shows the savebar");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.vocabulary === "Göteborg\npyannote\nKristineberg" && Object.keys(sent).length === 1, "saves only the word list, trimmed: " + JSON.stringify(sent));
}
{ // ajustes: Check for new versions (dictado-cjk), on by default
  const { window, doc } = await load("page=ajustes");
  const sw = doc.querySelector("#f-update-check");
  check(sw?.checked === true, "Check for new versions is on by default");
  sw.checked = false; sw.dispatchEvent(new window.Event("change", { bubbles: true }));
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.update_check === false && Object.keys(sent).length === 1, "turning it off saves only that: " + JSON.stringify(sent));
}
{ // ajustes: Replace, heard -> write (dictado-b7u)
  const { window, doc } = await load("page=ajustes");
  const rows = () => [...doc.querySelectorAll("#reps .rep")];
  check(rows().length === 1 && rows()[0].querySelector(".rep-heard").value === "poll request"
    && rows()[0].querySelector(".rep-write").value === "pull request", "Replace shows the saved pair");
  doc.querySelector("#rep-add").click();
  const r = rows()[1];
  r.querySelector(".rep-heard").value = "eco scribe"; r.querySelector(".rep-write").value = "Ecoscribe";
  r.querySelector(".rep-write").dispatchEvent(new window.Event("input", { bubbles: true }));
  check(!doc.querySelector("#savebar").hidden, "typing a replacement shows the savebar");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && JSON.stringify(sent.replacements) === JSON.stringify([{ heard: "poll request", write: "pull request" }, { heard: "eco scribe", write: "Ecoscribe" }])
    && Object.keys(sent).length === 1, "saves the replacements: " + JSON.stringify(sent));
}
{ // dark mode and Settings > Appearance (dictado-u9h)
  const { window, doc, errors } = await load("page=ajustes&theme=dark");
  const root = doc.documentElement, sel = doc.querySelector("#f-theme");
  check(root.dataset.theme === "dark" && sel?.value === "dark" && sel.options.length === 3, "theme=dark: the page is dark and Appearance says Dark");
  sel.value = "light"; sel.dispatchEvent(new window.Event("change", { bubbles: true }));
  check(root.dataset.theme === "light" && !doc.querySelector("#savebar").hidden, "picking Light previews it at once, with the save bar");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.theme === "light" && Object.keys(sent).length === 1 && doc.querySelector("#toast").textContent === "Saved." && !errors.length,
        "saves only the theme, no restart: " + JSON.stringify(sent) + " / " + doc.querySelector("#toast").textContent);
}
{ // ajustes: Style per app (dictado-h0m, dictado-lrm): three named choices per kind of app, and what a sentence becomes
  const { window, doc, errors } = await load("page=ajustes");
  const rows = () => [...doc.querySelectorAll("#st-rows .st-row")];
  const segs = (i) => [...rows()[i].querySelectorAll(".st-looks .seg")], on = (i) => rows()[i].querySelector('.seg[aria-checked="true"]');
  const out = (i) => rows()[i].querySelector(".st-out").textContent, vcOf = (i) => rows()[i].querySelector(".st-vc input");
  const sw = doc.querySelector("#f-per-app");
  check(sw && !sw.checked && rows().length === 4 && doc.querySelector("#st-wrap").classList.contains("off")
    && rows().every((r) => [...r.querySelectorAll("button, input")].every((i) => i.disabled)), "Style per app: off by default, four rows, greyed out");
  check(segs(1).map((b) => b.textContent).join("|") === "Normal|No full stop|Lower case" && on(0).textContent === "Lower case"
    && out(0) === "check the logs first" && out(3) === "Check the logs first.", "each row names its choices and shows what a sentence becomes");
  sw.checked = true; sw.dispatchEvent(new window.Event("change", { bubbles: true }));
  check(!segs(1)[0].disabled && vcOf(1).disabled && rows()[1].querySelector(".st-vc span").textContent === "Voice commands (off in Behaviour)",
    "on: the choices work; a greyed voice commands switch says why");
  segs(1)[0].click();
  check(on(1).textContent === "Normal" && out(1) === "Check the logs first.", "picking Normal shows the full stop come back");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  const chat = sent && sent.app_styles.find((r) => r.kind === "chat");
  check(sent && sent.per_app_styles === true && chat.full_stop === true && chat.capital === true && typeof chat.commands === "boolean"
    && Object.keys(sent).length === 2 && !errors.length, "saves the switch and the choices: " + JSON.stringify(sent));
}
{ // ajustes: voice memory (t0u.32)
  const { window, doc } = await load("page=ajustes");
  await sleep(50);
  check(doc.querySelector("#f-voice-memory")?.checked === true, "remember voices on by default");
  check(!doc.querySelector("#voices-row").hidden && doc.querySelector("#voices-known").textContent === "Knows 2 voices: Ana, Tom", "known voices listed");
  doc.querySelector("#voices-forget").click(); await sleep(100);
  check(doc.querySelector("#voices-row").hidden, "forget all voices empties the list");
}
{ // "Command mode is off" box > Open Settings: Settings at the With Claude card, lit (dictado-1b7)
  const { doc, errors } = await load("page=ajustes/claude");
  await sleep(50);
  const card = doc.querySelector('[data-card="claude"]');
  check(!doc.querySelector("#page-ajustes").hidden && card && card.classList.contains("card-lit") && !errors.length,
        "ajustes/claude: Settings open at the With Claude card, which lights up");
}
{ // ajustes: Claude app (t0u.31)
  const { window, doc } = await load("page=ajustes");
  await sleep(50);
  const b = doc.querySelector("#claude-connect");
  check(b && b.textContent === "Connect" && !b.disabled, "Claude app: Connect offered");
  b.click(); await sleep(100);
  check(b.textContent === "Connected" && b.disabled, "Claude app: connected after the click");
}
{ // ajustes: where downloads go (dictado-yq9)
  const { doc } = await load("page=ajustes");
  await sleep(50);
  check(doc.querySelector("#export-dir").textContent === "C:/x/Downloads" && doc.querySelector("#export-reset").hidden, "downloads: the Downloads folder by default");
  doc.querySelector("#export-change").click(); await sleep(80);
  check(doc.querySelector("#export-dir").textContent === "D:/Transcripts" && !doc.querySelector("#export-reset").hidden, "downloads: a picked folder, with a way back");
  doc.querySelector("#export-reset").click(); await sleep(80);
  check(doc.querySelector("#export-dir").textContent === "C:/x/Downloads" && doc.querySelector("#export-reset").hidden, "downloads: back to Downloads");
}
{ // ajustes: Google Calendar sign-in (dictado-k19)
  const { window, doc } = await load("page=ajustes");
  await sleep(50);
  const b = doc.querySelector("#gcal-connect");
  check(!doc.querySelector("#gcal-row").hidden && b.textContent === "Connect", "Google Calendar: Connect offered");
  b.click(); await sleep(150);
  check(doc.querySelector("#gcal-result").textContent === "Connected: 3 events today. Right now: Weekly sync."
    && b.textContent === "Disconnect", "Google Calendar: connected, says what it found");
  window.confirm = () => true;
  b.click(); await sleep(150);
  check(b.textContent === "Connect" && !window.__gcal, "Google Calendar: disconnect");
}
{ // ajustes: snippets (t0u.29)
  const { window, doc } = await load("page=ajustes");
  check(doc.querySelectorAll(".snip").length === 1 && doc.querySelector(".snip-trigger").value === "my email", "saved snippet shown");
  doc.querySelector("#snip-add").click();
  const rows = doc.querySelectorAll(".snip");
  rows[1].querySelector(".snip-trigger").value = "  My  Signature ";
  rows[1].querySelector(".snip-text").value = "Best,\nAlex";
  rows[1].querySelector(".snip-text").dispatchEvent(new window.Event("input", { bubbles: true }));
  check(!doc.querySelector("#savebar").hidden, "a new snippet shows the savebar");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && Object.keys(sent).length === 1 && sent.snippets?.[1]?.trigger === "my signature" && sent.snippets[1].text === "Best,\nAlex",
        "saves the snippets: " + JSON.stringify(sent));
  rows[0].querySelector(".snip-del").click();
  check(doc.querySelectorAll(".snip").length === 1, "remove drops the row");
}
{ // inicio: the dictation languages, read-only (dictado-bvf: set them in Settings)
  const { doc } = await load("page=inicio");
  check(doc.querySelector("#fact-lang").textContent === "English", "Home shows the dictation language: " + doc.querySelector("#fact-lang").textContent);
}
{ // ajustes: speakers toggle follows the add-on (t0u.22)
  const on = await load("page=ajustes");
  check(!on.doc.querySelector("#f-speakers").disabled && on.doc.querySelector("#f-speakers").checked, "speakers toggle on with the add-on");
  const off = await load("page=ajustes&addon=0");
  check(off.doc.querySelector("#f-speakers").disabled && /isn't installed/.test(off.doc.querySelector("#f-speakers-help").textContent), "no add-on: toggle off and says why");
}
{ // insights (dictado-3je): off by default, a Settings switch adds the tab
  const off = await load("page=inicio");
  check(off.doc.querySelector("#nav-insights").hidden, "Insights tab hidden by default");
  check(off.doc.querySelector("#f-insights") && !off.doc.querySelector("#f-insights").checked, "Insights switch off by default");
  const { window, doc, errors } = await load("page=insights&insights=1");
  await sleep(50);
  check(!doc.querySelector("#nav-insights").hidden && !doc.querySelector("#page-insights").hidden, "Insights tab shown when switched on");
  check(doc.querySelector("#i-saved").textContent === "3 h 22 min", "time saved: " + doc.querySelector("#i-saved").textContent);
  check(!doc.querySelector("#i-week").hidden && doc.querySelector("#i-week-text").textContent.includes("2.2 → 1.8"), "this week: hedges went down (dictado-6oe.6)");
  check(doc.querySelectorAll("#i-hours path.bar").length > 5 && doc.querySelectorAll("#i-days .tick").length === 3, "hour and day charts drawn");
  check(doc.querySelectorAll("#i-langs .i-hbar").length === 4 && doc.querySelector("#i-langs .i-hbar-name").textContent === "English", "languages by name");
  check([...doc.querySelectorAll("#i-apps .i-hbar-name")].some((e) => e.textContent === "Snipping Tool"), "a program name reads as words (dictado-d4h)");
  const wpm = doc.querySelector("#i-wpm"), saved0 = doc.querySelector("#i-saved").textContent;
  check(wpm && wpm.value === "40", "typing speed shows 40 until set (dictado-d8e)");
  wpm.value = "80"; wpm.dispatchEvent(new window.Event("change", { bubbles: true })); await sleep(80);
  check(window.__wpm === 80 && doc.querySelector("#i-wpm").value === "80" && doc.querySelector("#i-saved-how").textContent.includes("type at 80"), "a new typing speed is saved and used");
  check(/ words · \d+%$/.test(doc.querySelector("#i-langs .i-hbar-val").textContent)
    && / dictations?$/.test(doc.querySelector("#i-apps .i-hbar-val").textContent), "languages count words, apps dictations (dictado-7qo)");
  check(/^The highlighted bar is your busiest hour, \d\d:00-\d\d:00\.$/.test(doc.querySelector("#i-hours-note").textContent), "the dark hour is explained (dictado-7qo)");
  check(doc.querySelector("#i-habits").textContent.includes("3.1"), "filler words per 100");
  check(doc.querySelector("#i-clarity").textContent === "91%" && doc.querySelector("#i-clarity-empty").hidden
    && doc.querySelectorAll("#i-clarity-weeks path.bar").length === 4, "clarity: score and the weeks that have one (9jc.1)");
  check(doc.querySelectorAll("#i-unsure .i-chip").length === 4 && doc.querySelector("#i-unsure .i-chip").title === "Unsure 4 of the 6 times you said it", "words it wasn't sure of, per language");
  check(doc.querySelector("#i-hedges").textContent === "2.4" && doc.querySelectorAll("#i-markers-weeks path.bar").length === 5
    && doc.querySelectorAll("#i-top-hedges .i-chip").length === 3, "hedges and fillers in messages to people (9jc.3)");
  check(doc.querySelectorAll("#i-pace-rows .i-habit").length === 2 && doc.querySelector("#i-pace-rows .i-habit-num").textContent === "148"
    && doc.querySelectorAll("#i-pace-hist path.bar:not(.dim)").length === 3, "pace to people and to AI apps, the 130-160 band marked (9jc.4)");
  const meetRow = doc.querySelector("#i-meet-list tbody tr");
  check(doc.querySelector("#i-meet-share").textContent === "41%" && doc.querySelectorAll("#i-meet-list tbody tr").length === 4
    && meetRow.querySelector(".i-table-name span").textContent === "Weekly planning with the product team"
    && [...meetRow.querySelectorAll("td.num")].map((td) => td.textContent).join("|") === "0|6|1.4"
    && doc.querySelector("#i-meet-how").textContent.startsWith("From 4 recorded meetings"), "meetings: share, long turns, questions, hedges per meeting, whole names (9jc.5, 9bl.3)");
  check(doc.querySelector("#i-markers-how").textContent.includes("Hedges soften what you say"), "what a hedge is, under the number (9bl.1)");
  const ticks = [...doc.querySelectorAll("#i-markers-weeks .tick")].map((t) => t.textContent);
  check(ticks.length === 6 && ticks[5] === "This week" && /^\d+ \w+$/.test(ticks[0]), "weekly chart: from the first week with data, every week labelled (9bl.5): " + ticks.join(", "));
  const hit = doc.querySelectorAll("#i-markers-weeks rect.hit")[4];
  hit.dispatchEvent(new window.Event("focus"));
  const tipLines = [...doc.querySelector("#i-tip").children].map((e) => e.textContent);
  check(/^Week of /.test(tipLines[0]) && tipLines[1] === "2.2 hedges per 100 words" && tipLines[2] === "1.1 filler words per 100 words", "tooltip: the week first, one value per line (9bl.2): " + tipLines.join(" / "));
  hit.dispatchEvent(new window.Event("blur"));
  check(doc.querySelector("#i-suggest li .i-suggest-word").textContent.includes("probably Ecoscribe"), "words to add say what they are (9bl.4)");
  const add = doc.querySelector("#i-suggest li button");
  add.click(); await sleep(30);
  check(window.__added === "Ecoscribe" && doc.querySelectorAll("#i-suggest li").length === 2, "Add puts the suggested spelling in Your words");
  doc.querySelector('#i-range .seg[data-days="7"]').click(); await sleep(30);
  check(doc.querySelector('#i-range .seg[data-days="7"]').getAttribute("aria-checked") === "true" && doc.querySelector("#i-words").textContent === "3,540", "7 days range");
  check(errors.length === 0, "no errors on Insights: " + errors.join("; "));
}
{ // inicio
  const { doc, errors } = await load("page=inicio");
  check(doc.body.dataset.ready === "1", "boots in demo mode");
  check(!doc.querySelector("#page-inicio").hidden, "inicio visible");
  check(doc.querySelector("#hero-title").textContent === "Ready to dictate", "hero says ready");
  check(doc.querySelector("#fact-mic").textContent === "Anker PowerConf C20", "mic name prettified");
  check(doc.querySelector("#stat-today").textContent === "152", "today stat");
  check(doc.querySelector("#last-text").textContent.startsWith("Can you check"), "last dictation shown");
  check(doc.querySelector(".nav-item.active").dataset.page === "inicio", "nav highlights inicio");
  check(doc.querySelector("#setup").hidden, "no setup when done");
  check(doc.querySelector("#update-note").hidden, "no new-version notice when there's none");
  check(errors.length === 0, "no JS errors: " + errors.join("; "));
}
{ // dictado-2xpp: each Settings section ends with its guide; Help and setup opens all guides and this platform's troubleshooting
  const { window, doc, errors } = await load("page=ajustes&sec=meetings");
  await sleep(50);
  const shown = [...doc.querySelectorAll(".guide-foot")].filter((p) => !p.hidden);
  check(shown.length === 1 && /Meetings guide/.test(shown[0].textContent), "the Meetings section ends with its guide");
  shown[0].querySelector("a").click(); await sleep(20);
  check(window.__guide === "meetings", "the link opens the Meetings guide");
  window.__secShow("help"); await sleep(20);
  doc.querySelector('[data-guide="troubleshooting#os"]').click(); await sleep(20);
  check(window.__guide === "troubleshooting#windows", "Troubleshooting opens this platform's part");
  check(errors.length === 0, "no JS errors: " + errors.join("; "));
}
{ // dictado-cjk: a newer version is out
  const { window, doc, errors } = await load("page=inicio&update=1");
  await sleep(50);
  const note = doc.querySelector("#update-note");
  check(!note.hidden && doc.querySelector("#update-title").textContent === "Ecoscribe 1.18.0 is out", "Home says a newer version is out");
  check(/You have \d+\.\d+/.test(doc.querySelector("#update-sub").textContent), "and which one you have");
  doc.querySelector("#update-get").click(); await sleep(20);
  check(window.__updOpened === true, "Download opens the release page");
  doc.querySelector("#update-x").click(); await sleep(50);
  check(note.hidden && window.__updDismissed === "1.18.0", "× hides it for that version");
  check(errors.length === 0, "no JS errors with the update notice: " + errors.join("; "));
}
{ // dictado-7e1: the GPU part downloading / failed shows in the engine fact
  const { doc } = await load("page=inicio&gpurt=downloading");
  check(doc.querySelector("#fact-engine").textContent === "CPU · getting GPU 44%"
    && doc.querySelector("#fact-engine").title === "Downloading the GPU part once: 214 MB of 476 MB", "GPU part download progress");
  const f = (await load("page=inicio&gpurt=failed")).doc;
  check(f.querySelector("#fact-engine").textContent === "CPU · GPU download failed" && f.querySelector("#fact-engine").title.includes("no connection"),
    "GPU part download failed, why in the tooltip");
  check(doc.querySelector("#fact-engine") && (await load("page=inicio")).doc.querySelector("#fact-engine").textContent === "GPU · fast", "GPU as before");
}
{ // dictado-nmo: Install when idle, then the steps it goes through
  const { window, doc, errors } = await load("page=inicio&update=1");
  await sleep(50);
  const idle = doc.querySelector("#update-idle"), get = doc.querySelector("#update-get");
  check(!idle.hidden && !get.hidden, "the row offers Install when idle next to Download");
  idle.click(); await sleep(50);
  check(window.__updInstall === "1.18.0" && idle.hidden && get.hidden, "Install when idle okays that version; the buttons go");
  check(/42%/.test(doc.querySelector("#update-sub").textContent) && /never during a call/.test(doc.querySelector("#update-sub").textContent),
    "it says how far the download is and that it never installs during a call");
  for (const [q, re] of [["ready", /is ready/], ["failed", /is out/]]) {
    const { doc: d } = await load("page=inicio&update=" + q);
    await sleep(50);
    check(re.test(d.querySelector("#update-title").textContent), q + ": the title says so");
    check(d.querySelector("#update-idle").hidden && d.querySelector("#update-get").hidden === (q === "ready"), q + ": the right buttons");
  }
  const { doc: mac } = await load("page=inicio&update=1&mac=1");
  await sleep(50);
  check(mac.querySelector("#update-idle").hidden && !mac.querySelector("#update-get").hidden, "the Mac keeps Download only");
  check(errors.length === 0, "no JS errors with Install when idle: " + errors.join("; "));
}
{ // ajustes: Install new versions by itself (dictado-nmo), off by default, Windows only
  const { window, doc } = await load("page=ajustes");
  const sw = doc.querySelector("#f-auto-update");
  check(sw?.checked === false && !doc.querySelector("#row-auto-update").hidden, "Install new versions by itself is there and off");
  sw.checked = true; sw.dispatchEvent(new window.Event("change", { bubbles: true }));
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.auto_update === true && Object.keys(sent).length === 1, "turning it on saves only that: " + JSON.stringify(sent));
  const { doc: mac } = await load("page=ajustes&mac=1");
  check(mac.querySelector("#row-auto-update").hidden, "the Mac hides it (dictado-6gr)");
}
{ // stopped
  const { doc } = await load("page=inicio&state=stopped");
  check(doc.querySelector("#hero-actions button")?.textContent === "Start Ecoscribe", "stopped offers start button");
  check(doc.querySelector(".side-facts").hidden && !doc.querySelector("#side-off").hidden,
    "stopped shows no stale facts, and says why");
}
{ // historial + search
  const { window, doc } = await load("page=historial");
  check(doc.querySelectorAll(".h-item:not(.h-meeting)").length === 5, "history lists 5 dictations");
  check(doc.querySelectorAll(".h-meeting").length === 5, "and the 5 meeting transcripts");
  const done = [...doc.querySelectorAll(".h-meeting")].find((li) => li.textContent.includes("Planering"));
  check(done && [...done.querySelectorAll("button")].map((b) => b.textContent).join(",") === "Open,Download .md", "a finished meeting: Open + Download .md");
  done.querySelectorAll("button")[1].click(); await sleep(80);
  const tb = doc.querySelector("#toast .toast-btn");
  check(doc.querySelector("#toast").textContent.startsWith("In Downloads: t.md") && tb && tb.textContent === "Open folder", "a download says where, with Open folder (dictado-yq9)");
  tb.click(); await sleep(30);
  check(window.__revealed === "C:/x/Downloads/t.md" && doc.querySelector("#toast").hidden, "Open folder shows the file");
  done.querySelector("button").click(); await sleep(200);
  check(!doc.querySelector("#page-reuniones").hidden && !doc.querySelector("#r-detail-view").hidden, "Open jumps to the transcript");
  doc.querySelector('.nav-item[data-page="historial"]').click(); await sleep(150);
  check(doc.querySelector("#page-historial .h-tag-dark")?.textContent.startsWith("Not pasted"), "not-pasted chip");
  check(doc.querySelectorAll("#history .h-group").length >= 1, "History: a card per day (dictado-6oe.5)");
  doc.querySelector('#h-filter [data-kind="meet"]').click(); await sleep(150);
  check([...doc.querySelectorAll("#history .h-item")].every((li) => li.classList.contains("h-meeting")), "the Meetings filter shows only meetings");
  doc.querySelector('#h-filter [data-kind="all"]').click(); await sleep(150);
  const s = doc.querySelector("#search");
  s.value = "climbing"; s.dispatchEvent(new window.Event("input"));
  await sleep(250);
  check(doc.querySelectorAll(".h-item").length === 1, "search filters");
  s.value = "zzz"; s.dispatchEvent(new window.Event("input"));
  await sleep(250);
  check(!doc.querySelector("#history-empty").hidden && doc.querySelector("#history-empty-text").textContent.includes("zzz"), "empty search state");
  s.value = ""; s.dispatchEvent(new window.Event("input")); await sleep(250);
  doc.querySelector("#history-clear").click(); await sleep(100);
  check(doc.querySelectorAll(".h-item:not(.h-meeting)").length === 0 && doc.querySelectorAll(".h-meeting").length === 5, "clear history removes dictations, keeps meetings");
}
{ // ajustes
  const { window, doc } = await load("page=ajustes");
  check(doc.querySelector("#f-hotkey").value === "rctrl" && doc.querySelector("#hk-label").textContent === "Right Ctrl", "hotkey loaded");
  const key = (type, code, mods = {}) => doc.dispatchEvent(new window.KeyboardEvent(type, { code, bubbles: true, cancelable: true, ...mods }));
  doc.querySelector("#hk-change").click();
  check(doc.querySelector("#hk-label").textContent === "Press it now…", "recorder listens");
  key("keydown", "ControlLeft", { ctrlKey: true }); key("keydown", "KeyL", { ctrlKey: true }); await sleep(50);
  check(doc.querySelector("#f-hotkey").value === "ctrl+l" && doc.querySelector("#hk-label").textContent === "Ctrl+L", "recorder takes a combo");
  check(!doc.querySelector("#savebar").hidden, "a new shortcut marks the form dirty");
  doc.querySelector("#hk-change").click();
  key("keydown", "ControlLeft", { ctrlKey: true }); key("keydown", "KeyC", { ctrlKey: true }); await sleep(50);
  check(doc.querySelector("#f-hotkey").value === "ctrl+l" && doc.querySelector("#hk-hint").classList.contains("hk-bad"), "a taken combo is refused with the reason");
  doc.querySelector("#hk-change").click();
  key("keydown", "ControlRight", { ctrlKey: true }); key("keyup", "ControlRight"); await sleep(50);
  check(doc.querySelector("#f-hotkey").value === "rctrl" && doc.querySelector("#hk-label").textContent === "Right Ctrl", "recorder takes a lone Right Ctrl tap");
  check(doc.querySelector("#f-mic").selectedOptions[0].textContent.includes("Anker"), "mic selected");
  check(doc.querySelector("#savebar").hidden, "no savebar before changes");
  const sounds = doc.querySelector("#f-sounds");
  sounds.checked = false; sounds.dispatchEvent(new window.Event("change", { bubbles: true }));
  check(!doc.querySelector("#savebar").hidden, "savebar appears on change");
  sounds.checked = true; sounds.dispatchEvent(new window.Event("change", { bubbles: true }));
  check(doc.querySelector("#savebar").hidden, "savebar hides when change undone");
  // languages as add-ons (dictado-ehs): only English shows by default (dictado-607), Spanish added from the picker
  check([...doc.querySelectorAll("#f-languages input")].map((i) => i.value).join(",") === "en", "only English by default, no Swedish");
  check(!doc.querySelector("#f-languages .lang-x"), "English can't be removed");
  const vcCols = () => [...doc.querySelectorAll("#vc-head th")].map((t) => t.textContent).join(",");
  check(vcCols() === "What it does,English" && !doc.querySelector("#vc-help").textContent.includes("Spanish")
    && !doc.querySelector("#vc-rows").textContent.includes("ny rad"), "voice commands: English only: " + vcCols());
  check([...doc.querySelectorAll("#sc-head th")].map((t) => t.textContent).join(",") === "What it does,English", "self-correction phrases: English only");
  check([...doc.querySelectorAll("#f-meet-lang option")].map((o) => o.value).join(",") === "en,auto", "meeting language: English or Detect");
  const add = doc.querySelector("#lang-add");
  check([...add.options].some((o) => o.value === "es") && [...add.options].some((o) => o.value === "sv"), "the picker offers Spanish and Swedish alike");
  add.value = "es"; add.dispatchEvent(new window.Event("change", { bubbles: true }));
  const es = doc.querySelector('#f-languages input[value="es"]');
  check(es && es.checked && doc.querySelector("#f-languages .lang-x"), "Spanish added, ticked, removable");
  check(vcCols() === "What it does,English,Spanish" && doc.querySelector("#vc-help").textContent.includes('Spanish works too: "nueva línea", "envíalo".'),
    "voice commands follow: Spanish column and example");
  check(!doc.querySelector("#savebar").hidden, "language change marks dirty");
  let sent = null;
  const api = window.__ecoscribe.api;
  const orig = api.save_settings;
  api.save_settings = async (v) => { sent = v; return orig(v); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.languages === "en,es" && JSON.stringify(sent.extra_languages) === '["es"]' && Object.keys(sent).length === 2,
        "saves the added language and the ticks: " + JSON.stringify(sent));
  check(doc.querySelector("#savebar").hidden && !doc.querySelector("#toast").hidden, "saved: bar gone, toast shown");
  doc.querySelector("#mic-test").click(); await sleep(300);
  check(doc.querySelector("#mic-test").textContent === "Stop" && parseFloat(doc.querySelector("#meter-fill").style.width) > 0, "mic test moves the meter");
  doc.querySelector('.nav-item[data-page="inicio"]').click(); await sleep(100);
  check(doc.querySelector("#mic-test").textContent === "Test", "leaving ajustes stops the mic test");
  // races: count open tests through the fake api
  let open = 0;
  const a2 = window.__ecoscribe.api;
  const s0 = a2.mic_test_start, s1 = a2.mic_test_stop;
  a2.mic_test_start = async (d) => { await sleep(60); open = 1; return s0(d); };
  a2.mic_test_stop = async () => { open = 0; return s1(); };
  doc.querySelector('.nav-item[data-page="ajustes"]').click(); await sleep(150);
  const b = doc.querySelector("#mic-test");
  b.click(); b.click(); await sleep(250);          // double click: start then stop
  check(open === 0 && b.textContent === "Test", "double click leaves no mic open");
  b.click(); await sleep(10);
  doc.querySelector('.nav-item[data-page="historial"]').click(); await sleep(300);  // leave mid-start
  check(open === 0, "leaving during a start leaves no mic open");
}
{ // reuniones: list, live, done, drop, deep link
  const { window, doc, errors } = await load("page=reuniones");
  check(!doc.querySelector("#page-reuniones").hidden, "reuniones visible");
  check(doc.querySelectorAll(".r-row").length === 5, "list shows 5 sessions");
  check(doc.querySelector(".r-row .r-chip").textContent === "Recording", "first row is the recording one");
  check([...doc.querySelectorAll(".r-chip")].some((c) => c.textContent === "Transcribing 42 %"), "job shows its percent");
  check(!doc.querySelector("#r-now").hidden && doc.querySelector("#r-start").disabled, "banner while recording, start disabled");
  check(doc.querySelector("#r-lang").options.length === 2 && doc.querySelector("#r-lang").value === "en", "meeting languages: only the user's English, and Detect (dictado-607)");
  const s = doc.querySelector("#r-search");
  s.value = "planering"; s.dispatchEvent(new window.Event("input")); await sleep(250);
  check(doc.querySelectorAll(".r-row").length === 1, "search filters sessions");
  s.value = ""; s.dispatchEvent(new window.Event("input")); await sleep(250);
  doc.querySelector(".r-row").click(); await sleep(150);
  check(!doc.querySelector("#r-detail-view").hidden && doc.querySelector("#r-list-view").hidden, "one click opens the session");
  check(!doc.querySelector("#r-d-live-actions").hidden && doc.querySelector("#r-d-stop").textContent === "Stop", "Stop visible while recording");
  const sel = doc.querySelector("#r-d-lang");
  check(sel.value === "sv" && sel.options.length === 3, "live view shows the meeting language, even one outside the user's list");
  sel.value = "en"; sel.dispatchEvent(new window.Event("change")); await sleep(100);
  check(window.__lang === "en" && doc.querySelector("#toast").textContent.includes("English"), "switching the language mid-meeting");
  const first = doc.querySelectorAll(".r-seg").length;
  const firstNode = doc.querySelector(".r-seg");
  await sleep(1150);
  check(doc.querySelectorAll(".r-seg").length > first && doc.querySelector(".r-seg") === firstNode, "live poll appends without re-rendering old lines");
  { // t0u.19: reading back while it records must not yank the list to the bottom
    const list = doc.querySelector("#r-segs");
    Object.defineProperty(list, "scrollHeight", { configurable: true, get: () => 2000 });
    Object.defineProperty(list, "clientHeight", { configurable: true, get: () => 400 });
    list.scrollTop = 300;  // scrolled up
    const n = doc.querySelectorAll(".r-seg").length;
    await sleep(1150);
    check(doc.querySelectorAll(".r-seg").length > n && list.scrollTop === 300, "scrolled up: a new live line keeps the scroll");
    check(!doc.querySelector("#r-jump").hidden, "scrolled up: 'Jump to latest' shows");
    doc.querySelector("#r-jump").click();
    check(list.scrollTop === 2000 && doc.querySelector("#r-jump").hidden, "'Jump to latest' goes to the bottom and hides");
  }
  doc.querySelector("#r-back").click(); await sleep(150);
  check(!doc.querySelector("#r-list-view").hidden, "back to the list");
  [...doc.querySelectorAll(".r-row")].find((li) => li.dataset.name === "2026-10-05_0915_planering").click(); await sleep(150);
  check(!doc.querySelector("#r-d-done-actions").hidden && doc.querySelectorAll(".r-seg").length === 4, "done session: transcript + actions");
  check(doc.querySelector('.r-who[data-who="Others"]') !== null, "speaker labels shown");
  check(doc.querySelector("#r-copy-summary")?.textContent.startsWith("Copy a summary prompt"), "done session offers a summary prompt (in the Copy menu)");
  check(doc.querySelectorAll("#r-d-done-actions > .btn, #r-d-done-actions > details").length === 3, "three actions: Copy ▾, Email, ··· (dictado-6oe.4)");
  check(doc.querySelectorAll("#r-list .r-day").length >= 1, "the list is grouped by day");
  { // t0u.22: several remote speakers, named and renamed
    doc.querySelector("#r-back").click(); await sleep(150);
    [...doc.querySelectorAll(".r-row")].find((li) => li.dataset.name === "2026-10-04_1600_kund").click(); await sleep(150);
    const whos = () => [...doc.querySelectorAll(".r-who")].map((w) => w.textContent);
    check(JSON.stringify(whos()) === JSON.stringify(["Me", "Speaker 1", "Ana", "Speaker 3", "Me"]), "speakers shown, a named one by its name: " + whos());
    const w = [...doc.querySelectorAll(".r-who-edit")].find((x) => x.dataset.label === "Speaker 1");
    w.click();
    const inp = w.querySelector("input");
    check(inp && inp.value === "Speaker 1", "click a label: an input with the current name");
    inp.value = "Leo"; inp.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter" })); await sleep(50);
    check(window.__renamed?.[0] === "Speaker 1" && window.__renamed?.[1] === "Leo" && whos()[1] === "Leo", "Enter saves and relabels");
  }
  const drop = new window.Event("drop", { bubbles: true, cancelable: true });
  drop.dataTransfer = { files: [{ name: "pod.mp3", path: "C:\\x\\pod.mp3" }], types: ["Files"] };
  doc.dispatchEvent(drop); await sleep(100);
  check(JSON.stringify(window.__imported) === JSON.stringify(["C:\\x\\pod.mp3"]), "drop imports the file paths");
  check(errors.length === 0, "no JS errors on reuniones: " + errors.join("; "));
  const deep = await load("page=reuniones/2026-10-04_1600_kund");
  await sleep(150);
  check(!deep.doc.querySelector("#r-detail-view").hidden && deep.doc.querySelector("#r-d-title").value === "Client call", "deep link opens a session");
}
{ // t0u.30: notes during a call, kept while the live view polls
  const { window, doc } = await load("page=reuniones/2026-10-05_1400_retro");
  await sleep(200);
  const box = doc.querySelector("#r-notes-text");
  check(box && box.value.startsWith("- Is the export date firm?"), "live session shows its saved notes");
  box.value += "\n- budget"; box.dispatchEvent(new window.Event("input", { bubbles: true }));
  await sleep(900);
  check(window.__notes?.["2026-10-05_1400_retro"]?.endsWith("- budget") && doc.querySelector("#r-notes-state").textContent === "Saved.", "typing saves the notes");
  check(box.value.endsWith("- budget"), "a live poll doesn't overwrite the notes");
}
{ // dictado-7t38: a PC without an NVIDIA card needs the small model; the GPU two start unticked
  const { window, doc } = await load("page=bienvenida&welcome=1&sstep=models&nogpu=1");
  await sleep(200);
  const rows = doc.querySelectorAll("#s-models .s-row");
  const box = (i) => rows[i].querySelector("[data-model]");
  check(rows.length === 3 && rows[0].textContent.includes("For this computer") && rows[0].textContent.includes("Needed on this computer"),
    "no GPU: the small model is listed first, needed on this computer");
  check(box(0).checked && box(0).disabled && !box(1).checked && !box(2).checked, "only the small model is ticked; the GPU models are optional");
  check(doc.querySelector("#s-download").textContent.includes("484 MB"), "download offers only the small model (484 MB)");
  check(doc.querySelector("#s-models-hint").textContent.includes("no NVIDIA graphics card") && rows[1].textContent.includes("Optional"),
    "the hint and tags say the GPU models are optional here");
}
{ // dictado-5d6y: a card too small for the big models gets the same three rows, with its own reason
  const { doc } = await load("page=bienvenida&welcome=1&sstep=models&nogpu=small");
  await sleep(200);
  const rows = doc.querySelectorAll("#s-models .s-row");
  const hint = doc.querySelector("#s-models-hint").textContent;
  check(rows.length === 3 && hint.startsWith("This computer's graphics card has 2 GB") && !hint.includes("no NVIDIA"),
    "small card: the hint names the card's memory, not a missing card");
  check(rows[1].textContent.includes("slow on this computer"), "small card: the GPU rows say slow on this computer");
}
{ // setup (dictado-zpz): every step on Windows, then the summary
  const { window, doc } = await load("page=bienvenida&welcome=1");
  const on = () => doc.querySelector(".sstep.on")?.dataset.step;
  const next = doc.querySelector("#s-next");
  check(!doc.querySelector("#setup").hidden, "setup opens on first run");
  check(on() === "languages", "Windows skips the permissions step");
  check(doc.querySelectorAll("#s-steps li").length === 6, "the side panel lists every step (dictado-6oe.8)");
  check(doc.querySelectorAll("#s-langs .s-lchip").length === 1 && doc.querySelector("#s-langs").textContent.includes("English")
    && !doc.querySelector("#s-langs [data-x]"), "starts with English only, which can't be removed");
  check(doc.querySelector("#s-skip").hidden, "the first run can't be skipped");
  const add = doc.querySelector("#s-lang-more");
  add.value = "sv"; add.dispatchEvent(new window.Event("change")); await sleep(20);
  add.value = "el"; add.dispatchEvent(new window.Event("change")); await sleep(20);
  check(doc.querySelectorAll("#s-langs .s-lchip").length === 3, "Add a language adds chips");
  doc.querySelector('#s-langs [data-x="el"]').click(); await sleep(20);
  check(doc.querySelectorAll("#s-langs .s-lchip").length === 2 && !doc.querySelector("#s-langs").textContent.includes("Greek"), "✕ removes one");
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape" })); await sleep(50);
  check(!doc.querySelector("#setup").hidden, "Esc doesn't skip the first run");
  next.click(); await sleep(150);
  check(on() === "models", "languages -> models");
  const rows = doc.querySelectorAll("#s-models .s-row");
  check(rows.length === 2 && rows[1].textContent.includes("Needed for your languages"), "Swedish makes the accurate model required");
  check(rows[0].textContent.includes("Recommended"), "the other model is recommended");
  check(next.disabled, "can't go on before the required model is there");
  check(doc.querySelector("#s-download").textContent.includes("4.7 GB"), "download offers both models (4.7 GB)");
  doc.querySelector("#s-download").click();
  for (let i = 0; i < 150 && next.disabled; i++) await sleep(100);  // the demo download takes ~4 s: don't race it
  check(!next.disabled && doc.querySelectorAll("#s-models .s-model.ready").length === 2, "both models download, then Continue");
  next.click(); await sleep(250);
  check(on() === "mic" && doc.querySelector("#s-mic").options.length > 1, "mic step lists the mics");
  await sleep(400);
  check(doc.querySelectorAll("#s-bars i.on").length > 0, "mic bars light up");
  next.click(); await sleep(150);
  check(on() === "shortcut" && doc.querySelector("#s-key").textContent === "Right Ctrl", "key step shows the key");
  doc.querySelector('input[name="s-mode"][value="hold"]').click();
  next.click(); await sleep(150);
  check(on() === "try" && doc.querySelector("#s-try-sub").textContent.startsWith("Hold Right Ctrl"), "try step uses the chosen mode");
  const box = doc.querySelector("#s-try-box");
  box.value = "Testing one two three."; box.dispatchEvent(new window.Event("input", { bubbles: true }));
  check(!doc.querySelector("#s-try-ok").hidden, "text in the box says it works");
  next.click(); await sleep(150);
  const sum = doc.querySelector("#s-summary").textContent;
  check(on() === "done" && sum.includes("Swedish") && sum.includes("Hold") && sum.includes("Most accurate"), "summary lists languages, key and models");
  check(next.textContent === "Start using Ecoscribe", "last button");
  next.click(); await sleep(150);
  check(doc.querySelector("#setup").hidden && !doc.querySelector("#page-inicio").hidden, "setup closes to Home");
  doc.querySelector("#setup-again").click(); await sleep(200);
  check(!doc.querySelector("#setup").hidden && on() === "languages", "Run setup again reopens it");
  check(!doc.querySelector("#s-skip").hidden && doc.querySelector("#s-skip").textContent === "Cancel", "a rerun can be cancelled");
  doc.querySelector("#s-skip").click(); await sleep(100);
  check(doc.querySelector("#setup").hidden, "Cancel closes the rerun");
}
{ // setup on the Mac starts with the permissions
  const { window, doc } = await load("page=bienvenida&welcome=1&mac=1");
  check(doc.querySelector(".sstep.on")?.dataset.step === "permissions", "Mac starts with permissions");
  check(doc.querySelectorAll("#s-perms .s-row").length === 3 && doc.querySelector("#s-perms").textContent.includes("✓ On"), "three permissions, granted ones ticked");
  doc.querySelector("#s-perms [data-perm]").click(); await sleep(20);
  check(window.__perm === "accessibility", "Open settings opens that pane");
  check(doc.querySelector("#s-done-sub").textContent.includes("menu bar"), "Mac wording on the last step");
  check(doc.querySelector("#s-skip").hidden, "no skipping on the Mac's first run either");
}
{ // Home tips (dictado-3vj): one that applies, x hides it for good
  const { window, doc } = await load("page=inicio");
  await sleep(200);
  const box = doc.querySelector("#home-tip"), first = box.dataset.tip;
  check(!box.hidden && first && doc.querySelector("#home-tip-text").textContent.startsWith("Tip"), "a tip shows: " + first);
  check(first !== "snippets", "a tip already acted on is skipped (snippets are set up in the demo)" );
  box.querySelector("#home-tip-x").click(); await sleep(100);
  check(box.hidden || box.dataset.tip !== first, "x hides that tip");
  let saved = null; try { saved = window.localStorage.getItem("ecoscribe.tips.hidden"); } catch { /* no storage on file:// in jsdom */ }
  check(saved === null || JSON.parse(saved).includes(first), "and remembers it where storage works");
}
{ // History > Retry (dictado-a2r)
  const { window, doc } = await load("page=historial");
  await sleep(200);
  const items = [...doc.querySelectorAll("#history .h-item")].filter((li) => !li.classList.contains("h-meeting"));
  check(items[0].querySelector(".h-retry") && !items[2].querySelector(".h-retry"), "Retry only where the audio is kept");
  items[0].querySelector(".h-retry button").click(); await sleep(150);
  const opts = [...items[0].querySelectorAll(".h-menu-item")].map((b) => b.textContent);
  check(opts[0] === "Again, detect the language" && opts.includes("Again, in English"), "the menu offers detect + each language");
  items[0].querySelectorAll(".h-menu-item")[0].click(); await sleep(150);
  check(items[0].querySelector(".h-text").textContent.startsWith("Could you"), "the new text replaces the old one");
  check(!doc.querySelector("#toast").hidden && doc.querySelector("#toast").textContent.includes("copied"), "says it's copied");
}
{ // History > Delete with Undo (dictado-vfo)
  const { window, doc } = await load("page=historial&undo_ms=200");
  await sleep(200);
  const dicts = () => [...doc.querySelectorAll("#history .h-item")].filter((li) => !li.classList.contains("h-meeting"));
  const before = dicts().length, first = dicts()[0];
  first.querySelector(".h-del").click(); await sleep(30);
  check(first.hidden && doc.querySelector("#toast .toast-btn").textContent === "Undo", "Delete hides the row and offers Undo");
  doc.querySelector("#toast .toast-btn").click(); await sleep(300);
  check(!first.hidden && !window.__deletedDictation, "Undo brings it back, nothing deleted");
  first.querySelector(".h-del").click(); await sleep(450);
  check(window.__deletedDictation && dicts().length === before - 1, "without Undo it's deleted for good");
}
{ // Settings > Speech models (dictado-z4q)
  const { window, doc } = await load("page=ajustes");
  await sleep(250);
  const rows = doc.querySelectorAll("#m-rows .m-row");
  check(rows.length === 2 && rows[0].textContent.includes("In use") && rows[0].textContent.includes("on this computer"), "models listed, the one in use on disk");
  check(rows[1].textContent.includes("Not downloaded") && rows[1].querySelector("[data-get]"), "the other can be downloaded");
  rows[1].querySelector("[data-get]").click();
  for (let i = 0; i < 40 && !doc.querySelector("#m-rows [data-del='Systran/faster-whisper-large-v3']"); i++) await sleep(100);
  check(doc.querySelector("#m-rows [data-del='Systran/faster-whisper-large-v3']"), "download runs to Ready, then it can be deleted");
  doc.querySelector("#m-rows [data-del='large-v3-turbo']").click(); await sleep(200);
  check(window.__deleted === "large-v3-turbo" && doc.querySelector("#toast").textContent.includes("free"), "delete frees the space");
}
{ // Meetings > Email to participants (dictado-fnw)
  const { window, doc } = await load("page=reuniones/2026-10-05_0915_planering");
  await sleep(300);
  const b = doc.querySelector("#r-email");
  check(b && !doc.querySelector("#r-d-done-actions").hidden, "a finished meeting offers Email to participants");
  b.click(); await sleep(150);
  check(window.__emailed === "2026-10-05_0915_planering" && doc.querySelector("#toast").textContent.includes("to 2 people")
    && doc.querySelector("#toast").textContent.includes("paste it in"), "opens a draft to the participants, says to paste");
  const ng = await load("page=reuniones/2026-10-05_0915_planering&noguests=1");
  await sleep(300);
  ng.doc.querySelector("#r-email").click(); await sleep(150);
  const t = ng.doc.querySelector("#toast").textContent;
  check(ng.window.__emailHow === "" && t.startsWith("Transcript copied. Google Calendar is open on") && t.includes("Email guests"),
    "no invite: Google Calendar on that day, the steps in the toast");
}
{ // dictado-607: a user with Swedish and Spanish sees both, Swedish removable like an added one
  const { window, doc } = await load("page=ajustes&langs=en,sv,es");
  await sleep(200);
  check([...doc.querySelectorAll("#f-languages input")].map((i) => i.value).join(",") === "en,sv,es", "ticked Swedish shows");
  check([...doc.querySelectorAll("#vc-head th")].map((t) => t.textContent).join(",") === "What it does,English,Swedish,Spanish", "both columns");
  check(doc.querySelector("#vc-help").textContent.includes("Swedish and Spanish work too"), "both in the help line");
  doc.querySelector('#f-languages input[value="sv"]').closest("label").querySelector(".lang-x").click(); await sleep(20);
  check(!doc.querySelector('#f-languages input[value="sv"]') && [...doc.querySelector("#lang-add").options].some((o) => o.value === "sv"),
    "removed Swedish goes back to the picker");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (v) => { sent = v; return orig(v); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.languages === "en,es" && !("extra_languages" in sent), "saves the ticks without Swedish: " + JSON.stringify(sent));
}
{ // dictado-pcz: Snippets and Voice commands say how they differ and point at each other
  const { doc } = await load("page=ajustes");
  await sleep(200);
  const snipHead = doc.querySelector("#snips-card .group-head").textContent;
  const vcRow = doc.querySelector("#row-voice-commands").textContent;
  check(snipHead.includes("A phrase that types saved text.") && vcRow.includes("A phrase that does an action."), "one line on each says what it is");
  doc.querySelector('#row-voice-commands .go-link').click(); await sleep(20);
  check(!doc.querySelector("#snips-card").hidden && doc.querySelector('#set-tabs .seg.active').dataset.sec === "words"
    && !doc.querySelector("#f-voice-commands").checked, "Snippets link opens Languages and words, the switch untouched");
  doc.querySelector('#snips-card .go-link').click(); await sleep(20);
  check(!doc.querySelector("#row-voice-commands").closest(".group").hidden && doc.querySelector('#set-tabs .seg.active').dataset.sec === "dictation",
    "Voice commands link opens Dictation");
}
{ // dictado-67v: the voice command phrases are the user's to change, per language, with Reset
  const { window, doc } = await load("page=ajustes");
  await sleep(200);
  const heads = () => [...doc.querySelectorAll("#vc-list thead th")].map((t) => t.textContent).join(",");
  const chips = (key) => [...doc.querySelectorAll(`.vc-add[data-key="${key}"][data-lang="en"]`)].flatMap((i) =>
    [...i.parentElement.querySelectorAll(".vc-chip")].map((c) => c.firstChild.textContent));
  check(heads() === "What it does,English", "columns: English and the user's languages: " + heads());
  check(chips("line").join(",") === "new line" && doc.querySelector("#vc-reset-all").hidden, "built-in phrases, nothing to reset");
  const add = (key, text) => { const i = doc.querySelector(`.vc-add[data-key="${key}"][data-lang="en"]`); i.value = text;
    i.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })); };
  add("line", "  Next Line! ");
  check(chips("line").join(",") === "new line,next line" && !doc.querySelector("#vc-reset-all").hidden
    && doc.querySelector('.vc-add[data-key="line"]').parentElement.querySelector(".vc-reset"), "a phrase added, cleaned; Reset offered");
  check(!doc.querySelector("#savebar").hidden, "an added phrase offers Save");
  add("line", "send it");
  check(chips("line").join(",") === "new line,next line" && doc.querySelector("#toast").textContent.includes("already Press Enter"),
    "a phrase of another command is refused with the reason");
  doc.querySelector('.vc-add[data-key="enter"]').parentElement.querySelector(".vc-x").click(); await sleep(20);
  check(chips("enter").join(",") === "press enter", "× removes a phrase");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (v) => { sent = v; return orig(v); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && JSON.stringify(sent.voice_phrases) === '{"line":{"en":["new line","next line"]},"enter":{"en":["press enter"]}}'
    && Object.keys(sent).length === 1, "saves only what differs: " + JSON.stringify(sent));
  doc.querySelector("#vc-reset-all").click(); await sleep(20);
  check(chips("line").join(",") === "new line" && chips("enter").join(",") === "send it,press enter" && doc.querySelector("#vc-reset-all").hidden,
    "Back to the built-in phrases resets every cell");
  const sv = await load("page=ajustes&vp=1");
  await sleep(200);
  check([...sv.doc.querySelectorAll('.vc-add[data-key="enter"][data-lang="en"]')][0].parentElement.textContent.includes("ship it"), "saved phrases show on load");
}
{ // dictado-a1d: Command mode by that name, with keys the user picks (the dictation key's picker)
  const { window, doc } = await load("page=ajustes");
  await sleep(200);
  const key = (type, code, mods = {}) => doc.dispatchEvent(new window.KeyboardEvent(type, { code, bubbles: true, cancelable: true, ...mods }));
  check(doc.querySelector("#row-command-mode .row-label").textContent === "Command mode", "the row is called Command mode");
  check(doc.querySelector("#row-command-mode #cm-change")?.textContent === "change" && !doc.querySelector("#row-command-keys")
    && doc.querySelector("#cm-hint").hidden, "look B: the keys and a change link inside the sentence, no extra row, no hint at rest");
  check(doc.querySelector("#cm-press").textContent === "Right Ctrl + E"
    && doc.querySelector("#cm-stop").textContent === "tap Right Ctrl", "default keys: Right Ctrl + E, then tap Right Ctrl");
  doc.querySelector("#cm-change").click();
  check(doc.querySelector("#cm-press").textContent === "Press it now…" && doc.querySelector("#cm-change").textContent === "cancel"
    && !doc.querySelector("#cm-hint").hidden && doc.querySelector("#cm-hint").textContent.startsWith("Hold Right Ctrl and press a letter")
    && !doc.querySelector("#f-command-mode").checked, "the picker listens in the sentence, says how, and leaves the switch alone");
  key("keydown", "ControlRight", { ctrlKey: true }); key("keydown", "KeyK", { ctrlKey: true }); await sleep(50);
  key("keyup", "KeyK", { ctrlKey: true }); key("keyup", "ControlRight"); await sleep(20);
  check(doc.querySelector("#f-command-key").value === "k" && doc.querySelector("#cm-press").textContent === "Right Ctrl + K"
    && doc.querySelector("#cm-change").textContent === "change", "holding Right Ctrl and pressing K picks Right Ctrl + K");
  check(!doc.querySelector("#savebar").hidden, "a new pick offers Save");
  doc.querySelector("#cm-change").click();
  key("keydown", "ControlRight", { ctrlKey: true }); key("keydown", "KeyL", { ctrlKey: true }); await sleep(50);
  key("keyup", "KeyL", { ctrlKey: true }); key("keyup", "ControlRight"); await sleep(20);
  check(doc.querySelector("#f-command-key").value === "k" && doc.querySelector("#cm-hint").classList.contains("hk-bad")
    && !doc.querySelector("#cm-hint").hidden && doc.querySelector("#cm-press").textContent === "Right Ctrl + K", "Right Ctrl + L (next language) is refused with the reason");
  doc.querySelector("#cm-change").click();
  key("keydown", "ControlLeft", { ctrlKey: true }); key("keydown", "ShiftLeft", { ctrlKey: true, shiftKey: true });
  key("keydown", "KeyE", { ctrlKey: true, shiftKey: true }); await sleep(50);
  check(doc.querySelector("#f-command-key").value === "ctrl+shift+e" && doc.querySelector("#cm-stop").textContent === "press Ctrl+Shift+E again",
    "a combo of its own: Ctrl+Shift+E, pressed again to stop");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (v) => { sent = v; return orig(v); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.command_key === "ctrl+shift+e" && Object.keys(sent).length === 1, "saves only the keys: " + JSON.stringify(sent));
}
{ // Settings > the two switches that use Claude (dictado-bd6)
  const { doc } = await load("page=ajustes");
  await sleep(200);
  check(doc.querySelector("#f-self-corrections") && doc.querySelector("#f-command-mode") && !doc.querySelector("#row-command-mode").hidden, "self-corrections and command mode have switches");
  check(doc.querySelectorAll("#sc-rows tr").length === 2 && doc.querySelector("#sc-rows").textContent.includes("scratch that"), "the phrases are listed");
  check(doc.querySelector("#cm-press").textContent === "Right Ctrl + E", "command mode names its keys (the dictation key + E)");
  doc.querySelector("#f-command-mode").click(); await sleep(50);
  check(!doc.querySelector("#savebar").hidden, "turning one on offers Save");
  const mac = await load("page=ajustes&mac=1");
  await sleep(200);
  check(!mac.doc.querySelector("#cm-block").hidden, "the Mac has command mode too (dictado-waw)");
  check(/\+ E$/.test(mac.doc.querySelector("#cm-press").textContent) && mac.doc.querySelector("#row-command-mode").textContent.includes("⌘Z"),
        "with the Mac's keys: " + mac.doc.querySelector("#cm-press").textContent);
}
{ // Command mode: your writing style file (dictado-jq7p)
  const { window, doc } = await load("page=ajustes");
  check(doc.querySelector("#row-cm-style").hidden, "the style row waits for Command mode to be on");
  doc.querySelector("#f-command-mode").click(); await sleep(50);
  check(!doc.querySelector("#row-cm-style").hidden && doc.querySelector("#cm-style-pick").textContent === "Choose file"
        && doc.querySelector("#cm-style-open").hidden, "on: Choose file, nothing to open yet");
  doc.querySelector("#cm-style-pick").click(); await sleep(50);
  check(doc.querySelector("#cm-style-text b")?.textContent === "writing-style.md" && !doc.querySelector("#cm-style-clear").hidden
        && doc.querySelector("#cm-style-pick").textContent === "Change", "a picked file shows its name, Open and Remove");
  doc.querySelector("#cm-style-open").click(); await sleep(50);
  check(window.__styleOpened === "C:/Users/you/Documents/writing-style.md", "Open opens that file");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.command_style_file === "C:/Users/you/Documents/writing-style.md" && sent.command_mode === true,
        "Save sends the file with the switch: " + JSON.stringify(sent));
  doc.querySelector("#cm-style-clear").click(); await sleep(50);
  check(doc.querySelector("#cm-style-pick").textContent === "Choose file" && !doc.querySelector("#savebar").hidden, "Remove clears it and offers Save");
}
{ // History > Edit, and learn the fixed name (dictado-1ph)
  const { window, doc } = await load("page=historial");
  await sleep(200);
  const li = doc.querySelector('#history .h-item[data-id="d1b"]');
  li.querySelector(".h-edit-btn").click();
  const box = li.querySelector(".h-edit");
  check(box && li.querySelector(".h-text").hidden, "Edit opens the text in a box");
  box.value = "Send the draft to Quintavelle before lunch, she has the numbers.";
  [...li.querySelectorAll(".h-edit-bar button")].find((b) => b.textContent === "Save").click(); await sleep(100);
  check(window.__edited?.includes("Quintavelle") && li.querySelector(".h-text").textContent.includes("Quintavelle") && !li.querySelector(".h-edit"), "Save keeps the new text");
  const chip = li.querySelector(".h-learn .h-learn-chip");
  check(chip && chip.textContent === "+ Quintavelle", "the fixed name is offered");
  chip.click(); await sleep(50);
  check(JSON.stringify(window.__learned) === JSON.stringify(["word", "Quintavelle", ""]) && chip.classList.contains("done"), "a click learns it");
  li.querySelector(".h-edit-btn").click();
  li.querySelector(".h-edit").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape" }));
  check(!li.querySelector(".h-edit") && !li.querySelector(".h-text").hidden, "Escape cancels");
}
{ // Meetings > the checked summary above the transcript (dictado-nl5)
  const { doc } = await load("page=reuniones/2026-10-05_0915_planering");
  await sleep(300);
  const box = doc.querySelector("#r-summary");
  check(box && !box.hidden && doc.querySelector("#r-sum-check").textContent === "2 of 3 points found in the call", "a done summary shows, with how many points were found");
  const miss = [...doc.querySelectorAll("#r-sum-lists li.unchecked")];
  check(miss.length === 1 && miss[0].querySelector(".r-sum-miss")?.textContent === "Not found in the call", "the point not found in the call is marked");
  const at = doc.querySelector("#r-sum-lists .r-sum-at");
  at.click(); await sleep(50);
  check(doc.querySelector("#r-segs .r-seg-hit") !== null, "a point's time jumps to that line of the transcript");
  const writing = await load("page=reuniones/2026-10-04_1600_kund");
  await sleep(300);
  check(!writing.doc.querySelector("#r-summary").hidden && writing.doc.querySelector("#r-sum-text").textContent.startsWith("Writing the summary"), "a summary being written says so");
  const none = await load("page=reuniones/2026-10-05_1130_podcast");
  await sleep(300);
  check(none.doc.querySelector("#r-summary").hidden, "no summary: no card");
}
{ // Settings in sections (dictado-6oe.7)
  const { window, doc } = await load("page=ajustes");
  await sleep(150);
  const vis = () => [...doc.querySelectorAll("#settings .group")].filter((g) => !g.hidden).map((g) => g.dataset.sec);
  check(vis().length > 0 && vis().every((k) => k === "dictation"), "Settings opens on one section");
  doc.querySelector('#set-tabs [data-sec="meetings"]').click(); await sleep(50);
  check(vis().length > 0 && vis().every((k) => k === "meetings"), "a tab shows only its section");
}
{ // Meetings > apply the Replace list to a saved transcript, and Undo (dictado-9lo)
  const { window, doc, errors } = await load("page=reuniones/2026-10-04_1600_kund");
  await sleep(300);
  const box = doc.querySelector("#r-replace"), title = () => doc.querySelector("#r-replace-title").textContent;
  const texts = () => [...doc.querySelectorAll("#r-segs .r-text")].map((p) => p.textContent).join(" | ");
  check(box && !box.hidden && title() === "2 places match your Replace list", "a transcript with matches offers the Replace list, with the count");
  check(doc.querySelector("#r-replace-detail").textContent === "poll request → pull request", "it names the pair");
  check(texts().includes("one more poll request") && !doc.querySelector("#r-replace-go").hidden, "nothing changes before Apply");
  doc.querySelector("#r-replace-go").click(); await sleep(200);
  check(window.__replaced === 2 && !texts().includes("poll request") && texts().includes("one more pull request"), "Apply changes the lines");
  check(title() === "Changed 2 places with your Replace list" && !doc.querySelector("#r-replace-undo").hidden
    && doc.querySelector("#r-replace-go").hidden, "then says what it changed, with Undo");
  doc.querySelector("#r-replace-undo").click(); await sleep(200);
  check(texts().includes("one more poll request") && doc.querySelector("#toast").textContent.startsWith("Undone"), "Undo puts the text back");
  check(!box.hidden && title().startsWith("2 places match"), "and offers it again");
  doc.querySelector("#r-replace-later").click();
  check(box.hidden, "Not now hides it");
  check(errors.length === 0, "no JS errors: " + errors.join("; "));
  const none = await load("page=reuniones/2026-10-05_0915_planering");
  await sleep(300);
  check(none.doc.querySelector("#r-replace").hidden, "nothing matches: no offer");
}
{ // Home > your own to-dos from the week's call summaries, by person (dictado-xuu)
  const { window, doc } = await load("page=inicio");
  await sleep(200);
  const box = doc.querySelector("#todos");
  const people = () => [...doc.querySelectorAll(".todo-person strong")].map((e) => e.textContent);
  check(box && !box.hidden && people().join("|") === "Ana|Mia and Leo|Tom", "the week's to-dos show, one column per person: " + people());
  check(doc.querySelector("#todos-sub").textContent.startsWith("6 of 7 still to do · from 4 calls"), "it says how many are left: " + doc.querySelector("#todos-sub").textContent);
  check(doc.querySelector(".todo.unchecked .r-sum-miss")?.textContent === "Not found in the call", "a to-do whose words weren't found is marked");
  const box2 = [...doc.querySelectorAll(".todo-tick input")].find((c) => !c.checked);
  box2.checked = true; box2.dispatchEvent(new window.Event("change", { bubbles: true }));
  await sleep(150);
  check(window.__todoDone && window.__todoDone[1] === true && doc.querySelector("#todos-sub").textContent.startsWith("5 of 7"), "a tick saves and counts it done");
  doc.querySelector('#todos-weeks [data-back="1"]').click(); await sleep(150);
  check(doc.querySelector("#todos-title").textContent === "Your to-dos last week" && people().join("|") === "Tom", "Last week shows last week's list");
  doc.querySelector(".todo-from").click(); await sleep(200);
  check(!doc.querySelector("#page-reuniones").hidden, "a to-do's call opens on the Meetings page");
  const lit = await load("page=inicio/todos");
  await sleep(200);
  check(lit.doc.querySelector("#todos").classList.contains("card-lit"), "the Sunday notice's Open lands on the card, lit up");
  const none = await load("page=inicio&todos=0");
  await sleep(200);
  check(!none.doc.querySelector("#todos").hidden && !none.doc.querySelector("#todos-empty").hidden
    && none.doc.querySelector("#todos-empty").textContent.startsWith("None yet this week"), "no to-dos yet: the card says what will show up");
}
{ // dictado-s1a: what the meeting records, live, and a warning with a switch when a source hears nothing
  const ok = await load("page=reuniones/2026-10-05_1400_retro");
  await sleep(300);
  const box = ok.doc.querySelector("#r-src");
  check(!box.hidden && ok.doc.querySelector("#r-src-warn").hidden, "both sources shown, no warning while they hear something");
  check(box.querySelector('[data-src="mic"]').title === "You: Microphone (Jabra Evolve2 65) · hearing you", "the mic's device and state on hover");
  check(box.parentElement.id === "r-d-live-actions", "look C: small meters in the Stop row");
  const bad = await load("page=reuniones/2026-10-05_1400_retro&src=mic");
  await sleep(300);
  const warn = bad.doc.querySelector("#r-src-warn");
  check(!warn.hidden && warn.textContent.includes("hears nothing from your mic") && warn.textContent.includes("Teams uses Microphone (Jabra Evolve2 65)"),
    "a silent mic with the call on another one: the warning says both");
  check(bad.doc.querySelector('[data-src="mic"]').classList.contains("bad") && bad.doc.querySelector('[data-src="mic"]').title.endsWith("silent 1:35"),
    "the silent row says for how long");
  bad.doc.querySelector("#r-src-fix").click(); await sleep(50);
  check(JSON.stringify(bad.window.__srcSwitched) === '["mic","Microphone (Jabra Evolve2 65)"]' && bad.doc.querySelector("#toast").textContent.includes("from now on"),
    "the button records the call's mic from now on");
  bad.doc.querySelector("#r-src-x").click(); await sleep(50);
  check(warn.hidden && bad.doc.querySelector('[data-src="mic"]').classList.contains("bad"), "the × hides the warning; the row still says it's silent");
  const done = await load("page=reuniones/2026-10-05_0915_planering");
  await sleep(300);
  check(done.doc.querySelector("#r-src").hidden && done.doc.querySelector("#r-src-warn").hidden, "a finished meeting shows neither");
}
{ // dictado-gvai: a decision page from tools/before_after.py shows what happened to each choice after the read-back
  const { execFileSync } = await import("child_process");
  const py = 'import sys; sys.path.insert(0, "tools"); import before_after as b; '
    + 'sys.stdout.buffer.write(b.build("Pill", "look-test", ["Calm", "Bold", "Plain"], {}, [980], True).encode())';
  let page = null;
  for (const exe of ["python3", "python"]) {
    try { page = execFileSync(exe, ["-c", py], { cwd: path.resolve(here, "../.."), stdio: ["ignore", "pipe", "ignore"] }).toString("utf8"); break; } catch {}
  }
  const open = (html) => {
    const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true });
    return dom.window.document.querySelector("#outcome");
  };
  if (!page) { check(false, "tools/before_after.py builds a page (needs python3 or python)"); page = ""; }
  check(open(page)?.hidden, "a decision page before the read-back has no What happened panel");
  const read = page.replace('{ id: "calm", title: "Calm" },', '{ id: "calm", title: "Calm", done: "Shipped in 1.0.0." },');
  const oc = open(read), lines = [...oc.querySelectorAll("p")];
  check(!oc.hidden && lines.length === 3, "after the read-back: one line per choice");
  check(lines[0].className === "done" && lines[0].textContent === "CalmShipped in 1.0.0.", "a choice with a done line shows it");
  check(lines[1].className === "open" && lines[1].textContent === "BoldOpen.", "a choice without one shows Open");
}
console.log(failed ? `\n${failed} FAILED` : "\nall ok");
process.exit(failed ? 1 : 0);
