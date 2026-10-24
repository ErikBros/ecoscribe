# Troubleshooting

([All guides](README.md).) First stop for anything: Settings > Help and setup > **Copy debug info for Claude** and paste
it to Claude together with the [last section of this page](#for-your-claude-paste-this-section-when-asking-for-help).
It holds the version, settings (calendar link removed), the end of every log and recent crashes; no dictation or
meeting text.

## Windows

| Problem | Try this |
|---|---|
| Nothing happens when I tap Right Ctrl | Look for the tray icon (near the clock, maybe under ^). If it's missing, start **Ecoscribe** from the Start menu. Home says "Ready" when it can dictate. |
| Engine says "CPU · slow" | No NVIDIA card found, its driver is old, or the GPU libraries are still downloading (first start; it runs on the processor meanwhile). Update the NVIDIA driver and restart Ecoscribe. |
| "Didn't hear you, twice" | Two dictations in a row heard nothing. **Check the mic** opens Settings: pick the right mic and press Test. A mic muted in Windows: turn on **Unmute the mic only while dictating**. |
| Text is wrong or in the wrong language | Tick only the languages you speak (Settings > Languages and words). For one dictation, Right Ctrl + L picks the next language. A recent one: History > **Retry ▾** in the right language. |
| A name keeps coming out wrong | Add it to **Your words**; if it's still wrong, add a **Replace** pair. Insights > **Words to add** suggests names. |
| The text didn't appear | No text box had the cursor: it's on the clipboard (Ctrl+V) and in **History**. |
| "Command mode is off" | You pressed Right Ctrl + E: turn on Command mode in Settings > Dictation > With Claude. |
| The meeting box never appears | Settings > Meetings must be on *Ask* or *Start by itself*. Some apps only take the mic once the call connects. Start it by hand from Home > **Record a meeting**. |
| Meeting transcript only has "Me" | The computer's sound wasn't captured. During the call the meters next to Stop show it: when "hearing them" stays silent, press the **Record** button the warning offers. |
| "Ecoscribe hears nothing from your mic" during a call | The call uses another mic: press **Record** + its name in the warning, or pick the mic in Settings. |
| The meeting pill is in the way | Drag it somewhere else; double-click puts it back. |
| Installing an update says a meeting is recording | Stop the meeting first, wait for it to show Ready, then click Retry. Setup won't cut a recording. **Install when idle** waits by itself. |
| A crash card on Home | Ecoscribe restarted itself and kept the dictation you were in. **Copy crash report for Claude** and paste it. |
| Anything else | Open the log: tray icon > **Open log**, or Settings > Help and setup > Logs and crash reports > Open folder. |

## Mac

| Problem | Try this |
|---|---|
| Right Command does nothing | System Settings > Privacy & Security: **Accessibility** and **Input Monitoring** must both be on for Ecoscribe. If you just turned them on, quit Ecoscribe from the menu bar and open it again. |
| The first dictation came out empty | macOS asked for the microphone during it. Click Allow; the next ones work. |
| Meeting transcript only has "Me" | Allow **Screen & System Audio Recording** for Ecoscribe in System Settings > Privacy & Security (macOS 14.4 or newer). |
| "Ecoscribe can't be opened" after an update | Each new version needs **Open Anyway** once ([Getting started on a Mac, step 2](mac.md#2-install)). |
| Anything else | `~/Library/Application Support/Ecoscribe` has `ecoscribe.log` and the crash reports. |

## For your Claude (paste this section when asking for help)

Ecoscribe is one Python 3.12 codebase for Windows and macOS (PyInstaller). Windows: faster-whisper/CTranslate2 on
CUDA, pywebview window, pystray tray, low-level keyboard hook in its own process. macOS: mlx-whisper on Metal,
WKWebView window, AppKit menu bar, CGEventTap, a Core Audio process tap for meetings. One background process owns the
hook, the tray and the meetings controller. It starts workers for the dictation model (`--engine-worker`, on demand),
meetings (`--meeting DIR`), file jobs (`--transcribe DIR`), the speakers pass (`--speakers DIR`, runs
`EcoscribeSpeakers.exe <audio> <out.json>`, pyannote), the Claude app connection (`--mcp`, read-only MCP server over
stdio) and search by meaning (`--meaning-index`). A watchdog restarts a crashed or frozen app.

Data folder: Windows `%LOCALAPPDATA%\ecoscribe\` (settings in `%APPDATA%\ecoscribe\config.toml`), Mac
`~/Library/Application Support/Ecoscribe/` (settings in `config.toml` there). Files to read when something fails:

- `ecoscribe.log`: background app (startup, ready line, meetings controller, reloads)
- `engine-worker.log`: dictation model load and errors
- `status.json`: current state, version, device, model, mic
- `meetings.json`: what is recording / transcribing / queued
- `detect.log` and `detector.log`: call detection decisions (Mac: `python -m ecoscribe.callprobe` prints the signals live)
- `transcripts\<session>\worker.log` and `meta.json`: one meeting or file; `notes.md` your notes, `voices.json` the
  voices in that call, `summary.md` a personal call's summary
- `mcp.log`: the Claude app connection
- `meaning.log`: search by meaning (model download, indexing); `transcripts\.search-misses.json` counts the searches
  that found nothing, `transcripts\.meaning.sqlite` is its index (a cache, safe to delete)
- `crashes\`: crash reports, freeze traces and the last snapshot before a frozen app was restarted; `crashes\health.md`
  counts starts, crashes, freezes and restarts by version (no text)
- `voices.json`: voices learned for Remember voices (one averaged speaker embedding per name)
- `config.toml` sections: `[hotkey]`, `[audio]`, `[whisper]`, `[text]` (vocabulary, screen_names, voice_commands,
  snippets, replacements, app_styles, self_corrections, command_mode), `[ui]`, `[meetings]`, `[transcribe]`,
  `[personal]`, `[claude]`, `[summaries]`, `[search]`. After editing by hand, quit from the tray and start Ecoscribe
  again.

Notes: Swedish dictation uses `Systran/faster-whisper-large-v3` (int8_float16); English and Spanish use
`large-v3-turbo`. Never install an update while `meetings.json` shows a meeting (Setup refuses anyway). pyannote's
usage telemetry is switched off in the add-on (`PYANNOTE_METRICS_ENABLED=false`).
