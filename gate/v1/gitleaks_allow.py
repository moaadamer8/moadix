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

0.8.1 (task-tracker MF-63): a document that quotes a test fixture's value (a findings log, a README) holds the same
string, and its history hit stays for good. An entry may cover that one finding in any tracked file that is not under a
src/ directory and is not configuration, when it names the test-fixture entry whose value it repeats:

        - fingerprint: "<commit>:docs/moadix-findings.md:generic-api-key:389"
          path: docs/moadix-findings.md
          reason: "the findings log quotes the UI test's throwaway password"
          same-value-as: "tests/ui/core-loop.spec.ts:generic-api-key:7"   # a fixture: true entry under tests/

The scan applies it only when the finding's matched secret is the very value of that fixture's finding in the same scan
(compared by sha256 inside the gate; the value is never printed or kept), and the fixture entry is under tests/.
check-security's own secret scan applies the same adopted allowlist (0.8.1, MF-65).
"""
import os
import re
import sys

KEYS = ("fingerprint", "path", "reason", "fixture")
SAME_KEYS = ("fingerprint", "path", "reason", "same-value-as")  # 0.8.1 (MF-63): a quote of a fixture's value
SEGMENT = re.compile(r"^[A-Za-z0-9._@+-]+$")
FINGERPRINT = re.compile(r"^(?:(?P<commit>[0-9a-f]{40}):)?(?P<path>[^:*?\[\]{}\s]+):(?P<rule>[a-z0-9][a-z0-9-]*):"
                         r"(?P<line>[1-9][0-9]*)$")
FIXTURE_DIRS = ("fixtures", "__fixtures__")
MAX_ENTRIES = 500
TOOLS_REL = os.path.join(".sdlc", "config", "product-tools.yaml")
# 0.8.1 (MF-63): a quoted value is never allowlisted in configuration: a directory that holds it, a dotfile (.env,
# .npmrc), or a configuration file type or name
CONFIG_DIRS = {"config", "configs", "conf", "settings", "deploy", "infra", "k8s", "helm", "terraform"}
CONFIG_EXT = (".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg", ".json", ".jsonc", ".json5", ".properties", ".env",
              ".xml", ".plist", ".tf", ".tfvars", ".hcl", ".config", ".cnf", ".pem", ".key", ".crt")
CONFIG_STEMS = ("dockerfile", "containerfile", "compose", "docker-compose", "makefile", "procfile", "env")


def fingerprint(mode, commit, path, rule, line):
    """gitleaks' fingerprint of a finding: commit:path:rule:line in the history (mode git), path:rule:line in the tree."""
    return ("%s:%s:%s:%s" % (commit, path, rule, line)) if mode == "git" else ("%s:%s:%s" % (path, rule, line))


def _segments_ok(path):
    parts = str(path or "").split("/")
    ok = bool(path) and all(SEGMENT.match(p) for p in parts) and not any(p in (".", "..") for p in parts)
    return ok, parts


def fixture_path(path):
    """A repo-relative file under tests/ or under a fixtures directory, never with a src/ directory."""
    ok, parts = _segments_ok(path)
    if not ok or "src" in parts[:-1]:
        return False
    return parts[0] == "tests" or any(p in FIXTURE_DIRS for p in parts[:-1])


def quote_path(path):
    """0.8.1 (MF-63): a repo-relative file that may hold a quote of a test fixture's value: any file except one under a
    src/ directory or configuration (a configuration directory, a dotfile or dot-directory, a configuration file)."""
    ok, parts = _segments_ok(path)
    if not ok or "src" in parts[:-1] or any(p.startswith(".") for p in parts):
        return False
    if any(p.lower() in CONFIG_DIRS for p in parts[:-1]):
        return False
    base = parts[-1].lower()
    stem = base.split(".")[0]
    return not base.endswith(CONFIG_EXT) and stem not in CONFIG_STEMS and ".config." not in base and \
        ".conf." not in base and not stem.startswith("env")


def tests_fixture(e):
    """A fixture: true entry under tests/: the only kind a same-value-as entry may name."""
    return isinstance(e, dict) and e.get("fixture") is True and "same-value-as" not in e and \
        fixture_path(e.get("path")) and str(e.get("path")).split("/")[0] == "tests"


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
        same = "same-value-as" in e
        keys = SAME_KEYS if same else KEYS
        bad = sorted(str(k) for k in e if k not in keys)
        if bad:
            out.append("%s: key(s) %s are refused; an entry has only %s" % (tag, ", ".join(bad), ", ".join(keys)) + (
                "" if same else " (or same-value-as in place of fixture, for a quote of a test fixture's value)"))
        fp, path = str(e.get("fingerprint") or ""), str(e.get("path") or "")
        m = FINGERPRINT.match(fp)
        if not fp:
            out.append("%s names no finding's fingerprint: a whole rule or path is never allowlisted" % tag)
        elif not m:
            out.append("%s: %r is not one finding's gitleaks fingerprint (commit:path:rule:line in the history, "
                       "path:rule:line in the tree)" % (tag, fp))
        elif m.group("path") != path:
            out.append("%s: the fingerprint's path %s is not the entry's path %s" % (tag, m.group("path"), path or "(none)"))
        if same:
            ref = str(e.get("same-value-as") or "")
            target = next((x for x in entries if isinstance(x, dict) and str(x.get("fingerprint") or "") == ref), None)
            if not quote_path(path):
                out.append("%s: path %s may not hold an allowlisted value: never under src/, never configuration (a "
                           "configuration directory, a dotfile, a configuration file), never a glob" % (
                               tag, path or "(none)"))
            if not FINGERPRINT.match(ref):
                out.append("%s: same-value-as %r is not one finding's gitleaks fingerprint" % (tag, ref))
            elif ref == fp:
                out.append("%s: same-value-as names the entry itself" % tag)
            elif not tests_fixture(target):
                out.append("%s: same-value-as %s is not a fixture: true entry under tests/ in this allowlist; a value "
                           "is allowlisted outside tests/ only when the same value is allowlisted as a test fixture" % (
                               tag, ref))
        else:
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


def adopted_allowlist(root, product_tools):
    """0.8.1: ({fingerprint: entry}, problems), the product's allowlist as check-gitleaks and check-security apply it
    (MF-65: one allowlist for both). It applies only when every entry passes and product-tools.yaml is exactly what ADOPT
    recorded; otherwise nothing is allowlisted and each reason is returned. product_tools: a reader (root -> mapping)."""
    entries, probs = from_tools(product_tools(root))
    if not entries and not probs:
        return {}, []
    gate = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if os.path.dirname(gate) not in sys.path:
        sys.path.insert(0, os.path.dirname(gate))
    from gate import adopt  # noqa: E402 (late: the gate package, as check_exec imports it)
    if not adopt.adopted(root, TOOLS_REL):
        probs = probs + ["the gitleaks allowlist in %s was not adopted (the file is not what ADOPT recorded), so it is "
                         "not applied; propose it in .sdlc-proposals/config/product-tools.yaml for the operator to "
                         "ADOPT" % TOOLS_REL]
    if probs:
        return {}, probs
    return {str(e["fingerprint"]): e for e in entries}, []


def tree_line(fp):
    """(path, line) of a tree fingerprint (path:rule:line), else None."""
    m = FINGERPRINT.match(str(fp or ""))
    return (m.group("path"), int(m.group("line"))) if m and not m.group("commit") else None
