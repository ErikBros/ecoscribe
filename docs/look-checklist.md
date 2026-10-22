# Look checklist

Every change to how the window, the pill, a pop-up or a page looks or reads passes these before it is
shown for approval (CLAUDE.md rule 10). `tests/ui/look.mjs` checks the ones a test can judge (marked
**test**) on every demo page; the rest the builder and the reviewer check by eye on the before/after page
(`tools/before_after.py`).

1. **Every number says what it counts.** "4,877 words", not "4,877". A chart axis has a title. (**test**)
2. **No placeholders.** No "—" or empty boxes: say what is missing ("No mic yet"). (**test**)
3. **The words match the state.** Stopped or loading: no "tap the key"; failed: say what failed and what to do. (**test**)
4. **Status shows once per screen.** One place says Ready / Recording / Stopped. (**test**)
5. **One colour set.** Colours, sizes and corner radii come from the `:root` tokens; the count of colours written
   elsewhere may only go down. (**test**, a ratchet)
6. **One badge family.** Status chips share one shape, size and type; only the token colour changes.
7. **A primary button never looks disabled while it works.** Disabled looks only when a click does nothing.
8. **Numbers line up.** Tabular figures in tables, lists and timers.
9. **Uses the width.** Checked at 980 (the window), 1470 and 1920 px: no half-empty screen at desktop width,
   nothing cut off in the window.
10. **One icon style.** Same stroke width and size as the icons next to it.
