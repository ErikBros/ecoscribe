# Getting started on a Mac

(On Windows: [windows.md](windows.md). All guides: [README](README.md).) Ecoscribe is a voice dictation and meeting
transcription app for Windows and macOS. On a Mac, Whisper runs on the Apple GPU (mlx): no account, no subscription,
and no audio or text leaves the computer.

- **Dictation:** tap **Right Command**, talk, tap again. The text is pasted wherever your cursor is, in any app. Hold
  Right Command and press Esc to cancel; Right Command + L picks the next dictation's language.
- **Meetings:** when a call app starts using the mic, Ecoscribe offers to take notes. You get a transcript with each
  line labelled **Me** or **Others**.
- **Files:** drag an audio or video file onto the window to transcribe it.

The how-to pages ([Dictation](dictation.md), [Meetings](meetings.md) and the rest) are shared with Windows: read
Right Command where they say Right Ctrl, and the menu bar icon where they say the tray icon. What isn't on the Mac yet
is listed at the end of this page.

## 1. Requirements

- **A Mac with Apple Silicon** (M1 or newer). Intel Macs aren't supported: the speech engine runs on the Apple GPU.
- **macOS 14.4 or newer** (meetings record the other side of a call through a Core Audio tap, new in 14.4).
- **Disk:** about 1 GB for the app, plus the speech models it downloads the first time each is needed (1.6 GB for
  English, Spanish and most languages, about 3 GB more for Swedish, Greek and some others).
- **Internet only for the first model downloads** (Hugging Face, no account). After that it works offline.

## 2. Install

1. Download **`Ecoscribe-<version>.dmg`** from [Releases](https://github.com/ErikBros/ecoscribe/releases/latest), open
   it and drag **Ecoscribe** to **Applications**.
2. Open Ecoscribe from Applications. It isn't signed with a paid Apple Developer ID yet, so the first time macOS says
   it can't check it: click **Done** (on macOS 15, right-click > Open no longer gets past this). Then open **System
   Settings > Privacy & Security**, scroll down to **Security** and click **Open Anyway** next to Ecoscribe, enter
   your password, and click **Open Anyway** once more. Once per version: each new download is checked again until
   Ecoscribe has a Developer ID.
3. The first-run setup opens (next section).

**Updating:** quit Ecoscribe, drag the new one over the old one in Applications, then Open Anyway once more (step 2).
Your settings, history and transcripts stay, and so do the permissions (same signing certificate). Home tells you
when a new version is out (Settings > Dictation > Behaviour > Check for new versions).

## 3. First-run setup

1. **Let Ecoscribe listen and type:** three switches in System Settings > Privacy & Security.
   - **Microphone**, to hear you.
   - **Accessibility** and **Input Monitoring**, for the Right Command key and to paste the text.

   **Allow** shows macOS's own prompt, then **Open settings** takes you to the right page. Each one ticks on the setup
   page by itself within a few seconds. Once both key permissions are on, Ecoscribe restarts itself so the key works
   at once (macOS only hands a key watcher to an app when it starts).
2. **Languages**, **speech models** (download with progress), **mic test**, **dictation key**, and **a first
   dictation**, the same as on Windows ([Getting started on Windows, step 4](windows.md#4-first-run-setup)).

**Screen & System Audio Recording** is asked for at your first meeting (to hear the other side of the call). It isn't
needed for dictation.

Run the setup again any time: Settings > Help and setup > **Run setup again**. **Open at login** is a switch in
Settings > Dictation > Behaviour.

## 4. Where your files are

| What | Where |
|---|---|
| Settings, history, transcripts, crash reports | `~/Library/Application Support/Ecoscribe` |
| Speaker add-on (optional) | `Ecoscribe Speakers.app` in Applications |

## 5. Not on the Mac yet

Each has a ticket; [FEATURES.md](../FEATURES.md) has the full table.

- Not tried on a Mac yet: command mode (Right Command + E), taking back the last paste ("scratch that"), pasting it
  again (Right Command + R), fix it when you correct yourself, call summaries and the to-dos built from them (they
  run Claude Code from the app).
- Install new versions by itself (Home still offers Download).
- Moving the meeting pill by dragging it, and the meeting following the call's mic and output.
- The speakers pass during a call (it runs after the call).
