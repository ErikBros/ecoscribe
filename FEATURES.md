# Features by platform

Ecoscribe is one codebase. Most features live in shared code and work on Windows and macOS alike;
only the OS-specific pieces differ. Rules:

- A pull request that adds or changes a feature updates this file.
- Something OS-specific goes in `ecoscribe/platform/base.py` **and** the platform table below, with
  the other platform done, a ticket (`dictado-xxx`), or "not needed" with the reason.
- `tests/test_platform_contract.py` checks the platform table against the code on every test run
  (and in CI on Windows and macOS), so it can't drift.

## Shared features

Built once for both. "Check on Mac" = works in tests, still to be tried for real on the Mac.

| Feature | Windows | macOS |
|---|---|---|
| Dictation: tap or hold, paste, cancel with key + Esc | done | done |
| Pill with timer, level and cancel hint | done (minimal: dot, waveform, timer; the hint for 2 s) | done (dictado-dlm: breathing dot, 24-bar waveform, timer; keycaps hint for 2 s; pill A since dictado-v5g) |
| Pill A: every state and notice is one 40 px dark capsule (turning arc for Writing it down, a language badge, a struck mic + the mic's name, a warning ring); notice.py turns a flash into icon + words + detail | done (dictado-v5g) | done (dictado-v5g: the same capsule, arc, badge, struck mic and warning ring; flashes through notice(); drawn offscreen and checked against the board) |
| Window: Home, History, Meetings, Settings | done | done |
| One look: every colour, corner and font size of the window from the tokens in app.css (matching palette.py), checked by tests/test_look_tokens.py; dark mode that follows the system or Settings > Appearance (dictado-u9h) | done | check on Mac (shared page; WKWebView follows the system) |
| Languages: English + Swedish built in, "Add a language" for any of Whisper's 100; dictation auto-detects among the ticked ones | done | done (auto-detect: English + Spanish at the Mac desktop, 100 % recall; "Add a language": German + Finnish added in the real Settings page, saved, in the menu bar and meeting lists, removed again (tools/mac_lang_check.py); dictated at the desktop, 100 % recall, Finnish moves dictation to large-v3) |
| Several languages in one dictation (Spanish + Greek...): each piece between pauses in its own language | done (a breath at the switch is enough; +0.1-0.6 s) | done (mlx quick piece check, ~0.1 s a piece; es + el on large-v3: 12 s mixed dictation in 2.3-2.9 s, right in 7 of 8 real clips) |
| Pill shows the language it heard, tray "Next dictation in" | done | check on Mac |
| Your words (spelling list) | done | done |
| Snippets | done | done |
| Voice commands + full list in Settings | done | done (real desktop run: line break + Enter, no command words typed) |
| Style per app: terminal, chat, email, everything else, each with capital at the start, full stop at the end and voice commands on or off, picked by the app (or browser site) the text goes into; Settings > Dictation > Style per app, off by default (dictado-h0m) | done | check on Mac (shared code; bundle ids for the app) |
| Self-corrections: "scratch that" drops the sentence before it (rules); "no wait", "no perdón", "nej förlåt", "όχι συγγνώμη" send that dictation to Claude Haiku, 5 s limit, else the text as heard ([text] self_corrections, off by default) (dictado-ehc) | done (config.toml only; Settings switch: dictado-bd6) | check on Mac (dictado-1xg) |
| Meetings: live transcript, notes, Me / Others, exports, Copy for Claude | done | check on Mac (dictado-tjn): needs the System Audio Recording permission |
| Meeting / file languages incl. Greek + Spanish mixed | done | done (GPU test passes on mlx) |
| Meeting pill: a small chip (dot + timer) that shows the live line when the mouse is on it | done | done (dictado-f6o: polls the mouse, stays click-through; checked on screen) |
| Meeting prompt box: a rounded dark card that says which meeting, rounded buttons, language as a chip with a menu | done | done (dictado-jfz; 6oe.9: icon tile per kind, light primary button, countdown line along the bottom) |
| History: Retry a recent dictation (again, or in a chosen language); the last 20 keep their audio on this computer | done | check on Mac |
| Settings > Speech models: each model's use, size on disk, download with progress, delete to free space | done | check on Mac |
| Email to participants: a draft in your own mail program, to the calendar invite's guests, the transcript in it or copied to paste; no guests and no calendar connected: the transcript copied and Google Calendar opened on the call's day for its Email guests button, the steps in a toast (dictado-qxr) | done | check on Mac (shared code, `open` for the link) |
| Meeting names + attendees from a calendar (iCal link) | done | check on Mac (dictado-tjn) |
| Meeting names, guests and Email participants from Google Calendar by signing in (no iCal link needed; an older meeting looks its event up on Email participants) | done (dictado-k19; token DPAPI-encrypted) | check on Mac (dictado-k19; token in an owner-only file) |
| Meeting name from the Google Meet tab when the calendar has no event (no link, or the secret address is turned off) | done | check on Mac (dictado-4ar: window titles via Accessibility) |
| Your own command after a transcript is done ([transcribe] after_transcribe in config.toml; gets the session folder, runs detached) | done | check on Mac (shared code; detached with start_new_session) |
| Personal calls: Signal / WhatsApp / Telegram / Discord, a title starting "p-", or a language listed in [personal]; automatic steps over meetings touch only these (dictado-qlj) | done | done (shared code) |
| Meeting search: titles and what was said, ranked and grouped by call, case and accents ignored in every script (Greek too); the Meetings search box and the Claude app's search_meetings (dictado-8h8) | done | check on Mac (shared code, SQLite FTS5) |
| Calls with a person: the Claude app's calls_with_person finds the calls where someone is a named speaker, a calendar guest or in the title (part of a name, accents ignored); list_meetings shows the guests (dictado-igs) | done | check on Mac (shared code) |
| Debrief my call: a prompt in the Claude app (debrief_call) that turns a call's to-dos into proposed tickets, made only after the user's OK, and drafts a follow-up to paste; never the mailbox or calendar (dictado-2mu) | done | check on Mac (shared code) |
| Search by meaning for the Claude app: a search_meetings that finds no call is counted (never its words); from the first miss on (or [search] meaning = "on"), multilingual-e5-large int8 (0.55 GB, CPU, onnxruntime) indexes the calls in the background while nothing records, and an empty word search, or by_meaning, answers with the calls closest in meaning (dictado-2i1) | done | check on Mac (shared code; the int8 model on the Apple CPU not tried yet) |
| Replace list on a saved meeting: its page says how many places the list would change (and which pairs); Apply rewrites the transcript and its downloads, never the audio; one Undo right after (transcript.before-replace.json); refused while the transcript is still being written (dictado-9lo) | done | check on Mac (shared code) |
| Call summaries: after a personal call, summary.md next to it (decisions, to-dos, open questions by kind of call), every item with its time and quote, checked against the transcript; the Claude app reads it first ([summaries] enabled, off by default; `--summarize DIR` by hand) (dictado-crf, dictado-xu2) | done | check on Mac (dictado-1xg) |
| Your to-dos for the week: Home shows your own to-dos from this week's personal call summaries (or last week's), one column per person, each ticked off and linked to its call; Sunday from 18:00 the week is written to <data>/todos/<monday>.md with one notice (dictado-xuu) | done | check on Mac with summaries (shared code, dictado-1xg) |
| File transcription (drag and drop) | done | done (installed app: Greek file on the Apple GPU, 2.4% WER) |
| First-run setup: languages, speech models (both recommended, with download progress), mic test, dictation key, a first dictation, summary; Settings > Run setup again | done | done (checked with a fresh data folder: both models downloaded with a moving bar, the first dictation pasted into the box) |
| Crash reports, freeze traces, watchdog restart | done | done |
| Last snapshot before a frozen app is restarted (every thread's stack, log tail, versions, state; reports kept to the newest 20, 50 MB), and a counts-only health check by version in crashes/health.md (starts, crashes, freezes, restarts; no text) (dictado-dhr) | done | check on Mac (shared code; the last snapshot also sends SIGUSR1 for the native dump) |
| A newer version is out: once a day the app asks GitHub for the latest release (no account, errors silent), Home shows it with Download (the release page: .exe and .dmg) and ×; Settings > Check for new versions (updates.py) | done (dictado-cjk) | done (shared code; only releases with a .dmg are announced, dictado-6gr) |
| Dictation recovered after a crash | done | done (real crash mid-dictation: back in History, not pasted) |
| Home crash card, Settings > Troubleshooting | done | done (real SIGSEGV of the installed app: report, restart, card) |
| Call detection tried on real calls | done | needs real calls (dictado-nhn) |
| Insights: in your meetings (your share of the talking, turns over 90 s, questions, hedges) | done | done (needs recorded meetings with the call's sound: dictado-qkg) |
| Insights: pace (words a minute of speech) and pauses, to people vs to AI apps, with the 130-160 range as information | done | done (people / AI split: dictado-9jc.7) |
| Insights: filler words and hedges in messages to people (per 100 words, weekly), optional note on the pill after such a message | done | done (pill note: check on Mac, dictado-9jc.7) |
| Insights: how clearly you speak (share of words heard clearly per week, words it wasn't sure of per language) | done | done (word confidence from mlx) |

## Platform-specific

| Capability | Windows | macOS |
|---|---|---|
| Hotkey (tap / hold / combo, Esc cancel) | done (low-level keyboard hook) | done (CGEventTap, Right Command) |
| Language key (dictation key + L picks the next language) | done (Right Ctrl + L, swallowed) | done (Right Command + L, swallowed; real desktop run) |
| Take back the last paste ("scratch that") and paste it again (dictation key + R) | done ("scratch that" alone sends Ctrl+Z, only in the window the dictation went into and within 60 s; with voice commands or self-corrections on) (dictado-ost) | done (⌘Z into the same front window, Right Command + R; not tried on a Mac yet) (dictado-cp1) |
| Command mode (dictation key + E: say how to change the selection) | done (the selection by Ctrl+C, clipboard put back; Haiku's answer pasted over it, Ctrl+Z undoes; [text] command_mode, off by default) (dictado-ua2) | done (the selection by ⌘C; Right Command + E; not tried on a Mac yet) (dictado-waw) |
| Command mode keys picked in Settings (the dictation key + a letter, or a combo) | done (Settings > With Claude > Command mode keys, the dictation key's picker; [text] command_key; a combo of its own works with a combo dictation key and is pressed again to stop) (dictado-a1d) | done (the same picker; not tried on a Mac yet) (dictado-waw) |
| Command mode in the user's writing style (a .md or .txt style file) | done (Settings > Command mode > Your writing style: Choose file, Open, Remove; read on every edit, sent with it; Sonnet when a style is set; [text] command_style_file) (dictado-jq7p) | done (shared code, the same Settings row; not tried on a Mac yet) (dictado-jq7p) |
| Numpad Enter as a second dictation key | done (Settings > Numpad Enter dictates too; swallowed, the main Enter untouched) | done (keypad Enter, keycode 76, on an external keyboard; swallowed, Return untouched) |
| No text box at the stop: keep it on the clipboard, say so | done (UI Automation: desktop, file lists, buttons; unknown windows still get the paste) | done (Accessibility role: Finder icons and lists, buttons; unknown still pastes; the pill says ⌘V) |
| Dark mode follows the system (Settings > Appearance: Match / Light / Dark) | done (Windows app mode) | done (macOS appearance) |
| Title bar matches the window's light or dark look | done (Windows 11 dark title bar) | done (the window's appearance, Aqua or Dark Aqua; not tried on a Mac yet) (dictado-zkh) |
| Which app gets the paste, read just before it (Style per app) | done (process name + window title) | done (bundle id + window title through Accessibility) |
| Paste text where the cursor is | done (clipboard + Ctrl+V) | done (NSPasteboard + Cmd+V) |
| Names on your screen | done (UI Automation, one COM thread) | done (Accessibility API) |
| Speech engine on the GPU | done (faster-whisper, CUDA) | done (mlx-whisper, Metal) |
| Mic list in Settings | done | done |
| Unmute the mic only while recording | done | not needed: macOS mics aren't left muted at volume 0 |
| System audio for meetings (the other side of a call) | done (WASAPI loopback) | done (Core Audio process tap; real capture: check on Mac, dictado-tjn) |
| Call detection (who uses the mic, call windows) | done (who is on the mic from Windows' consent store and the live audio sessions, so a call still counts when Windows stops updating the store; a browser call counts by the meeting tab title or by two-way audio: the browser captures the mic and plays sound, dictado-pprg) | done (a browser call also counts when it captures the mic and plays sound, so a Meet tab behind another tab is still a call; each audio process counts as the app that launched it, so Chrome's helpers, a WebKit view inside a call app and FaceTime's audio daemon are named right; Arc and Vivaldi are browsers; detect.log notes what the detector sees and a missing Accessibility grant; `python -m ecoscribe.callprobe` prints the signals live; real-call check: dictado-nhn) |
| Show a download in its folder | done (dictado-yq9: Explorer with the file selected; the toast's Open folder; Settings > Meetings > Downloads go to) | done (dictado-yq9: open -R, Finder with the file selected) |
| Tray / menu bar, pill and prompt box | done | done (AppKit) |
| Smooth pill: see-through corners, a soft shadow, the app's font | done (dictado-acm: drawn as one picture by pillart, shown with UpdateLayeredWindow) | ticket dictado-vx1 (AppKit already smooth; shadow and font to check) |
| Live text on the pill while dictating | done (a quick pass every 2 s; the careful one is still what gets pasted) | done (Overlay.live: the pill grows to 440x66, the newest words on one line cut on the left; 15 s preview on the Apple GPU 0.7 s with turbo, 1.9 s with large-v3) |
| Start at login | done (Run key; the old "Dictado" value moves to "Ecoscribe") | done (LaunchAgent com.erikbros.ecoscribe; the old com.erikbros.dictado one moves over) |
| Single instance | done | done |
| Settings saved -> restart signal | done | done |
| Window buttons -> background app (commands) | done | done |
| Watchdog: watch, restart, kill a frozen app | done | done |
| A frozen app can't lag the computer's input | done (hooks in their own process) | not needed: macOS times out a stuck event tap by itself |
| Speakers + Remember voices (add-on) | done (Ecoscribe Speakers; the old Dictado Speakers still found) | done (Ecoscribe Speakers.app, the old Dictado Speakers.app still found; pyannote on the Apple GPU, same results as CPU, 2x faster) |
| Speakers pass during a call (when the GPU has room) | done (runs next to a recording call when the NVIDIA GPU has 3 GB free; else after the call) | ticket dictado-692 (waits for the call to end, as before) |
| Claude app connection (MCP) | done | done (~/Library/Application Support/Claude) |
| Word confidence for Insights (clarity, words it wasn't sure of) | done (a second pass with word timestamps after the paste, ~0.3 s on the GPU, only with Insights on and nothing waiting) | done (the dictation's own tokens aligned to the audio, ~0.56 s on large-v3-turbo; the first after a load ~1 s) |
| Window title at the paste (who a dictation was for: people / AI app) | done (GetWindowText; only the label is saved) | done (Accessibility: the focused window's title; desktop check: dictado-9jc.7) |
| App at the paste by a locale-independent id (people / AI app) | not needed: process names (slack.exe) are the same in every language | done (bundle id, so a translated app name still counts: dictado-uee) |
| Setup: permissions step (first run) | not needed: Windows asks for no permission to listen, type or watch the keyboard | done (Microphone, Accessibility, Input Monitoring: Allow shows macOS's own prompt, then Open settings; ticks live; once both key permissions are on, the app restarts itself so the key works at once) |
| Setup: speech model download with progress | done (bytes from the download, both models, Continue once the needed one is there) | done (mlx weights, bytes off the network so xet downloads move too, never backwards: dictado-kuu) |
| No NVIDIA GPU: setup and the app fetch the CPU speech model, with a word on screen | done (dictado-7t38: setup lists the small model as needed on this computer and leaves the GPU models unticked; at start, when it's missing, the app fetches it and the pill says so and when it's ready; a dictation that comes first waits for it, the pill showing the MB so far, and is typed when it's there. dictado-5d6y: an NVIDIA card with under ~2.8 GB, too small for the big models, counts as no GPU, and setup and the pill say the card is too small) | not needed: every supported Mac has its GPU: mlx runs on Metal |
| GPU runtime: the CUDA libraries download once, not in every installer | done (dictado-7e1: the app fetches a versioned, checksummed pack from the GitHub release on first start, resumes a cut download, runs on the CPU meanwhile; an update keeps it; an install from 1.17 or older moves its own copy over, no download) | not needed: no CUDA: mlx runs on Metal, which comes with macOS |
| Install a new version by itself: when idle or at Quit, never in a call (Settings switch, off by default; Home > Install when idle) | done (dictado-nmo: downloads the release's own installer, checks size and SHA-256, runs it silently only with no meeting, job or dictation) | done (dictado-6gr: the release's .dmg, same checks; a script swaps Ecoscribe.app after the app quits, only for an app signed with the same certificate, so permissions stay; a release without a .dmg isn't announced on the Mac) |
| Installer | done (.exe, Inno Setup) | done (Ecoscribe.app + .dmg, com.erikbros.ecoscribe, self-signed: this Mac only; a public build needs a Developer ID) |
| Claude Code from the app (summaries, self-corrections) | done (wsl.exe, a login shell: Claude Code lives in WSL) | ticket dictado-1xg (a zsh login shell; not yet tried on the Mac) |
| Move the pill: drag the meeting chip, it stays there; double-click puts it back | done (dictado-06i: click-through except while the mouse is on the chip; the spot in pill.json) | ticket dictado-8dy |
| Which mic and output a call app uses (the meeting follows the call, the page shows it) | done (dictado-s1a: audio sessions per device; a silent source switches to the call's device) | ticket dictado-7bw |
