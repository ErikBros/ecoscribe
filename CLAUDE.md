# Ecoscribe: instructions for every Claude session (Windows and Mac)

Ecoscribe is one codebase for Windows and macOS. Two Claude sessions work on it: one on Windows
(merges and runs the Windows desktop/GPU tests), one on the Mac. Erik isn't a programmer: he gets
outcomes in plain words and only real choices (money, publishing, his desktop, what the app does).

## How we work: STANDARD PROCESS (enforced, not optional)

1. **One ticket = one branch = one pull request.** Branch from the *latest* `origin/main`
   (`git fetch && git switch -c <short-name> origin/main`). Name the ticket in commits:
   `(ticket: dictado-xxx)`.
2. **Never stack.** Never branch from another open branch. A follow-up waits until the first PR
   is merged, then starts from the updated main. The `pr-shape` check fails stacked PRs.
3. **Open the PR as soon as the branch is pushed** (`gh pr create --base main`), even if small.
4. **Merge only when green:** `unit (windows-latest)`, `unit (macos-14)` and `pr-shape` must pass
   (GitHub enforces it on `main`, for everyone). The Windows session also runs the local desktop
   and GPU suites when a PR touches shared code. Merge commits, no squash.
5. **Short-lived branches:** merge within the day; branches are deleted on merge. If main moves,
   rebase your one branch, never a pile.
6. **Nothing goes straight to main.** Tickets are not in this repo: they live in the private ticket store
   (Beads below) and sync with `bd sync`, never through a PR.
7. **Public repo:** before every push, `tests/test_no_secrets.py`, `tests/test_repo_hygiene.py` and
   `tests/test_no_personal_data.py` pass and the diff has no names, personal paths, keys or calendar links.
   **Never any of Erik's personal data** anywhere public: git, commit messages, branch names, PR titles,
   bodies and comments, release notes: no dictation or meeting text, no quotes of what he says, no numbers
   about his speech or usage. Tests and demo data use invented text; describe requests neutrally ("the user
   wants X"). **Private tickets** may say what he wants and why, but still no dictation or meeting text
   (they sit on GitHub's servers). **Private text reaches public only rewritten, never copied:** every
   public text passes `tools/privacy_guard.py` (commits, pushes and branch names through the git hooks;
   `gh` PR, release and issue text through the Claude Code check), which also refuses pieces copied from a
   ticket. PR bodies follow the outline in AGENTS.md (Public text).
8. **Parity:** OS-specific work updates `ecoscribe/platform/base.py` + `FEATURES.md` in the same PR
   (`tests/test_platform_contract.py` checks it); the other platform gets done, a ticket, or
   "not needed" with a reason.
9. **gh account:** the repo belongs to ErikBros. Use `GH_TOKEN=$(gh auth token --user ErikBros) gh ...`
   per command; never leave `gh auth switch` on the personal account (other sessions are work).
10. **Design gate.** Any change to how a screen, the pill, a pop-up or a page looks or reads: render
    before/after stills (2 to 3 variants when it's a choice of look), show Erik, and merge, install or
    call it done only after he approves. Logic-only PRs skip this. `tools/before_after.py` builds the
    page (every window page at 980/1470/1920 px, only what changed, slider, Approve / Not this); write it
    into his local decision-page folder so his answer is saved (his personal CLAUDE.md has where).
    Before showing it, the change passes `docs/look-checklist.md` (`npm run look` checks the testable part).
11. **User guides.** A PR that changes the window, the pill, the tray or the prompt box updates the guides in
    `docs/` (index: `docs/README.md`) or has a line in its body: `docs: not needed, because <reason>`.
    pr-shape checks it (`tools/docs_check.py`).
12. **Installs on Erik's PC.** Check `%LOCALAPPDATA%\ecoscribe\meetings.json` before installing or
    restarting; never during a live meeting (the installer also waits). Builds leave ~0.5 GB installers
    in the build folder (not in Downloads since dictado-38z): check C: free space before a build, and after an install delete every older Setup without asking
    (the owner's standing yes, 2026-10-23; the delete goes through the guard's queue).

## Build & test

```bash
. tools/winpy.sh                                   # Windows (from WSL): WINPY + APP_W
wtest "$APP_W\\tests" -q -m "not gpu and not win"   # unit
wtest "$APP_W\\tests" -q -m gpu                     # GPU (NVIDIA)
wtest "$APP_W\\tests" -q -m win                     # real desktop, waits for 45 s idle
npm install && npm run smoke                       # the window's JavaScript (jsdom)
wpy "$APP_W\\tools\\build.py" --installer          # Windows installer
wpy "$APP_W\\tools\\build.py" --installer --install  # installer, release gate, install only on all PASS
python tools/build_mac.py                          # macOS .app + .dmg (on the Mac; releases: GitHub mac-release)
tools/mac_check.sh                                 # macOS test suite (on the Mac)
```


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB, synced by `bd sync` through the **private** remote
ErikBros/ecoscribe-tickets (`refs/dolt/data`). The old `.beads/issues.jsonl` here is frozen (no export writes it) until it
is removed from git. A fresh clone joins with
`bd init --prefix dictado --remote git+ssh://git@github-personal/ErikBros/ecoscribe-tickets.git`, never an empty
`bd init` (it would push an empty database; the mass-delete guard asks first). See
https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session start (Windows and Mac)

The first lines of a session are the in-step check (`tools/in_step.py`). Act on them before anything else:
`bd sync` when tickets aren't synced; merge green PRs (any platform's); on the Mac, build and attach the missing Mac
downloads (`tools/release.py`); a `STOP:` line is fixed first.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items, then `bd sync`
4. **PUSH YOUR BRANCH AND OPEN/UPDATE ITS PR** (see STANDARD PROCESS above; main is protected):
   ```bash
   git fetch && git rebase origin/main   # your one branch only
   git push -u origin HEAD
   gh pr create --base main              # if it has no PR yet
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
