#!/usr/bin/env python3
"""Public audit (dictado-trtz.1): everything this repo has ever put on GitHub, through the privacy check.

    python3 tools/public_audit.py [--repo owner/name] [--verbose] [--weekly]

Downloads every PR (title, body, branch name), issue (title, body), issue and PR comment, PR review and
review comment, commit comment and release (name, tag, notes), runs tools/privacy_guard.py's `text`
check on each (gitleaks, the user's own dictations, copies of private ticket text), then
`privacy_guard.py history` over the whole git history. Prints counts and where a hit is
("PR #12 body: speech check ..."), never the matched text. Exit 1 on any hit or a check that can't run.
Token: $GH_TOKEN if set, else `gh auth token --user ErikBros` (the repo's account).

Hits a person has looked at and found harmless go in tools/audit_reviewed.txt (one "<where>: <ticket>"
per line, with the reason after " # "); they are counted, not reported again. Only ticket-copy hits can be
reviewed: a speech or gitleaks hit is always reported.

--weekly (run by /close, dictado-trtz.6): does nothing when the last audit, on either computer, was less
than 7 days ago (private ticket memory public-audit-last). Otherwise it runs, records the date and the
result there, and on a hit opens a private P1 ticket with the locations (never in anything public).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import privacy_guard as guard  # noqa: E402

DEFAULT_REPO = "ErikBros/ecoscribe"
TICKETS_FILE = ".beads/issues.jsonl"
REVIEWED = Path(__file__).resolve().parent / "audit_reviewed.txt"
LAST_KEY = "public-audit-last"
WEEK_DAYS = 7
HIT_TICKET = "Public audit found text to look at"
REVIEWS = """query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes { number reviews(first: 100) { nodes { body } } }
    }
  }
}"""


def token() -> str:
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    r = subprocess.run(["gh", "auth", "token", "--user", DEFAULT_REPO.split("/")[0]], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(f"public audit: no GitHub token (set GH_TOKEN or log in with gh): {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def gh_pages(args: list[str], env: dict) -> list:
    """`gh api --paginate` output (one JSON document per page, back to back) as one list of pages."""
    r = subprocess.run(["gh", "api", "--paginate", *args], capture_output=True, text=True, encoding="utf-8", env=env)
    if r.returncode != 0:
        sys.exit(f"public audit: gh api {args[0]} failed: {r.stderr.strip()[:300]}")
    dec, out, i, s = json.JSONDecoder(), [], 0, r.stdout
    while i < len(s):
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            break
        doc, i = dec.raw_decode(s, i)
        out.append(doc)
    return out


def gh_list(path: str, env: dict) -> list[dict]:
    items = []
    for page in gh_pages([path], env):
        items += page if isinstance(page, list) else [page]
    return items


def _num(url: str | None) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def public_texts(repo: str, env: dict) -> list[tuple[str, str]]:
    """(where, text) for every piece of text the repo has on GitHub."""
    out: list[tuple[str, str]] = []
    for pr in gh_list(f"repos/{repo}/pulls?state=all&per_page=100", env):
        n = pr["number"]
        out += [(f"PR #{n} title", pr.get("title") or ""), (f"PR #{n} body", pr.get("body") or ""),
                (f"PR #{n} branch name", (pr.get("head") or {}).get("ref") or "")]
    for it in gh_list(f"repos/{repo}/issues?state=all&per_page=100", env):
        if "pull_request" not in it:
            n = it["number"]
            out += [(f"issue #{n} title", it.get("title") or ""), (f"issue #{n} body", it.get("body") or "")]
    for c in gh_list(f"repos/{repo}/issues/comments?per_page=100", env):
        out.append((f"#{_num(c.get('issue_url'))} comment {c.get('id')}", c.get("body") or ""))
    for c in gh_list(f"repos/{repo}/pulls/comments?per_page=100", env):
        out.append((f"PR #{_num(c.get('pull_request_url'))} review comment {c.get('id')}", c.get("body") or ""))
    for c in gh_list(f"repos/{repo}/comments?per_page=100", env):
        out.append((f"commit {str(c.get('commit_id'))[:9]} comment {c.get('id')}", c.get("body") or ""))
    for rel in gh_list(f"repos/{repo}/releases?per_page=100", env):
        tag = rel.get("tag_name") or "?"
        out += [(f"release {tag} name", f"{tag}\n{rel.get('name') or ''}"), (f"release {tag} notes", rel.get("body") or "")]
    owner, name = repo.split("/", 1)
    for page in gh_pages(["graphql", "-f", f"query={REVIEWS}", "-F", f"owner={owner}", "-F", f"name={name}"], env):
        for pr in page["data"]["repository"]["pullRequests"]["nodes"]:
            for k, rv in enumerate(pr["reviews"]["nodes"]):
                out.append((f"PR #{pr['number']} review {k + 1}", rv.get("body") or ""))
    return [(w, t) for w, t in out if t.strip()]


def gitleaks_all(texts: list[tuple[str, str]]) -> list[str]:
    """One gitleaks run over every text (a file each in a temp folder); hits by where."""
    with tempfile.TemporaryDirectory(prefix="ecoscribe-audit-") as d:
        for i, (_, t) in enumerate(texts):
            Path(d, f"{i}.txt").write_text(t, encoding="utf-8")
        found = guard.gitleaks_findings([guard.gitleaks_exe(), "dir", d])
    return [f"{texts[int(Path(f.get('File', '')).stem)][0]}: gitleaks rule {f.get('RuleID')} on line {f.get('StartLine')}"
            for f in found if Path(f.get("File", "")).stem.isdigit()]


def exported_tickets_raw() -> str:
    """The last .beads/issues.jsonl that origin/main published. After the file left git (dictado-trtz.2) that is
    the version just before the commit that removed it: still public, in the history."""
    try:
        return guard._git("show", f"origin/main:{TICKETS_FILE}")
    except (OSError, subprocess.CalledProcessError):
        pass
    try:
        last = guard._git("rev-list", "-1", "origin/main", "--", TICKETS_FILE).strip()
        return guard._git("show", f"{last}^:{TICKETS_FILE}") if last else ""
    except (OSError, subprocess.CalledProcessError):
        return ""


def exported_ticket_words(raw: str | None = None) -> str:
    """The ticket free text that the repo itself published in .beads/issues.jsonl, as a word stream: a PR that
    copied it leaked nothing new (tickets were public until they moved to a private store)."""
    raw = exported_tickets_raw() if raw is None else raw
    chunks = []
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        texts = [rec.get(f) for f in guard.TICKET_FIELDS] + [c.get("text") for c in rec.get("comments") or []
                                                             if isinstance(c, dict)]
        chunks += [" ".join(guard.words(t)) for t in texts if isinstance(t, str)]
    return " " + " \n ".join(chunks) + " "


def reviewed_keys(path: Path = REVIEWED) -> set[str]:
    """"<where>: <ticket>" lines from tools/audit_reviewed.txt (a comment runs from "# " to the end of the line)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    keys = (re.split(r"(?:^|\s)#(?:\s|$)", ln, maxsplit=1)[0].strip() for ln in lines)
    return {k for k in keys if k}


