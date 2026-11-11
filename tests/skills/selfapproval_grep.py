#!/usr/bin/python3
"""Grep every vendored skill for text that tells the agent to approve, merge,
ship, commit, mark done or auto-advance (skills/VENDORING.md).

    /usr/bin/python3 tests/skills/selfapproval_grep.py [--all]

A hit passes only if an allowlist row (skills/grep-allowlist.tsv, or
skills/<name>/MOADIX-GREP-ALLOW.tsv) has a path glob and a line regex that both match, with a reason (a data value, a quotation of a rule that
forbids the action, ...). Exit 0 when every hit is allowlisted.
--all prints allowlisted hits too.
"""
import fnmatch
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
SKILLS = os.path.join(REPO, "skills")
ALLOW = os.path.join(SKILLS, "grep-allowlist.tsv")
NOT_SCANNED = {"MOADIX-CHANGES.md", "MOADIX-GREP-ALLOW.tsv", "LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE.md", "NOTICE"}
NOT_SCANNED_TOP = {"SOURCES.yaml", "VENDORING.md", "grep-allowlist.tsv"}
TEXT_EXT = (".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".csv", ".py", ".js", ".sh", ".html", ".mjs", ".ts", "")

PATTERNS = [
    ("approve", r"\b(?:approve[sd]?|approving|approvals?|sign(?:s|ed)?[- ]off|lgtm)\b"),
    ("merge", r"\b(?:merge[sd]?|merging)\b"),
    ("ship", r"\b(?:ship|ships|shipped|shipping|release[sd]? (?:it|the|to)|deploy(?:s|ed|ing)?)\b"),
    ("commit", r"\bgit (?:commit|push|merge|tag)\b|\bcommit(?:s|ted|ting)? (?:the|your|all|these|this|it|them|to git|changes)\b"),
    ("mark-done", r"\bmark(?:s|ed|ing)?\b[^.\n]{0,40}\b(?:done|complete[d]?|finished|resolved|final)\b"
                  r"|\bstatus\s*[:=]\s*['\"`]?(?:done|complete[d]?|final|approved)\b"
                  r"|\b(?:flip|set)\b[^.\n]{0,30}\bstatus\b[^.\n]{0,20}\b(?:done|complete[d]?|final)\b"),
    ("auto-advance", r"\bnext phase\b|\bauto[- ]?advanc|\bautomatically (?:invoke|proceed|continue|start|run)\b"
                     r"|\bcommon next\b|\bproceed (?:to|with) (?:the )?next (?:phase|skill|workflow|story|epic)\b"),
]
RX = [(k, re.compile(p, re.I)) for k, p in PATTERNS]


def allow_files():
    out = [ALLOW] if os.path.exists(ALLOW) else []
    for d, dirs, files in os.walk(SKILLS):
        dirs.sort()
        if "MOADIX-GREP-ALLOW.tsv" in files:
            out.append(os.path.join(d, "MOADIX-GREP-ALLOW.tsv"))
    return out


def load_allow():
    """Rows: <path glob, repo-relative>TAB<line regex>TAB<reason>."""
    rows = []
    for path in allow_files():
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 3 or not parts[2].strip():
                raise SystemExit("%s line %d: need <path glob>TAB<line regex>TAB<reason>" % (path, n))
            rows.append((parts[0], re.compile(parts[1], re.I), parts[2]))
    return rows


def scan(root=SKILLS):
    allow = load_allow()
    hits = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in ("__pycache__", ".git"))
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(d, f), REPO)
            if f in NOT_SCANNED or f.startswith(("LICENSE", "NOTICE")) or (d == root and f in NOT_SCANNED_TOP):
                continue
            if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                continue
            try:
                text = open(os.path.join(d, f), encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for kind, rx in RX:
                    m = rx.search(line)
                    if not m:
                        continue
                    reason = next((r for g, lrx, r in allow if fnmatch.fnmatch(rel, g) and lrx.search(line)), None)
                    hits.append({"path": rel, "line": n, "kind": kind, "match": m.group(0), "text": line.strip()[:200],
                                 "allowed": reason})
    return hits


def main():
    hits = scan()
    bad = [h for h in hits if not h["allowed"]]
    for h in (hits if "--all" in sys.argv else bad):
        print("%s %s:%d [%s] %r  %s" % ("ALLOWED" if h["allowed"] else "HIT", h["path"], h["line"], h["kind"],
                                       h["match"], h["text"][:140]))
        if h["allowed"] and "--all" in sys.argv:
            print("        reason: %s" % h["allowed"])
    files = len({h["path"] for h in hits})
    print("selfapproval grep: %d match(es) in %d file(s); %d allowlisted with a reason; %d NOT allowed" % (
        len(hits), files, len(hits) - len(bad), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
