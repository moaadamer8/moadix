#!/usr/bin/env python3
"""check-baseline -- onboarding phase B (increment 6; DESIGN.md Amendment 2).

MOADIX-native. A product INITialised on a repository that already has code starts
at phase B (Baseline). Its documents describe the product AS IT IS, in the
product's own document names (so later feature cycles validate against them):

  sdlc/00-*.md            as-is BRD: purpose, users, business goals (BG-n)
  sdlc/02-*.md            as-is PRD: current features as stories (US-n), EARS
                          acceptance criteria where possible
  sdlc/03-*.md            architecture: components and where they live
  sdlc/04-*.md            threat model of the current system: each SEC-ID with
                          its current status (mitigated | partial | open | unknown)
  sdlc/B-test-inventory.md   test command, test environment, suites, coverage
                             per acceptance criterion
  sdlc/B-known-gaps.md       the known-gaps register (GAP-n): untested acceptance
                             criteria, open findings, anything else not in order
  sdlc/B-accounts.md         accounts and services in use, without secrets

Checks (templates: templates/baseline/):
  completeness   every document exists with its sections; no template placeholder
  citations      EVERY path:line citation in them resolves at HEAD (the file exists
                 in the commit, the lines are inside it); a citation into sdlc/ or
                 .sdlc/ is not code. Every claim carries one: each goal, story,
                 acceptance criterion, component, SEC-ID, suite and account
  register       a SEC-ID that is not `mitigated` and an acceptance criterion with
                 no test are each in the known-gaps register (gaps go to the
                 register, not into approvals)
  no secrets     the accounts document names where a secret lives, never its value
  never prod     the test environment is loopback or a declared test host; a URL
                 that looks like production fails (the suite never runs against it)

The baseline records the current state; it does not certify that the code passed
phases 8-10. The fresh-context moadix:baseline-verifier checks the claims against
the code (check-verifiers-B).

Exit 0 pass, 1 fail, 2 unknown.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import check_handoff as hl  # noqa: E402
import hlib  # noqa: E402

GIT = "/usr/bin/git"
DOCS = [
    ("sdlc", "00-*.md", "as-is BRD", ["Purpose", "Users", "Business Goals"]),
    ("sdlc", "02-*.md", "as-is PRD", []),
    ("sdlc", "03-*.md", "architecture", ["Components"]),
    ("sdlc", "04-*.md", "threat model", ["Trust Boundaries"]),
    ("sdlc", "B-test-inventory.md", "test inventory", ["Test command", "Test environment", "Suites", "Coverage"]),
    ("sdlc", "B-known-gaps.md", "known-gaps register", ["Gaps"]),
    ("sdlc", "B-accounts.md", "accounts and services", ["Accounts and services"]),
]
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s|)>`'\"]+", re.I)
CITE = re.compile(r"(?<![\w/.@-])((?:[\w.-]+/)*(?:[\w.-]+\.[A-Za-z0-9]{1,8}|Dockerfile|Makefile|Procfile|Gemfile|"
                  r"Rakefile|Justfile)):(\d+)(?:-(\d+))?(?![\w:])")
STATUSES = ("mitigated", "partial", "open", "unknown")
GAP_KINDS = ("untested-ac", "open-finding", "missing-doc", "other")
SECRETS = [re.compile(p) for p in (
    r"AKIA[0-9A-Z]{16}", r"\bgh[pousr]_[A-Za-z0-9]{20,}", r"\bsk-[A-Za-z0-9_-]{20,}", r"\bxox[abpr]-[A-Za-z0-9-]{10,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S{6,}",
    r"(?<![\w/.-])[A-Za-z0-9+]{32,}={0,2}(?![\w/.-])")]
PROD_HOST = re.compile(r"(?i)(?:^|[.-])(?:prod|production|live)(?:[.-]|$)")
LOOPBACK = re.compile(r"^(?:localhost|127\.\d+\.\d+\.\d+|\[::1\]|::1|0\.0\.0\.0)$", re.I)


def head(root):
    p = subprocess.run([GIT, "-C", root, "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def lines_at(root, hd, path, memo):
    if path not in memo:
        if path.startswith("/") or ".." in path.split("/"):
            memo[path] = None
        else:
            p = subprocess.run([GIT, "-C", root, "show", "%s:%s" % (hd, path)], capture_output=True)
            memo[path] = (p.stdout.count(b"\n") + (0 if p.stdout.endswith(b"\n") or not p.stdout else 1)) \
                if p.returncode == 0 else None
    return memo[path]


def citations(text):
    """[(citation text, path, a, b)] in a document, URLs removed first (host:port is not path:line)."""
    clean = URL.sub(" ", text)
    return [(m.group(0), m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))) for m in CITE.finditer(clean)]


def section(text, name):
    m = re.search(r"^##\s+%s\b.*?$(.*?)(?=^##\s|\Z)" % re.escape(name), text, re.M | re.S | re.I)
    return m.group(1) if m else None


def rows(text, prefix):
    """{ID: row text} for table rows whose first cell is <prefix>-n."""
    return {m.group(1): m.group(0) for m in re.finditer(r"^\|\s*(%s-\d+)\s*\|.*$" % prefix, text, re.M)}


def table_rows(sec):
    """Data rows of the first markdown table in a section (header and separator skipped)."""
    out = []
    lines = [ln for ln in (sec or "").splitlines() if ln.strip().startswith("|")]
    for i, ln in enumerate(lines):
        if i < 2 and (i == 0 or re.match(r"^\s*\|[\s:|-]+\|\s*$", ln)):
            continue
        out.append(ln)
    return out


def main():
    root = hlib.project_root()
    errs, notes = [], []
    print("check-baseline (phase B: the existing product, as it is, with every claim citing code)")
    hd = head(root)
    if not hd:
        print("  UNKNOWN  the repository has no commit; citations resolve against HEAD")
        return 2
    docs = {}
    for d, pat, what, secs in DOCS:
        rx = re.compile("^" + pat.replace(".", r"\.").replace("*", ".*") + "$")
        dd = os.path.join(root, d)
        hits = sorted(f for f in os.listdir(dd) if rx.match(f)) if os.path.isdir(dd) else []
        if not hits:
            errs.append("missing the %s (%s/%s); start from templates/baseline/" % (what, d, pat))
            continue
        rel = "%s/%s" % (d, hits[0])
        text = hl.read(os.path.join(root, rel)) or ""
        docs[what] = (rel, text)
        for s in secs:
            if section(text, s) is None:
                errs.append("%s: no '## %s' section" % (rel, s))
        if "{{" in text:
            errs.append("%s: unfilled template placeholders remain (%s)" % (
                rel, ", ".join(sorted(set(re.findall(r"\{\{[^}]*\}\}", text)))[:4])))
    # every citation resolves at HEAD, and is code
    memo = {}
    total = 0
    for _what, (rel, text) in docs.items():
        for cit, path, a, b in citations(text):
            total += 1
            if path.startswith(("sdlc/", ".sdlc/")):
                errs.append("%s cites %s: a baseline document is not code; cite the code itself" % (rel, cit))
                continue
            n = lines_at(root, hd, path, memo)
            if n is None:
                errs.append("DEAD CITATION %s in %s: %s does not exist at %s" % (cit, rel, path, hd[:12]))
            elif a < 1 or b < a or b > n:
                errs.append("DEAD CITATION %s in %s: line %d is outside %s (%d lines at %s)" % (
                    cit, rel, b, path, n, hd[:12]))

    def needs_cite(rel, where, text):
        if not citations(text):
            errs.append("%s: %s cites no code (path:line); every claim about the existing product cites the code "
                        "that shows it" % (rel, where))

    brd = docs.get("as-is BRD")
    goals = {}
    if brd:
        goals = rows(section(brd[1], "Business Goals") or "", "BG")
        if not goals:
            errs.append("%s: no business goals ('| BG-1 | ... |' rows under '## Business Goals')" % brd[0])
        for gid, row in sorted(goals.items()):
            needs_cite(brd[0], gid, row)
    prd = docs.get("as-is PRD")
    acs = []
    if prd:
        stories = {}
        stories.update(hl.blocks(prd[1], "US"))
        stories.update(hl.blocks(prd[1], "NFR"))
        if not stories:
            errs.append("%s: no stories ('### US-001 — <title>'): describe each current feature" % prd[0])
        for sid, blk in sorted(stories.items()):
            impl = hl.field(blk, "Implemented in") or ""
            needs_cite(prd[0], "%s's '**Implemented in:**'" % sid, impl)
            for ref in re.findall(r"\bBG-\d+\b", hl.field(blk, "BRD goal") or ""):
                if goals and ref not in goals:
                    errs.append("%s traces to %s, which the as-is BRD does not define" % (sid, ref))
            if not re.findall(r"\bBG-\d+\b", hl.field(blk, "BRD goal") or ""):
                errs.append("%s: no '**BRD goal:**' naming a BG-n" % sid)
            found = re.findall(r"^\s*[-*]\s*\*\*(AC-\d+):?\*\*\s*(.+?)\s*$", blk, re.M)
            if not found:
                errs.append("%s: no acceptance criteria ('- **AC-1:** ...')" % sid)
            for ac, sent in found:
                acs.append("%s/%s" % (sid, ac))
                needs_cite(prd[0], "%s/%s" % (sid, ac), sent)
                core = re.split(r"\s*\((?:code|evidence|as-is)\b", sent, maxsplit=1)[0]
                ok, why = hl.is_ears(core)
                if not ok and not re.search(r"\(as-is,\s*not EARS:\s*[^)]+\)", sent, re.I):
                    errs.append("%s/%s is not EARS (%s); write it in EARS where possible, or mark it "
                                "'(as-is, not EARS: <why>)'" % (sid, ac, why))
    arch = docs.get("architecture")
    if arch:
        comp = table_rows(section(arch[1], "Components"))
        if not comp:
            errs.append("%s: no component rows under '## Components'" % arch[0])
        for row in comp:
            needs_cite(arch[0], "component %r" % row.split("|")[1].strip()[:40], row)
    gaps_doc = docs.get("known-gaps register")
    gaps = rows(gaps_doc[1], "GAP") if gaps_doc else {}
    if gaps_doc:
        for gid, row in sorted(gaps.items()):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) < 4 or cells[1] not in GAP_KINDS:
                errs.append("%s: %s needs '| GAP-n | kind (%s) | ref | description | ... |'" % (
                    gaps_doc[0], gid, "/".join(GAP_KINDS)))
    gap_text = "\n".join(gaps.values())
    tm = docs.get("threat model")
    if tm:
        tbs = rows(tm[1], "TB")
        secs = hl.blocks(tm[1], "SEC")
        if not secs:
            errs.append("%s: no SEC-IDs ('### SEC-001 - <title>'): model the current system's threats" % tm[0])
        for sid, blk in sorted(secs.items()):
            refs = re.findall(r"\bTB-\d+\b", hl.field(blk, "Trust boundary") or "")
            if not refs or any(r not in tbs for r in refs):
                errs.append("%s: '**Trust boundary:**' must name a TB-n from '## Trust Boundaries'" % sid)
            status = (hl.field(blk, "Current status") or "").strip().lower().split(" ")[0].strip(".,;")
            if status not in STATUSES:
                errs.append("%s: '**Current status:**' must be one of %s" % (sid, "/".join(STATUSES)))
            needs_cite(tm[0], "%s's '**Evidence:**'" % sid, hl.field(blk, "Evidence") or "")
            if status in ("partial", "open", "unknown") and not re.search(r"\b%s\b" % sid, gap_text):
                errs.append("%s is %s: it must be in the known-gaps register as an open finding" % (sid, status))
    inv = docs.get("test inventory")
    if inv:
        cmd = section(inv[1], "Test command") or ""
        if not re.search(r"`[^`]+`", cmd):
            errs.append("%s: '## Test command' names no command (in backticks)" % inv[0])
        env = section(inv[1], "Test environment") or ""
        for u in URL.findall(env):
            host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u, flags=re.I).split("/")[0].rsplit("@", 1)[-1]
            host = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            if PROD_HOST.search(host) or not (LOOPBACK.match(host) or re.search(r"(?i)(?:^|[.-])(?:test|staging|"
                                                                                 r"local|sandbox|dev)(?:[.-]|$)",
                                                                                 host)):
                errs.append("%s: the test environment names %s; the existing suite runs in a test environment "
                            "(loopback or a test host), never against production" % (inv[0], u))
        for row in table_rows(section(inv[1], "Suites")):
            needs_cite(inv[0], "suite %r" % row.split("|")[1].strip()[:40], row)
        cov = {}
        for row in table_rows(section(inv[1], "Coverage")):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if cells and re.match(r"^(?:US|NFR)-\d+/AC-\d+$", cells[0]):
                cov[cells[0]] = cells[1] if len(cells) > 1 else ""
        for ac in acs:
            if ac not in cov:
                errs.append("%s: '## Coverage' has no row for %s (say which test covers it, or `none`)" % (inv[0], ac))
            elif cov[ac].lower().startswith("none"):
                if not re.search(r"\b%s\b" % re.escape(ac), gap_text):
                    errs.append("%s has no test: it must be in the known-gaps register as untested-ac" % ac)
            else:
                needs_cite(inv[0], "the coverage of %s" % ac, cov[ac])
    acc = docs.get("accounts and services")
    if acc:
        rws = table_rows(section(acc[1], "Accounts and services"))
        for row in rws:
            needs_cite(acc[0], "service %r" % row.split("|")[1].strip()[:40], row)
        for rx in SECRETS:
            for m in rx.finditer(URL.sub(" ", acc[1])):
                errs.append("%s holds what looks like a secret value (%s...); name where it lives, never the value" % (
                    acc[0], m.group(0)[:6]))
    notes.append("%d citation(s) checked against %s" % (total, hd[:12]))
    for n in notes:
        print("  note  %s" % n)
    for e in errs:
        print("  FAIL  %s" % e)
    if errs:
        return 1
    print("  PASS  the baseline is complete and every claim cites code that exists at %s" % hd[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
