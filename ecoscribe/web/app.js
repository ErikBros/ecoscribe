/* Ecoscribe window logic. Talks to Python through window.pywebview.api (see ecoscribe/window.py).
   ?demo=1 swaps in a fake API so the page can be screenshotted and smoke-tested anywhere. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const params = new URLSearchParams(location.search);
const LANG_LABEL = { en: "English", "en,es": "English and Spanish", es: "Spanish", sv: "Swedish", el: "Greek" };
// macOS (WKWebView): ?mac=1 forces it for screenshots. Windows wording stays the default everywhere else.
const MAC = /Mac/.test(navigator.platform || "") || new URLSearchParams(location.search).get("mac") === "1";
const HOTKEY_LABEL = { rctrl: MAC ? "Right Control" : "Right Ctrl", scrolllock: "Scroll Lock", pause: "Pause", rcmd: "Right Command", fn: "Fn" };
const DEFAULT_MIC = MAC ? "System default" : "Windows default";
const hotkeyLabel = (k) => HOTKEY_LABEL[k] || (k ? k.split("+").map((p) => (p.length > 1 && !/^f\d/.test(p) ? p[0].toUpperCase() + p.slice(1) : p.toUpperCase())).join("+") : (MAC ? "Right Command" : "Right Ctrl"));

/* ---------------------------------------------------------------- demo API */
function demoInsights(days) {  // invented numbers and text for the demo and screenshots
  const k = days === 7 ? 0.3 : days === 30 ? 0.8 : 1;
  const hours = [0, 0, 0, 0, 0, 0, 1, 3, 8, 12, 10, 6, 4, 9, 14, 11, 7, 4, 2, 3, 2, 1, 0, 0].map((v) => Math.round(v * k));
  const today = new Date();
  const dayList = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(today); d.setDate(today.getDate() - 13 + i);
    return { date: d.toISOString().slice(0, 10), words: [210, 480, 0, 350, 620, 0, 0, 390, 530, 270, 0, 440, 710, 380][i] };
  });
  return {
    days, first: "2026-09-14",
    totals: { dictations: Math.round(240 * k), words: Math.round(11800 * k), talk_s: Math.round(5530 * k), wpm: 128, saved_s: Math.round(12170 * k), typing_wpm: 40 },
    rhythm: { hours, days: dayList, streak: 2 },
    languages: [{ lang: "en", words: Math.round(8200 * k) }, { lang: "sv", words: Math.round(2900 * k) }, { lang: "de", words: Math.round(500 * k) }, { lang: "mixed", words: Math.round(200 * k) }],
    apps: [{ app: "slack.exe", dictations: 96 }, { app: "code.exe", dictations: 71 }, { app: "outlook.exe", dictations: 44 }, { app: "chrome.exe", dictations: 29 }, { app: "SnippingTool.exe", dictations: 3 }],
    habits: [{ lang: "en", words: 8200, per_100: 3.1, top: [{ word: "like", count: 120 }, { word: "you know", count: 61 }, { word: "basically", count: 40 }, { word: "kind of", count: 33 }] },
      { lang: "sv", words: 2900, per_100: 1.4, top: [{ word: "typ", count: 25 }, { word: "liksom", count: 16 }] }],
    phrases: [{ phrase: "at the end of", count: 18 }, { phrase: "let me check", count: 14 }, { phrase: "as soon as", count: 11 }, { phrase: "on the other hand", count: 9 }],
    suggestions: [{ heard: "Ecoskribe", count: 5, suggest: "Ecoscribe" }, { heard: "Klaude", count: 3, suggest: "Claude" }, { heard: "Kristineberg", count: 3, suggest: "Kristineberg" }],
    clarity: { dictations: Math.round(90 * k), clarity: 91, since: "2026-09-20",
      weeks: [null, null, null, null, 86, 89, 90, 93].map((c, i) => {
        const d = new Date(today); d.setDate(today.getDate() - today.getDay() + 1 - 7 * (7 - i));
        return { week: d.toISOString().slice(0, 10), clarity: c, dictations: c ? 20 : 0 };
      }),
      words: [{ lang: "en", words: [{ word: "particularly", unsure: 4, said: 6 }, { word: "Kristineberg", unsure: 3, said: 3 }, { word: "rural", unsure: 2, said: 5 }] },
        { lang: "sv", words: [{ word: "sjuksköterska", unsure: 2, said: 2 }] }] },
    markers: { words: Math.round(3100 * k), dictations: Math.round(64 * k), fillers_per_100: 1.2, hedges_per_100: 2.4,
      weeks: [null, null, 3.6, 3.1, 2.9, null, 2.2, 1.8].map((h, i) => {
        const d = new Date(today); d.setDate(today.getDate() - today.getDay() + 1 - 7 * (7 - i));
        return { week: d.toISOString().slice(0, 10), words: h ? 400 : 20, hedges_per_100: h, fillers_per_100: h ? 1.1 : null };
      }),
      top_fillers: [{ word: "like", count: 22 }, { word: "basically", count: 9 }],
      top_hedges: [{ word: "maybe", count: 31 }, { word: "i think", count: 24 }, { word: "kind of", count: 12 }] },
    meetings: { meetings: 4, talk_share: 41, monologues: 2, questions: 17, hedges_per_100: 1.9, top_hedges: [{ word: "i think", count: 14 }],
      list: [{ created: "2026-10-06T10:00", title: "Weekly planning", talk_share: 38, monologues: 0, questions: 6, longest_s: 70 },
        { created: "2026-10-03T14:30", title: "Design review", talk_share: 57, monologues: 2, questions: 3, longest_s: 140 },
        { created: "2026-10-01T09:00", title: "Intro call", talk_share: 29, monologues: 0, questions: 8, longest_s: 45 }] },
    pace: { people: { dictations: Math.round(64 * k), wpm: 148, pauses: 22, in_range: 58 }, ai: { dictations: Math.round(150 * k), wpm: 163, pauses: 31, in_range: 35 },
      range: [130, 160], histogram: [0, 1, 1, 3, 5, 8, 12, 14, 9, 5, 3, 2, 1, 0, 0].map((n, i) => ({ from: 80 + 10 * i, dictations: n })) },
  };
}

