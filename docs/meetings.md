# Meetings

([All guides](README.md).) Ecoscribe records your mic and the computer's sound during a call, shows a live
transcript, and after the call writes a better one with each line labelled **Me** (your mic) or **Others** (the
computer's sound). Everything stays on your computer.

## Before you record

- **Tell the people on the call that you're transcribing.** In many places that's expected, and in some it's
  required by law. Ecoscribe doesn't announce itself to anyone.
- **Check what it will hear.** Use the headset or speakers the call uses. The first time on a Mac, allow **Screen &
  System Audio Recording** when macOS asks, or only your side is recorded.
- **Pick the language** in the box that asks: one language, a pair like English + Spanish for a call that mixes
  them, or Detect. A wrong language gives a poor transcript; you can change it while the call runs.

## Taking notes in a call

- When a call app takes the mic (Teams, Slack, Zoom, Meet, Discord, Signal, Telegram, Webex...), a box asks **"Are you
  in a meeting? Take notes?"** with the app's name and a language chip. **Take notes** starts; **Not now** counts down
  10 seconds and is what happens if you ignore it.
- **Settings > Meetings > When a call starts:** *Ask* (default), *Start by itself*, or *Don't detect*.
- **A web page that uses the mic and talks back** (a language-practice or voice page) can look like a call in a browser. Add a word from its tab title to `not_calls` under `[meetings]` in `config.toml` (for example `not_calls = ["Practice"]`) and it isn't taken for a call; a Meet, Zoom or Teams tab still is.
- **By hand:** Home > **Record a meeting**, the Meetings tab > **Record meeting**, or the tray icon > *Transcribe meeting
  now* / *Stop meeting*.
- **The call ends** when the app has been off the mic for 10 seconds (Settings > Meetings > Stop recording after the
  call ends: 5 seconds to 2 minutes; longer keeps one recording through a quick rejoin). If both sides go quiet for a
  long time without the call ending, a box asks **Did the meeting end?** (Stop / Keep going).

### While it records

- **The meeting pill:** a small chip with a recording dot and the timer. Put the mouse on it to see the latest line.
- **Move it:** drag the chip where you want it; it stays there next time. Double-click puts it back. (Windows; Mac
  ticket dictado-8dy.)
- **The Meetings tab** shows the live transcript (**Watch live**), the language, and **Stop**.
- **What it's recording:** two small meters next to Stop, one for your mic ("hearing you") and one for the call
  ("hearing them"). Hover one to see the device. If one stays silent while the call app uses another device, a warning
  says so with a button to record that device instead (**Record** + the device's name). On Windows Ecoscribe also
  follows the call by itself: a silent source switches to the device the call app uses.
  The warning's × hides it for the rest of that meeting (useful in a room meeting, where nothing plays on the
  computer); the meter still shows the source as silent.
- **Your notes:** type in the notes box above the transcript, during or after the call. It saves itself, and Copy for
  Claude, the summary prompt and the .md download include it.

## After the call

A box says **Transcript ready** (Open). Open the meeting from the Meetings tab:

- **Copy ▾:** the transcript, **Copy for Claude** (with date, app and language, ready to paste into Claude), or **Copy a
  summary prompt** (decisions and action items).
- **Email participants:** a draft in your own mail program, addressed to the calendar invite's guests, with the
  transcript in it (or copied, to paste). You read it and press Send. No guests and no calendar connected: the
  transcript is copied and Google Calendar opens on the call's day, for the event's own **Email guests** button; a
  toast says the steps.
- **···:** download as Text (.txt), Markdown (.md) or Subtitles (.srt), **Open folder**, **Delete**. Downloads go to
  your Downloads folder (Settings > Meetings > Downloads go to; **Use Downloads** resets it). The file is shown
  selected in its folder.
- **Rename:** click the title and type.
- **Replace list on a saved meeting:** when your [Replace](dictation.md#getting-names-and-words-right) list would
  change something, the meeting page says how many places match and which words. **Apply** rewrites the transcript
  and its downloads (never the audio); **Undo** right after puts it back; **Not now** hides it. Not offered while the
  transcript is still being written.
- **Your name:** Settings > Meetings > Your name shows your lines with your name instead of "Me", in the window and in
  what you copy or download.

## Who said what (speaker add-on)

With the speaker add-on installed (Windows: download it from **[its release](https://github.com/ErikBros/ecoscribe/releases/tag/speakers-1.2.0)**, see [Windows](windows.md#1-what-to-download)) and **Tell the other speakers apart** on (Settings > Meetings), the other side
becomes **Speaker 1, 2, 3...** Click a speaker's label to type their name; every line and every download updates. On a
one-to-one call it stays "Others". On Windows the speakers pass runs during the call when the NVIDIA card has room,
otherwise after it.

**Remember voices** (on by default): once you've named a speaker, Ecoscribe recognises that voice in later calls and
names them by itself. Voices are kept on your computer only; **Forget all voices** deletes them.

## Meeting names from your calendar

A recorded call takes the name of the calendar event happening at that time, and the event's guests help spell names
and fill Email participants. Two ways, both in Settings > Meetings:

- **Google Calendar > Connect:** sign in once, read-only. Works on work accounts that hide the secret address. A call
  recorded before you connected looks its event up when you press Email participants.
- **Calendar address:** paste your calendar's secret address in iCal format (Google Calendar:
  Settings, your calendar, Integrate calendar) and press **Test**.

No event? A call in a Google Meet tab takes the tab's meeting name.

## Personal calls, summaries and to-dos

- **Personal calls:** a call on Signal, WhatsApp, Telegram or Discord, a call whose title starts with `p-`, or one in a
  language you list under `[personal] languages` in config.toml. The automatic steps below touch only these.
- **Call summaries** (`[summaries] enabled = true` in config.toml, off by default; needs Claude Code on the computer):
  after a personal call, a `summary.md` appears next to it with decisions, to-dos and open questions, each with its
  time and the words it came from, checked against the transcript. A box says **Summary ready**. The Claude app reads
  it first.
- **Your to-dos for the week:** with summaries on, Home shows your own to-dos from this week's personal calls (or last
  week's), one column per person, each ticked off and linked to its call. Sunday from 18:00 the week is written to
  `todos/<monday>.md` in Ecoscribe's data folder, with one notice.
- **Your own command after a transcript** (advanced): `[transcribe] after_transcribe` in config.toml runs a command of
  yours with the session folder when a transcript is done.

## Files

Drag an mp3, m4a, wav, ogg, opus, flac, mp4 or webm onto the window, or use Home > **Transcribe a file** or Meetings >
**Import file**. One job runs at a time; the rest wait in the queue. A file gets the same page, copies and downloads
as a meeting.

## Search

The search box on the Meetings tab finds titles and what was said, ranked and grouped by call. Case and accents
don't matter, in any script. To ask questions about your calls in plain words, see [With Claude](claude.md).
