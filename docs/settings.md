# Settings

([All guides](README.md).) The Settings tab has five sections on its left. Changes wait for **Save** at the bottom
(**Discard** drops them); a few apply the next time Ecoscribe starts, and the page says so.

Under each Settings section, a line links to the guide that covers it.

## Dictation

| Setting | What it does |
|---|---|
| **Shortcut** | Your dictation key (**Change**), **Hold to talk**, **Numpad Enter dictates too**. See [Dictation](dictation.md#the-basics). |
| **Mic** | Pick it by name, so it isn't lost when you plug in other devices. **Test** shows a level meter. On Windows, **Unmute the mic only while dictating** helps with a mic Windows keeps muted. |
| **Behaviour** | **Appearance**, **Free the GPU when you're not dictating**, **Sounds**, **Voice commands**, **On-screen pill**, **Live text on the pill**, **Insights tab**, **Note filler words after a message**, **Start with Windows** (Mac: **Open at login**), **Check for new versions**, **Install new versions by itself** |
| **Style per app** | A style for terminals, chats, email and everything else. See [Dictation](dictation.md#style-per-app). |
| **With Claude** | **Fix it when you correct yourself** and **Command mode**. See [With Claude](claude.md). |

### Light or dark

**Appearance:** *Match Windows* (Mac: *Match macOS*) follows your system's own setting; *Light* or *Dark* fixes it. On
Windows 11 and on a Mac the title bar follows too.

### New versions

- **Check for new versions** (on by default): once a day Ecoscribe asks GitHub for the newest version number. When
  there is one, Home says so with **Download** (the Releases page) and ×. Nothing from your dictations or meetings is
  sent.
- **Install when idle** (Windows): the button next to Download on Home. Ecoscribe gets the new version in the
  background, checks it, and installs it when you step away from the computer or quit Ecoscribe. Never during a call,
  while a meeting is being saved or while you dictate.
- **Install new versions by itself** (Windows, off by default): the same for every new version, without asking.

## Languages and words

**Languages you dictate in**, **Your words**, **Names on your screen**, **Replace** and **Snippets**. See
[Dictation](dictation.md#languages) and [Getting names and words right](dictation.md#getting-names-and-words-right).

## Meetings

| Setting | What it does |
|---|---|
| **When a call starts** | *Ask*, *Start by itself* or *Don't detect* |
| **Stop recording after the call ends** | How long the call app has to be off the mic (5 seconds to 2 minutes) |
| **Your name** | Your lines show it instead of "Me" |
| **Language when the app doesn't have one yet** | The language a call starts in before you pick one |
| **Tell the other speakers apart**, **Remember voices**, **Forget all voices** | The speaker add-on, see [Meetings](meetings.md#who-said-what-speaker-add-on) |
| **Name meetings from your calendar**, **Google Calendar** | See [Meetings](meetings.md#meeting-names-from-your-calendar) |
| **Downloads go to** | Where the meeting page's downloads go (**Change...**, **Use Downloads**) |
| **Claude app** | **Connect** lets the Claude desktop app read your meetings. See [With Claude](claude.md). |

## Speech models

Ecoscribe picks the model for each language by itself. Each model shows what it's for and its size on disk; download
it with progress, or delete one to free space (it downloads again when it's next needed). Both run on your computer,
offline.
On a Windows PC without an NVIDIA graphics card, a third one, **For this computer** (about 0.5 GB), is the one dictation
uses; the other two are only for meetings and files there, and slow.

## Help and setup

- **User guides:** **All guides** and **Troubleshooting** open these guides on GitHub, as of the version you have.
- **Run setup again:** languages, speech models, mic and key, step by step, like the first time.
- **Copy debug info for Claude:** version, settings (calendar link removed), the end of every log, recent crashes and
  freezes. Paste it to Claude.
- **Logs and crash reports > Open folder.**
- **Detailed logging:** writes much more to the log. On while chasing a problem, off after.

More in [Troubleshooting](troubleshooting.md).

## In config.toml only

A few settings have no switch in the window. They live in `config.toml` (Windows: `%APPDATA%\ecoscribe\config.toml`;
Mac: in `~/Library/Application Support/Ecoscribe`). Quit Ecoscribe from the tray before editing it.

| Setting | What it does |
|---|---|
| `[summaries] enabled = true` | Summaries of personal calls ([Meetings](meetings.md#personal-calls-summaries-and-to-dos)) |
| `[personal] languages = ["el"]` | A call in one of these languages counts as personal |
| `[transcribe] after_transcribe` | Your own command, run with the session folder when a transcript is done |
| `[search] meaning = "off"` | Never search by meaning ([With Claude](claude.md)) |
