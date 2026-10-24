# With Claude

([All guides](README.md).) Ecoscribe works with Claude in three ways. None of them is on until you turn it on, and
each says below what it sends where.

## Ask the Claude app about your meetings

If you use the Claude desktop app: Settings > Meetings > Claude app > **Connect**, then quit and reopen Claude. It
reads your transcripts (and your notes) through a small read-only server on your computer; it can never change them.

Now you can ask Claude:

- "Summarize yesterday's call", "what did Ana say about the budget?"
- "My calls with Ana": it finds the calls where someone is a named speaker, a calendar guest or in the title (part of
  a name is enough, accents don't matter).
- **Debrief my call:** pick it from Ecoscribe in Claude's + menu after a call. It lists the to-dos as tickets to make
  (only the ones you OK) and drafts a follow-up message for you to paste. It never opens your mail or calendar.

**Search by meaning:** when a search finds no call with your words, Ecoscribe counts the miss (only how many, never
the words) and from then on Claude can also search by meaning, so "the trip with friends" finds a call where it was
said in other words or another language. For that it downloads a 0.55 GB model once and, while nothing is recording,
reads your calls with it on the processor (about a minute for an hour of call). To keep it off: `[search] meaning =
"off"` in config.toml.

To disconnect, remove the `ecoscribe` entry under `mcpServers` in Claude's `claude_desktop_config.json`.

## Copy for Claude

On any meeting page, **Copy ▾ > Copy for Claude** copies the transcript with its date, app and language (and your
notes), ready to paste into any Claude chat. **Copy a summary prompt** adds a request for decisions and action items.
Settings > Help and setup > **Copy debug info for Claude** does the same for a problem with Ecoscribe itself.

## Fix it when you correct yourself

Settings > Dictation > With Claude > **Fix it when you correct yourself** (off by default). Needs Claude Code logged in
on the computer; Ecoscribe sends the text through it and nothing else.

- **"scratch that"** drops the sentence before it. No Claude needed for this one. Said on its own right after a paste, it
  takes the whole last dictation back (Ctrl+Z, only in the same window and within 60 seconds; Windows, and also with
  Voice commands on).
- **"no wait"** or **"sorry, I mean"**: Claude fixes that dictation before it's pasted. "On Tuesday, no wait, on
  Thursday" becomes "on Thursday", about 3 seconds later. If Claude doesn't answer in 5 seconds, the text goes in as
  you said it.

| What it does | English | Spanish | Swedish | Greek |
|---|---|---|---|---|
| Drops the sentence before it | "scratch that", "delete that", "strike that" | "borra eso", "tacha eso" | "stryk det", "sudda det" | "σβήσε το", "σβήσ' το" |
| Claude applies the correction | "no wait", "sorry I mean", "sorry I meant", "correction" | "no perdón", "no espera", "perdón quise decir", "corrijo" | "nej förlåt", "nej vänta", "förlåt jag menar", "rättelse" | "όχι συγγνώμη", "όχι περίμενε", "συγγνώμη εννοώ" |

A phrase only counts on its own, after a pause or punctuation: "scratch that itch" stays text. Only dictations with
one of these phrases go to Claude.

## Command mode

Settings > Dictation > With Claude > **Command mode** (off by default, Windows; Mac ticket dictado-waw). Change selected
text by voice:

1. Select text anywhere.
2. Press **Right Ctrl + E**.
3. Say what to change: "make it shorter", "translate to Swedish".
4. Tap Right Ctrl.

Claude rewrites it in place; Ctrl+Z brings the old text back. **change** next to the keys picks other ones (your
dictation key + a letter, or a combo of its own, pressed again to stop). Pressing the keys while it's off shows a box
that takes you to the switch.