const DEMO_LANG_NAMES = { en: "English", sv: "Swedish", es: "Spanish", el: "Greek", de: "German", fr: "French" };
function demoApi() {
  const demoLangs = (params.get("langs") || "en").split(",").filter((c) => DEMO_LANG_NAMES[c]);  // ?langs=en,sv,es
  const now = new Date();
  const iso = (mins) => new Date(now - mins * 60000).toISOString().slice(0, 19);
  const dl = { running: false, error: null, models: {} };  // the demo model download
  let settings = {
    values: { hotkey: "rctrl", mic: "Anker PowerConf", languages: demoLangs.join(","), extra_languages: demoLangs.filter((c) => !["en", "sv"].includes(c)), sounds: true, overlay: true, live_text: true, insights: params.get("insights") === "1", speech_feedback: false, unmute: true, startup: true,
      meet_mode: "prompt", meet_end: "10", meet_lang: demoLangs[0], on_demand: true, speakers: true, vocabulary: "Göteborg\npyannote", voice_commands: params.get("styles") === "1", self_corrections: false, command_mode: false, command_key: params.get("cmkey") || "e", voice_phrases: params.get("vp") === "1" ? { line: { en: ["new line", "next line"] }, enter: { en: ["send it", "press enter", "ship it"] } } : {}, screen_names: true, hold_to_talk: false, numpad_enter: false, voice_memory: true, update_check: true, auto_update: params.get("auto") === "1", theme: params.get("theme") || "system",
      export_dir: "C:/x/Downloads", export_default: true,
      snippets: [{ trigger: "my email", text: "alex@example.com" }], replacements: [{ heard: "poll request", write: "pull request" }],
      per_app_styles: params.get("styles") === "1",
      app_styles: [
        { kind: "terminal", label: "Terminal", apps: "Windows Terminal, PowerShell, iTerm2, Warp", capital: false, full_stop: false, commands: true },
        { kind: "chat", label: "Chat", apps: "Slack, Teams, WhatsApp, Claude, ChatGPT, and their sites", capital: true, full_stop: false, commands: true },
        { kind: "email", label: "Email", apps: "Outlook, Mail, Thunderbird, Gmail in a browser", capital: true, full_stop: true, commands: true },
        { kind: "other", label: "Everything else", apps: "Word, Notepad, a code editor, any other app", capital: true, full_stop: true, commands: true }] },
    options: {
      hotkeys: [{ value: "rctrl", label: "Right Ctrl (recommended)" }, { value: "scrolllock", label: "Scroll Lock" }, { value: "pause", label: "Pause" }, { value: "f13", label: "F13" }],
      mics: [{ value: "", label: DEFAULT_MIC }, { value: "Headset (Zone Vibe 100)", label: "Zone Vibe 100" }, { value: "Anker PowerConf", label: "Anker PowerConf C20" }],
      languages: [{ value: "en", label: "English" }, { value: "sv", label: "Swedish" }],
      base_languages: ["en", "sv"],
      all_languages: [{ value: "el", label: "Greek" }, { value: "de", label: "German" }, { value: "es", label: "Spanish" }, { value: "fr", label: "French" }],
      meet_modes: [{ value: "prompt", label: "Ask" }, { value: "auto", label: "Start by itself" }, { value: "off", label: "Don't detect" }],
      themes: [{ value: "system", label: MAC ? "Match macOS" : "Match Windows" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }],
      meet_ends: [{ value: "5", label: "5 seconds" }, { value: "10", label: "10 seconds" }, { value: "15", label: "15 seconds" }, { value: "30", label: "30 seconds" }, { value: "60", label: "1 minute" }, { value: "120", label: "2 minutes" }],
      meet_langs: [...demoLangs.map((c) => ({ value: c, label: DEMO_LANG_NAMES[c] })),  // only the user's (dictado-607)
        ...(demoLangs.length > 1 ? [{ value: demoLangs.join(","), label: demoLangs.map((c) => DEMO_LANG_NAMES[c]).join(" + ") }] : []), { value: "auto", label: "Detect" }],
    },
    can_startup: true,
    speakers_addon: params.get("addon") !== "0",
    auto_update_supported: !MAC,
    voice_command_list: [  // like window._voice_command_list: `builtin` per language; get_settings adds `phrases` (dictado-67v)
      { key: "paragraph", what: "Paragraph break", builtin: { en: ["new paragraph"], es: ["nuevo párrafo", "punto y aparte"], sv: ["nytt stycke"] } },
      { key: "line", what: "Line break", builtin: { en: ["new line"], es: ["nueva línea"], sv: ["ny rad"] } },
      { key: "enter", what: "Press Enter after the text (at the very end only)", builtin: { en: ["send it", "press enter"], es: ["envíalo", "enviar"], sv: ["skicka"] } }],
    correction_list: [{ what: "Drops the sentence before it", en: '"scratch that", "delete that", "strike that"', es: '"borra eso", "tacha eso"', sv: '"stryk det", "sudda det"', el: '"σβήσε το", "σβήσ\' το"' },
      { what: "Claude applies the correction", en: '"no wait", "sorry I mean", "sorry I meant", "correction"', es: '"no perdón", "no espera", "perdón quise decir", "corrijo"', sv: '"nej förlåt", "nej vänta", "förlåt jag menar", "rättelse"', el: '"όχι συγγνώμη", "όχι περίμενε", "συγγνώμη εννοώ"' }],
  };
  const history = [
    { ts: iso(2), text: "Can you check why the deploy failed last night and send me the logs before the standup? ", target: "WindowsTerminal.exe", pasted: true, id: "d1", audio: true },
    { ts: iso(14), text: "Sounds good, let's do Thursday at six. I'll bring the new shoes. ", target: "slack.exe", pasted: true, id: "d2", audio: true },
    { ts: iso(41), text: "Remind me to book the climbing gym for the weekend. ", target: "chrome.exe", pasted: false },
    { ts: iso(60 * 26), text: "The quick brown fox jumps over the lazy dog, then runs back to the barn. ", target: "notepad.exe", pasted: true },
    { ts: iso(60 * 27), text: "Send the draft to Quinta Vell before lunch, she has the numbers. ", target: "slack.exe", pasted: true, id: "d1b" },
  ];
  let t = 0;
  const S = (name, title, mins, status, extra = {}) => ({ name, title, created: iso(mins), status, lang: "sv", lang_name: "Swedish",
    duration_s: 1860, source: "meeting", pct: null, error: null, slow: false, ...extra });
  const rec = params.get("rec") !== "0";
  const sess = [
    ...(rec ? [S("2026-10-05_1400_retro", "Sprint retro", 12, "recording", { duration_s: null })] : []),
    S("2026-10-05_1130_podcast", "Super Easy Greek 12", 40, "running", { lang: "el", lang_name: "Greek", source: "import", pct: 42, duration_s: 412 }),
    S("2026-10-05_0915_planering", "Planering vecka 41", 60 * 5, "done", { summary: "done" }),
    S("2026-10-04_1600_kund", "Client call", 60 * 22, "done", { lang: "en", lang_name: "English", duration_s: 2710, speakers: "done", speaker_names: { "Speaker 2": "Ana" }, summary: "running" }),
    S("2026-10-03_1000_fallo", "Meeting", 60 * 50, "failed", { error: "CUDA out of memory", duration_s: 300 }),
  ];
  const SEGS = [
    { t0: 4.2, t1: 9.8, text: "Okej, ska vi köra? Jag tänkte att vi börjar med det som inte gick bra.", speaker: "Me" },
    { t0: 10.1, t1: 16.4, text: "Ja, deployen i torsdags tog nästan två timmar och ingen visste varför.", speaker: "Others" },
    { t0: 16.9, t1: 22.0, text: "Det var cachen. Vi glömde att rensa den efter migreringen.", speaker: "Others" },
    { t0: 22.6, t1: 28.3, text: "Bra, då skriver vi in det som en åtgärd till nästa sprint.", speaker: "Me" },
  ];
  const SEGS_MULTI = [
    { t0: 3.1, t1: 8.0, text: "Thanks for joining, everyone. Shall we start with the timeline?", speaker: "Me" },
    { t0: 8.6, t1: 15.2, text: "Yes. The data team needs two more weeks and one more poll request for the export.", speaker: "Speaker 1" },
    { t0: 15.8, t1: 21.0, text: "Two weeks works for us if the format stays the same.", speaker: "Speaker 2" },
    { t0: 21.4, t1: 26.9, text: "I can confirm that on Friday after I talk to legal.", speaker: "Speaker 3" },
    { t0: 27.3, t1: 31.0, text: "Great, I'll open the poll request and we lock the plan today.", speaker: "Me" },
  ];
  const SUMMARY = { kind: "job", checked: 2, total: 3,  // dictado-nl5: what summary.json holds, invented
    summary: "Retro om den långsamma deployen i torsdags: orsaken var cachen efter migreringen.",
    decisions: [{ text: "Rensa cachen efter varje migrering", at: "00:00:16", quote: "Vi glömde att rensa den efter migreringen", checked: true }],
    todos: [{ text: "Skriv in åtgärden i nästa sprint", at: "00:00:22", quote: "då skriver vi in det som en åtgärd", checked: true },
            { text: "Boka en genomgång med plattformsteamet", at: "00:00:25", quote: "vi bokar en genomgång med plattformsteamet", checked: false }],
    open_questions: [] };
  // dictado-xuu: the week's own to-dos by person, invented. ?todos=0: a week with none yet
  const day = (k) => { const d = new Date(now); d.setDate(now.getDate() - k); return d.toISOString().slice(0, 10); };
  const T = (text, k, session, title, extra = {}) => ({ text, at: "00:12:40", checked: true, session, title, day: day(k), key: `${session}/${text.toLowerCase()}`, done: false, ...extra });
  const weeks = [[
    { person: "Ana", items: [T("Send Ana the photos from the trip", 3, "2026-10-04_1600_kund", "Catch-up with Ana", { done: true }),
      T("Book the table for Friday at eight", 3, "2026-10-04_1600_kund", "Catch-up with Ana"),
      T("Ask the landlord about the bike room", 1, "2026-10-05_0915_planering", "Ana, weekend plans", { checked: false })] },
    { person: "Mia and Leo", items: [T("Buy the museum tickets for Saturday", 2, "2026-10-05_0915_planering", "Saturday plans"),
      T("Bring the board game", 2, "2026-10-05_0915_planering", "Saturday plans")] },
    { person: "Tom", items: [T("Read chapter 4 before the next lesson", 0, "2026-10-05_0915_planering", "Lesson 12"),
      T("Practise the past tense, ten sentences", 0, "2026-10-05_0915_planering", "Lesson 12")] },
  ], [
    { person: "Tom", items: [T("Write five sentences with the new words", 8, "2026-10-05_0915_planering", "Lesson 11", { done: true })] },
  ]];
  const todoDone = {};
  const weekOf = (back) => {
    const people = params.get("todos") === "0" ? [] : weeks[back] || [];
    const groups = people.map((g) => ({ ...g, items: g.items.map((i) => ({ ...i, done: todoDone[i.key] ?? i.done })) }));
    const all = groups.flatMap((g) => g.items);
    const mon = new Date(now); mon.setDate(now.getDate() - ((now.getDay() + 6) % 7) - 7 * back);
    const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
    return { start: mon.toISOString().slice(0, 10), end: sun.toISOString().slice(0, 10), people: groups, count: all.length,
      open: all.filter((i) => !i.done).length, calls: new Set(all.map((i) => i.title)).size, enabled: true, back };
  };
  let liveN = 2;
  const notes = { "2026-10-05_1400_retro": "- Is the export date firm?\n- Ask legal about the format" };
  const find = (n) => sess.find((s) => s.name === n);
  const segsNow = {}, segsBefore = {};  // dictado-9lo: the demo transcripts, which the Replace list changes
  const segsFor = (n) => segsNow[n] || (segsNow[n] = (n.endsWith("kund") ? SEGS_MULTI : SEGS).map((x) => ({ ...x })));
  const replaceIn = (n) => {  // like text.replace_counted: whole words, any case, longest first, real changes counted
    const rep = Object.fromEntries(settings.values.replacements.map((p) => [p.heard.toLowerCase().split(/\s+/).join(" "), p.write]));
    const keys = Object.keys(rep).sort((a, b) => b.length - a.length), counts = {};
    if (!keys.length) return { segs: segsFor(n), counts };
    const alt = keys.map((k) => k.split(" ").map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+")).join("|");
    const rx = new RegExp(`(?<![\\p{L}\\p{N}_])(${alt})(?![\\p{L}\\p{N}_])`, "giu");
    const segs = segsFor(n).map((x) => ({ ...x, text: x.text.replace(rx, (m) => {
      const k = m.toLowerCase().split(/\s+/).join(" ");
      if (m !== rep[k]) counts[k] = (counts[k] || 0) + 1;
      return rep[k];
    }) }));
    return { segs, counts, rep };
  };
  const total = (counts) => Object.values(counts).reduce((a, b) => a + b, 0);
  const mstate = () => ({ meeting: rec && find("2026-10-05_1400_retro")?.status === "recording"
    ? { name: "2026-10-05_1400_retro", app: "ms-teams", lang: "sv", started: iso(12), status: "recording" } : null, job: null, queue: [] });
  return {
    list_sessions: async (q) => ({ items: sess.filter((s) => !q || s.title.toLowerCase().includes(q.toLowerCase())), state: mstate() }),
    get_session: async (n) => ({ session: find(n), segments: find(n)?.status !== "done" ? [] : segsFor(n),
      exports: ["transcript.txt"], notes: notes[n] || "", summary: find(n)?.summary === "done" ? SUMMARY : null }),
    voices_info: async () => window.__noVoices ? { count: 0, names: [], on: true } : { count: 2, names: ["Ana", "Tom"], on: true },
    crashes: async () => (params.get("crash") === "1" ? { items: [{ name: "2026-10-06_140325", when: "2026-10-06 140325", exit: MAC ? "unknown" : "0xC0000005 (access violation)" }], gave_up: false } : { items: [], gave_up: false }),
    copy_crash_report: async () => ({ ok: true }), dismiss_crash: async () => ({ ok: true }),
    update_notice: async () => {  // update=1 offer, dl downloading, ready, failed (dictado-nmo)
      const u = params.get("update");
      if (!u || window.__updDismissed) return {};
      const n = { version: "1.18.0", url: "https://github.com/ErikBros/ecoscribe/releases/tag/v1.18.0" };
      if (MAC) return n;
      const install = window.__updInstall ? "downloading" : { 1: "offer", dl: "downloading", ready: "ready", failed: "failed" }[u] || "offer";
      return { ...n, install, ...(install === "downloading" ? { pct: 42 } : {}) };
    },
    install_update_when_idle: async (v) => { window.__updInstall = v; return { ok: true }; },
    open_update: async () => { window.__updOpened = true; return { ok: true }; },
    dismiss_update: async (v) => { window.__updDismissed = v; return { ok: true }; },
    copy_debug_info: async () => ({ ok: true }), open_logs_folder: async () => ({ ok: true }),
    save_export: async (name, fmt) => { window.__exported = fmt; return { ok: true, path: "C:/x/Downloads/t." + fmt, name: "t." + fmt, folder: "Downloads" }; },
    show_export: async (p) => { window.__revealed = p; return { ok: true }; },
    pick_export_dir: async () => ({ ok: true, export_dir: "D:/Transcripts", export_default: false }),
    set_export_dir: async (p) => ({ ok: true, export_dir: p || "C:/x/Downloads", export_default: !p }),
    google_calendar: async () => ({ connected: !!window.__gcal, client: true }),
    connect_google: async () => { window.__gcal = true; return { ok: true, today: 3, now: "Weekly sync" }; },
    disconnect_google: async () => { window.__gcal = false; return { ok: true }; },
    test_calendar: async (u) => (u ? { ok: true, today: 4, now: "Sprint retro" } : { ok: false, error: "Paste the secret address in iCal format first." }),
    forget_voices: async () => { window.__noVoices = true; return { ok: true }; },
    claude_app: async () => ({ connected: !!window.__claude, frozen: true }),
    connect_claude_app: async () => { window.__claude = true; return { ok: true, files: ["C:/x/claude_desktop_config.json"] }; },
    save_notes: async (n, text) => { notes[n] = text; window.__notes = notes; return { ok: true }; },
    get_live: async (n, since) => {  // a meeting that keeps talking: the 4 lines again, later on
      liveN += 1;
      const lines = [];
      for (let i = since; i < liveN; i++) { const x = SEGS[i % SEGS.length], k = Math.floor(i / SEGS.length) * 30; lines.push({ ...x, t0: x.t0 + k, t1: x.t1 + k }); }
      return { lines, next: Math.max(since, liveN), session: find(n), notes: notes[n] || "" };
    },
    meetings_state: async () => mstate(),
    start_meeting: async () => ({ ok: true, dir: "C:/x/2026-10-05_1400_retro" }),
    set_meeting_lang: async (lang) => { const s = find("2026-10-05_1400_retro"); if (s) s.lang = lang; window.__lang = lang; return { ok: true }; },
    stop_meeting: async () => { const s = find("2026-10-05_1400_retro"); if (s) s.status = "finalizing"; return { ok: true }; },
    import_files: async (paths) => { window.__imported = paths; return { ok: true, queued: paths.length }; },
    pick_files: async () => ({ paths: [] }),
    rename_session: async (n, title) => { find(n).title = title; return { ok: true }; },
    rename_speaker: async (n, label, name) => { const s = find(n); s.speaker_names = { ...(s.speaker_names || {}) };
      if (name) s.speaker_names[label] = name; else delete s.speaker_names[label]; window.__renamed = [label, name]; return { ok: true, names: s.speaker_names }; },
    delete_session: async (n) => { sess.splice(sess.indexOf(find(n)), 1); return { ok: true }; },
    open_folder: async () => ({ ok: true }),
    replace_preview: async (n) => {
      const { counts, rep } = replaceIn(n);
      const pairs = Object.entries(counts).map(([heard, k]) => ({ heard, write: rep[heard], n: k })).sort((a, b) => b.n - a.n);
      return { ok: true, places: total(counts), pairs, empty: !settings.values.replacements.length, undo: !!segsBefore[n] };
    },
    apply_replacements: async (n) => {
      if (!settings.values.replacements.length) return { ok: false, error: "Your Replace list is empty: add pairs in Settings › Languages and words." };
      const { segs, counts } = replaceIn(n), places = total(counts);
      if (places) { segsBefore[n] = segsFor(n); segsNow[n] = segs; }
      window.__replaced = places;
      return { ok: true, places };
    },
    undo_replacements: async (n) => {
      if (!segsBefore[n]) return { ok: false, error: "There's nothing to undo." };
      segsNow[n] = segsBefore[n]; delete segsBefore[n]; window.__undone = n;
      return { ok: true };
    },
    copy_transcript: async () => ({ ok: true }),
    week_todos: async (back) => weekOf(back || 0),
    todo_done: async (key, done) => { todoDone[key] = !!done; window.__todoDone = [key, !!done]; return { ok: true }; },
    email_participants: async (name, how) => {  // ?noguests=1: a call with no invite and no calendar (dictado-qxr)
      window.__emailed = name; window.__emailHow = how || "";
      if (how === "calendar" || (how !== "draft" && params.get("noguests") === "1"))
        return { ok: true, to: [], via: "calendar", day: (find(name)?.created || "2026-10-05").slice(0, 10), chars: 9000 };
      return { ok: true, to: params.get("noguests") === "1" ? [] : ["ana@example.com", "bo@example.com"], inline: false, chars: 9000, via: "draft" };
    },
    get_status: async () => (params.get("state") === "stopped" ? { state: "stopped", alive: false, version: "1.1.0" }
      : { state: params.get("state") || "ready", alive: true, device: "cuda", model: "large-v3-turbo", mic: "Microphone (Anker PowerConf C20", languages: settings.values.languages.split(","), hotkey: "rctrl", version: "1.1.0",
          ...(params.get("gpurt") === "downloading" ? { device: "cpu", gpu_runtime: { state: "downloading", version: 1, done: 214e6, total: 476e6 } }
            : params.get("gpurt") === "failed" ? { device: "cpu", gpu_runtime: { state: "failed", version: 1, error: "no connection", retry_s: 300 } } : {}) }),
    start_app: async () => ({ ok: true }),
    restart_app: async () => ({ ok: true }),
    get_settings: async () => {
      const out = JSON.parse(JSON.stringify(settings));
      for (const r of out.voice_command_list) {  // the user's phrases over the built-in ones, as the window gets them
        r.phrases = { ...r.builtin, ...((out.values.voice_phrases || {})[r.key] || {}) };
        for (const [l, ps] of Object.entries(r.phrases)) if (ps.length) r[l] = ps.map((p) => `"${p}"`).join(", ");
      }
      return out;
    },
    check_command_key: async (v, hk) => {  // dictado-a1d, like window.check_command_key
      const k = String(v).toLowerCase().replace(`${hk}+`, "");
      if (/^[a-z0-9]$/.test(k) && !hk.includes("+") && !"lr".includes(k)) return { ok: true, value: k, label: `${hotkeyLabel(hk)} + ${k.toUpperCase()}` };
      if (/^(ctrl|alt|shift|win)\+/.test(k) && k !== hk && !/^ctrl\+[cvxzyasfpwnt]$/.test(k)) return { ok: true, value: k, label: hotkeyLabel(k) };
      return { ok: false, error: `${hotkeyLabel(k)} can't start Command mode: hold ${hotkeyLabel(hk)} and press a letter, or press a combo like Ctrl+Shift+E` };
    },
    check_hotkey: async (v) => (/^(ctrl\+[cvxzyasfpwnt]|alt\+tab|[a-z0-9])$/.test(v) ? { ok: false, error: `${v} is not allowed` }
      : { ok: true, value: v, label: hotkeyLabel(v) }),
    save_settings: async (v) => { Object.assign(settings.values, v); return { ok: true, restarting: true }; },
    mic_test_start: async () => ({ device: "Microphone (Anker PowerConf C20", fell_back: false }),
    mic_test_level: async () => { t += 1; return Math.abs(Math.sin(t / 3)) * 0.08; },
    mic_test_stop: async () => ({ ok: true }),
    get_history: async (limit, q) => {
      const items = history.filter((r) => !q || r.text.toLowerCase().includes(q.toLowerCase()));
      return { items, stats: { total: 312, total_words: 4210, today_words: 152 } };
    },
    copy_text: async () => ({ ok: true }),
    get_insights: async (days) => { const d = demoInsights(days); if (window.__wpm) d.totals.typing_wpm = window.__wpm; return d; },
    set_typing_wpm: async (n) => { window.__wpm = Math.max(10, Math.min(200, Math.round(n) || 40)); return { ok: true, typing_wpm: window.__wpm }; },
    delete_dictation: async (id, ts) => {
      const i = history.findIndex((x) => (id ? x.id === id : x.ts === ts));
      if (i >= 0) history.splice(i, 1);
      window.__deletedDictation = id || ts;
      return { ok: true, gone: i >= 0 };
    },
    edit_dictation: async (id, ts, text) => {  // dictado-1ph: the demo learns the one name it knows
      const r = history.find((x) => (id ? x.id === id : x.ts === ts));
      if (!r) return { ok: false, error: "That dictation isn't in the history any more." };
      const before = r.text; r.text = text; window.__edited = text;
      return { ok: true, text, learn: /Quintavelle/.test(text) && !/Quintavelle/.test(before) ? [{ kind: "word", write: "Quintavelle" }] : [] };
    },
    learn_word: async (kind, write, heard) => { window.__learned = [kind, write, heard || ""]; return { ok: true }; },
    add_word: async (w) => { settings.values.vocabulary += "\n" + w; window.__added = w; return { ok: true }; },
    insights_for_claude: async () => ({ ok: true, chars: 5120 }),
    clear_history: async () => { history.length = 0; return { ok: true }; },
    open_log: async () => ({ ok: true }),
    get_welcome: async () => ({ done: params.get("welcome") !== "1" }),
    get_theme: async () => ({ theme: settings.values.theme }),
    window_theme: async () => ({ ok: true }),
    finish_welcome: async () => ({ ok: true }),
    setup_info: async (langs) => {
      const big = (langs || "").split(",").some((c) => c && !["en", "es", "de", "fr"].includes(c));
      return { models: [
        { name: "large-v3-turbo", label: "Fast", use: "For your English; finds the language in meetings and files", size: 1.62e9, required: !big, ready: params.get("models") === "ready" },
        { name: "Systran/faster-whisper-large-v3", label: "Most accurate", use: "Languages the fast one isn't good at; meetings and files in them", size: 3.09e9, required: big, ready: false }],
      permissions: MAC ? [{ key: "microphone", label: "Microphone", granted: true }, { key: "accessibility", label: "Accessibility", granted: false },
        { key: "input", label: "Input Monitoring", granted: false, ask: true }] : [] };
    },
    setup_models_start: async (names) => {
      dl.models = Object.fromEntries(names.map((n) => [n, { done: 0, total: n.includes("turbo") ? 1.62e9 : 3.09e9, ready: false }]));
      dl.running = true; dl.error = null;
      return JSON.parse(JSON.stringify(dl));
    },
    setup_models_progress: async () => {  // each poll moves the demo download along
      for (const m of Object.values(dl.models)) if (!m.ready && dl.running) { m.done = Math.min(m.total, m.done + m.total / 4); m.ready = m.done >= m.total; break; }
      dl.running = Object.values(dl.models).some((m) => !m.ready);
      return JSON.parse(JSON.stringify(dl));
    },
    open_permission: async (k) => { window.__perm = k; return { ok: true }; },
    retry_dictation: async (id, lang) => {  // the demo "hears" it again in the asked language
      const r = history.find((x) => x.id === id);
      if (!r) return { ok: false, error: "That dictation's audio isn't kept any more." };
      r.text = lang === "sv" ? "Kan du kolla varför deployen misslyckades i går? " : r.text.replace("Can you", "Could you");
      r.lang = lang || "en"; r.retried = true;
      return { ok: true, text: r.text, lang: r.lang };
    },
    models_info: async () => ({ models: [
      { name: "large-v3-turbo", label: "Fast", use: "For your English; finds the language in meetings and files", size: 1.62e9, required: true, ready: !window.__deleted, disk: 1.62e9 },
      { name: "Systran/faster-whisper-large-v3", label: "Most accurate", use: "Languages the fast one isn't good at; meetings and files in them", size: 3.09e9, required: false,
        ready: !!(dl.models["Systran/faster-whisper-large-v3"] || {}).ready, disk: 3.09e9 }] }),
    delete_model: async (name) => { window.__deleted = name; return { ok: true }; },
  };
}

let api = null;
function getApi() {
  if (params.get("demo") === "1" || !window.pywebview) return demoApi();
  return window.pywebview.api;
}

/* ---------------------------------------------------------------- helpers */
function toast(msg, ms = 2600) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), ms);
}
const UNDO_MS = Number(params.get("undo_ms")) || 5000;  // smoke tests wait less
function toastUndo(msg, onUndo, ms = UNDO_MS) {  // a toast with Undo (dictado-vfo); false when it times out
  return toastAction(msg, "Undo", onUndo, ms);
}
function toastAction(msg, label, onClick, ms) {  // a toast with one button: true when it was clicked
  const el = $("#toast");
  el.textContent = msg + " ";
  const b = document.createElement("button");
  b.type = "button"; b.className = "toast-btn"; b.textContent = label;
  el.append(b);
  el.hidden = false;
  clearTimeout(toast._t);
  return new Promise((done) => {
    b.onclick = () => { clearTimeout(toast._t); el.hidden = true; onClick(); done(true); };
    toast._t = setTimeout(() => { el.hidden = true; done(false); }, ms);
  });
}
async function download(name, fmt) {  // dictado-yq9: say where it went, with Open folder
  const out = await api.save_export(name, fmt);
  if (!out.ok) { toast(out.error || "Couldn't export."); return; }
  toastAction(`In ${out.folder}: ${out.name}`, "Open folder", () => api.show_export(out.path), 6000);
}
function prettyMic(n) {
  const m = /^[^(]*\((.+?)\)?$/.exec(n || "");
  return m ? m[1].trim() : (n || "");
}
function fmtNum(n) { return Number(n || 0).toLocaleString("en-GB"); }
function appName(exe) {
  const m = { "windowsterminal.exe": "Terminal", "slack.exe": "Slack", "chrome.exe": "Chrome", "msedge.exe": "Edge",
    "code.exe": "VS Code", "teams.exe": "Teams", "ms-teams.exe": "Teams", "notepad.exe": "Notepad", "firefox.exe": "Firefox",
    "obsidian.exe": "Obsidian", "outlook.exe": "Outlook", "olk.exe": "Outlook", "python.exe": "Python", "pythonw.exe": "Python",
    "explorer.exe": "File Explorer", "winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint",
    "whatsapp.exe": "WhatsApp", "whatsapp.root.exe": "WhatsApp", "chatgpt.exe": "ChatGPT", "vlc.exe": "VLC" };
  if (!exe) return "";
  const known = m[exe.toLowerCase()];
  if (known) return known;
  // anything else as words: "SnippingTool.exe" -> "Snipping Tool", "discord" -> "Discord" (dictado-d4h)
  const base = exe.replace(/\.exe$/i, "").replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").trim();
  return base.charAt(0).toUpperCase() + base.slice(1);
}
function when(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d)) return "";
  const today = new Date();
  const hm = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `Today, ${hm}`;
  const y = new Date(today); y.setDate(today.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Yesterday, ${hm}`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + `, ${hm}`;
}
async function copy(text, btn) {
  await api.copy_text(text);
  if (btn) {
    const old = btn.textContent;
    btn.textContent = "Copied";
    btn.classList.add("done");
    setTimeout(() => { btn.textContent = old; btn.classList.remove("done"); }, 1400);
  }
}

/* ---------------------------------------------------------------- navigation */
const PAGES = ["inicio", "reuniones", "historial", "insights", "ajustes"];
let current = null;
async function show(page) {
  let card = null;  // "ajustes/claude": Settings, scrolled to that card, which lights up (dictado-1b7)
  if (page && page.startsWith("ajustes/")) { card = page.slice("ajustes/".length); page = "ajustes"; }
  if (page && page.startsWith("inicio/")) { card = page.slice("inicio/".length); page = "inicio"; }  // "inicio/todos" (dictado-xuu)
  if (page && page.startsWith("reuniones/")) { r.open = page.slice("reuniones/".length); r.next = 0; r.status = null; $("#r-segs").innerHTML = ""; page = "reuniones"; }
  if (!PAGES.includes(page)) page = "inicio";
  if (current === "ajustes" && page !== "ajustes") await stopMicTest();
  current = page;
  $("#side-status").hidden = page === "inicio";  // Home's hero says it (dictado-9jf)
  for (const p of PAGES) $(`#page-${p}`).hidden = p !== page;
  for (const b of $$(".nav-item")) b.classList.toggle("active", b.dataset.page === page);
  if (page === "inicio") await renderInicio();
  if (page === "reuniones") await renderReuniones();
  if (page === "historial") await renderHistory();
  if (page === "insights") await renderInsights();
  if (page === "ajustes") await renderSettings();
  const el = card && $(`[data-card="${card}"]`);
  if (el) {
    if (el.dataset.sec && window.__secShow) window.__secShow(el.dataset.sec);  // its Settings tab
    el.scrollIntoView?.({ block: "start" });
    el.classList.remove("card-lit"); void el.offsetWidth; el.classList.add("card-lit");
  }
}

/* ---------------------------------------------------------------- insights (dictado-3je) */
let iDays = null;
const SVGNS = "http://www.w3.org/2000/svg";
const langName = (c) => {
  if (c === "mixed") return "Mixed";
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(c); } catch { return c; }
};
function svgEl(tag, attrs) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  return e;
}
function tip(e, lines) {
  const t = $("#i-tip");
  if (!lines) { t.hidden = true; return; }
  t.textContent = "";
  const b = document.createElement("strong"); b.textContent = lines[0]; t.append(b);
  if (lines[1]) t.append(document.createTextNode(" " + lines[1]));
  t.hidden = false;
  const r = e.target.getBoundingClientRect();
  const x = e.clientX || r.left + r.width / 2, y = e.clientY || r.top;
  t.style.left = `${Math.min(window.innerWidth - t.offsetWidth - 8, x + 12)}px`;
  t.style.top = `${y - t.offsetHeight - 10}px`;
}
/* Columns, one series: thin bars (<= 24 px), 4 px rounded tops square at the baseline, a hairline
   baseline, a few tick labels, and a hover / focus readout per column (dataviz). */
