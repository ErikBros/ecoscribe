# Beads (bd) in Ecoscribe

Tickets live in bd, prefix `dictado-*`. No TodoWrite, TaskCreate or markdown TODO lists.

- Find work: `bd ready`, `bd list --status=open`, `bd show <id>`
- Start: `bd update <id> --claim`
- New: `bd create --title="..." --description="why + what" --type=task|bug|feature|epic --priority=0-4` (`--parent=<epic>` for children, `--acceptance="..."` for done criteria)
- Order: `bd dep add <issue> <depends-on>`; `bd blocked`
- Finish: `bd close <id> --reason="what was done"` (several ids at once is fine)
- Never `bd edit` (opens an editor and hangs).

Tickets are private: they sync through ErikBros/ecoscribe-tickets with `bd sync` (session start, after closing tickets, at /close), never through the public repo. They may say what the user wants and why, but never dictation or meeting text. Private text reaches public only rewritten (CLAUDE.md rule 7).

Authority: Claude commits, pushes its branch and opens the PR itself, per CLAUDE.md "How we work" (one ticket = one branch = one PR; ticket changes sync privately, never in a PR).

Memory routing: `bd remember` for project knowledge (shown below); Erik's own rules (CLAUDE.md layers) win over anything here.

Before ending a work session: close finished tickets and `bd sync`, run the checks if code changed, push the branch and open or update its PR.
