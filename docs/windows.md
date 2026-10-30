# Getting started on Windows

(On a Mac: [mac.md](mac.md). All guides: [README](README.md).) Ecoscribe is a voice dictation and meeting
transcription app for Windows and macOS. Everything runs on your own PC: no account, no subscription, and no audio
or text leaves the computer.

- **Dictation:** tap Right Ctrl, talk, tap again. The text is typed wherever your cursor is, in any app.
- **Meetings:** when Teams, Slack, Zoom, Meet, Discord, Signal, Telegram or Webex starts using the mic, Ecoscribe
  offers to take notes. You get a transcript with each line labelled **Me** or **Others**.
- **Who said what** (optional add-on): splits the other side of a call into Speaker 1, 2, 3, and you can name them.
- **Files:** drag an audio or video file onto the window to transcribe it.

The interface is in English.

---

## 1. What to download

From **[Releases](https://github.com/ErikBros/ecoscribe/releases/latest)**:

| File | What it is | Needed? |
|---|---|---|
| `Ecoscribe-Setup-<version>.exe` | The app (about 0.5 GB) | Yes |
| `Ecoscribe-Speakers-Setup-<version>.exe` | Speaker add-on: tells the people on a call apart (2.1 GB download, 4.6 GB installed) | Optional: its own release, **[Speaker add-on 1.2.0](https://github.com/ErikBros/ecoscribe/releases/tag/speakers-1.2.0)** |

## 2. Requirements

- **Windows 10 or 11, 64-bit.**
- **An NVIDIA graphics card is strongly recommended**, with 6 GB of graphics memory or more. Tested on an RTX 3070 Ti
  (8 GB). Without one, or with a card under 3 GB, Ecoscribe still works on the processor with a smaller model: slower
  and less accurate. Setup notices and picks that model for you.
- **Disk:** about 1 GB for the app, plus the speech models it downloads the first time each is needed: about 1.6 GB
  (English, Spanish and most languages) and about 3 GB more for the larger model (Swedish, Greek and some others).
  On an NVIDIA card it also downloads the GPU libraries once, in the background. Without one, dictation runs on the
  processor with a smaller model (about 0.5 GB): setup downloads it, or the app does at start and the pill says so.
  A dictation that comes before it's there waits, the pill showing how far the download is, and is typed after.
  Add 4.6 GB for the speaker add-on.
- **Internet only for the first downloads** (speech models from Hugging Face, the GPU libraries from this project's
  Releases page; no account needed). After that it works offline.
- A microphone. A headset works best for meetings.

## 3. Install

1. Double-click **`Ecoscribe-Setup-<version>.exe`**.
2. Windows will probably show **"Windows protected your PC"**. That's because the app isn't signed with a paid
   certificate, not because something is wrong. Click **More info**, then **Run anyway**.
3. No admin password needed. It installs for your user only, in `%LOCALAPPDATA%\Programs\Ecoscribe`.
4. Keep **"Start Ecoscribe with Windows"** ticked if you want it always ready.
5. At the end it opens Ecoscribe and the first-run setup.

**Updating:** install the new Setup over the old one; your settings, history and transcripts stay. Ecoscribe can
also tell you about a new version and install it by itself when you step away (see [Settings](settings.md#new-versions)).
Setup waits if a meeting is recording.

**Optional, the speaker add-on:** download it from **[its release](https://github.com/ErikBros/ecoscribe/releases/tag/speakers-1.2.0)** and run **`Ecoscribe-Speakers-Setup-<version>.exe`** the same way (same SmartScreen
steps). It installs separately in `%LOCALAPPDATA%\Programs\Ecoscribe Speakers` and Ecoscribe picks it up on its own.
Updating Ecoscribe never touches it.

## 4. First-run setup

The first time, Ecoscribe walks you through it step by step:

1. **Languages:** tick the ones you speak. Dictation picks among them by itself.
2. **Speech models:** both recommended models download with a progress bar; Continue once the one you need is there.
3. **Mic:** pick your microphone and watch the level move while you talk.
4. **Dictation key:** Right Ctrl by default, tap or hold. Click **Change key** and press another key or a combo
   (`Ctrl+L`). Right Alt isn't allowed: on many keyboards it's AltGr.
5. **A first dictation** into a box on the page, so you see it work.

You can run it again any time: Settings > General > Help > **Run setup again**.

Then look at **Settings > Meetings > When a call starts**: *Ask* (default), *Start by itself*, or *Don't detect*.

## 5. Where to go next

- [Dictation](dictation.md): everything about the key, your words, snippets and voice commands.
- [Meetings](meetings.md): taking notes in calls. Read "Before you record" first.
- [With Claude](claude.md), [Insights](insights.md), [Settings](settings.md).
- Something wrong: [Troubleshooting](troubleshooting.md).

## 6. Where things live

| What | Where |
|---|---|
| The app | `%LOCALAPPDATA%\Programs\Ecoscribe` |
| Speaker add-on | `%LOCALAPPDATA%\Programs\Ecoscribe Speakers` |
| Settings | `%APPDATA%\ecoscribe\config.toml` |
| History, transcripts, models, logs, crash reports | `%LOCALAPPDATA%\ecoscribe\` |
| Meeting transcripts | `%LOCALAPPDATA%\ecoscribe\transcripts\<date>_<title>\` (audio FLACs, transcript .txt/.md/.srt, your notes) |
| Downloads from a meeting page | Your Downloads folder (Settings > Meetings > Downloads go to) |

Paste a path like `%LOCALAPPDATA%\ecoscribe` into the File Explorer address bar to open it.

## 7. Uninstall

Windows Settings > Apps > **Ecoscribe** > Uninstall (and **Ecoscribe speaker add-on** if you installed it). Your
history, transcripts and settings stay in the folders above; delete them by hand if you want them gone.

## 8. Credits and licenses

- Speech recognition: OpenAI **Whisper** models (MIT) via **faster-whisper** and **CTranslate2** (MIT); model files
  from Systran and mobiuslabs on Hugging Face (MIT).
- Search by meaning: **multilingual-e5-large** (MIT) on **onnxruntime** (MIT).
- Speaker add-on: **pyannote.audio** (MIT) and **pyannote/speaker-diarization-community-1** by pyannoteAI, licensed
  **CC BY 4.0** (https://huggingface.co/pyannote/speaker-diarization-community-1).
- Built by ErikBros with Claude. MIT license, no warranty.
