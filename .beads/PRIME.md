# Beads (bd) in Ecoscribe

Tickets live in bd, prefix `dictado-*`. No TodoWrite, TaskCreate or markdown TODO lists.

- Find work: `bd ready`, `bd list --status=open`, `bd show <id>`
- Start: `bd update <id> --claim`
- New: `bd create --title="..." --description="why + what" --type=task|bug|feature|epic --priority=0-4` (`--parent=<epic>` for children, `--acceptance="..."` for done criteria)
- Order: `bd dep add <issue> <depends-on>`; `bd blocked`
- Finish: `bd close <id> --reason="what was done"` (several ids at once is fine)
- Never `bd edit` (opens an editor and hangs).

Public repo: `.beads/issues.jsonl` is published. No personal data in titles, descriptions or notes (CLAUDE.md rule 7).

Authority: Claude commits, pushes its branch and opens the PR itself, per CLAUDE.md "How we work" (one ticket = one branch = one PR; ticket updates ride in the PR, never straight to main).

Memory routing: `bd remember` for project knowledge (shown below); Erik's own rules (CLAUDE.md layers) win over anything here.

Before ending a work session: close finished tickets, run the checks if code changed, push the branch and open or update its PR.