def bd(*args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["bd", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return r.returncode, r.stdout


def days_since_last(memories_json: str, today: float) -> float | None:
    """Days since the date in the public-audit-last memory ("YYYY-MM-DD ..."), None when there is none."""
    try:
        value = json.loads(memories_json or "{}").get(LAST_KEY) or ""
        then = time.mktime(time.strptime(value.split()[0], "%Y-%m-%d"))
    except (ValueError, IndexError, AttributeError):
        return None
    return (today - then) / 86400


def record_run(hits: list[str]) -> None:
    """Shared memory with the date and result; a private ticket listing where the hits are (never public)."""
    result = f"{len(hits)} hit(s)" if hits else "clean"
    bd("remember", "--key", LAST_KEY, f"{time.strftime('%Y-%m-%d')} {result}")
    if hits:
        code, out = bd("list", "--status", "open,in_progress", "--title", HIT_TICKET, "--json")
        if not (code == 0 and HIT_TICKET in out):
            bd("create", "--title", HIT_TICKET, "--type", "bug", "--priority", "1", "--description",
               "Weekly public audit (tools/public_audit.py) found these. Look at each one: rewrite or remove the "
               "public text, or, when harmless, add it to tools/audit_reviewed.txt with the reason.\n"
               + "\n".join(hits))
    bd("dolt", "push")


def main(argv: list[str]) -> int:
    repo = argv[argv.index("--repo") + 1] if "--repo" in argv else DEFAULT_REPO
    weekly = "--weekly" in argv
    if weekly:
        code, out = bd("memories", "--json")
        since = days_since_last(out, time.time()) if code == 0 else None
        if since is not None and since < WEEK_DAYS:
            print(f"public audit: last run {int(since)} day(s) ago, next in {WEEK_DAYS - int(since)}.")
            return 0
    env = {**os.environ, "GH_TOKEN": token()}
    texts = public_texts(repo, env)
    kinds = Counter(" ".join(re.sub(r"^release \S+|#\d+|\b[0-9a-f]{9}\b|\b\d+\b", lambda m: "release" if
                                     m.group(0).startswith("release") else "", w).split()) for w, _ in texts)
    print(f"public audit of {repo}: {len(texts)} texts (" + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) + ")")
    exported = exported_ticket_words()
    reviewed = reviewed_keys()
    hits, was_public, seen = [], [], []
    try:
        hits = gitleaks_all(texts)
        for where, t in texts:
            speech = guard.speech_hits(t)
            if speech:
                hits.append(f"{where}: speech check, {len(speech)} piece(s) of your own dictations or meetings")
            for ticket, ps in sorted(guard.ticket_copies(t).items()):
                line = f"{where}: ticket-copy check, {len(ps)} piece(s) of {ticket}"
                if all(f" {p} " in exported for p in ps):
                    was_public.append(line)
                else:
                    (seen if f"{where}: {ticket.split()[0]}" in reviewed else hits).append(line)
    except guard.Unavailable as e:
        print(f"public audit: a check can't run, so nothing is proven clean: {e}", file=sys.stderr)
        return 1
    for h in sorted(hits):
        print(f"  HIT {h}")
    print(f"text checks: {len(hits)} hit(s) in {len(texts)} texts")
    if seen:
        print(f"  (+{len(seen)} reviewed earlier and harmless: tools/audit_reviewed.txt)")
    if was_public:
        print(f"  (+{len(was_public)} copies of ticket text in {len({w.split(':')[0] for w in was_public})} texts that "
              "the repo's own .beads/issues.jsonl already publishes: not a leak, but new text must not copy tickets)")
        if "--verbose" in argv:
            for h in sorted(was_public):
                print(f"  public-already {h}")
    hist = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "privacy_guard.py"), "history"])
    print(f"git history: {'clean' if hist.returncode == 0 else 'HIT (above)'}")
    if hist.returncode:
        hits.append("git history: privacy_guard.py history found something (run it to see where)")
    if weekly:
        record_run(hits)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
