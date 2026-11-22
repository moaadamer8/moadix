"""0.8.0 (task-tracker MF-59): the operator-reviewed gitleaks allowlist for test fixtures.

A gitleaks hit is HIGH and cannot be waived. A test fixture's password (a throwaway account's, in a test database a run
creates and drops) is not a credential, but it stays in the history for good, and rewriting the history would break the
ledger's approvals by commit. The operator may therefore allowlist one finding at a time, in
.sdlc/config/product-tools.yaml, adopted with ADOPT:

    gitleaks:
      allow:
        - fingerprint: "<commit>:tests/ui/core-loop.spec.ts:generic-api-key:7"   # history: commit:path:rule:line
          path: tests/ui/core-loop.spec.ts
          reason: "the throwaway account's password the UI test signs up with"
          fixture: true
        - fingerprint: "tests/ui/core-loop.spec.ts:generic-api-key:7"            # tree: path:rule:line
          ...

Each entry names exactly one finding (gitleaks' own fingerprint form), its path, the operator's reason, and that it is a
test fixture. A path outside tests/ or a fixtures directory, any path with a src/ directory, a glob, a whole rule or a
whole path is never allowlisted. The gate checks the entries when they are adopted (gate/adopt.py) and again when it
scans (check_scanners.py); an entry that fails is never applied, and the scan fails naming it. Every allowlisted finding
is listed in the validator's output (ALLOWLISTED lines), which REVIEW shows.
"""
import re

KEYS = ("fingerprint", "path", "reason", "fixture")
SEGMENT = re.compile(r"^[A-Za-z0-9._@+-]+$")
FINGERPRINT = re.compile(r"^(?:(?P<commit>[0-9a-f]{40}):)?(?P<path>[^:*?\[\]{}\s]+):(?P<rule>[a-z0-9][a-z0-9-]*):"
                         r"(?P<line>[1-9][0-9]*)$")
FIXTURE_DIRS = ("fixtures", "__fixtures__")
MAX_ENTRIES = 500


def fingerprint(mode, commit, path, rule, line):
    """gitleaks' fingerprint of a finding: commit:path:rule:line in the history (mode git), path:rule:line in the tree."""
    return ("%s:%s:%s:%s" % (commit, path, rule, line)) if mode == "git" else ("%s:%s:%s" % (path, rule, line))


def fixture_path(path):
    """A repo-relative file under tests/ or under a fixtures directory, never with a src/ directory."""
    parts = str(path or "").split("/")
    if not path or not all(SEGMENT.match(p) for p in parts) or any(p in (".", "..") for p in parts):
        return False
    if "src" in parts[:-1]:
        return False
    return parts[0] == "tests" or any(p in FIXTURE_DIRS for p in parts[:-1])


def problems(entries):
    """Why each entry cannot be applied ([] when all can). Entries: the list under gitleaks.allow."""
    if not isinstance(entries, list):
        return ["gitleaks.allow must be a list of entries"]
    if len(entries) > MAX_ENTRIES:
        return ["gitleaks.allow has %d entries; at most %d" % (len(entries), MAX_ENTRIES)]
    out, seen = [], set()
    for i, e in enumerate(entries, 1):
        tag = "gitleaks.allow entry %d" % i
        if not isinstance(e, dict):
            out.append("%s is not a mapping" % tag)
            continue
        tag += " (%s)" % (e.get("path") or e.get("fingerprint") or "no path")
        bad = sorted(str(k) for k in e if k not in KEYS)
        if bad:
            out.append("%s: key(s) %s are refused; an entry has only %s" % (tag, ", ".join(bad), ", ".join(KEYS)))
        fp, path = str(e.get("fingerprint") or ""), str(e.get("path") or "")
        m = FINGERPRINT.match(fp)
        if not fp:
            out.append("%s names no finding's fingerprint: a whole rule or path is never allowlisted" % tag)
        elif not m:
            out.append("%s: %r is not one finding's gitleaks fingerprint (commit:path:rule:line in the history, "
                       "path:rule:line in the tree)" % (tag, fp))
        elif m.group("path") != path:
            out.append("%s: the fingerprint's path %s is not the entry's path %s" % (tag, m.group("path"), path or "(none)"))
        if not fixture_path(path):
            out.append("%s: path %s is not a file under tests/ or a fixtures directory (never src/, never a glob): "
                       "only a test fixture can be allowlisted" % (tag, path or "(none)"))
        if e.get("fixture") is not True:
            out.append("%s must say fixture: true (the operator's statement that it is a test fixture, not a "
                       "credential)" % tag)
        reason = str(e.get("reason") or "").strip()
        if len(reason.split()) < 4:
            out.append("%s needs the operator's reason (why this is not a credential), in a few words" % tag)
        if fp and fp in seen:
            out.append("%s repeats the fingerprint %s" % (tag, fp))
        seen.add(fp)
    return out


def from_tools(doc):
    """(entries, problems) from a product-tools.yaml mapping; ([], []) when it has no gitleaks allowlist."""
    g = (doc or {}).get("gitleaks")
    if g is None:
        return [], []
    if not isinstance(g, dict) or any(k != "allow" for k in g):
        return [], ["product-tools.yaml gitleaks: may only hold allow (the test-fixture allowlist)"]
    entries = g.get("allow") or []
    return entries, problems(entries)