function columns(el, data, tickEvery) {
  el.textContent = "";
  const W = 320, H = 118, top = 6, base = 96, slot = W / data.length;
  const bw = Math.min(24, slot * 0.62), max = Math.max(1, ...data.map((d) => d.value));
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": el.dataset.label || "" });
  data.forEach((d, i) => {
    const x = i * slot + (slot - bw) / 2, h = d.value ? Math.max(2, (base - top) * d.value / max) : 0;
    const hit = svgEl("rect", { x: i * slot, y: top, width: slot, height: base - top, class: "hit", tabindex: 0 });
    const show = (e) => tip(e, [d.tipValue, d.tipLabel]);
    hit.addEventListener("pointermove", show); hit.addEventListener("focus", show);
    hit.addEventListener("pointerleave", () => tip(null)); hit.addEventListener("blur", () => tip(null));
    svg.append(hit);
    if (h > 0) {
      const r = Math.min(4, bw / 2, h);
      svg.append(svgEl("path", { class: d.dim ? "bar dim" : "bar",
        d: `M${x},${base}V${base - h + r}Q${x},${base - h} ${x + r},${base - h}H${x + bw - r}Q${x + bw},${base - h} ${x + bw},${base - h + r}V${base}Z` }));
    } else svg.append(svgEl("g"));
    if (tickEvery(i)) {
      const t = svgEl("text", { x: i * slot + slot / 2, y: base + 16, "text-anchor": "middle", class: "tick" });
      t.textContent = d.label; svg.append(t);
    }
  });
  svg.append(svgEl("line", { x1: 0, x2: W, y1: base + 0.5, y2: base + 0.5, class: "base" }));
  el.append(svg);
}
function hbars(el, items, scale) {  // scale: the full bar's value (100 for a share); default the biggest
  el.textContent = "";
  const box = document.createElement("div"); box.className = "i-hbars";
  const max = scale || Math.max(1, ...items.map((x) => x.value));
  for (const it of items) {
    const row = document.createElement("div"); row.className = "i-hbar";
    const name = document.createElement("span"); name.className = "i-hbar-name"; name.textContent = it.name; name.title = it.name;
    const track = document.createElement("span"); track.className = "i-hbar-track";
    const fill = document.createElement("span"); fill.className = "i-hbar-fill"; fill.style.display = "block";
    fill.style.width = `${Math.max(1.5, 100 * it.value / max)}%`; track.append(fill);
    const val = document.createElement("span"); val.className = "i-hbar-val"; val.textContent = it.label;
    row.append(name, track, val); box.append(row);
  }
  el.append(box);
}
function iChip(text, count, title) {
  const c = document.createElement("span"); c.className = "i-chip";
  c.append(document.createTextNode(text));
  if (count != null) { const b = document.createElement("b"); b.textContent = `×${count}`; c.append(b); }
  if (title) c.title = title;
  return c;
}
function renderMarkers(m) {  // dictado-9jc.3: fillers and hedges in messages to people
  const has = !!(m && m.words);
  $("#i-markers-empty").hidden = has; $("#i-markers-body").hidden = !has;
  if (!has) return;
  $("#i-hedges").textContent = String(m.hedges_per_100);
  $("#i-fillers").textContent = String(m.fillers_per_100);
  const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const n = m.weeks.length;
  columns($("#i-markers-weeks"), m.weeks.map((w, i) => {
    const v = w.hedges_per_100 == null ? 0 : w.hedges_per_100 + w.fillers_per_100;
    return { value: v, dim: i !== n - 1, label: i === n - 1 ? "This week" : day(w.week),
      tipValue: w.hedges_per_100 == null ? "Too few words to say" : `${w.hedges_per_100} hedges · ${w.fillers_per_100} fillers per 100`,
      tipLabel: `week of ${day(w.week)}` };
  }), (i) => i === 0 || i === n - 1);
  const chips = $("#i-top-hedges"); chips.textContent = "";
  for (const h of m.top_hedges) chips.append(iChip(h.word, h.count));
  if (!m.top_hedges.length) chips.append(iChip("None so far"));
}
function renderMeetings(m) {  // dictado-9jc.5
  const has = !!(m && m.meetings);
  $("#i-meet-empty").hidden = has; $("#i-meet-body").hidden = !has;
  if (!has) return;
  $("#i-meet-share").textContent = `${m.talk_share}%`;
  $("#i-meet-mono").textContent = fmtNum(m.monologues);
  $("#i-meet-q").textContent = fmtNum(m.questions);
  $("#i-meet-hedges").textContent = String(m.hedges_per_100);
  hbars($("#i-meet-list"), m.list.map((x) => {
    const extra = [x.monologues ? `${x.monologues} long ${x.monologues === 1 ? "turn" : "turns"}` : "",
      x.questions ? `${x.questions} ${x.questions === 1 ? "question" : "questions"}` : ""].filter(Boolean);
    return { name: x.title, value: x.talk_share, label: [`${x.talk_share}%`, ...extra].join(" · ") };
  }), 100);
}
function renderPace(p) {  // dictado-9jc.4
  const has = !!(p && (p.people || p.ai));
  $("#i-pace-empty").hidden = has; $("#i-pace-body").hidden = !has;
  if (!has) return;
  const rows = $("#i-pace-rows"); rows.textContent = "";
  for (const [key, who] of [["people", "to people"], ["ai", "to AI apps"]]) {
    const g = p[key]; if (!g) continue;
    const row = document.createElement("div"); row.className = "i-habit";
    const num = document.createElement("span"); num.className = "i-habit-num"; num.textContent = String(g.wpm);
    const lab = document.createElement("span"); lab.className = "muted";
    lab.textContent = `words a minute ${who}, ${g.pauses}% of the time pausing (${fmtNum(g.dictations)} ${g.dictations === 1 ? "dictation" : "dictations"})`;
    row.append(num, lab); rows.append(row);
  }
  const [lo, hi] = p.range, last = p.histogram.length - 1;
  $("#i-pace-hist").hidden = !p.histogram.length;
  columns($("#i-pace-hist"), p.histogram.map((b, i) => {
    const name = i === 0 ? `under ${b.from + 10}` : i === last ? `${b.from}+` : `${b.from}-${b.from + 9}`;
    return { value: b.dictations, dim: b.from < lo || b.from >= hi, label: i === last ? `${b.from}+` : String(b.from),
      tipValue: `${b.dictations} ${b.dictations === 1 ? "message" : "messages"}`, tipLabel: `${name} words a minute` };
  }), (i) => i === 0 || i === last || p.histogram[i].from === lo || p.histogram[i].from === hi);
}
function renderClarity(c) {  // dictado-9jc.1
  const has = !!(c && c.dictations);
  $("#i-clarity-empty").hidden = has; $("#i-clarity-body").hidden = !has;
  if (!has) return;
  const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  $("#i-clarity").textContent = `${c.clarity}%`;
  $("#i-clarity-how").textContent = `of your words heard clearly, over ${fmtNum(c.dictations)} ${c.dictations === 1 ? "dictation" : "dictations"} since ${day(c.since)}`;
  const n = c.weeks.length;
  columns($("#i-clarity-weeks"), c.weeks.map((w, i) => ({ value: w.clarity || 0, dim: i !== n - 1,
    label: i === n - 1 ? "This week" : day(w.week),
    tipValue: w.clarity == null ? "No dictations" : `${w.clarity}% heard clearly`, tipLabel: `week of ${day(w.week)}` })),
    (i) => i === 0 || i === n - 1);
  const box = $("#i-unsure"); box.textContent = "";
  for (const l of c.words) {
    const row = document.createElement("div"); row.className = "i-habit";
    const lab = document.createElement("span"); lab.className = "muted"; lab.textContent = langName(l.lang);
    const chips = document.createElement("span"); chips.className = "i-chips";
    for (const w of l.words) chips.append(iChip(w.word, w.unsure, `Unsure ${w.unsure} of the ${w.said} times you said it`));
    row.append(lab, chips); box.append(row);
  }
  if (!c.words.length) box.textContent = "None so far: every word came through clearly.";
}
function iWeek(m) {  // the one-line "this week" from the hedges per week (dictado-6oe.6)
  const box = $("#i-week");
  const weeks = ((m && m.weeks) || []).filter((w) => w.hedges_per_100 != null);
  box.hidden = weeks.length < 2;
  if (box.hidden) return;
  const [prev, last] = weeks.slice(-2), a = prev.hedges_per_100, b = last.hedges_per_100;
  const top = (m.top_hedges || [])[0];
  const dir = b < a ? "less" : b > a ? "more" : "as much as before";
  $("#i-week-text").innerHTML = `<b>This week:</b> you hedged ${dir === "as much as before" ? dir : dir + ` in messages to people, ${a} → ${b} per 100 words`}.`
    + (top ? ` <span></span>` : "");
  if (top) $("#i-week-text span").textContent = `"${top.word}" is still the one you use most.`;
}
async function renderInsights() {
  for (const b of $$("#i-range .seg")) b.setAttribute("aria-checked", String((b.dataset.days || null) === iDays));
  const d = await api.get_insights(iDays ? Number(iDays) : null);
  const t = d.totals;
  $("#i-empty").hidden = t.dictations > 0;
  $("#i-body").hidden = t.dictations === 0;
  if (!t.dictations) return;
  $("#i-saved").textContent = fmtDur(t.saved_s);
  $("#i-saved-how").textContent = t.wpm
    ? `You talk at ${t.wpm} words a minute and type at ${t.typing_wpm}. ${fmtNum(t.words)} words took ${fmtDur(t.talk_s)} to say.`
    : `Typing ${fmtNum(t.words)} words at ${t.typing_wpm} a minute takes longer than saying them.`;
  const wpmIn = $("#i-wpm");  // dictado-d8e: measured against the user's own typing speed
  if (document.activeElement !== wpmIn) wpmIn.value = String(t.typing_wpm);
  wpmIn.onchange = async () => {
    const res = await api.set_typing_wpm(Number(wpmIn.value));
    if (!res.ok) { toast(res.error); return; }
    wpmIn.value = String(res.typing_wpm);
    renderInsights();
  };
  $("#i-words").textContent = fmtNum(t.words);
  $("#i-dictations").textContent = fmtNum(t.dictations);
  $("#i-talk").textContent = fmtDur(t.talk_s);
  $("#i-streak").textContent = `${d.rhythm.streak} ${d.rhythm.streak === 1 ? "day" : "days"}`;
  const peak = Math.max(...d.rhythm.hours);
  columns($("#i-hours"), d.rhythm.hours.map((v, h) => ({ value: v, label: String(h).padStart(2, "0"), dim: v < peak,
    tipValue: `${v} ${v === 1 ? "dictation" : "dictations"}`, tipLabel: `${String(h).padStart(2, "0")}:00-${String((h + 1) % 24).padStart(2, "0")}:00` })),
    (i) => i % 6 === 0);
  const busy = d.rhythm.hours.indexOf(peak), hh = (h) => `${String(h % 24).padStart(2, "0")}:00`;  // dictado-7qo
  $("#i-hours-note").textContent = `The highlighted bar is your busiest hour, ${hh(busy)}-${hh(busy + 1)}.`;
  const n = d.rhythm.days.length;
  columns($("#i-days"), d.rhythm.days.map((x, i) => {
    const dt = new Date(x.date + "T12:00:00");
    return { value: x.words, dim: i !== n - 1,
      label: i === n - 1 ? "Today" : dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
      tipValue: `${fmtNum(x.words)} words`, tipLabel: dt.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) };
  }), (i) => i === 0 || i === n - 1 || i === Math.floor((n - 1) / 2));
  const lw = d.languages.reduce((a, x) => a + x.words, 0) || 1;
  hbars($("#i-langs"), d.languages.map((x) => ({ name: langName(x.lang), value: x.words,
    label: `${fmtNum(x.words)} ${x.words === 1 ? "word" : "words"} · ${Math.round(100 * x.words / lw)}%` })));
  hbars($("#i-apps"), d.apps.map((x) => ({ name: appName(x.app), value: x.dictations,
    label: `${fmtNum(x.dictations)} ${x.dictations === 1 ? "dictation" : "dictations"}` })));
  const hab = $("#i-habits"); hab.textContent = "";
  for (const h of d.habits) {
    const row = document.createElement("div"); row.className = "i-habit";
    const num = document.createElement("span"); num.className = "i-habit-num"; num.textContent = String(h.per_100);
    const lab = document.createElement("span"); lab.className = "muted"; lab.textContent = `filler words per 100 in ${langName(h.lang)}`;
    const chips = document.createElement("span"); chips.className = "i-chips";
    for (const f of h.top) chips.append(iChip(f.word, f.count));
    row.append(num, lab, chips); hab.append(row);
  }
  if (!d.habits.length) hab.textContent = "A few more dictations and your filler words show up here.";
  renderClarity(d.clarity);
  renderMarkers(d.markers);
  renderPace(d.pace);
  renderMeetings(d.meetings);
  iWeek(d.markers);
  const ph = $("#i-phrases"); ph.textContent = "";
  for (const p of d.phrases) ph.append(iChip(p.phrase, p.count));
  if (!d.phrases.length) ph.append(iChip("Nothing repeated three times yet"));
  const sl = $("#i-suggest"); sl.textContent = "";
  $("#i-suggest-card").hidden = !d.suggestions.length;
  for (const s of d.suggestions) {
    const li = document.createElement("li");
    const heard = document.createElement("span");
    heard.textContent = s.heard === s.suggest ? `“${s.heard}”, ${s.count} times` : `Heard “${s.heard}” ${s.count} times`;
    const input = document.createElement("input"); input.value = s.suggest; input.setAttribute("aria-label", `Add ${s.suggest} to Your words`);
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "btn btn-ghost btn-sm"; btn.textContent = "Add";
    btn.onclick = async () => {
      const r = await api.add_word(input.value);
      if (r.ok) { li.remove(); toast(`Added “${input.value.trim()}” to Your words.`); }
    };
    li.append(heard, input, btn); sl.append(li);
  }
  $("#i-foot").textContent = `Worked out on this computer from your dictation history${d.first ? ` since ${new Date(d.first + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long" })}` : ""}; nothing is sent anywhere.`;
}

/* ---------------------------------------------------------------- status */
const STATE_TEXT = {
  ready: ["Running", "Ready to dictate"],
  loading: ["Loading", "Loading the model…"],
  restarting: ["Restarting", "Applying your settings…"],
  error: ["Error", "Something failed at startup"],
  stopped: ["Stopped", "Ecoscribe isn't running"],
};
// what the hero says under the title while dictation can't start (dictado-9jf: no "tap the key" then)
const STATE_HOW = {
  loading: "The speech model is loading. Dictation works in a few seconds.",
  restarting: "Ecoscribe restarts with your new settings. Back in a few seconds.",
  error: "Open the log to see what failed, then start Ecoscribe again from the tray.",
  stopped: "Start it to dictate again. Your settings and history are kept.",
};
let lastStatus = null;
async function refreshStatus() {
  let s;
  try { s = await api.get_status(); } catch (e) { return; }
  lastStatus = s;
  const state = STATE_TEXT[s.state] ? s.state : "loading";
  const [short, long] = STATE_TEXT[state];
  const side = $("#side-status");
  side.dataset.state = state;
  $(".side-status-text", side).textContent = state === "ready" ? `Ready · ${hotkeyLabel(s.hotkey)}` : short;
  side.hidden = current === "inicio";  // Home's hero says it: status once per screen (dictado-9jf)
  $("#ver").textContent = `v${s.version || ""}`;
  paintFacts(s, state);  // the sidebar card, on every page (dictado-6oe.3)
  if (current === "inicio") paintHero(s, state, short, long);
}
function paintFacts(s, state) {
  // stopped: what it doesn't know yet, said once instead of three dashes (dictado-9jf)
  const off = state === "stopped" && !s.mic && !s.device;
  $(".side-facts").hidden = off;
  $("#side-off").hidden = !off;
  const none = "…";
  $("#fact-mic").textContent = s.mic ? (s.fell_back ? DEFAULT_MIC : prettyMic(s.mic)) : none;
  $("#fact-mic").title = s.mic || "";
  const langs = s.languages || [];
  $("#fact-lang").textContent = !langs.length ? none
    : langs.length === 1 ? (DICT_LANGS[langs[0]] || langs[0]) : langs.map((l) => l.toUpperCase()).join(" · ") + ", detected";
  $("#fact-lang").title = langs.map((l) => DICT_LANGS[l] || l).join(", ");
  $("#fact-engine").textContent = engineFact(s, none);
  $("#fact-engine").title = engineTitle(s.gpu_runtime);
}
// dictado-7e1: while the GPU part (the CUDA libraries) downloads once, dictation runs on the CPU
function engineFact(s, none) {
  const rt = s.gpu_runtime || {};
  if (rt.state === "downloading") return `CPU · getting GPU ${rt.total ? Math.floor((100 * rt.done) / rt.total) : 0}%`;
  if (rt.state === "failed") return "CPU · GPU download failed";
  return s.device ? (s.device === "cuda" || s.device === "mlx" ? "GPU · fast" : "CPU · slow") : none;
}
function engineTitle(rt) {
  if (!rt) return "";
  const mb = (n) => `${Math.round((n || 0) / 1e6)} MB`;
  if (rt.state === "downloading") return `Downloading the GPU part once: ${mb(rt.done)} of ${mb(rt.total)}`;
  if (rt.state === "failed") return `GPU part not downloaded: ${rt.error || "unknown error"}. Ecoscribe tries again by itself.`;
  return "";
}
function paintHero(s, state, short, long) {
  $(".hero").dataset.state = state;
  $("#hero-title").textContent = long;
  const actions = $("#hero-actions");
  actions.innerHTML = "";
  if (state === "stopped") {
    const b = document.createElement("button");
    b.className = "btn btn-primary"; b.textContent = "Start Ecoscribe";
    b.onclick = async () => { b.disabled = true; await api.start_app(); toast("Starting Ecoscribe…"); };
    actions.append(b);
  } else if (state === "error") {
    const b = document.createElement("button");
    b.className = "btn btn-ghost"; b.textContent = "Open the log";
    b.onclick = () => api.open_log();
    actions.append(b);
  }
  if (STATE_HOW[state]) {  // can't dictate right now: say why, not how to dictate
    $("#hero-how").textContent = STATE_HOW[state];
  } else if (s.hotkey && s.hotkey.includes("+")) {  // a combo: no tap, and no Esc cancel (tray > Cancel recording)
    $("#hero-how").textContent = `Press ${hotkeyLabel(s.hotkey)}, talk, and press it again. The text appears wherever the cursor is.`;
  } else if (s.hotkey) {  // the user's own key, as a keycap
    $("#hero-how").innerHTML = `Tap <kbd class="key key-wide"></kbd>, talk, and tap it again. The text appears wherever the cursor is.`;
    $("#hero-how kbd").textContent = hotkeyLabel(s.hotkey);
  }
  paintTip(s);
}

/* Home tips (dictado-3vj): one a day from the ones that still apply; × hides a tip for good. */
const TIPS = [
  { id: "cancel", when: (s) => s.hotkey && !s.hotkey.includes("+"), html: (k) => `Hold <kbd>${k}</kbd> and press <kbd>Esc</kbd> to cancel a dictation.` },
  { id: "lang-key", when: (s, v) => s.hotkey && !s.hotkey.includes("+") && String(v.languages || "").split(",").filter(Boolean).length > 1,
    html: (k) => `Wrong language? Hold <kbd>${k}</kbd> and press <kbd>L</kbd> to pick the next dictation's.` },
  { id: "retry", when: () => true, html: () => "A dictation came out wrong? <strong>Retry</strong> it from History, in the same or another language." },
  { id: "replace", when: (s, v) => !(v.replacements || []).length, html: () => "A word that keeps coming out wrong? Add it to <strong>Replace</strong> in Settings › Words." },
  { id: "snippets", when: (s, v) => !(v.snippets || []).length, html: () => "Say “my email.” on its own and Ecoscribe types the address: set up <strong>Snippets</strong> in Settings › Words." },
  { id: "calendar", when: (s, v) => !v.calendar_url, html: () => "Recorded meetings can take their names from your calendar: Settings › Meetings." },
  { id: "insights", when: (s, v) => !v.insights, html: () => "Turn on <strong>Insights</strong> in Settings to see how you talk and the time you save." },
  { id: "delete", when: () => true, html: () => "Delete a dictation from History with its <strong>Delete</strong> button; you get a few seconds to undo." },
];
let tipValues = null;
let tipsHidden = null;  // also kept in memory: storage may be off in a private or preview window
function hiddenTips() {
  if (!tipsHidden) { try { tipsHidden = new Set(JSON.parse(store("ecoscribe.tips.hidden") || "[]")); } catch { tipsHidden = new Set(); } }
  return tipsHidden;
}
async function paintTip(s) {
  if (!tipValues) { try { tipValues = (await api.get_settings()).values; } catch { return; } }
  const hidden = hiddenTips();
  const ok = TIPS.filter((t) => !hidden.has(t.id) && t.when(s, tipValues));
  const box = $("#home-tip");
  box.hidden = !ok.length;
  if (!ok.length) return;
  const day = Math.floor((Date.now() - new Date().getTimezoneOffset() * 60000) / 864e5);
  const t = ok[day % ok.length];
  const key = hotkeyLabel(s.hotkey).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  $("#home-tip-text").innerHTML = `<strong>Tip</strong> · ${t.html(key)}`;
  box.dataset.tip = t.id;
  $("#home-tip-x").onclick = () => { hidden.add(t.id); store("ecoscribe.tips.hidden", JSON.stringify([...hidden])); paintTip(s); };
}

// dictation languages (dictado-bvf): any mix, auto-detected among them; set in Settings
const DICT_LANGS = { en: "English", es: "Spanish", sv: "Swedish", el: "Greek" };

/* ---------------------------------------------------------------- inicio */
async function crashCard() {  // t0u.37: a crash is never silent
  const c = await api.crashes().catch(() => ({ items: [] }));
  const card = $("#crash-card"), x = c.items[0];
  card.hidden = !x && !c.gave_up;
  if (card.hidden) return;
  const more = c.items.length > 1 ? ` (${c.items.length} crashes)` : "";
  $("#crash-title").textContent = c.gave_up ? "Ecoscribe crashed 3 times and stopped" : `Ecoscribe crashed${x ? " " + x.when.slice(11, 13) + ":" + x.when.slice(13, 15) : ""} and restarted${more}`;
  $("#crash-sub").textContent = c.gave_up ? (MAC ? "Open it again from Applications." : "Start it again from the Start menu.") + " The reports say where it failed."
    : `${x.exit && x.exit !== "unknown" ? x.exit + ". " : ""}A report with everything needed to find the cause was saved.`;  // macOS: no exit code
  $("#crash-copy").hidden = !x;
  $("#crash-copy").onclick = async () => { await api.copy_crash_report(x.name); toast("Copied. Paste it to Claude."); crashCard(); };
  $("#crash-dismiss").onclick = async () => { for (const i of c.items) await api.dismiss_crash(i.name); crashCard(); };
}

async function updateNote() {  // dictado-cjk: a newer version is out (the app checks once a day)
  const n = await api.update_notice().catch(() => ({}));
  const box = $("#update-note");
  box.hidden = !n.version;
  if (box.hidden) return;
  // dictado-nmo: offer -> downloading -> ready (installs when idle or at Quit, never in a call); failed -> Download
  const step = n.install || "";
  const have = `You have ${lastStatus?.version || "an older version"}.`;
  const [title, sub] = {
    "": [`Ecoscribe ${n.version} is out`, `${have} Your settings and history stay as they are.`],
    offer: [`Ecoscribe ${n.version} is out`, `${have} Your settings and history stay as they are.`],
    downloading: [`Getting Ecoscribe ${n.version} ready`, n.error || `Downloading in the background, ${n.pct || 0}%. It installs when you step away or quit, never during a call.`],
    ready: [`Ecoscribe ${n.version} is ready`, "It installs when you step away from the computer or quit Ecoscribe. Never during a call."],
    failed: [`Ecoscribe ${n.version} is out`, "It couldn't install by itself. Download it and run the installer."],
  }[step] || [`Ecoscribe ${n.version} is out`, have];
  box.dataset.step = step;
  $("#update-title").textContent = title;
  $("#update-sub").textContent = sub;
  const get = $("#update-get"), idle = $("#update-idle");
  idle.hidden = step !== "offer";
  get.hidden = step === "downloading" || step === "ready";
  get.className = step === "offer" ? "btn btn-sm" : "btn btn-primary btn-sm";
  get.onclick = () => api.open_update();
  idle.onclick = async () => { await api.install_update_when_idle(n.version); updateNote(); };
  $("#update-x").onclick = async () => { await api.dismiss_update(n.version); updateNote(); };
  clearTimeout(updateNote.timer);
  if (step === "downloading") updateNote.timer = setTimeout(() => { if (!box.hidden && current === "inicio") updateNote(); }, 5000);
}

async function renderInicio() {  // the dictate banner, today's numbers, recent dictations (dictado-6oe.3)
  crashCard();
  const hour = new Date().getHours();
  $("#home-hello").textContent = hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  $("#home-date").textContent = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
  await refreshStatus();
  updateNote();  // after the status: it says which version you have
  const h = await api.get_history(200, "");
  const today = new Date().toISOString().slice(0, 10);
  const todays = h.items.filter((x) => String(x.ts || "").startsWith(today));
  $("#stat-today").textContent = fmtNum(h.stats.today_words);
  $("#stat-saved").textContent = `${Math.max(0, Math.round(h.stats.today_words / 40))} min`;  // typing runs about 40 words a minute
  $("#stat-count").textContent = fmtNum(todays.length);
  $("#stat-total").textContent = h.stats.total_words ? `${fmtNum(h.stats.total_words)} words in total` : "";
  const list = $("#recent-list");
  list.innerHTML = "";
  for (const [i, x] of h.items.slice(0, 3).entries()) {
    const li = document.createElement("li"); li.className = "recent-item";
    const p = document.createElement("p"); p.className = "last-text"; p.textContent = x.text.trim();
    if (i === 0) p.id = "last-text";
    const meta = document.createElement("span"); meta.className = "recent-meta";
    meta.textContent = [when(x.ts), x.pasted === false ? "" : appName(x.target)].filter(Boolean).join(" · ");
    li.append(p, meta);
    if (x.pasted === false) {  // dictado-bhe: no text box under the cursor at the stop
      const b = document.createElement("span"); b.className = "badge"; b.textContent = "Not pasted"; li.append(b);
    }
    const c = document.createElement("button"); c.type = "button"; c.className = "btn btn-ghost btn-sm"; c.textContent = "Copy";
    c.onclick = () => copy(x.text, c);
    li.append(c);
    list.append(li);
  }
  if (!h.items.length) list.innerHTML = '<li class="recent-item"><p class="last-text" id="last-text"><span class="muted">You haven\'t dictated anything yet. Tap the key and talk.</span></p></li>';
  await renderTodos();
}

/* Home > your own to-dos from the week's call summaries, one column per person (dictado-xuu) */
let todoBack = 0;
const shortDay = (iso) => new Date(iso + "T12:00").toLocaleDateString("en-GB", { weekday: "short" });
const shortDate = (iso) => new Date(iso + "T12:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
async function renderTodos() {
  const box = $("#todos");
  let w;
  try { w = await api.week_todos(todoBack); } catch { box.hidden = true; return; }
  box.hidden = !w.enabled && !w.count && !todoBack;  // summaries off and nothing to show: no card
  if (box.hidden) return;
  for (const b of $$("#todos-weeks .seg")) b.setAttribute("aria-checked", String(Number(b.dataset.back) === todoBack));
  $("#todos-title").textContent = todoBack ? "Your to-dos last week" : "Your to-dos this week";
  const range = `${shortDate(w.start)} to ${shortDate(w.end)}`;
  $("#todos-sub").textContent = w.count
    ? `${w.open} of ${w.count} still to do · from ${w.calls} ${w.calls === 1 ? "call" : "calls"}, ${range}` : range;
  const people = $("#todos-people");
  people.textContent = "";
  const empty = $("#todos-empty");
  empty.hidden = !!w.count;
  empty.textContent = !w.enabled ? "Call summaries are off, so no to-dos are collected. Turn them on in Settings."
    : todoBack ? "No to-dos came out of last week's personal calls."
    : "None yet this week. When a personal call's summary is written, the things you said you'd do show up here, by person.";
  for (const g of w.people) {
    const col = document.createElement("div"); col.className = "todo-person";
    const who = document.createElement("div"); who.className = "todo-who";
    const ini = document.createElement("span"); ini.className = "todo-initial"; ini.setAttribute("aria-hidden", "true");
    ini.textContent = (g.person.trim()[0] || "?").toUpperCase();
    const name = document.createElement("strong"); name.textContent = g.person; name.title = g.person;
    const n = document.createElement("span"); n.className = "muted small";
    const left = g.items.filter((i) => !i.done).length;
    n.textContent = left ? `${left} to do` : "all done";
    who.append(ini, name, n);
    const ul = document.createElement("ul"); ul.className = "todo-list";
    for (const it of g.items) {
      const li = document.createElement("li"); li.className = "todo";
      li.classList.toggle("done", !!it.done);
      li.classList.toggle("unchecked", !it.checked);
      const lab = document.createElement("label"); lab.className = "todo-tick";
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!it.done;
      const txt = document.createElement("span"); txt.className = "todo-text"; txt.textContent = it.text;
      cb.onchange = async () => {
        li.classList.toggle("done", cb.checked);
        const out = await api.todo_done(it.key, cb.checked);
        if (!out.ok) { toast(out.error || "Couldn't save that."); cb.checked = !cb.checked; }
        renderTodos();
      };
      lab.append(cb, txt);
      const from = document.createElement("button"); from.type = "button"; from.className = "todo-from";
      from.textContent = `${shortDay(it.day)} · ${it.title}`; from.title = "Open this call";
      from.onclick = () => show("reuniones/" + it.session);
      li.append(lab, from);
      if (!it.checked) {
        const miss = document.createElement("span"); miss.className = "r-sum-miss"; miss.textContent = "Not found in the call";
        miss.title = "The words this to-do came from aren't in the transcript near that moment: check it before you rely on it.";
        li.append(miss);
      }
      ul.append(li);
    }
    col.append(who, ul);
    people.append(col);
  }
}

/* ---------------------------------------------------------------- reuniones */
const SPEAKER = { Yo: "Me", Otros: "Others" };
// Meeting / file languages: the user's own (dictado-ehs, dictado-607); boot() loads the real list.
let R_LANGS = [["en", "English"], ["auto", "Detect"]], R_DEFAULT = "";
const R_STATUS = {
  recording: "Recording", finalizing: "Saving", stopping: "Saving", queued: "Queued", new: "Queued",
  running: "Transcribing", downloading: "Downloading model", done: "Ready", failed: "Failed",
};
const r = { open: null, next: 0, timer: null, status: null, segs: 0, busy: false, speakers: null, names: {} };
const ACTIVE = new Set(["recording", "finalizing", "stopping", "queued", "new", "running", "downloading"]);
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
function rLang() { return $("#r-lang").value || R_LANGS[0][0]; }
function fmtDur(s) {
  if (!s && s !== 0) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min` : `${x} s`;
}
function fmtT(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
}
function statusText(row) {
  const t = R_STATUS[row.status] || row.status || "";
  if (row.status === "running" && row.pct != null) return `${t} ${row.pct} %`;
  return t;
}
function chip(el, row) {
  el.textContent = statusText(row);
  el.dataset.status = row.status || "";
}
async function renderReuniones() {
  if (r.open) return renderDetail(r.open);
  $("#r-list-view").hidden = false; $("#r-detail-view").hidden = true;
  let out;
  try { out = await api.list_sessions($("#r-search").value); } catch (e) { return; }
  paintNow(out.state);
  const list = $("#r-list");
  list.innerHTML = "";
  let day = null;
  for (const row of out.items) {
    const d = dayLabel(row.created);  // grouped by day (dictado-6oe.4)
    if (d !== day) {
      day = d;
      const h = document.createElement("li"); h.className = "r-day"; h.textContent = d; list.append(h);
    }
    const li = document.createElement("li");
    li.className = "h-item r-row"; li.tabIndex = 0; li.dataset.name = row.name;
    li.insertAdjacentHTML("afterbegin", row.source === "import"
      ? '<svg class="r-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z"/><path d="M14 3v4h4"/></svg>'
      : '<svg class="r-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/></svg>');
    const title = document.createElement("p");
    title.className = "h-text r-row-title"; title.textContent = row.title || "Untitled";
    const st = document.createElement("span");
    st.className = "r-chip"; chip(st, row);
    if (row.status === "done") { st.className = "r-dur"; st.textContent = fmtDur(row.duration_s); }  // finished: just how long
    const meta = document.createElement("div");
    meta.className = "h-meta";
    meta.textContent = [timeOf(row.created), row.source === "import" ? "file" : appName((row.app || "") + ".exe") || "meeting", row.lang_name,
      row.people && row.people.length ? row.people.slice(0, 3).join(", ") : ""].filter(Boolean).join(" · ");
    li.append(title, st, meta);
    li.onclick = () => openSession(row.name);
    li.onkeydown = (e) => { if (e.key === "Enter") openSession(row.name); };
    list.append(li);
  }
  const q = $("#r-search").value;
  $("#r-empty").hidden = out.items.length > 0;
  $("#r-empty-text").textContent = q ? `Nothing matches "${q}".` : "Your meetings and the audio you import will show up here.";
}
function dayLabel(iso) {
  const d = new Date(iso || 0), t = new Date(), y = new Date(t); y.setDate(t.getDate() - 1);
  if (isNaN(d)) return "Earlier";
  if (d.toDateString() === t.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}
function timeOf(iso) { const d = new Date(iso || 0); return isNaN(d) ? "" : d.toTimeString().slice(0, 5); }
function paintNow(state) {
  const m = state && state.meeting;
  $("#r-now").hidden = !m;
  $("#r-start").disabled = !!m;
  if (!m) return;
  const stopping = m.status === "stopping" || m.status === "finalizing";
  $("#r-now-title").textContent = stopping ? "Saving the meeting" : "Recording";
  const lang = (R_LANGS.find(([c]) => c === m.lang) || [null, DICT_LANGS[m.lang] || m.lang])[1];
  $("#r-now-meta").textContent = [m.app ? appName(m.app + ".exe") : "", lang, m.started ? `since ${when(m.started)}` : ""].filter(Boolean).join(" · ");
  $("#r-now-stop").hidden = stopping;
  $("#r-now-open").onclick = () => openSession(m.name);
}
function atBottom(el) { return el.scrollHeight - el.scrollTop - el.clientHeight < 40; }
function renameSpeaker(el) {
  if (el.querySelector("input")) return;
  const label = el.dataset.label, input = document.createElement("input");
  input.className = "r-who-input"; input.value = whoName(label); input.maxLength = 40;
  input.setAttribute("aria-label", "Speaker name");
  el.textContent = ""; el.append(input); input.focus(); input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    const v = input.value.trim();
    if (save && v !== whoName(label)) {
      const out = await api.rename_speaker(r.open, label, v);
      if (!out.ok) toast(out.error || "Couldn't rename.");
      else if (out.merged) { toast(`Merged into ${whoName(out.merged)}.`); openSession(r.open); return; }  // dictado-gk9
      else r.names = out.names;
    }
    for (const w of document.querySelectorAll(".r-who-edit")) if (w.dataset.label === label) w.textContent = whoName(label);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); e.stopPropagation(); };
  input.onblur = () => finish(true);
  input.onclick = (e) => e.stopPropagation();
}
async function openSession(name) {
  r.open = name; r.next = 0; r.status = null; r.segs = 0; r.speakers = null; r.names = {};
  r.notesLoaded = false; clearTimeout(r.notesTimer);
  r.repAsked = false; paintReplace(null);
  $("#r-notes-text").value = "";
  $("#r-segs").innerHTML = "";
  $("#r-jump").hidden = true;
  await renderDetail(name);
}
/* the call's summary (dictado-nl5): every point with its moment in the call, and marked when its words weren't found */
const SUM_SECTIONS = [["decisions", "Decisions"], ["todos", "To-dos"], ["open_questions", "Open questions"]];
const atSecs = (at) => String(at || "").split(":").reduce((t, x) => t * 60 + (Number(x) || 0), 0);
function renderSummary(s, summ) {
  const box = $("#r-summary");
  box.hidden = !(summ || s.summary === "running");
  if (box.hidden) return;
  $("#r-sum-check").textContent = summ ? `${summ.checked} of ${summ.total} points found in the call` : "";
  const text = $("#r-sum-text");
  text.textContent = summ ? (summ.summary || "") : "Writing the summary…";
  text.classList.toggle("muted", !summ);
  const lists = $("#r-sum-lists");
  lists.textContent = "";
  if (!summ) return;
  for (const [key, title] of SUM_SECTIONS) {
    const items = summ[key] || [];
    if (!items.length) continue;
    const h = document.createElement("h4"); h.className = "r-sum-h"; h.textContent = title;
    const ul = document.createElement("ul"); ul.className = "r-sum-list";
    for (const it of items) {
      const li = document.createElement("li");
      const txt = document.createElement("span"); txt.className = "r-sum-item";
      txt.textContent = it.text + (it.who ? ` (${it.who})` : "");
      const at = document.createElement("button"); at.type = "button"; at.className = "r-sum-at";
      at.textContent = fmtT(atSecs(it.at)); at.title = "Go to this moment in the transcript";
      at.onclick = () => jumpTo(atSecs(it.at));
      li.append(txt, at);
      if (!it.checked) {
        li.classList.add("unchecked");
        const miss = document.createElement("span"); miss.className = "r-sum-miss"; miss.textContent = "Not found in the call";
        miss.title = "The words this point came from aren't in the transcript near that moment: check it before you rely on it.";
        li.append(miss);
      }
      ul.append(li);
    }
    lists.append(h, ul);
  }
}
function jumpTo(t) {  // the last line that starts at or before t
  const lines = [...$$("#r-segs .r-seg")];
  const li = lines.filter((x) => Number(x.dataset.t0) <= t + 1).pop() || lines[0];
  if (!li) return;
  const list = $("#r-segs");
  list.scrollTop = li.offsetTop - list.offsetTop - 8;
  li.classList.remove("r-seg-hit"); void li.offsetWidth; li.classList.add("r-seg-hit");
}
function whoName(label) { return r.names[label] || SPEAKER[label] || label || ""; }  // transcripts before 1.2.1 say Yo / Otros
function segLi(s, editable) {
  const li = document.createElement("li");
  li.className = "r-seg";
  li.dataset.t0 = s.t0;
  const t = document.createElement("span");
  t.className = "r-t"; t.textContent = fmtT(s.t0);
  const who = document.createElement("span");
  const sp = SPEAKER[s.speaker] || s.speaker || "";
  who.className = "r-who"; who.textContent = whoName(s.speaker);
  who.dataset.who = sp.startsWith("Speaker") ? "Others" : sp;
  if (editable && s.speaker) {
    who.dataset.label = s.speaker; who.tabIndex = 0; who.classList.add("r-who-edit");
    who.title = "Click to name this speaker. Give two speakers the same name to make them one.";
    who.onclick = () => renameSpeaker(who);
    who.onkeydown = (e) => { if (e.key === "Enter") renameSpeaker(who); };
  }
  const p = document.createElement("p");
  p.className = "r-text"; p.textContent = s.text;
  const av = document.createElement("span");  // a conversation, not a table (dictado-6oe.4)
  av.className = "r-av"; av.dataset.who = who.dataset.who; av.setAttribute("aria-hidden", "true");
  const nm = whoName(s.speaker);  // "Me" until the user gives their name in Settings
  av.textContent = nm === "Me" ? "Me" : (nm || "?").slice(0, 1).toUpperCase();
  const head = document.createElement("span"); head.className = "r-seg-head";
  head.append(who, t);
  li.append(av, head, p);
  return li;
}
async function renderDetail(name) {
  $("#r-list-view").hidden = true; $("#r-detail-view").hidden = false;
  const live = r.status === null || r.status === "recording" || r.status === "stopping" || r.status === "finalizing";
  let s, segs = null, summ = null;
  try {
    if (live) {
      const out = await api.get_live(name, r.next);
      s = out.session;
      notesIn(out.notes);
      if (s.status === "recording" || s.status === "finalizing" || s.status === "stopping") {
        const list = $("#r-segs"), follow = atBottom(list);  // scrolled up to read: stay there
        for (const l of out.lines) list.append(segLi(l, false));
        r.next = out.next;
        r.segs += out.lines.length;
        if (out.lines.length) { if (follow) list.scrollTop = list.scrollHeight; else $("#r-jump").hidden = false; }
      }
    }
    if (!s || !(s.status === "recording" || s.status === "finalizing" || s.status === "stopping")) {
      const out = await api.get_session(name);
      s = out.session; segs = out.segments; summ = out.summary || null;
      notesIn(out.notes);
    }
  } catch (e) {
    if (!/FileNotFound|not found/i.test(String(e && (e.message || e)))) { console.error(e); return; }  // a hiccup: next poll retries
    toast("That session no longer exists."); r.open = null; return renderReuniones();
  }
  const changed = s.status !== r.status || (s.speakers || null) !== r.speakers;  // a finished speakers pass relabels the lines
  r.status = s.status; r.speakers = s.speakers || null; r.names = s.speaker_names || {};
  if (document.activeElement !== $("#r-d-title")) $("#r-d-title").value = s.title || "";
  chip($("#r-d-status"), s);
  $("#r-d-meta").textContent = [when(s.created), s.lang_name, fmtDur(s.duration_s),
    s.source === "import" ? "imported file" : "mic and the computer's audio",
    s.recovered ? `recovered (${s.recovered}): the text ends where the recording stopped` : "",
    s.speakers === "running" ? "identifying speakers…" : "",
    s.speakers === "pending" ? "speakers: waiting to start" : "",
    s.speakers === "failed" ? "couldn't tell the speakers apart" : "",
    s.recognised?.length ? `recognised by voice: ${s.recognised.join(", ")}` : ""].filter(Boolean).join(" · ");
  const recording = s.status === "recording";
  if (recording && document.activeElement !== $("#r-d-lang")) {
    const dl = $("#r-d-lang");
    if (s.lang && ![...dl.options].some((o) => o.value === s.lang)) {  // a language outside the user's list (dictado-607)
      const o = document.createElement("option"); o.value = s.lang; o.textContent = s.lang_name || s.lang; dl.append(o);
    }
    dl.value = s.lang || R_LANGS[0][0];
  }
  $("#r-d-live-actions").hidden = !recording;
  if (!recording) $("#r-jump").hidden = true;
  $("#r-d-done-actions").hidden = s.status !== "done";
  const working = s.status === "running" || s.status === "queued" || s.status === "new" || s.status === "downloading";
  $("#r-d-progress").hidden = !working;
  if (working) {
    $("#r-d-progress-fill").style.width = `${s.pct || 0}%`;
    $("#r-d-progress-text").textContent = s.status === "queued" || s.status === "new" ? "Queued: starts when the previous one finishes."
      : s.status === "downloading" ? "Downloading this language's model (first time only)." : `${s.pct || 0} %${s.slow ? " · on CPU, slow" : ""}`;
  }
  const people = s.people || [];
  $("#r-people").hidden = !people.length;
  $("#r-people-list").innerHTML = "";
  for (const n of people) {
    const li = document.createElement("li");
    li.innerHTML = '<span class="r-av"></span><span></span>';
    li.firstChild.textContent = n.slice(0, 1).toUpperCase(); li.lastChild.textContent = n;
    $("#r-people-list").append(li);
  }
  if (segs && (changed || $("#r-segs").childElementCount !== segs.length)) {
    const list = $("#r-segs");
    list.innerHTML = "";
    for (const x of segs) list.append(segLi(x, s.status === "done"));
  }
  renderSummary(s, s.status === "done" ? summ : null);
  if (s.status === "done" && s.speakers !== "pending" && s.speakers !== "running" && !r.repAsked) { r.repAsked = true; replaceCheck(name); }
  const n = $("#r-segs").childElementCount;
  $("#r-segs-empty").hidden = n > 0;
  $("#r-segs-empty-text").textContent = s.status === "failed" ? `Failed: ${s.error || "unknown error"}`
    : recording ? "Listening: the first text arrives in a few seconds." : working ? "The text appears when it finishes." : "This session has no text.";
}
/* the Replace list on a saved transcript (dictado-9lo): offered when it would change something, one Undo after */
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
async function replaceCheck(name) {
  const out = await api.replace_preview(name).catch(() => ({ ok: false }));
  if (r.open === name) paintReplace(out.ok && out.places > 0 ? { offer: out } : null);
}
function paintReplace(st) {
  $("#r-replace").hidden = !st;
  if (!st) return;
  const o = st.offer;
  if (o) {
    $("#r-replace-title").textContent = `${plural(o.places, "place matches", "places match")} your Replace list`;
    $("#r-replace-detail").textContent = o.pairs.slice(0, 3).map((p) => `${p.heard} → ${p.write}${o.pairs.length > 1 ? ` (${p.n})` : ""}`).join(" · ")
      + (o.pairs.length > 3 ? ` · and ${o.pairs.length - 3} more` : "");
  } else {
    $("#r-replace-title").textContent = `Changed ${plural(st.done, "place", "places")} with your Replace list`;
    $("#r-replace-detail").textContent = "Also in the downloads. The audio is untouched.";
  }
  $("#r-replace-go").hidden = !o; $("#r-replace-undo").hidden = !!o;
  $("#r-replace-later").textContent = o ? "Not now" : "Hide";
}
async function reloadSegs(name) {  // the same lines with their new text, where the reader was
  const list = $("#r-segs"), top = list.scrollTop;
  list.innerHTML = "";
  await renderDetail(name);
  list.scrollTop = top;
}
async function replaceApply() {
  const name = r.open, b = $("#r-replace-go");
  b.disabled = true;
  const out = await api.apply_replacements(name).catch(() => ({ ok: false }));
  b.disabled = false;
  if (!out.ok) { toast(out.error || "Couldn't apply the Replace list."); return; }
  if (r.open !== name) return;
  if (!out.places) { paintReplace(null); toast("Nothing in this transcript matches your Replace list now."); return; }
  await reloadSegs(name);
  paintReplace({ done: out.places });
}
async function replaceUndo() {
  const name = r.open;
  const out = await api.undo_replacements(name).catch(() => ({ ok: false }));
  if (!out.ok) { toast(out.error || "Couldn't undo it."); return; }
  if (r.open !== name) return;
  await reloadSegs(name);
  toast("Undone: the transcript is back as it was.");
  replaceCheck(name);
}
function notesIn(text) {  // once per open: polls must never overwrite what the user is typing
  if (r.notesLoaded) return;
  r.notesLoaded = true;
  $("#r-notes-text").value = text || "";
}
function notesWire() {
  const box = $("#r-notes-text"), state = $("#r-notes-state");
  box.addEventListener("input", () => {
    clearTimeout(r.notesTimer);
    const name = r.open;
    state.textContent = "Saving…";
    r.notesTimer = setTimeout(async () => {
      const out = await api.save_notes(name, box.value).catch(() => ({ ok: false }));
      state.textContent = out.ok ? "Saved." : "Couldn't save the notes.";
    }, 600);
  });
}
function rPoll() {
  clearInterval(r.timer);
  r.timer = setInterval(async () => {
    if (current !== "reuniones" || r.busy) return;  // a slow call must not run twice and append lines twice
    r.busy = true;
    try {
      if (r.open) { if (ACTIVE.has(r.status) || r.status === null || r.speakers === "pending" || r.speakers === "running") await renderDetail(r.open); }
      else if (document.activeElement !== $("#r-search")) await renderReuniones();
    } finally { r.busy = false; }
  }, 1000);
}
async function rStart() {
  $("#r-start").disabled = true;
  const out = await api.start_meeting(rLang());
  if (!out.ok) { $("#r-start").disabled = false; toast(out.error || "Couldn't start."); return; }
  toast("Taking notes.");
  if (out.dir) openSession(out.dir.split(/[\\/]/).pop());
  else renderReuniones();
}
async function rStop() {
  const out = await api.stop_meeting();
  if (!out.ok) { toast(out.error || "Couldn't stop."); return; }
  toast("Stopping: saving the transcript.");
  if (r.open) renderDetail(r.open); else renderReuniones();
}
async function rImport(paths) {
  if (!paths || !paths.length) return;
  const out = await api.import_files(paths, rLang());
  if (!out.ok) { toast(out.error || "Couldn't import."); return; }
  toast(paths.length === 1 ? "Queued for transcription." : `${paths.length} files queued.`);
  r.open = null;
  setTimeout(renderReuniones, 600);
}
async function rDropped(paths) {  // from Python's drop handler: full paths of the dropped files
  $("#r-drop").hidden = true;
  if (current !== "reuniones") await show("reuniones");
  const ok = (paths || []).filter(Boolean);
  if (!ok.length) { toast(MAC ? "Drag the file from Finder." : "Drag the file from Windows Explorer."); return; }
  await rImport(ok);
}
function rWire() {
  const sel = $("#r-lang");
  for (const [c, n] of R_LANGS) { const o = document.createElement("option"); o.value = c; o.textContent = n; sel.append(o); }
  sel.value = store("ecoscribe.r-lang") || R_DEFAULT;  // else Settings' meeting language
  if (!sel.value) sel.value = R_LANGS[0][0];  // a stored language that was removed
  sel.onchange = () => store("ecoscribe.r-lang", sel.value);
  $("#r-start").onclick = rStart;
  $("#home-record").onclick = async () => { await show("reuniones"); rStart(); };  // Home's quick actions (dictado-6oe.3)
  $("#home-file").onclick = async () => { const out = await api.pick_files(); if (out.paths && out.paths.length) { await show("reuniones"); rImport(out.paths); } };
  $("#recent-all").onclick = (e) => { e.preventDefault(); show("historial"); };
  $("#r-now-stop").onclick = rStop;
  document.addEventListener("click", (e) => {  // the Copy and ··· menus: close after a choice or a click elsewhere
    for (const m of $$("details.menu[open]")) if (!m.contains(e.target) || e.target.closest(".menu-item")) m.open = false;
  });
  $("#r-d-stop").onclick = rStop;
  $("#r-segs").addEventListener("scroll", () => { if (atBottom($("#r-segs"))) $("#r-jump").hidden = true; });
  $("#r-jump").onclick = () => { const l = $("#r-segs"); l.scrollTop = l.scrollHeight; $("#r-jump").hidden = true; };
  const dl = $("#r-d-lang");
  for (const [c, n] of R_LANGS) { const o = document.createElement("option"); o.value = c; o.textContent = n; dl.append(o); }
  dl.onchange = async () => {
    const out = await api.set_meeting_lang(dl.value);
    toast(out.ok ? `Now transcribing in ${dl.selectedOptions[0].textContent}. The final transcript uses it for the whole meeting.` : out.error || "Couldn't change the language.");
  };
  $("#r-import").onclick = async () => { const out = await api.pick_files(); rImport(out.paths); };
  $("#r-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderReuniones, 120); });
  $("#r-back").onclick = () => { r.open = null; renderReuniones(); };
  $("#r-d-title").addEventListener("change", async () => {
    const out = await api.rename_session(r.open, $("#r-d-title").value);
    if (!out.ok) toast(out.error); else toast("Title saved.");
  });
  $("#r-copy").onclick = async () => { await api.copy_transcript(r.open, "text"); toast("Copied."); };
  $("#r-copy-claude").onclick = async () => { await api.copy_transcript(r.open, "claude"); toast("Copied with date, app and language, ready to paste into Claude."); };
  $("#r-email").onclick = async () => {  // dictado-fnw: the user's mail program sends, never Ecoscribe
    const res = await api.email_participants(r.open);
    if (!res.ok) { toast(res.error || "Couldn't open a draft."); return; }
    if (res.via === "calendar") {  // dictado-qxr: no guest list and no calendar to ask: Google Calendar on the call's day
      const day = new Date(res.day + "T12:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
      toast(`Transcript copied. Google Calendar is open on ${day}: click this call, then Email guests (the envelope), and paste.`, 9000);
      return;
    }
    const who = res.to.length ? `to ${res.to.length} ${res.to.length === 1 ? "person" : "people"}` : "with an empty To (no calendar invite)";
    toast(res.inline ? `Draft opened ${who}. Check it and press Send.` : `Draft opened ${who}. The transcript is copied: paste it in, then Send.`, 5000);
  };
  $("#r-copy-summary").onclick = async () => { await api.copy_transcript(r.open, "summary"); toast("Summary prompt copied: paste it into Claude."); };
  for (const b of $$("[data-fmt]")) b.onclick = () => download(r.open, b.dataset.fmt);
  $("#r-folder").onclick = () => api.open_folder(r.open);
  $("#r-replace-go").onclick = replaceApply;
  $("#r-replace-undo").onclick = replaceUndo;
  $("#r-replace-later").onclick = () => paintReplace(null);
  $("#r-delete").onclick = async () => {
    if (!confirm("Delete this transcript and its audio? This can't be undone.")) return;
    const out = await api.delete_session(r.open);
    if (!out.ok) { toast(out.error); return; }
    r.open = null; toast("Deleted."); renderReuniones();
  };
  // drag and drop: the page shows where to drop; Python reads the full paths (pywebview DOM drop event)
  let depth = 0;
  const dragging = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  document.addEventListener("dragenter", (e) => { if (!dragging(e)) return; depth++; $("#r-drop").hidden = false; });
  document.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) $("#r-drop").hidden = true; });
  document.addEventListener("dragover", (e) => { if (dragging(e)) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; $("#r-drop").hidden = true;
    if (!window.pywebview) rDropped([...(e.dataTransfer?.files || [])].map((f) => f.path || f.name));  // demo / tests
  });
  rPoll();
}

/* ---------------------------------------------------------------- historial */
let searchTimer = null;
let hKind = "all";  // History's filter: all | dict | meet (dictado-6oe.5)
async function renderHistory() {
  const q = $("#search").value;
  const h = await api.get_history(200, q);
  let meets = [];
  try { meets = (await api.list_sessions(q)).items; } catch (e) { meets = []; }
  const list = $("#history");
  list.innerHTML = "";
  const rows = [...h.items.map((x) => ({ kind: "dict", ts: x.ts, x })), ...meets.map((x) => ({ kind: "meet", ts: x.created, x }))]
    .filter((row) => hKind === "all" || row.kind === hKind)
    .sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  let day = null, group = null;
  for (const row of rows) {
    const d = dayLabel(row.ts);  // grouped by day, a card each (dictado-6oe.5)
    if (d !== day) {
      day = d;
      const hd = document.createElement("li"); hd.className = "r-day"; hd.textContent = d; list.append(hd);
      const g = document.createElement("li"); g.className = "h-group"; group = document.createElement("ol"); group.className = "h-group-list";
      g.append(group); list.append(g);
    }
    if (row.kind === "meet") { group.append(meetingHistoryItem(row.x)); continue; }
    const r = row.x;
    const li = document.createElement("li");
    li.className = "h-item"; if (r.id) li.dataset.id = r.id;
    const t = document.createElement("span"); t.className = "h-time"; t.textContent = timeOf(r.ts);
    const p = document.createElement("p");
    p.className = "h-text"; p.textContent = r.text.trim();
    const meta = document.createElement("div");
    meta.className = "h-meta";
    const tag = (txt, cls = "") => { const b = document.createElement("span"); b.className = "h-tag " + cls; b.textContent = txt; meta.append(b); };
    if (r.lang && !String(r.lang).includes("+")) tag(String(r.lang).toUpperCase(), "h-tag-line");
    if (appName(r.target)) tag(appName(r.target));
    if (r.pasted === false) tag("Not pasted: copy it here", "h-tag-dark");
    if (r.retried) tag("Retried", "h-tag-blue");
    const btns = document.createElement("div");
    btns.className = "h-btns";
    if (r.audio && r.id) btns.append(retryButton(r, p));
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost btn-sm h-copy"; btn.textContent = "Copy";
    btn.onclick = () => copy(r.text, btn);
    btns.append(btn);
    const ed = document.createElement("button");  // dictado-1ph
    ed.className = "btn btn-ghost btn-sm h-copy h-edit-btn"; ed.textContent = "Edit"; ed.title = "Fix the text; a name you fix can be learned";
    ed.onclick = () => editDictation(r, li, p, btns);
    btns.append(ed);
    const del = document.createElement("button");  // dictado-vfo
    del.className = "btn btn-ghost btn-sm h-copy h-del"; del.textContent = "Delete"; del.title = "Delete this dictation";
    del.onclick = () => deleteDictation(r, li);
    btns.append(del);
    li.append(t, p, btns, meta);
    group.append(li);
  }
  const empty = rows.length === 0;
  $("#history-empty").hidden = !empty;
  $("#history-empty-text").textContent = q ? `Nothing matches "${q}".` : "Everything you dictate will show up here.";
  const count = h.stats.total ? `${fmtNum(h.stats.total)} dictations · ${fmtNum(h.stats.total_words)} words` : "";
  $("#history-count").textContent = count;
  $("#history-sub").textContent = count ? count + " · kept on this computer" : "";
  $("#history-clear").hidden = !h.stats.total;
  const demo = $('#history .h-item[data-id="d1b"]');  // screenshots of the edit and the offer
  if (demo && params.get("hedit") === "1") demo.querySelector(".h-edit-btn").click();
  if (demo && params.get("learn") === "1") {
    showLearn(demo, [{ kind: "word", write: "Quintavelle" }, { kind: "replace", heard: "eco scribe", write: "Ecoscribe" }]);
    demo.scrollIntoView?.({ block: "center" });
  }
}

/* History > Edit (dictado-1ph): fix the text in place; a misheard name you fix is offered for next
   time (Your words, or a Replace rule when it's already there). Nothing is learned until a chip is clicked. */
function editDictation(r, li, p, btns) {
  if (li.querySelector(".h-edit")) return;
  const box = document.createElement("textarea");
  box.className = "h-edit"; box.value = r.text.trim(); box.setAttribute("aria-label", "Dictation text");
  box.rows = Math.min(8, Math.max(2, Math.ceil(box.value.length / 70)));
  const bar = document.createElement("div"); bar.className = "h-edit-bar";
  const hint = document.createElement("span"); hint.className = "muted small"; hint.textContent = "Fix a misheard name and Ecoscribe offers to learn it.";
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn btn-ghost btn-sm"; cancel.textContent = "Cancel";
  const save = document.createElement("button"); save.type = "button"; save.className = "btn btn-primary btn-sm"; save.textContent = "Save";
  bar.append(hint, cancel, save);
  const close = () => { box.remove(); bar.remove(); p.hidden = false; btns.hidden = false; };
  cancel.onclick = close;
  box.onkeydown = (e) => {
    if (e.key === "Escape") close();
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save.click();
  };
  save.onclick = async () => {
    const text = box.value.trim();
    if (!text || text === r.text.trim()) { close(); return; }
    save.disabled = true;
    const res = await api.edit_dictation(r.id || "", r.id ? "" : r.ts, text);
    save.disabled = false;
    if (!res.ok) { toast(res.error || "Couldn't save it."); return; }
    r.text = res.text; p.textContent = res.text; close();
    if ((res.learn || []).length) showLearn(li, res.learn); else toast("Saved.");
  };
  p.hidden = true; btns.hidden = true;
  p.after(box, bar);
  box.focus();
}
function showLearn(li, items) {  // one quiet line of chips under the dictation (look B, picked)
  li.querySelector(".h-learn")?.remove();
  const box = document.createElement("div"); box.className = "h-learn h-learn-chips";
  const lab = document.createElement("span"); lab.className = "muted small"; lab.textContent = "Learn for next time:";
  box.append(lab);
  for (const s of items) {
    const chip = document.createElement("button"); chip.type = "button"; chip.className = "h-learn-chip";
    chip.textContent = s.kind === "replace" ? `${s.heard} → ${s.write}` : `+ ${s.write}`;
    chip.title = s.kind === "replace" ? "Add a Replace rule" : "Add to Your words";
    chip.onclick = async () => {
      const out = await api.learn_word(s.kind, s.write, s.heard || "");
      if (!out.ok) { toast(out.error || "Couldn't learn it."); return; }
      chip.disabled = true; chip.classList.add("done"); chip.textContent = `✓ ${s.write}`;
    };
    box.append(chip);
  }
  const x = document.createElement("button"); x.type = "button"; x.className = "btn btn-ghost btn-sm"; x.textContent = "Not now";
  x.onclick = () => box.remove();
  box.append(x);
  li.append(box);
}

/* History > Delete (dictado-vfo): the row goes at once; the line and its audio after a few seconds to Undo. */
async function deleteDictation(r, li) {
  li.hidden = true;
  const undone = await toastUndo("Dictation deleted.", () => { li.hidden = false; });
  if (undone) return;
  const res = await api.delete_dictation(r.id || "", r.id ? "" : r.ts);
  if (!res.ok) { li.hidden = false; toast(res.error || "Couldn't delete it."); return; }
  renderHistory();
}

/* History > Retry (dictado-a2r): transcribe a recent dictation again, by itself or in a language.
   Only the last few keep their audio, so only those have the button. */
let retryLangs = null;
function retryButton(r, textEl) {
  const wrap = document.createElement("div");
  wrap.className = "h-retry";
  const b = document.createElement("button");
  b.className = "btn btn-ghost btn-sm h-copy"; b.textContent = "Retry ▾";
  const menu = document.createElement("div");
  menu.className = "h-menu"; menu.hidden = true;
  b.onclick = async (e) => {
    e.stopPropagation();
    $$(".h-menu").forEach((m) => { if (m !== menu) m.hidden = true; });
    if (!retryLangs) {
      try {
        const st = await api.get_settings();
        const lab = Object.fromEntries([...st.options.languages, ...st.options.all_languages].map((o) => [o.value, o.label]));
        retryLangs = st.values.languages.split(",").filter(Boolean).map((c) => [c, lab[c] || c]);
      } catch { retryLangs = []; }
    }
    menu.innerHTML = "";
    for (const [code, label] of [["", "Again, detect the language"], ...retryLangs.map(([c, l]) => [c, `Again, in ${l}`])]) {
      const it = document.createElement("button");
      it.type = "button"; it.className = "h-menu-item"; it.textContent = label;
      it.onclick = async (ev) => {
        ev.stopPropagation();
        menu.hidden = true;
        b.disabled = true; b.textContent = "Retrying…";
        const res = await api.retry_dictation(r.id, code);
        b.disabled = false; b.textContent = "Retry ▾";
        if (!res.ok) { toast(res.error || "Couldn't retry it."); return; }
        r.text = res.text; textEl.textContent = res.text.trim();
        toast("Done: the new text is copied, paste it where you need it.");
      };
      menu.append(it);
    }
    menu.hidden = !menu.hidden;
  };
  wrap.append(b, menu);
  return wrap;
}
document.addEventListener("click", () => $$(".h-menu").forEach((m) => (m.hidden = true)));

function meetingHistoryItem(m) {  // a meeting transcript in History: opens in Meetings, .md to Downloads
  const li = document.createElement("li");
  li.className = "h-item h-meeting";
  const p = document.createElement("p");
  p.className = "h-text"; p.textContent = m.title || "Untitled";
  const st = document.createElement("span"); st.className = "r-chip"; chip(st, m);
  const meta = document.createElement("div");
  meta.className = "h-meta";
  meta.textContent = [m.source === "import" ? "Imported file" : "Meeting", m.lang_name, fmtDur(m.duration_s)].filter(Boolean).join(" · ");
  if (m.status !== "done") meta.prepend(st);  // a finished one needs no chip (dictado-6oe.5)
  const t = document.createElement("span"); t.className = "h-time"; t.textContent = timeOf(m.created);
  const btns = document.createElement("div");
  btns.className = "h-btns";
  const open = document.createElement("button");
  open.className = "btn btn-ghost btn-sm"; open.textContent = "Open";
  open.onclick = () => show("reuniones/" + m.name);
  btns.append(open);
  if (m.status === "done") {
    const dl = document.createElement("button");
    dl.className = "btn btn-ghost btn-sm"; dl.textContent = "Download .md";
    dl.onclick = () => download(m.name, "md");
    btns.append(dl);
  }
  li.append(t, p, btns, meta);
  return li;
}

/* ---------------------------------------------------------------- ajustes */
let saved = null;   // values as last loaded/saved
function formValues() {
  return {
    hotkey: $("#f-hotkey").value, mic: $("#f-mic").value,
    languages: $$("#f-languages input:checked").map((i) => i.value).join(",") || "en",
    extra_languages: [...extraLangs],
    sounds: $("#f-sounds").checked, overlay: $("#f-overlay").checked, live_text: $("#f-live-text").checked, insights: $("#f-insights").checked, speech_feedback: $("#f-speech-feedback").checked, unmute: $("#f-unmute").checked, startup: $("#f-startup").checked,
    meet_mode: $("#f-meet-mode").value, meet_end: $("#f-meet-end").value, meet_lang: $("#f-meet-lang").value, on_demand: $("#f-on-demand").checked,
    speakers: $("#f-speakers").checked, voice_commands: $("#f-voice-commands").checked,
    voice_phrases: vcSaved(),  // dictado-67v
    self_corrections: $("#f-self-corrections").checked, command_mode: $("#f-command-mode").checked, command_key: $("#f-command-key").value,
    screen_names: $("#f-screen-names").checked, hold_to_talk: $("#f-hold").checked, numpad_enter: $("#f-numpad-enter").checked,
    theme: $("#f-theme").value || "system",
    voice_memory: $("#f-voice-memory").checked, debug_log: $("#f-debug-log").checked, update_check: $("#f-update-check").checked, auto_update: $("#f-auto-update").checked, calendar_url: $("#f-calendar").value.trim(), my_name: $("#f-my-name").value.trim(),
    vocabulary: $("#f-vocabulary").value.split("\n").map((w) => w.trim()).filter(Boolean).join("\n"),
    snippets: $$(".snip").map((r) => ({ trigger: $(".snip-trigger", r).value.trim().toLowerCase().replace(/\s+/g, " "),
                                       text: $(".snip-text", r).value }))
      .filter((x) => x.trigger && x.text.trim()),
    replacements: $$(".rep").map((r) => ({ heard: $(".rep-heard", r).value.trim(), write: $(".rep-write", r).value.trim() }))
      .filter((x) => x.heard && x.write),
    per_app_styles: $("#f-per-app").checked,
    app_styles: $$("#st-rows .st-row").map((row) => {
      const [capital, full_stop] = $(".st-look", row).value.split(",").map((x) => x === "1");
      return { kind: row.dataset.kind, capital, full_stop, commands: $(".st-vc input", row).checked };
    }),
  };
}
// Style per app (dictado-h0m): one row per kind of app, a menu of how a sentence comes out there, and voice commands.
const ST_SAMPLE = "Check the logs first.";
const ST_LOOKS = [[true, true], [true, false], [false, false]];  // [capital first, full stop]
function stSample(capital, fullStop) {
  let t = ST_SAMPLE;
  if (!capital) t = t[0].toLowerCase() + t.slice(1);
  if (!fullStop) t = t.replace(/\.$/, "");
  return t;
}
function stylesCard(rows) {
  const body = $("#st-rows"); body.innerHTML = "";
  for (const r of rows || []) {
    const row = document.createElement("div"); row.className = "row st-row"; row.dataset.kind = r.kind;
    row.innerHTML = '<span class="row-text"><span class="row-label"></span><span class="muted small"></span></span>'
      + '<span class="st-ctl"><select class="st-look"></select>'
      + '<label class="st-vc"><input type="checkbox" class="switch"><span class="muted small">Voice commands</span></label></span>';
    $(".row-label", row).textContent = r.label; $(".muted", row).textContent = r.apps;
    const sel = $(".st-look", row), mine = [!!r.capital, !!r.full_stop];
    const looks = ST_LOOKS.some(([c, f]) => c === mine[0] && f === mine[1]) ? ST_LOOKS : [...ST_LOOKS, mine];  // a saved mix the menu lacks stays
    for (const [c, f] of looks) {
      const o = document.createElement("option"); o.value = `${+c},${+f}`; o.textContent = stSample(c, f); sel.append(o);
    }
    sel.value = `${+mine[0]},${+mine[1]}`;
    sel.setAttribute("aria-label", `${r.label}: how a sentence comes out`);
    const vc = $(".st-vc input", row); vc.checked = !!r.commands;
    sel.onchange = vc.onchange = () => { stylesState(); dirty(); };
    body.append(row);
  }
  stylesState();
}
function stylesState() {
  const on = $("#f-per-app").checked, vc = $("#f-voice-commands").checked;
  $("#st-wrap").classList.toggle("off", !on);
  for (const row of $$("#st-rows .st-row")) {
    $(".st-look", row).disabled = !on;
    $(".st-vc input", row).disabled = !on || !vc;
  }
  $("#st-vc-off").hidden = !on || vc;
}
// Languages you dictate in (dictado-ehs): English, plus the ones the user added from "Add a language".
// dictado-607: a built-in language nobody ticked (Swedish) waits in the picker like any other, so the
// card, the voice commands and the meeting lists show only the user's own languages.
let extraLangs = [], langNames = {}, baseLangs = ["en", "sv"], shownBase = [];
function langCard(on) {
  const box = $("#f-languages");
  box.innerHTML = "";
  for (const code of ["en", ...shownBase, ...extraLangs]) {
    const l = document.createElement("label"); l.className = "lang-check";
    const i = document.createElement("input"); i.type = "checkbox"; i.value = code; i.checked = on.has(code);
    i.onchange = () => { if (!$$("#f-languages input:checked").length) i.checked = true; phraseTables(); dirty(); };  // at least one
    l.append(i, document.createTextNode(langNames[code] || code));
    if (code !== "en") {
      const x = document.createElement("button"); x.type = "button"; x.className = "lang-x"; x.textContent = "×";
      x.title = `Remove ${langNames[code] || code}`; x.setAttribute("aria-label", x.title);
      x.onclick = (e) => { e.preventDefault(); extraLangs = extraLangs.filter((c) => c !== code); shownBase = shownBase.filter((c) => c !== code);
        const checks = currentChecks(on); checks.delete(code); if (![...checks].length) checks.add("en");
        langCard(checks); dirty(); };
      l.append(x);
    }
    box.append(l);
  }
  const add = $("#lang-add");
  add.innerHTML = '<option value="">Add a language…</option>';
  for (const [code, label] of Object.entries(langNames).sort((a, b) => a[1].localeCompare(b[1]))) {
    if (code === "en" || shownBase.includes(code) || extraLangs.includes(code)) continue;
    const o = document.createElement("option"); o.value = code; o.textContent = label; add.append(o);
  }
  add.onchange = () => {
    if (!add.value) return;
    (baseLangs.includes(add.value) ? shownBase : extraLangs).push(add.value);
    const checks = currentChecks(on); checks.add(add.value);  // a new language is ticked right away
    langCard(checks); dirty();
  };
  phraseTables();
}
// The user's own languages (dictado-607): ticked or added in the card above.
function myLangs() {
  return [...new Set([...$$("#f-languages input:checked").map((i) => i.value), ...extraLangs])];
}
const andList = (xs) => xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1];
let vcList = [], scList = [];
// Voice commands and the self-correction phrases: English (they always work), then the user's other
// languages that have phrases; nobody sees Spanish or Swedish they never added (dictado-607).
function phraseTables() {
  const mine = myLangs(), cols = ["en", ...mine.filter((c) => c !== "en")];
  const label = (c) => langNames[c] || DICT_LANGS[c] || c;
  const table = (head, body, rows) => {
    const have = cols.filter((c) => c === "en" || rows.some((r) => r[c]));
    head.innerHTML = "";
    for (const t of ["What it does", ...have.map(label)]) { const th = document.createElement("th"); th.textContent = t; head.append(th); }
    body.innerHTML = "";
    for (const r of rows) {
      const tr = document.createElement("tr");
      for (const k of ["what", ...have]) { const td = document.createElement("td"); td.textContent = r[k] || ""; tr.append(td); }
      body.append(tr);
    }
  };
  vcEditor();  // the voice commands: the user's own phrases, per language (dictado-67v)
  table($("#sc-head"), $("#sc-rows"), scList);
  const first = (key, c) => { const p = vcPhrases(vcList.find((r) => r.key === key) || {}, c)[0]; return p && `"${p}"`; };
  const more = cols.filter((c) => c !== "en" && vcList.some((r) => vcPhrases(r, c).length));
  const eg = more.flatMap((c) => [first("line", c), first("enter", c)]).filter(Boolean);
  $("#vc-help").textContent = 'Say "new line" or "new paragraph" for a break, and end with "send it" to press Enter after the text (handy in Claude Code).'
    + (more.length ? ` ${andList(more.map(label))} work${more.length === 1 ? "s" : ""} too: ${eg.join(", ")}.` : "");
}
// Voice commands > See all commands (dictado-67v): the phrases are the user's to change, per action and
// language: English (built in for everyone) and the user's other languages. × removes one, typing and
// Enter adds one, Reset puts a cell back to the built-in phrases. Saved as [text] voice_phrases (only
// what differs), and the real matcher uses it.
let vcCustom = {};
function vcCols() { return ["en", ...myLangs().filter((c) => c !== "en")]; }
const vcLabel = (c) => langNames[c] || DICT_LANGS[c] || c;
const vcSame = (a, b) => JSON.stringify(a || []) === JSON.stringify(b || []);
function vcPhrases(row, lang) { return (vcCustom[row.key] || {})[lang] ?? (row.builtin || {})[lang] ?? []; }
function vcSet(row, lang, list) {
  const cell = { ...(vcCustom[row.key] || {}) };
  if (vcSame(list, row.builtin[lang] || [])) delete cell[lang]; else cell[lang] = list;
  if (Object.keys(cell).length) vcCustom[row.key] = cell; else delete vcCustom[row.key];
  phraseTables(); dirty();  // the help line names the first phrases too
}
function vcSaved() {  // what formValues() saves: commands in table order, languages sorted
  const out = {};
  for (const r of vcList) {
    const c = vcCustom[r.key];
    if (c) out[r.key] = Object.fromEntries(Object.keys(c).sort().map((l) => [l, c[l]]));
  }
  return out;
}
function vcAdd(row, lang, input) {
  const p = input.value.toLowerCase().replace(/\s+/g, " ").replace(/^[\s.,;:!?"“”']+|[\s.,;:!?"“”']+$/g, "").slice(0, 40);
  if (!p) return;
  const other = vcList.find((r) => r.key !== row.key && vcCols().concat(Object.keys(r.builtin || {})).some((l) => vcPhrases(r, l).includes(p)));
  if (other) { toast(`“${p}” is already ${other.what.split(" (")[0]}: keep it in one.`); input.select(); return; }
  const list = vcPhrases(row, lang);
  if (list.includes(p)) { input.value = ""; return; }
  if (list.length >= 8) { toast("Up to 8 phrases each."); return; }
  vcSet(row, lang, [...list, p]);
  $(`.vc-add[data-key="${row.key}"][data-lang="${lang}"]`)?.focus();
}
function vcEditor() {
  const cols = vcCols(), head = $("#vc-list thead tr"), body = $("#vc-rows");
  head.replaceChildren(...["What it does", ...cols.map(vcLabel)].map((t) => { const th = document.createElement("th"); th.textContent = t; return th; }));
  body.replaceChildren();
  for (const r of vcList) {
    const tr = document.createElement("tr"), what = document.createElement("td");
    what.textContent = r.what; tr.append(what);
    for (const lang of cols) {
      const td = document.createElement("td"), box = document.createElement("div"); box.className = "vc-cell";
      for (const p of vcPhrases(r, lang)) {
        const chip = document.createElement("span"); chip.className = "vc-chip"; chip.textContent = p;
        const x = document.createElement("button"); x.type = "button"; x.className = "vc-x"; x.textContent = "×";
        x.title = `Remove “${p}”`; x.setAttribute("aria-label", x.title);
        x.onclick = () => vcSet(r, lang, vcPhrases(r, lang).filter((q) => q !== p));
        chip.append(x); box.append(chip);
      }
      const add = document.createElement("input"); add.className = "vc-add"; add.maxLength = 40; add.spellcheck = false;
      add.placeholder = "Add…"; add.dataset.key = r.key; add.dataset.lang = lang;
      add.setAttribute("aria-label", `Add a ${vcLabel(lang)} phrase for ${r.what.split(" (")[0].toLowerCase()}`);
      add.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); vcAdd(r, lang, add); } };
      add.onchange = (e) => e.stopPropagation();  // typing isn't a change until it's added
      add.oninput = (e) => e.stopPropagation();
      box.append(add);
      if (!vcSame(vcPhrases(r, lang), r.builtin[lang] || [])) {
        const back = document.createElement("button"); back.type = "button"; back.className = "vc-reset";
        back.textContent = "Reset"; back.title = (r.builtin[lang] || []).length ? `Back to ${r.builtin[lang].map((q) => `“${q}”`).join(", ")}` : "Back to none";
        back.onclick = () => vcSet(r, lang, r.builtin[lang] || []);
        box.append(back);
      }
      td.append(box); tr.append(td);
    }
    body.append(tr);
  }
  $("#vc-reset-all").hidden = !Object.keys(vcCustom).length;
}
function currentChecks(fallback) {
  const boxes = $$("#f-languages input");
  return boxes.length ? new Set(boxes.filter((i) => i.checked).map((i) => i.value)) : fallback;
}
function snipRow(trigger = "", text = "") {
  const row = document.createElement("div");
  row.className = "snip";
  row.innerHTML = `<input class="snip-trigger" placeholder="Name you say: my email" maxlength="60" spellcheck="false">
    <textarea class="snip-text vocab" rows="2" placeholder="Text it types"></textarea>
    <button type="button" class="btn btn-ghost btn-sm snip-del" title="Remove this snippet">Remove</button>`;
  $(".snip-trigger", row).value = trigger; $(".snip-text", row).value = text;
  $(".snip-del", row).onclick = () => { row.remove(); dirty(); };
  $("#snips").append(row);
  return row;
}
function repRow(heard = "", write = "") {  // Replace: heard -> write (dictado-b7u)
  const row = document.createElement("div");
  row.className = "rep";
  row.innerHTML = `<input class="rep-heard rep-input" placeholder="poll request" maxlength="60" spellcheck="false" aria-label="When it writes">
    <span class="rep-arrow" aria-hidden="true">→</span>
    <input class="rep-write rep-input" placeholder="pull request" maxlength="200" spellcheck="false" aria-label="Write instead">
    <button type="button" class="btn btn-ghost btn-sm snip-del" title="Remove this replacement">Remove</button>`;
  $(".rep-heard", row).value = heard; $(".rep-write", row).value = write;
  $(".snip-del", row).onclick = () => { row.remove(); dirty(); };
  $("#reps").append(row);
  return row;
}
function fillSelect(sel, options, value) {
  sel.innerHTML = "";
  for (const o of options) {
    const opt = document.createElement("option");
    opt.value = o.value; opt.textContent = o.label;
    sel.append(opt);
  }
  sel.value = value;
}
/* Settings > Speech models (dictado-z4q): what each model is for, on disk or not, download / delete. */
async function renderModelsPage() {
  let info, p;
  try { [info, p] = [await api.models_info(), await api.setup_models_progress()]; } catch { return; }
  const box = $("#m-rows");
  box.innerHTML = info.models.map((m) => {
    const g = (p.models || {})[m.name] || {};
    const going = p.running && p.models[m.name] && !g.ready;
    const total = g.total || m.size;
    const pct = going && g.done ? Math.min(99, Math.round((100 * g.done) / total)) : 0;
    const tag = m.required ? '<span class="s-tag req">In use</span>' : '<span class="s-tag">Recommended</span>';
    const state = m.ready ? `${gb(m.disk || m.size)} on this computer` : going ? (g.done ? `Downloading: ${gb(g.done)} of ${gb(total)}` : "Waiting…")
      : `Not downloaded · ${gb(m.size)}`;
    const act = m.ready ? `<button type="button" class="btn btn-ghost btn-sm" data-del="${m.name}">Delete</button>`
      : going ? "" : `<button type="button" class="btn btn-ghost btn-sm" data-get="${m.name}">Download</button>`;
    return `<div class="row m-row"><span class="row-text"><span class="row-label">${m.label} ${tag}</span>
      <span class="muted small">${m.use}</span>
      ${going ? `<div class="s-progress"><div style="width:${pct}%"></div></div>` : ""}
      <span class="muted small">${state}</span></span>${act}</div>`;
  }).join("") + (p.error ? `<p class="muted small m-err">Download stopped: ${p.error}</p>` : "");
  $$("#m-rows [data-get]").forEach((b) => (b.onclick = async () => { await api.setup_models_start([b.dataset.get]); renderModelsPage(); watchModelsPage(); }));
  $$("#m-rows [data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this model? It downloads again the next time it's needed.")) return;
    const r = await api.delete_model(b.dataset.del);
    toast(r.ok ? "Deleted. The space is free." : r.error || "Couldn't delete it.");
    renderModelsPage();
  }));
  if (p.running) watchModelsPage();
}
let mPoll = null;
function watchModelsPage() {
  if (mPoll) return;
  mPoll = setInterval(async () => {
    const p = await api.setup_models_progress();
    if ($("#page-ajustes").hidden) { clearInterval(mPoll); mPoll = null; return; }
    if (!p.running) { clearInterval(mPoll); mPoll = null; }
    renderModelsPage();
  }, 700);
}

async function renderSettings() {
  renderModelsPage();
  const s = await api.get_settings();
  $("#f-hotkey").value = s.values.hotkey;
  $("#hk-label").textContent = s.values.hotkey_label || hotkeyLabel(s.values.hotkey);
  fillSelect($("#f-mic"), s.options.mics, s.values.mic);
  fillSelect($("#f-meet-mode"), s.options.meet_modes, s.values.meet_mode);
  fillSelect($("#f-meet-end"), s.options.meet_ends, s.values.meet_end);
  fillSelect($("#f-meet-lang"), s.options.meet_langs, s.values.meet_lang);
  $("#f-on-demand").checked = s.values.on_demand;
  $("#f-vocabulary").value = s.values.vocabulary || "";
  $("#f-voice-commands").checked = !!s.values.voice_commands;
  $("#f-self-corrections").checked = !!s.values.self_corrections;  // dictado-bd6
  $("#f-command-mode").checked = !!s.values.command_mode;
  $("#cm-block").hidden = MAC;  // the Mac has no command mode yet (dictado-waw)
  $("#f-command-key").value = s.values.command_key || "e";  // dictado-a1d
  cmPaint();
  $("#f-screen-names").checked = s.values.screen_names !== false;
  $("#f-hold").checked = !!s.values.hold_to_talk; $("#f-numpad-enter").checked = !!s.values.numpad_enter;
  holdFits();
  claudeRow(); gcalRow(); exportRow(s.values);
  $("#f-voice-memory").checked = s.values.voice_memory !== false;
  voicesRow();
  $("#f-calendar").value = s.values.calendar_url || "";
  $("#f-my-name").value = s.values.my_name || "";
  $("#f-debug-log").checked = !!s.values.debug_log;
  $("#f-update-check").checked = s.values.update_check !== false;
  $("#f-auto-update").checked = !!s.values.auto_update;  // dictado-nmo: off by default
  $("#row-auto-update").hidden = !s.auto_update_supported;  // the Mac: Download only (dictado-6gr)
  fillSelect($("#f-theme"), s.options.themes || [{ value: "system", label: "Match Windows" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }],
             s.values.theme || "system");
  applyTheme(s.values.theme || "system");  // back to the saved one (Discard, or a preview left unsaved)
  $("#f-theme").onchange = () => { applyTheme($("#f-theme").value, false); dirty(); };  // a preview until Save
  if (params.get("vc") === "1") $("#vc-list").open = true;  // screenshot
  vcCustom = JSON.parse(JSON.stringify(s.values.voice_phrases || {}));  // dictado-67v
  $("#vc-reset-all").onclick = () => { vcCustom = {}; phraseTables(); dirty(); };
  if (params.get("sc") === "1") $("#sc-list").open = true;  // screenshot
  vcList = s.voice_command_list || []; scList = s.correction_list || [];  // drawn after the language card (phraseTables)
  $("#dbg-copy").onclick = async () => { await api.copy_debug_info(); toast("Copied. Paste it to Claude."); };
  $("#dbg-open").onclick = () => api.open_logs_folder();
  $("#cal-result").textContent = "";
  $("#cal-test").onclick = calendarTest;
  $("#snips").innerHTML = "";
  for (const x of s.values.snippets || []) snipRow(x.trigger, x.text);
  $("#snip-add").onclick = () => { $(".snip-trigger", snipRow()).focus(); };
  $("#reps").innerHTML = "";
  for (const x of s.values.replacements || []) repRow(x.heard, x.write);
  $("#rep-add").onclick = () => { $(".rep-heard", repRow()).focus(); };
  $("#f-per-app").checked = !!s.values.per_app_styles;
  stylesCard(s.values.app_styles);
  $("#f-per-app").onchange = $("#f-voice-commands").onchange = () => { stylesState(); dirty(); };
  if (params.get("styles") === "1") $("#styles-card").scrollIntoView?.({ block: "start" });  // screenshot
  if (params.get("vc") === "1") $("#f-voice-commands").closest(".row").scrollIntoView?.({ block: "start" });  // screenshot
  $("#f-speakers").checked = s.values.speakers && s.speakers_addon;
  $("#f-speakers").disabled = !s.speakers_addon;
  $("#f-speakers-help").textContent = s.speakers_addon
    ? "After a call, the other side is split into Speaker 1, 2, 3… Click a name in a transcript to rename that person."
    : MAC ? "Needs the speaker add-on (Ecoscribe Speakers, drag it to Applications), which isn't installed." : "Needs the speaker add-on (Ecoscribe-Speakers-Setup), which isn't installed.";
  extraLangs = [...(s.values.extra_languages || [])];
  langNames = Object.fromEntries([...s.options.languages, ...(s.options.all_languages || [])].map((o) => [o.value, o.label]));
  baseLangs = s.options.base_languages || ["en", "sv"];
  shownBase = String(s.values.languages || "en").split(",").filter((c) => baseLangs.includes(c) && c !== "en");
  langCard(new Set(String(s.values.languages || "en").split(",")));
  $("#lang-key").textContent = hotkeyLabel(s.values.hotkey || "rctrl");
  $("#f-sounds").checked = s.values.sounds; $("#f-overlay").checked = s.values.overlay; $("#f-live-text").checked = s.values.live_text !== false; $("#f-insights").checked = !!s.values.insights; $("#f-speech-feedback").checked = !!s.values.speech_feedback;
  $("#nav-insights").hidden = !s.values.insights;
  $("#f-unmute").checked = s.values.unmute; $("#f-startup").checked = s.values.startup;
  $("#f-startup").disabled = !s.can_startup;
  $("#startup-hint").textContent = s.can_startup ? "Ecoscribe starts by itself when you sign in." : "Available in the installed version.";
  saved = formValues();
  dirty();
}
function dirty() {
  if (!saved) return;
  const changed = JSON.stringify(formValues()) !== JSON.stringify(saved);
  $("#savebar").hidden = !changed;
  $("#savebar-text").textContent = "You have unsaved changes.";
}
async function save() {
  const btn = $("#save");
  btn.disabled = true;
  const v = formValues();
  const changed = Object.fromEntries(Object.entries(v).filter(([k, x]) => JSON.stringify(saved[k]) !== JSON.stringify(x)));
  let r;
  try { r = await api.save_settings(changed); } catch (e) { r = { ok: false, error: String(e) }; }
  finally { btn.disabled = false; }
  if (!r.ok) { toast(`Couldn't save: ${r.error}`); return; }
  saved = v;
  $("#savebar").hidden = true;
  if ("insights" in changed) $("#nav-insights").hidden = !v.insights;
  if ("theme" in changed) applyTheme(v.theme);
  const needsRestart = Object.keys(changed).some((k) => k !== "startup" && k !== "insights" && k !== "theme");
  toast(!needsRestart ? "Saved." : r.restarting ? "Saved. Ecoscribe restarts, a few seconds."
    : "Saved. It applies the next time Ecoscribe starts.");
  refreshStatus();
}
/* One mic-test controller for Ajustes and the welcome. `on` flips synchronously so a
   double click or a fast page change can't start two tests; a start that resolves after
   a newer start/stop is stale and gets undone. */
const mic = { on: false, token: 0, timer: null };
async function micStart(device, onLevel) {
  const my = ++mic.token;
  mic.on = true;
  clearInterval(mic.timer); mic.timer = null;
  let r;
  try { r = await api.mic_test_start(device); } catch (e) { r = { error: String(e) }; }
  if (my !== mic.token) {                       // superseded while starting
    if (!mic.on) await api.mic_test_stop();     // ...by a stop: make sure nothing stays open
    return null;
  }
  if (r.error) { mic.on = false; toast("Couldn't open the mic."); return r; }
  mic.timer = setInterval(async () => {
    const lvl = await api.mic_test_level();
    if (my === mic.token && mic.on) onLevel(lvl);
  }, 80);
  return r;
}
async function micStop() {
  if (!mic.on) return;
  mic.token++; mic.on = false;
  clearInterval(mic.timer); mic.timer = null;
  await api.mic_test_stop();
}
const meterWidth = (lvl) => `${Math.min(100, Math.sqrt(lvl) * 260)}%`;

async function startMicTest() {
  $("#mic-test").textContent = "Stop";
  $("#meter").classList.add("live");
  const r = await micStart($("#f-mic").value, (lvl) => { $("#meter-fill").style.width = meterWidth(lvl); });
  if (!mic.on) resetMeter();
  return r;
}
function resetMeter() {
  $("#mic-test").textContent = "Test";
  $("#meter").classList.remove("live");
  $("#meter-fill").style.width = "0";
}
async function stopMicTest() {
  await micStop();
  resetMeter();
}

/* Shortcut recorder: Change, then tap a lone key or press a combo; Python validates it. */
const HK_CODE = MAC ? { MetaRight: "rcmd", ControlRight: "rctrl", Fn: "fn" } : { ControlRight: "rctrl", ScrollLock: "scrolllock", Pause: "pause" };
const HK_HINT = MAC ? "Tap a lone key (Right Command, Fn, F13-F19) or press a combo like Shift+Cmd+D."
  : "Tap a lone key (Right Ctrl, F13-F24, Pause) or press a combo like Ctrl+L.";
const HK_MODS = new Set(["ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight"]);
async function voicesRow() {
  const v = await api.voices_info().catch(() => ({ count: 0, names: [] }));
  $("#voices-row").hidden = !v.count;
  $("#voices-known").textContent = v.count ? `Knows ${v.count} voice${v.count > 1 ? "s" : ""}: ${v.names.join(", ")}` : "";
  $("#voices-forget").onclick = async () => {
    if (!confirm("Forget every voice Ecoscribe has learned? Names already in transcripts stay.")) return;
    await api.forget_voices(); toast("Voices forgotten."); voicesRow();
  };
}
async function calendarTest() {  // t0u.35: download the link now and say what it found
  const out = $("#cal-result"), b = $("#cal-test");
  b.disabled = true; out.textContent = "Reading the calendar…";
  const r = await api.test_calendar($("#f-calendar").value.trim()).catch(() => ({ ok: false, error: "Couldn't test the link." }));
  b.disabled = false;
  out.textContent = !r.ok ? r.error
    : `Works: ${r.today} event${r.today === 1 ? "" : "s"} today.` + (r.now ? ` Right now: ${r.now}.` : "") + " Save to use it.";
}
async function gcalRow() {  // dictado-k19: sign in to Google Calendar instead of the iCal link
  const st = await api.google_calendar().catch(() => ({ connected: false, client: false }));
  const b = $("#gcal-connect"), out = $("#gcal-result");
  $("#gcal-row").hidden = !st.client && !st.connected;
  b.textContent = st.connected ? "Disconnect" : "Connect";
  b.disabled = false;
  b.onclick = async () => {
    if (st.connected) {
      if (!confirm("Disconnect Google Calendar? Meetings stop taking names and guests from it.")) return;
      await api.disconnect_google(); out.textContent = ""; toast("Google Calendar disconnected."); gcalRow(); return;
    }
    b.disabled = true; out.textContent = "Sign in in the browser window that just opened…";
    const r = await api.connect_google().catch(() => ({ ok: false, error: "Couldn't connect to Google. Try again." }));
    out.textContent = !r.ok ? r.error
      : `Connected: ${r.today} event${r.today === 1 ? "" : "s"} today.` + (r.now ? ` Right now: ${r.now}.` : "");
    gcalRow();
  };
}
function exportRow(v) {  // dictado-yq9: where Download puts transcripts
  $("#export-dir").textContent = v.export_dir; $("#export-dir").title = v.export_dir;
  $("#export-reset").hidden = !!v.export_default;
  const done = (r) => { if (r.ok) { exportRow(r); toast("Downloads now go to " + r.export_dir); } else if (r.error) toast(r.error); };
  $("#export-change").onclick = async () => done(await api.pick_export_dir());
  $("#export-reset").onclick = async () => done(await api.set_export_dir(""));
}
async function claudeRow() {
  const st = await api.claude_app().catch(() => ({ connected: false }));
  const b = $("#claude-connect");
  b.textContent = st.connected ? "Connected" : "Connect";
  b.disabled = st.connected;
  b.onclick = async () => {
    const out = await api.connect_claude_app();
    if (!out.ok) { toast(out.error || "Couldn't connect."); return; }
    toast("Done. Quit and reopen the Claude app, then ask it about your meetings.");
    claudeRow();
  };
}
function holdFits() {  // hold-to-talk needs a lone key: a combo fires on its press
  const combo = ($("#f-hotkey").value || "").includes("+");
  $("#f-hold").disabled = combo;
  if (combo) $("#f-hold").checked = false;
  $("#f-hold-help").textContent = combo ? `Needs a lone key like ${MAC ? "Right Command" : "Right Ctrl"}: a combo can't be held.`
    : "Hold the key while you speak and let go to stop. A quick tap still starts hands-free dictation.";
}
const hk = { other: false };  // the setup's key step (sKeyRecord)
function hkName(e) {
  const c = e.code;
  if (/^Key[A-Z]$/.test(c)) return c.slice(3).toLowerCase();
  if (/^Digit\d$/.test(c)) return c.slice(5);
  if (/^F\d{1,2}$/.test(c)) return c.toLowerCase();
  return HK_CODE[c] || c.toLowerCase();
}
// A key picker: click Change, press the keys (dictado-a1d: the dictation key's, reused for Command mode).
// o: label, input, button, hint (elements); idle() the hint at rest; shown() the label at rest;
// check(value) -> {ok, value, label, error}; done(r) the hint after a pick; lone: a lone modifier tap
// counts; chord(): the browser code of a held key that makes "<key>+<letter>" (Command mode's
// dictation key + E), or null; listening() the hint while it listens; words: the button's two texts.
// An empty hint is hidden.
function keyPicker(o) {
  const st = { on: false, other: false, held: new Set() };
  const [rest, busy] = o.words || ["Change", "Cancel"];
  const stop = (msg, bad = false) => {
    st.on = false;
    o.button.textContent = rest;
    o.label.classList.remove("listening");
    o.hint.textContent = msg || o.idle();
    o.hint.classList.toggle("hk-bad", bad);
    o.hint.hidden = !o.hint.textContent;
  };
  const tryIt = async (value) => {
    const r = await o.check(value);
    if (!r.ok) { stop(r.error, true); o.label.textContent = o.shown(); return; }
    o.input.value = r.value;
    o.label.textContent = r.label;
    stop(o.done(r));
    o.after?.();
    dirty();
  };
  o.button.onclick = () => {
    if (st.on) { stop(); o.label.textContent = o.shown(); return; }
    st.on = true; st.other = false; st.held.clear();
    o.button.textContent = busy;
    o.label.textContent = "Press it now…";
    o.label.classList.add("listening");
    o.hint.textContent = o.listening?.() || "Esc cancels.";
    o.hint.classList.remove("hk-bad");
    o.hint.hidden = false;
  };
  document.addEventListener("keydown", (e) => {
    if (!st.on) return;
    e.preventDefault(); e.stopPropagation();
    if (e.code === "Escape" && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) { stop(); o.label.textContent = o.shown(); return; }
    const chord = o.chord?.();
    if (HK_MODS.has(e.code) || (chord && e.code === chord)) { st.held.add(e.code); return; }  // wait: a combo or a lone modifier tap
    st.other = true;
    if (chord && st.held.has(chord) && [...st.held].every((c) => c === chord)) { tryIt(`${HK_CODE[chord] || chord.toLowerCase()}+${hkName(e)}`); return; }
    const mods = [e.ctrlKey && "ctrl", e.altKey && "alt", e.shiftKey && "shift", e.metaKey && (MAC ? "cmd" : "win")].filter(Boolean);
    tryIt([...mods, hkName(e)].join("+"));
  }, true);
  document.addEventListener("keyup", (e) => {
    if (!st.on) return;
    e.preventDefault();
    st.held.delete(e.code);
    if (o.lone && HK_MODS.has(e.code) && !st.other) tryIt(hkName(e));  // a lone modifier tap, e.g. Right Ctrl
  }, true);
  return { stop };
}
// Command mode's keys (dictado-a1d): the dictation key + a letter (E), or a combo of its own. Look B
// (picked): the keys sit in the row's sentence with a "change" link; the hint shows only while picking.
const CM_HOW = () => ($("#f-hotkey").value || "").includes("+")
  ? "Press a combo like Ctrl+Shift+E. Esc cancels."
  : `Hold ${hotkeyLabel($("#f-hotkey").value)} and press a letter, or press a combo like Ctrl+Shift+E. Esc cancels.`;
const CM_BAD = "The dictation key is a combo now: change Command mode's keys to a combo too, like Ctrl+Shift+E.";
function cmText() {  // the keys as words, from the form (the dictation key may have changed, unsaved)
  const key = $("#f-command-key").value || "e", dict = $("#f-hotkey").value;
  if (key.includes("+")) return hotkeyLabel(key);
  return dict.includes("+") ? "" : `${hotkeyLabel(dict)} + ${key.toUpperCase()}`;
}
function cmPaint() {
  const t = cmText(), key = $("#f-command-key").value || "e";
  $("#cm-press").textContent = t || "its keys";
  const stop = $("#cm-stop"), k = document.createElement("kbd"); k.className = "cm-key";
  k.textContent = key.includes("+") ? t : hotkeyLabel($("#f-hotkey").value);
  stop.replaceChildren(key.includes("+") ? "press " : "tap ", k, key.includes("+") ? " again" : "");
  const bad = !t;
  $("#cm-hint").textContent = bad ? CM_BAD : "";
  $("#cm-hint").classList.toggle("hk-bad", bad);
  $("#cm-hint").hidden = !bad;
}
function hkWire() {
  keyPicker({ label: $("#hk-label"), input: $("#f-hotkey"), button: $("#hk-change"), hint: $("#hk-hint"), lone: true,
    idle: () => HK_HINT, shown: () => hotkeyLabel($("#f-hotkey").value), check: (v) => api.check_hotkey(v),
    done: (r) => r.value.includes("+") ? `${r.label}: press it to start and again to stop. Save to apply.` : `${r.label}: tap it on its own. Save to apply.`,
    after: () => { holdFits(); cmPaint(); } });
  keyPicker({ label: $("#cm-press"), input: $("#f-command-key"), button: $("#cm-change"), hint: $("#cm-hint"),
    words: ["change", "cancel"], listening: CM_HOW, idle: () => (cmText() ? "" : CM_BAD), shown: () => cmText() || "its keys", check: (v) => api.check_command_key(v, $("#f-hotkey").value),
    chord: () => { const k = $("#f-hotkey").value || ""; return k.includes("+") ? null : Object.keys(HK_CODE).find((c) => HK_CODE[c] === k) || (k.startsWith("f") ? k.toUpperCase() : null); },
    done: (r) => `${r.label} starts Command mode. Save to apply.`, after: cmPaint });
}

/* ---------------------------------------------------------------- setup (dictado-zpz) */
// The first run, full window: (Mac) permissions, languages, speech models, mic, key, a first
// dictation, a summary. Each step saves what it changed when you leave it.
const S_COMMON = ["en", "sv", "es", "de", "fr", "el", "fi", "it", "pt", "nl", "da", "no"];
const sx = { steps: [], i: 0, cfg: null, langs: [], extra: [], hotkey: "", hold: false, mic: "",
  models: [], want: new Set(), poll: null, permPoll: null, keyRec: false, rerun: false };
const gb = (n) => (n < 1e9 ? `${Math.round(n / 1e6)} MB` : `${(n / 1e9).toFixed(1)} GB`);
const sKey = () => hotkeyLabel(sx.hotkey);

async function openSetup(rerun = false) {  // the first run can't be skipped; Run setup again can be cancelled
  sx.rerun = rerun === true;
  const st = await api.get_settings();
  sx.cfg = st;
  sx.langs = st.values.languages.split(",").filter(Boolean);
  sx.extra = [...(st.values.extra_languages || [])];
  sx.hotkey = st.values.hotkey; sx.hold = !!st.values.hold_to_talk; sx.mic = st.values.mic || "";
  const info = await api.setup_info(sx.langs.join(","));
  sx.steps = $$(".sstep").map((el) => el.dataset.step).filter((k) => k !== "permissions" || info.permissions.length);
  const label = { permissions: "Permissions", languages: "Languages", models: "Speech models", mic: "Microphone", shortcut: "Dictation key", try: "Try it", done: "Done" };
  $("#s-steps").innerHTML = sx.steps.map((k, i) => `<li data-step="${k}"><span class="s-num">${i + 1}</span>${label[k] || k}</li>`).join("");
  $("#s-bars").innerHTML = Array.from({ length: 12 }, (_, i) => `<i style="height:${18 + i * 4}px"></i>`).join("");
  sx.i = Math.max(0, sx.steps.indexOf(params.get("sstep")));  // ?sstep=models: screenshots of one step
  $("#setup").hidden = false;
  await paintSetup();
}

async function paintSetup() {
  const step = sx.steps[sx.i];
  $$(".sstep").forEach((el) => el.classList.toggle("on", el.dataset.step === step));
  $$("#s-steps li").forEach((el, i) => { el.classList.toggle("done", i < sx.i); el.classList.toggle("on", i === sx.i);
    el.querySelector(".s-num").textContent = i < sx.i ? "✓" : String(i + 1); if (i === sx.i) el.setAttribute("aria-current", "step"); else el.removeAttribute("aria-current"); });
  const eb = $(`.sstep[data-step="${step}"] .s-eyebrow`);
  if (eb && step !== "done") eb.textContent = `Step ${sx.i + 1} of ${sx.steps.length - 1}`;
  $("#s-back").style.visibility = sx.i ? "visible" : "hidden";
  $("#s-skip").hidden = !sx.rerun || step === "done";
  $("#s-next").textContent = step === "done" ? "Start using Ecoscribe" : "Continue →";
  $("#s-next").disabled = false;
  clearInterval(sx.permPoll); sx.permPoll = null;
  if (step !== "mic") await micStop();
  if (step === "permissions") { await paintPerms(); sx.permPoll = setInterval(paintPerms, 2000); }
  if (step === "languages") paintLangs();
  if (step === "models") await paintModels();
  if (step === "mic") await paintMic();
  if (step === "shortcut") paintKey();
  if (step === "try") {
    $$(".s-keyname").forEach((el) => (el.textContent = sKey()));
    $("#s-try-sub").innerHTML = (sx.hold ? "Hold " : "Tap ") + `<strong class="s-keyname">${sKey()}</strong>` +
      (sx.hold ? ", say something, and let go." : ", say something, and tap it again.");
    setTimeout(() => $("#s-try-box").focus(), 50);
  }
  if (step === "done") await paintSummary();
}

async function paintPerms() {
  const info = await api.setup_info(sx.langs.join(","));
  const why = { microphone: "So Ecoscribe can hear you", accessibility: "So it can type into any app",
    input: "So the dictation key works everywhere" };
  $("#s-perms").innerHTML = info.permissions.map((p) => `<div class="s-row">
      <div class="s-row-text"><strong>${p.label}</strong><span class="muted small">${why[p.key] || ""}</span></div>
      ${p.granted ? '<span class="s-ok">✓ On</span>' : `<button type="button" class="btn btn-ghost btn-sm" data-perm="${p.key}">${p.ask ? "Allow" : "Open settings"}</button>`}
    </div>`).join("");
  $$("#s-perms [data-perm]").forEach((b) => (b.onclick = async () => { await api.open_permission(b.dataset.perm); paintPerms(); }));
}

function paintLangs() {  // the chosen languages as chips (✕ removes one), and Add a language
  const all = Object.fromEntries([...sx.cfg.options.languages, ...sx.cfg.options.all_languages].map((o) => [o.value, o.label]));
  $("#s-langs").innerHTML = sx.langs.map((c) => `<span class="s-lchip"><span>${all[c] || c}</span>${sx.langs.length > 1
    ? `<button type="button" class="s-chip-x" data-x="${c}" aria-label="Remove ${all[c] || c}">✕</button>` : ""}</span>`).join("");
  $$("#s-langs [data-x]").forEach((b) => (b.onclick = () => { sx.langs = sx.langs.filter((c) => c !== b.dataset.x); paintLangs(); }));
  const rest = Object.entries(all).filter(([c]) => !sx.langs.includes(c));
  const common = S_COMMON.filter((c) => all[c] && !sx.langs.includes(c)).map((c) => [c, all[c]]);
  const opt = ([c, l]) => `<option value="${c}">${l}</option>`;
  $("#s-lang-more").innerHTML = '<option value="">Add a language…</option>'
    + (common.length ? `<optgroup label="Common">${common.map(opt).join("")}</optgroup>` : "")
    + `<optgroup label="All languages">${rest.sort((x, y) => x[1].localeCompare(y[1])).map(opt).join("")}</optgroup>`;
  $("#s-lang-more").onchange = (e) => { if (e.target.value) { sx.langs.push(e.target.value); paintLangs(); } };
  $("#s-next").disabled = !sx.langs.length;
}

async function saveLangs() {
  const base = sx.cfg.options.base_languages;
  const extra = [...new Set([...sx.extra, ...sx.langs.filter((c) => !base.includes(c))])];
  const r = await api.save_settings({ extra_languages: extra, languages: sx.langs.join(",") });
  if (r && r.ok) sx.extra = extra;
  return r;
}

async function paintModels() {
  const info = await api.setup_info(sx.langs.join(","));
  sx.models = info.models;
  if (!sx.want.size || ![...sx.want].every((n) => sx.models.some((m) => m.name === n))) sx.want = new Set(sx.models.map((m) => m.name));
  sx.models.filter((m) => m.required).forEach((m) => sx.want.add(m.name));
  const p = await api.setup_models_progress();
  renderModels(p);
  if (p.running) watchModels();
}

function renderModels(p) {
  const rows = sx.models.map((m) => {
    const g = (p.models || {})[m.name] || {};
    const ready = m.ready || g.ready;
    const total = g.total || m.size;
    const pct = ready ? 100 : g.done ? Math.min(99, Math.round((100 * g.done) / total)) : 0;
    const going = p.running && g && !ready && sx.want.has(m.name);
    const first = sx.models.find((x) => p.running && (p.models || {})[x.name] && !(p.models[x.name] || {}).ready && sx.want.has(x.name));
    const queued = going && first && first.name !== m.name && !g.done;  // the one after: waits its turn
    const tag = m.required ? "Needed for your languages" : "Recommended";
    const state = ready ? "Ready" : queued ? "Waiting…" : going ? (g.done ? `${gb(g.done)} of ${gb(total)}` : "Starting…") : gb(m.size);
    return `<div class="s-row s-model${ready ? " ready" : ""}">
      <input type="checkbox" data-model="${m.name}" ${sx.want.has(m.name) || ready ? "checked" : ""} ${m.required || ready || p.running ? "disabled" : ""} aria-label="${m.label}">
      <div class="s-row-text"><strong>${m.label} <span class="s-tag${m.required ? " req" : ""}">${tag}</span></strong>
        <span class="muted small">${m.use}</span>
        <div class="s-progress"><div style="width:${pct}%"></div></div>
        <span class="muted small">${state}</span></div>
      ${ready ? '<span class="s-ok">✓</span>' : ""}
    </div>`;
  });
  $("#s-models").innerHTML = rows.join("");
  $$("#s-models [data-model]").forEach((el) => (el.onchange = () => {
    el.checked ? sx.want.add(el.dataset.model) : sx.want.delete(el.dataset.model); renderModels(p);
  }));
  const todo = sx.models.filter((m) => sx.want.has(m.name) && !(m.ready || (p.models[m.name] || {}).ready));
  const reqReady = sx.models.filter((m) => m.required).every((m) => m.ready || (p.models[m.name] || {}).ready);
  $("#s-download").hidden = !todo.length || p.running;
  $("#s-download").textContent = `Download ${gb(todo.reduce((n, m) => n + m.size, 0))}`;
  $("#s-models-note").textContent = p.error ? `Download stopped: ${p.error}. Check the connection and try again.`
    : p.running ? (reqReady ? "You can go on; the rest keeps downloading." : "Keep this window open while it downloads.")
    : !todo.length ? "All set, nothing to download." : "";
  if (p.error) $("#s-download").textContent = "Try again";
  if (sx.steps[sx.i] === "models") $("#s-next").disabled = !reqReady;
}

function watchModels() {
  clearInterval(sx.poll);
  sx.poll = setInterval(async () => {
    const p = await api.setup_models_progress();
    if (sx.steps[sx.i] === "models") renderModels(p);
    if (!p.running) { clearInterval(sx.poll); sx.poll = null; if (sx.steps[sx.i] === "models") paintModels(); }
  }, 500);
}

async function paintMic() {
  const mics = sx.cfg.options.mics;
  $("#s-mic").innerHTML = mics.map((m) => `<option value="${m.value}">${m.label}</option>`).join("");
  $("#s-mic").value = sx.mic;
  $("#s-mic").onchange = async () => { sx.mic = $("#s-mic").value; await micStop(); paintMic(); };
  const bars = $$("#s-bars i");
  await micStart(sx.mic, (lvl) => {
    const n = Math.round(Math.min(1, Math.sqrt(lvl) * 2.6) * bars.length);
    bars.forEach((b, i) => b.classList.toggle("on", i < n));
  });
}

function paintKey() {
  $("#s-key").textContent = sKey();
  $$('input[name="s-mode"]').forEach((r) => { r.checked = (r.value === "hold") === sx.hold; r.onchange = () => (sx.hold = r.value === "hold"); });
}

function sKeyRecord() {
  sx.keyRec = !sx.keyRec;
  hk.other = false;
  $("#s-key-change").textContent = sx.keyRec ? "Cancel" : "Change key";
  $("#s-key").textContent = sx.keyRec ? "Press it now…" : sKey();
  $("#s-key").classList.toggle("listening", sx.keyRec);
  $("#s-key-hint").hidden = !sx.keyRec;
  $("#s-key-hint").textContent = "A lone key (Right Ctrl, F13-F24, Pause) or a combo like Ctrl+L. Esc cancels.";
}
async function sKeyTry(v) {
  const r = await api.check_hotkey(v);
  if (!r.ok) { $("#s-key-hint").textContent = r.error; return; }
  sx.hotkey = r.value; sKeyRecord();
}

async function paintSummary() {
  const lab = Object.fromEntries([...sx.cfg.options.languages, ...sx.cfg.options.all_languages].map((o) => [o.value, o.label]));
  const [info, p] = [await api.setup_info(sx.langs.join(",")), await api.setup_models_progress()];
  const ready = info.models.map((m) => (m.ready || (p.models[m.name] || {}).ready ? m.label
    : p.running && p.models[m.name] ? `${m.label} (still downloading)` : "")).filter(Boolean);
  const micLabel = (sx.cfg.options.mics.find((m) => m.value === sx.mic) || {}).label || DEFAULT_MIC;
  const rows = [
    ["Languages", sx.langs.map((c) => lab[c] || c).join(", ")],
    ["Speech models", ready.join(" + ") || "Download when first needed"],
    ["Dictation key", `${sx.hold ? "Hold" : "Tap"} <kbd class="key">${sKey()}</kbd>`],
    ["Microphone", micLabel],
  ];
  const off = info.permissions.filter((x) => !x.granted).map((x) => x.label);  // Mac: the key stays dead without them
  if (off.length) rows.push(["Permissions", `Still off: ${off.join(", ")}. Turn them on in System Settings.`, false]);
  $("#s-summary").innerHTML = rows.map(([k, v, ok = true]) => `<div class="s-row"><div class="s-row-text"><strong>${k}</strong><span class="muted small">${v}</span></div>${ok ? '<span class="s-ok">✓</span>' : ""}</div>`).join("");
}

async function leaveStep(step) {  // save what this step changed; false keeps you on it
  if (step === "languages") {
    const r = await saveLangs();
    if (!r || !r.ok) { toast((r && r.error) || "Couldn't save the languages."); return false; }
    sx.want = new Set();
  }
  if (step === "mic") { await micStop(); await api.save_settings({ mic: sx.mic }); }
  if (step === "shortcut") {
    if (sx.keyRec) sKeyRecord();
    const r = await api.save_settings({ hotkey: sx.hotkey, hold_to_talk: sx.hold });
    if (!r || !r.ok) { toast((r && r.error) || "Couldn't save the key."); return false; }
  }
  return true;
}

async function setupNext() {
  const step = sx.steps[sx.i];
  if (step === "done") return closeSetup();
  $("#s-next").disabled = true;
  const ok = await leaveStep(step);
  $("#s-next").disabled = false;
  if (!ok) return;
  sx.i += 1; await paintSetup();
}
async function setupBack() { if (sx.i) { await micStop(); sx.i -= 1; await paintSetup(); } }

async function closeSetup() {
  await micStop();
  clearInterval(sx.permPoll); sx.permPoll = null;
  if (sx.keyRec) sKeyRecord();
  await api.finish_welcome();
  $("#setup").hidden = true;
  show("inicio");
}

function setupWire() {
  $("#s-next").onclick = setupNext;
  $("#s-back").onclick = setupBack;
  $("#s-skip").onclick = closeSetup;
  $("#setup-again").onclick = () => openSetup(true);
  $("#s-download").onclick = async () => {
    const names = sx.models.filter((m) => sx.want.has(m.name)).map((m) => m.name);
    renderModels(await api.setup_models_start(names));
    watchModels();
  };
  $("#s-try-box").addEventListener("input", () => { $("#s-try-ok").hidden = !$("#s-try-box").value.trim(); });
  $("#s-key-change").onclick = sKeyRecord;
  document.addEventListener("keydown", (e) => {
    if (!sx.keyRec) return;
    e.preventDefault(); e.stopPropagation();
    if (e.code === "Escape" && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) { sKeyRecord(); return; }
    if (HK_MODS.has(e.code)) return;
    hk.other = true;
    const mods = [e.ctrlKey && "ctrl", e.altKey && "alt", e.shiftKey && "shift", e.metaKey && (MAC ? "cmd" : "win")].filter(Boolean);
    sKeyTry([...mods, hkName(e)].join("+"));
  }, true);
  document.addEventListener("keyup", (e) => {
    if (!sx.keyRec) return;
    e.preventDefault();
    if (HK_MODS.has(e.code) && !hk.other) sKeyTry(hkName(e));
  }, true);
  document.addEventListener("keydown", (e) => {  // Esc leaves only a setup opened from Settings
    if (sx.keyRec || !sx.rerun) return;
    if (e.key === "Escape" && !$("#setup").hidden && sx.steps[sx.i] !== "try") closeSetup();
  });
}

/* ---------------------------------------------------------------- boot */
/* Light or dark (dictado-u9h): index.html's head picks it before the first paint from the last choice; the
   saved one is checked here, and "system" keeps following the OS while the window is open. */
let themeChoice = "system";
function applyTheme(choice, remember = true) {
  if (remember) { themeChoice = choice || "system"; store("ecoscribe.theme", themeChoice); }
  const c = choice || "system";
  const dark = c === "dark" || (c !== "light" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  try { api?.window_theme?.(dark)?.catch?.(() => {}); } catch {}
}
async function boot() {
  api = getApi();
  try { applyTheme(params.get("theme") || (await api.get_theme()).theme); } catch { applyTheme(store("ecoscribe.theme") || "system"); }
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyTheme(themeChoice, false));
  if (MAC) macify();
  try { const st = await api.get_settings(); R_LANGS = st.options.meet_langs.map((o) => [o.value, o.label]); R_DEFAULT = st.values.meet_lang || ""; } catch {}
  for (const b of $$(".nav-item")) b.onclick = () => { if (b.dataset.page === "reuniones") r.open = null; show(b.dataset.page); };
  try { $("#nav-insights").hidden = !(await api.get_settings()).values.insights; } catch {}
  for (const b of $$("#i-range .seg")) b.onclick = () => { iDays = b.dataset.days || null; renderInsights(); };
  for (const b of $$("#todos-weeks .seg")) b.onclick = () => { todoBack = Number(b.dataset.back) || 0; renderTodos(); };
  $("#i-claude").onclick = async () => {
    const r = await api.insights_for_claude();
    if (r.ok) toast("Copied: paste it into Claude.");
  };
  rWire();
  notesWire();
  hkWire();
  $("#search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderHistory, 120); });
  for (const b of $$("#h-filter .seg")) b.onclick = () => {
    hKind = b.dataset.kind; $$("#h-filter .seg").forEach((x) => x.classList.toggle("active", x === b)); renderHistory();
  };
  $("#history-clear").onclick = async () => {
    if (!confirm("Clear the whole history? A backup copy is kept in the Ecoscribe folder.")) return;
    await api.clear_history(); renderHistory(); toast("History cleared.");
  };
  const secShow = (k) => {  // Settings in short sections (dictado-6oe.7); the save bar covers them all
    $$("#set-tabs .seg").forEach((b) => b.classList.toggle("active", b.dataset.sec === k));
    $$("#settings .group[data-sec]").forEach((g) => (g.hidden = g.dataset.sec !== k));
    store("ecoscribe.set-sec", k);
  };
  for (const b of $$("#set-tabs .seg")) b.onclick = () => secShow(b.dataset.sec);
  for (const b of $$(".go-link")) b.onclick = (e) => {  // Snippets <-> Voice commands (dictado-pcz)
    e.preventDefault(); e.stopPropagation();
    secShow(b.dataset.go); $(b.dataset.to)?.scrollIntoView?.({ block: "center" });
  };
  secShow(params.get("sec") || store("ecoscribe.set-sec") || "dictation");  // ?sec=words: a screenshot of that section
  window.__secShow = secShow;
  $("#settings").addEventListener("change", dirty);
  $("#settings").addEventListener("input", (e) => { if (e.target.id === "f-vocabulary" || e.target.id === "f-calendar" || e.target.closest(".snip") || e.target.closest(".rep")) dirty(); });  // savebar while typing words
  $("#settings").addEventListener("submit", (e) => e.preventDefault());
  $("#save").onclick = save;
  $("#discard").onclick = renderSettings;
  $("#mic-test").onclick = () => (mic.on ? stopMicTest() : startMicTest());
  $("#f-mic").addEventListener("change", async () => { if (mic.on) { await micStop(); startMicTest(); } });
  setupWire();

  let page = params.get("page");  // demo and screenshots; the real window asks Python (no query: see Api.initial_page)
  if (!page && api.initial_page) { try { page = await api.initial_page(); } catch {} }
  await show(page === "bienvenida" ? "inicio" : page || "inicio");
  const w = await api.get_welcome();
  if (page === "bienvenida" || !w.done) openSetup();
  setInterval(refreshStatus, 1500);
  setInterval(async () => {  // a notice's button asked this open window for a page (Windows; macOS calls show)
    const p = api.take_page ? await api.take_page().catch(() => null) : null;
    if (p) show(p);
  }, 1000);
  if (params.get("demo") === "1" && params.get("replaced") === "1") setTimeout(() => $("#r-replace-go")?.click(), 500);  // screenshot (dictado-9lo)
  if (params.get("demo") === "1" && params.get("email") === "1") setTimeout(() => $("#r-email")?.click(), 500);  // screenshot (dictado-qxr)
  if (params.get("demo") === "1" && params.get("retrymenu") === "1") setTimeout(() => $(".h-retry button")?.click(), 300);  // screenshot
  if (params.get("demo") === "1" && params.get("models") === "scroll") setTimeout(() => $("#m-rows").scrollIntoView(), 300);  // screenshot
  if (params.get("demo") === "1" && params.get("addlangs")) setTimeout(() => { sx.langs.push(...params.get("addlangs").split(",")); paintLangs(); }, 300);  // screenshot
  if (params.get("demo") === "1" && params.get("dirty") === "1") {  // screenshot of the save bar
    $("#f-sounds").checked = !$("#f-sounds").checked; dirty();
  }
  document.body.dataset.ready = "1";
}

/* macOS wording: the same page, Mac keys and places (uat.5) */
function macify() {
  const set = (sel, html) => { const el = $(sel); if (el) el.innerHTML = html; };
  set("#hero-how", 'Tap <kbd class="key key-wide">⌘</kbd> <span class="key-side">(right Command)</span>, talk, and tap it again. The text appears wherever the cursor is.');
  set("#hk-label", "Right Command");
  set("#hk-hint", HK_HINT);
  for (const el of $$(".tip .keys kbd.key")) if (el.textContent === "Ctrl") el.textContent = "⌘";
  const startup = $("#row-startup .row-label"); if (startup) startup.textContent = "Open at login";
  set("#theme-help", "Light or dark. Match macOS follows the Mac's own setting (System Settings, Appearance).");
  const unmute = $("#f-unmute"); if (unmute) unmute.closest("label").hidden = true;  // a PC fix (mics muted at 0)
  for (const el of $$("#page-ajustes .muted")) {  // dictado-p7c: Mac words in Settings
    el.innerHTML = el.innerHTML.replaceAll("this PC", "this Mac")
      .replace("(or the tray icon: Next dictation in)", "(or the menu bar icon: Dictation language)");
  }
  set("#s-done-sub", "Ecoscribe lives in the menu bar (the mic at the top right) and opens at login. Open this window any time from that menu or from Applications.");
}

if (params.get("demo") === "1") boot();               // screenshots, smoke tests
else if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot, { once: true });
window.__ecoscribe = { show, openSetup, closeSetup, formValues, dropped: rDropped, openSession, get api() { return api; } };
