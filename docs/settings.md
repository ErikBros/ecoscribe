# Settings

([All guides](README.md).) The Settings tab has four sections: **Dictation**, **Words**, **Meetings** and
**General**. Changes wait for **Save** at the bottom (**Discard** drops them); a few apply the next time Ecoscribe
starts, and the page says so.

Under each Settings section, a line links to the guide that covers it.

## Dictation

| Setting | What it does |
|---|---|
| **Shortcut** | Your dictation key (**Change**) and **Hold to talk**. See [Dictation](dictation.md#the-basics). |
| **Mic** | Pick it by name, so it isn't lost when you plug in other devices. **Test** shows a level meter. On Windows, **Unmute the mic only while dictating** helps with a mic Windows keeps muted. |
| **While you dictate** | **On-screen pill** (*Timer and live text*, *Timer only* or *Off*), **Sounds**, **Note filler words after a message** |
| **Style per app** | A style for terminals, chats, email and everything else. See [Dictation](dictation.md#style-per-app). |
| **With Claude** | **Fix it when you correct yourself** and **Command mode**. See [With Claude](claude.md). |

## Words

**Languages you dictate in**, **Your words**, **Names on your screen**, **Replace**, **Snippets** and **Voice
commands**. See [Dictation](dictation.md#languages) and
[Getting names and words right](dictation.md#getting-names-and-words-right).

## Meetings

| Setting | What it does |
|---|---|
| **Recording** | **When a call starts** (*Ask*, *Start by itself* or *Don't detect*), **Stop recording after the call ends** (5 seconds to 2 minutes), **Meeting language** (when the call app doesn't say) |
| **People** | **Your name** (your lines show it instead of "Me"), **Tell the other speakers apart**, **Remember voices**, **Forget all voices**. See [Meetings](meetings.md#who-said-what-speaker-add-on). |
| **Calendar** | **Google Calendar > Connect**, or paste a **Calendar address**. See [Meetings](meetings.md#meeting-names-from-your-calendar). |
| **Files and apps** | **Downloads go to** (**Change...**, **Use Downloads**) and **Claude app > Connect** (see [With Claude](claude.md)) |

## General

### App

- **Appearance:** *Match Windows* (Mac: *Match macOS*) follows your system's own setting; *Light* or *Dark* fixes it.
  On Windows 11 and on a Mac the title bar follows too.
- **Start with Windows** (Mac: **Open at login**).
- **Insights tab:** see [Insights](insights.md).

### New versions

**New versions** has three choices:

- *Tell me on Home* (the default): once a day Ecoscribe asks GitHub for the newest version number. When there is one,
  Home says so with **Download** (the Releases page) and ×. **Install when idle** next to it gets the new version in
  the background and installs it when you step away or quit Ecoscribe. Nothing from your dictations or meetings is
  sent. On a Mac, only a version that has a Mac download is shown.
- *Install by itself*: the same for every new version, without asking. Never during a call, while a meeting
  is being saved or while you dictate.
- *Don't check*.

### Speech models

Ecoscribe picks the model for each language by itself. Each model shows what it's for and its size on disk; download
it with progress, or delete one to free space (it downloads again when it's next needed). Both run on your computer,
offline.
On a Windows PC without an NVIDIA graphics card, or with one under 3 GB, a third one, **For this computer** (about 0.5 GB), is the one dictation
uses; the other two are only for meetings and files there, and slow.

### Help

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
| `[hotkey] numpad_enter = true` | The Enter key on the number pad works like your dictation key (it stops typing Enter) |
| `[whisper] on_demand = false` | Keep the speech model loaded all day instead of freeing the GPU 10 minutes after the last dictation |
