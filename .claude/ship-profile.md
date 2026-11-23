# Ship profile: Ecoscribe

How /ship builds, checks and releases a change to Ecoscribe, the dictation and meeting-notes app for Windows and
macOS (one codebase). Read `CLAUDE.md` first: its standard process (one ticket, one branch from the latest
`origin/main`, one PR, never stacked) applies to every /ship run. The repo is public, so rule 7 there (no personal
data anywhere public) holds for every commit, branch name and PR text. Windows commands run from WSL at the repo
root after `. tools/winpy.sh`, which defines `wpy`, `wtest` and `APP_W`. Every `gh` call uses
`GH_TOKEN=$(gh auth token --user ErikBros)`.

## Build
- A normal ticket has nothing to compile: the app is Python plus the window's HTML and JavaScript, and the tests
  run it from source. `npm install` once per worktree for the jsdom tests.
- An install build (the release step under Deploy): first check C: has at least 2 GB free, then
  `wpy "$APP_W\\tools\\build.py" --installer`. It freezes `Ecoscribe.exe` and writes
  `Ecoscribe-Setup-<version>.exe` in the build folder (`%USERPROFILE%\ecoscribe-build`, never Downloads).
  Only one build at a time on this PC.
- The Mac app (`python tools/build_mac.py`) is built by the GitHub Mac workflow on each release, or by the Mac
  session; never from Windows.

## Test
- Fast checks for the part that changed: `bash tools/quick_tests.sh py` (Python) and `bash tools/quick_tests.sh js`
  (the window's JavaScript and the look checklist). Both exit 0 on a healthy repo.
- The full unit suite: `wtest "$APP_W\\tests" -q -m "not gpu and not win"`, plus `npm run smoke` and `npm run look`.
  The same suite runs in CI on every PR; `unit (windows-latest)`, `unit (macos-15)` and `pr-shape` must all be green
  before a merge (GitHub enforces it).
- Before every push: `wtest "$APP_W\\tests\\test_no_secrets.py" "$APP_W\\tests\\test_repo_hygiene.py" "$APP_W\\tests\\test_no_personal_data.py" -q`.
- A PR that touches shared code also runs the GPU suite (`-m gpu`) and the real-desktop suite (`-m win`, it waits
  for 45 s of idle), but only while Erik is away from the PC. While he is at it, merge on green CI and note the
  owed local suites in the ticket.
- Only one Windows test run at a time. A bug fix ships with a test that fails before the fix. OS-specific work
  keeps `tests/test_platform_contract.py` green (it checks `ecoscribe/platform/base.py` and `FEATURES.md`).

## Render
- The window's pages: `wpy "$APP_W\\tools\\before_after.py" --before origin/main --out <decision folder>/<round>.html --round <round>`
  shoots every window page (headless Edge with the demo API, nothing on screen) from main and from the branch at
  980, 1470 and 1920 px, and writes one page with only the screens that changed (side by side, slider, difference).
  `--pages` narrows it; `--variant "Name=<folder>"` (2 or 3 of them) when the change is a choice of look.
  The decision folder is the one served at http://localhost:8766 (Erik's personal CLAUDE.md names it); open the
  page in Chrome and start its `wait_send.py <round>` in the background.
- Before showing it, the change passes `docs/look-checklist.md`; `npm run look` checks the testable part.
- The pill, the tray menu, the prompt box and other pop-ups live outside the window pages: draw them from their
  own code (the pill's states come from `ecoscribe/platform/windows/pillart.py`) or shoot them in the running app
  only after 45 s of idle, and add them to the same page.
- The Mac look comes from the Mac session (`tools/mac_shoot.py`). No picture files for Erik: every picture goes on
  the decision page. A change with no screen says so in the report.

## Deploy
- Every ticket: commit with `(ticket: dictado-...)`, push the branch, open the PR at once
  (`gh pr create --base main`, body in the AGENTS.md "Public text" outline, with the guides in `docs/` updated or a
  `docs: not needed, because <reason>` line). Merge when the three checks are green:
  `gh pr merge <n> --merge --delete-branch`. Then `bd close` the ticket and `bd sync`.
- Install on Erik's PC, once per batch of merged user-facing tickets, never per ticket: a version PR that raises
  `ecoscribe/__init__.py` and adds the new lines to `ecoscribe/whatsnew.py`, merged green; then from the updated
  main check `%LOCALAPPDATA%\ecoscribe\meetings.json` (no install during a live meeting; wait and say so) and run
  `wpy "$APP_W\\tools\\build.py" --installer --install`, which runs the release gate and installs only when every
  line says PASS.
- After a passing install: `python3 tools/release.py` makes the GitHub release (the What's new lines as notes, privacy
  checked; the Mac .dmg is added by the Mac workflow), and the older Setup files in the build folder are deleted
  (standing yes; the delete goes through the guard's queue). Tell the Mac session about the new version with SendMessage.

## Verify live
- A merge: `gh pr view <n>` says MERGED and `git log origin/main` has the commit.
- An install: the release gate's last lines read `Installed: yes, <version>` and `Running now: yes`, read from
  `%LOCALAPPDATA%\ecoscribe\status.json` (state `ready`, the new version). `bd memories installed-windows` shows the
  new version, and `gh release view v<version>` lists `Ecoscribe-Setup-<version>.exe`.
- `python3 tools/in_step.py` prints no `STOP:` line and no release still missing its Mac download.

## Ask first
- Publishing anything public beyond the standard flow: a new repo, making the tickets repo public, a share link,
  anything posted outside this repo's PRs and releases. (Branches, PRs and the GitHub release of each installed
  version are the standing process and need no question.)
- Money: any purchase, paid service, paid API or signing certificate.
- Deletes of anything that existed before the run, Erik's data above all (`%LOCALAPPDATA%\ecoscribe`: history,
  meetings, recordings, settings). The one standing yes: older Setup files after an install.
- Anything on Erik's desktop while he works: the real-desktop tests, keys, windows, clipboard, the microphone.
- Swapping a speech engine or model for a faster but less accurate one (accuracy comes first).
- A Mac-only or Windows-only change that leaves the other platform without a done, a ticket or a reason.

## Design gate
Design is any change to how the window, the pill, the tray menu, the prompt box, a pop-up, the installer screens
or the What's new lines look or read: layout, colours, sizes, spacing, wording, labels, what a screen shows.
/ship builds it, runs the look checklist, renders before and after (2 or 3 variants when it is a choice of look)
on a decision page at http://localhost:8766, and then waits for Erik's Approve on that page before merge, install
or calling it done. "Not this" with a note means rework and a new page. Logic-only PRs skip the gate.

## No-go
- None of Erik's personal data anywhere public: no dictation or meeting text, no quotes of what he says, no numbers
  about his speech or usage, no names, personal paths, keys or calendar links in git, branch names, PR text or
  release notes. Tests and demo data use invented text. Private ticket text reaches public only rewritten, and
  every public text passes `tools/privacy_guard.py`.
- Nothing straight to main, no stacked branches, no squash merges, no merge before the checks are green.
- Never `git push --no-verify` or skipping a hook; a refused commit or push is fixed, never bypassed.
- Never install or restart the app during a live meeting.
- Never an empty `bd init` and never ticket files in this repo (`.beads/issues.jsonl` stays ignored).
- Never leave `gh auth switch` on the personal account; never add another remote.
- No picture files handed to Erik; looks go on the decision page.
- No em dashes in anything a user or Erik reads.
