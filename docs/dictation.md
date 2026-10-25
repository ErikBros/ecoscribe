# Dictation

([All guides](README.md).) Keys are written for Windows; on a Mac read Right Command for Right Ctrl and the menu bar
icon for the tray icon.

## The basics

- **Tap Right Ctrl, talk, tap Right Ctrl again.** The text appears where your cursor is, a moment later, in any app.
  Ecoscribe adds the punctuation.
- **Cancel:** hold Right Ctrl and press Esc.
- **Hold to talk** (Settings > Dictation > Shortcut, off by default): hold Right Ctrl while you speak, let go to stop.
  A quick tap still starts hands-free dictation.
- **Another key:** Settings > Dictation > Shortcut > **Change**, then press a lone key (Right Ctrl, F13-F24, Pause) or
  a combo like `Ctrl+L`.
- **Numpad Enter dictates too** (Settings > Dictation > Shortcut): the Enter key in the corner of the number pad works
  like your dictation key. It stops typing Enter; the main Enter is untouched.
- While you talk you can switch apps or click around; it keeps recording and pastes where the cursor is when you stop.
- **No text box at the stop** (the desktop, a file list, a button): the text stays on the clipboard and the pill says
  so. Paste it with Ctrl+V. Every dictation is also in **History**.
- **Paste the last one again:** Right Ctrl + R (Mac: Right Command + R) pastes your last dictation once more at the
  cursor.

## The pill

A small dark capsule at the bottom of the screen shows what's happening: a dot and the waveform while you dictate, a
turning arc while it writes it down, the language it heard, and a short notice when something needs you (a mic it
can't use, for example).

- **Live text on the pill** (Settings > Dictation > Behaviour, on by default): the pill shows what it hears while you
  talk, a few seconds behind. It's a quick draft; the careful transcription is what gets pasted.
- **On-screen pill** (same place) turns the pill off. **Sounds** plays a short sound at start and stop.

## Languages

- Settings > Languages and words > **Languages you dictate in**: tick the ones you speak. Each dictation, Ecoscribe
  picks among them by itself and the pill shows which one it heard. English and Swedish are built in; **Add a
  language** has any of Whisper's 100. An added language also appears for meetings and files.
- **Wrong guess?** Hold Right Ctrl and press L: the next dictation is in the next language. The tray icon > **Next
  dictation in** does the same.
- **Several languages in one dictation** work: each piece between pauses is written in its own language. A short
  breath at the switch is enough.

## Getting names and words right

All in Settings > Languages and words.

- **Your words:** names and terms, one per line, written the way you want them. Ecoscribe leans toward them when it
  hears something close. Used for dictation, meetings and files.
- **Names on your screen** (on by default): when you start dictating, Ecoscribe reads the names in the window you're
  typing into (an email's sender, the people in a chat) and spells them the same way. Read on your computer, never
  stored or sent.
- **Replace:** a fix after it writes, every time. When the text has the words on the left, they become the ones on
  the right. For a word Your words didn't fix, or one you always want written another way. A saved meeting can get
  the list too ([Meetings](meetings.md#after-the-call)).
- **Snippets:** say a snippet's name on its own ("my email.") and Ecoscribe types the saved text instead. Inside a
  sentence ("what's my email?") it stays as you said it.

## Voice commands

Settings > Dictation > Behaviour > **Voice commands** (off by default). A command only counts on its own: at the
start, or after a pause or punctuation, and before one or the end. "We need a new line of products" stays text.

| What it does | English | Spanish | Swedish |
|---|---|---|---|
| Paragraph break | "new paragraph" | "nuevo párrafo", "punto y aparte" | "nytt stycke" |
| Line break | "new line" | "nueva línea" | "ny rad" |
| Press Enter after the text (at the very end only) | "send it", "press enter" | "envíalo", "enviar" | "skicka" |

Every phrase works whichever of your languages you speak. **See all commands** lists them; type a phrase and press
Enter to add your own, × removes one, **Back to the built-in phrases** resets the list.

Always on, no switch: say "quote" ... "end quote" (or "open quote" / "close quote", "comillas" / "cierra comillas",
"citat" / "slut citat") and the words between get quotation marks.

## Style per app

Settings > Dictation > **Style per app** > Different style per app (off by default). A command in a terminal needs no
capital and no full stop; a chat line usually ends without one. With it on, each kind of app gets its own style:

- **Terminal**, **chat**, **email**, and **everything else**, each with three switches: capital at the start, full
  stop at the end, voice commands on or off.
- Ecoscribe picks the kind from the app the text goes into, read just before the paste (and the site, in a browser).

Off: every app gets a capital at the start and a full stop at the end.

## With Claude

Two extras send a dictation to Claude through your Claude Code login: **Fix it when you correct yourself** ("no wait,
I mean...") and **Command mode** (Right Ctrl + E changes the selected text by voice). Both are off until you turn them
on. See [With Claude](claude.md#fix-it-when-you-correct-yourself).

## History and Retry

The **History** tab has every dictation (and meeting), newest first, with the app it went into. Copy any of them.

- **Retry ▾** on a recent dictation transcribes it again: **Again, detect the language**, or **Again, in** one of
  your languages. The new text is copied, ready to paste. The last 20 dictations keep their audio on your computer
  for this; older ones have no Retry.
- **Clear history** removes the list.
- After a crash in the middle of a dictation, the dictation comes back in History (not pasted).

## Memory and speed

**Free the GPU when you're not dictating** (Settings > Dictation > Behaviour, on by default): the model loads when you
tap (while you talk) and unloads after 10 minutes without dictating. The first dictation after a pause loads it while
you talk.
