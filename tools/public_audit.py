#!/usr/bin/env python3
"""Public audit (dictado-trtz.1): everything this repo has ever put on GitHub, through the privacy check.

    python3 tools/public_audit.py [--repo owner/name] [--verbose]

Downloads every PR (title, body, branch name), issue (title, body), issue and PR comment, PR review and
review comment, commit comment and release (name, tag, notes), runs tools/privacy_guard.py's `text`
check on each (gitleaks, the user's own dictations, copies of private ticket text), then
`privacy_guard.py history` over the whole git history. Prints counts and where a hit is
("PR #12 body: speech check ..."), never the matched text. Exit 1 on any hit or a check that can't run.
Token: $GH_TOKEN if set, else `gh auth token --user ErikBros` (the repo's account).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import privacy_guard as guard  # noqa: E402

DEFAULT_REPO = "ErikBros/ecoscribe"
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


def exported_ticket_words() -> str:
    """The ticket free text that the repo itself publishes in .beads/issues.jsonl on origin/main, as a word
    stream: a PR that copied it leaked nothing new (tickets were public until they moved to a private store)."""
    try:
        raw = guard._git("show", "origin/main:.beads/issues.jsonl")
    except (OSError, subprocess.CalledProcessError):
        return " "
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


def main(argv: list[str]) -> int:
    repo = argv[argv.index("--repo") + 1] if "--repo" in argv else DEFAULT_REPO
    env = {**os.environ, "GH_TOKEN": token()}
    texts = public_texts(repo, env)
    kinds = Counter(" ".join(re.sub(r"^release \S+|#\d+|\b[0-9a-f]{9}\b|\b\d+\b", lambda m: "release" if
                                     m.group(0).startswith("release") else "", w).split()) for w, _ in texts)
    print(f"public audit of {repo}: {len(texts)} texts (" + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) + ")")
    exported = exported_ticket_words()
    hits, was_public = [], []
    try:
        hits = gitleaks_all(texts)
        for where, t in texts:
            speech = guard.speech_hits(t)
            if speech:
                hits.append(f"{where}: speech check, {len(speech)} piece(s) of your own dictations or meetings")
            for ticket, ps in sorted(guard.ticket_copies(t).items()):
                line = f"{where}: ticket-copy check, {len(ps)} piece(s) of {ticket}"
                (was_public if all(f" {p} " in exported for p in ps) else hits).append(line)
    except guard.Unavailable as e:
        print(f"public audit: a check can't run, so nothing is proven clean: {e}", file=sys.stderr)
        return 1
    for h in sorted(hits):
        print(f"  HIT {h}")
    print(f"text checks: {len(hits)} hit(s) in {len(texts)} texts")
    if was_public:
        print(f"  (+{len(was_public)} copies of ticket text in {len({w.split(':')[0] for w in was_public})} texts that "
              "the repo's own .beads/issues.jsonl already publishes: not a leak, but new text must not copy tickets)")
        if "--verbose" in argv:
            for h in sorted(was_public):
                print(f"  public-already {h}")
    hist = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "privacy_guard.py"), "history"])
    print(f"git history: {'clean' if hist.returncode == 0 else 'HIT (above)'}")
    return 1 if hits or hist.returncode else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
