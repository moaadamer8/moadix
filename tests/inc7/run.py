#!/usr/bin/python3
"""Increment-7 suite (docs/AMENDMENT-3.md): the cross-phase contract's linters, the gap critic
gate, the size rule, the phase-7 rules, skill hygiene, the tool pins and the toy-notes fixes.

    /usr/bin/python3 tests/inc7/run.py

Fixtures only (throwaway repos under $TMPDIR, the stub checker, no network: research links
are answered from the gate's own link cache, seeded by the test). Every linter has a passing
control and planted defects that must fail.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("v7").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import contract, session, validation  # noqa: E402
import contract_fixture  # noqa: E402

RESULTS = []
T0 = time.time()
GIT = "/usr/bin/git"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % str(evidence)[:900])


def short(s, n=300):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


def git(p, *args):
    return subprocess.run([GIT, "-C", p] + list(args), capture_output=True, text=True)


def mk(files, commit=True):
    """A throwaway git repo holding files."""
    p = tempfile.mkdtemp(prefix="lint-", dir=E.base)
    git(p, "init", "-q")
    write(p, files)
    if commit:
        E.commit(p, "docs")
    return p


def write(p, files):
    for rel, text in files.items():
        full = os.path.join(p, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


def st_for(label, feature=None, phases=None):
    return {"current_phase": label, "feature": feature, "phases": phases or [], "product_phases": [], "mode": None}


BRD_S = "# BRD\n\n- **Target Platform Ruling:** WEB\n- **Size:** S\n\n## Business Goals\n\n| ID | Goal |\n|---|---|\n| BG-1 | notes |\n"
BRD_M = BRD_S.replace("**Size:** S", "**Size:** M")
BRD_M_APP = BRD_M.replace("WEB\n", "APP-FIRST\n")


def coverage_files(label, brd=BRD_S, feature=None):
    root = mk({"sdlc/00-brd.md": brd}, commit=False)
    st = st_for(label, feature)
    size, ruling = contract.size_and_ruling(root, st)
    files = contract_fixture.files(label, st, size, ruling)
    shutil.rmtree(root, ignore_errors=True)
    files["sdlc/00-brd.md"] = brd
    return files


def lint(name, files, label, st=None, **kw):
    p = mk(files)
    st = st or st_for(label)
    f, m, i, *rest = {"coverage": contract.coverage_lint, "discovery": contract.discovery_lint,
                      "adr": contract.adr_lint, "trace": contract.trace_lint, "ears": contract.ears_lint,
                      "cite": lambda r, s, lab: contract.cite_lint(r, s, lab, **kw)}[name](p, st, label)
    return f, i, (rest[0] if rest else None), p


def has(fails, *words):
    return any(all(w in x for w in words) for x in fails)


# ------------------------------------------------------------------ coverage-lint
def test_coverage():
    G = "coverage-lint"
    good = coverage_files("0")
    f, i, _u, _p = lint("coverage", good, "0")
    record(G, "control: every phase-0 topic listed (size-S defaults pre-filled, the rest with real reasons) -> passes",
           not f and i["topics"] == 27 and "B24" in i["defaults"], f[:3])
    cov = "sdlc/0/COVERAGE.md"
    f, *_ = lint("coverage", {k: v for k, v in good.items() if k != cov}, "0")
    record(G, "planted: COVERAGE.md missing -> fails", has(f, "COVERAGE.md is missing"), f[:2])
    bad = dict(good)
    bad[cov] = "\n".join(ln for ln in good[cov].splitlines() if not ln.startswith("- B13:")) + "\n"
    f, *_ = lint("coverage", bad, "0")
    record(G, "planted: a topic left out (B13) -> fails, naming it", has(f, "B13", "missing"), f[:2])
    bad[cov] = good[cov] + "- B13: N/A: competitors are covered by another product line entirely here\n"
    f, *_ = lint("coverage", bad, "0")
    record(G, "planted: a topic listed twice -> fails", has(f, "B13", "more than once"), f[:2])
    bad[cov] = good[cov] + "- R1: N/A: this research topic does not belong to the BRD at all\n"
    f, *_ = lint("coverage", bad, "0")
    record(G, "planted: an ID from another phase (R1) -> fails", has(f, "R1 is not a topic of phase 0"), f[:2])
    bad = dict(good, **{"sdlc/00-brd.md": BRD_S + "\n## Problem\n\nNotes get lost; people want one place to keep them.\n"
                        "\n## Empty\n\n"})
    bad[cov] = good[cov].replace([ln for ln in good[cov].splitlines() if ln.startswith("- B1:")][0],
                                 "- B1: [problem](../00-brd.md#problem)")
    f, *_ = lint("coverage", bad, "0")
    record(G, "control: a topic anchored to a real section with content -> passes", not f, f[:2])
    for target, why, label in (("../00-brd.md#nowhere", "no section #nowhere", "a dead anchor"),
                               ("../00-missing.md#problem", "does not exist", "a missing file"),
                               ("../00-brd.md#empty", "hollow", "a hollow section"),
                               ("https://example.com/#x", "external link", "an external link")):
        b2 = dict(bad)
        b2[cov] = bad[cov].replace("- B1: [problem](../00-brd.md#problem)", "- B1: [problem](%s)" % target)
        f, *_ = lint("coverage", b2, "0")
        record(G, "planted: %s -> fails" % label, has(f, "B1", why), f[:2])
    for reason, label in (("N/A", "an empty reason"), ("N/A: none", "boilerplate"), ("N/A: not applicable", "boilerplate 2"),
                          ("N/A: tbd later", "too short")):
        b2 = dict(good)
        b2[cov] = re.sub(r"(?m)^- B9: .*$", "- B9: %s" % reason, good[cov])
        f, *_ = lint("coverage", b2, "0")
        record(G, "planted: N/A with %s (%r) -> fails" % (label, reason), has(f, "B9", "boilerplate"), f[:2])
    b2 = dict(good)
    same = "N/A: the toy product has no such concern in any way at all"
    b2[cov] = re.sub(r"(?m)^- (B8|B9|B10): .*$", lambda m: "- %s: %s" % (m.group(1), same), good[cov])
    f, *_ = lint("coverage", b2, "0")
    record(G, "planted: the same reason copied onto three topics -> fails as boilerplate", has(f, "same N/A reason"),
           f[:2])


# ------------------------------------------------------------------ size rule
def test_size():
    G = "size-rule"
    good = coverage_files("0")
    cov = "sdlc/0/COVERAGE.md"
    b = dict(good)
    b[cov] = re.sub(r"(?m)^- B9: .*$", "- B9: N/A: size-default", good[cov])
    f, *_ = lint("coverage", b, "0")
    record(G, "planted: `size-default` on a topic that is not N/A by default at size S (B9) -> fails",
           has(f, "B9", "not N/A by default at size S"), f[:2])
    b[cov] = re.sub(r"(?m)^- B17: .*$", "- B17: N/A: size-default", good[cov])
    f, *_ = lint("coverage", b, "0")
    record(G, "planted: a partial default (B17: only the 100x path is N/A at S) written as N/A -> fails",
           has(f, "B17", "only the 100x growth path"), f[:2])
    nos = dict(good, **{"sdlc/00-brd.md": BRD_S.replace("- **Size:** S\n", "")})
    f, *_ = lint("coverage", nos, "0")
    record(G, "planted: `size-default` while the BRD declares no size (B19) -> fails", has(f, "declares no size"), f[:2])
    # turned on at S: SV7 (ZAP baseline) may not be N/A in phase 9
    g9 = coverage_files("9")
    f, *_ = lint("coverage", g9, "9")
    record(G, "control: phase 9 at size S with SV7 (ZAP passive baseline, turned on at S) covered -> passes", not f, f[:2])
    b9 = dict(g9)
    b9["sdlc/9/COVERAGE.md"] = re.sub(r"(?m)^- SV7: .*$", "- SV7: N/A: the fixture product runs no web server for it",
                                      g9["sdlc/9/COVERAGE.md"])
    f, *_ = lint("coverage", b9, "9")
    record(G, "planted: SV7 N/A although size S turns on the ZAP baseline -> fails", has(f, "SV7", "turns on"), f[:2])
    # M: T20 must say ASVS L2; TS10 needs >= 70%
    g4 = coverage_files("4", BRD_M)
    f, *_ = lint("coverage", g4, "4")
    record(G, "control: phase 4 at size M (T20 names ASVS L2, pytm in T3) -> passes", not f, f[:2])
    b4 = dict(g4)
    b4["sdlc/4/notes.md"] = g4["sdlc/4/notes.md"].replace("ASVS L2 applies at level 2", "ASVS L1 applies")
    f, *_ = lint("coverage", b4, "4")
    record(G, "planted: at size M the T20 section names only ASVS L1 -> fails (M turns on L2)",
           has(f, "T20", "ASVS L2"), f[:3])
    g8 = coverage_files("8", BRD_M)
    b8 = dict(g8)
    b8["sdlc/8/notes.md"] = g8["sdlc/8/notes.md"].replace("threshold is 85%", "threshold is 60%")
    f, *_ = lint("coverage", b8, "8")
    record(G, "planted: at size M the Stryker threshold is 60%% (M turns on >= 70%%) -> fails",
           has(f, "TS10", "70%"), f[:2])
    # conditions: H23 is N/A by default at M only with no mobile client
    root = mk({"sdlc/00-brd.md": BRD_M})
    d_web = contract.defaults("3", *contract.size_and_ruling(root, st_for("3")))
    root2 = mk({"sdlc/00-brd.md": BRD_M_APP})
    d_app = contract.defaults("3", *contract.size_and_ruling(root2, st_for("3")))
    record(G, "the size rule reads B19: at M, H23 is N/A by default for WEB (no mobile) and not for APP-FIRST",
           "H23" in d_web and "H23" not in d_app, "WEB %s / APP-FIRST %s" % (sorted(d_web), sorted(d_app)))
    root3 = mk({"sdlc/00-brd.md": BRD_S.replace("**Size:** S", "**Size:** L")})
    record(G, "size L: no topic is N/A by default", contract.defaults("3", "L", "WEB") == {} and
           contract.defaults("11b", "S", "WEB") and not contract.defaults("11b", "S", "APP-FIRST"),
           sorted(contract.defaults("11b", "S", "APP-FIRST")))
    sk = contract.skeleton(root, st_for("0"), "0")
    sk_s = contract.skeleton(mk({"sdlc/00-brd.md": BRD_S}), st_for("0"), "0")
    record(G, "the skeleton pre-fills the size defaults with their canned reason; partial ones stay TODO with the note",
           re.search(r"(?m)^- B24: N/A: Size S default: a small, low-risk product has a single tenant", sk_s) and
           re.search(r"(?m)^- B17: TODO .*only the 10x growth path", sk_s) and "- B24: TODO" in sk, short(sk_s, 400))
    shutil.rmtree(root3, ignore_errors=True)


# ------------------------------------------------------------------ discovery-lint
DISC = ("# Discovery\n\n## Q-1: Which markets first?\n- A: one country\n- B: the EU\n- C: worldwide\n"
        "Recommendation: A, smallest legal surface\nChosen: A\n\n## Q-2: Payments at launch?\n- A: none\n- B: card\n"
        "Recommendation: A\nChosen: B\n")


def test_discovery():
    G = "discovery-lint"
    rel = "sdlc/0/DISCOVERY.md"
    f, i, *_ = lint("discovery", {rel: DISC}, "0")
    record(G, "control: two questions, 2-4 options each, a recommendation and the chosen option -> passes",
           not f and i["questions"] == 2, f)
    f, *_ = lint("discovery", {"sdlc/0/x.md": "x"}, "0")
    record(G, "planted: no discovery log -> fails", has(f, "DISCOVERY.md is missing"), f)
    for text, why, label in (
            (DISC.replace("- B: the EU\n- C: worldwide\n", ""), "has 1 options", "one option"),
            (DISC.replace("Recommendation: A, smallest", "Recommendation: D, smallest"), "recommends D", "a recommendation that is no option"),
            (DISC.replace("Chosen: B\n", ""), "no chosen option", "no answer logged"),
            (DISC.replace("Chosen: B", "Chosen: C"), "chosen C is not one of its options", "an answer that is no option"),
            (DISC.replace("## Q-2", "## Q-1"), "used twice", "a reused Q-n"),
            (DISC + "\n## Q-3: More?\n- A: x\n- B: y\n- C: z\n- D: w\n- E: v\nRecommendation: A\nChosen: A\n",
             "has 5 options", "five options")):
        f, *_ = lint("discovery", {rel: text}, "0")
        record(G, "planted: %s -> fails" % label, has(f, why), f)
    f, *_ = lint("discovery", {rel: "# D\n\nNo questions: the BRD came complete from the operator's own brief.\n"}, "0")
    record(G, "control: `No questions: <reason>` -> passes", not f, f)
    f, *_ = lint("discovery", {rel: "# D\n\nNo questions: none\n"}, "0")
    record(G, "planted: `No questions` without a reason -> fails", f, f)


# ------------------------------------------------------------------ adr-lint
ADR = ("# ADR-001: Store notes in SQLite\n\n- Status: accepted\n\n## Context\n\nThe toy needs durable storage for "
       "one writer.\n\n## Alternatives\n\n- SQLite\n- a JSON file\n- Postgres\n\n## Criteria\n\nOne process, zero "
       "operations, transactional writes.\n\n## Decision\n\nSQLite, one file next to the app.\n\n## Consequences\n\n"
       "No second writer without a migration to Postgres.\n\n## Sources\n\n- https://sqlite.org/whentouse.html "
       "(retrieved 2026-11-01)\n")


def test_adr():
    G = "adr-lint"
    rel = "sdlc/1/adr/ADR-001-storage.md"
    f, i, *_ = lint("adr", {rel: ADR}, "1")
    record(G, "control: a MADR record (context, 3 alternatives, criteria, decision, consequences, dated source) -> "
              "passes", not f and i["adrs"] == 1, f)
    for text, why, label in (
            (ADR.replace("## Criteria", "## Notes"), "no `## Criteria`", "no criteria"),
            (ADR.replace("- a JSON file\n- Postgres\n", ""), "lists 1 option", "one alternative"),
            (ADR.replace(" (retrieved 2026-11-01)", ""), "needs a URL and a date", "an undated source"),
            (ADR.replace("- Status: accepted\n", "- Status: accepted\n- Supersedes: ADR-007\n"), "ADR-007, which does not exist",
             "superseding a record that does not exist"),
            (ADR.replace("# ADR-001:", "# ADR-002:"), "the title must be", "a title that does not match the file")):
        f, *_ = lint("adr", {rel: text}, "1")
        record(G, "planted: %s -> fails" % label, has(f, why), f[:2])
    f, *_ = lint("adr", {rel: ADR, "sdlc/3/adr/ADR-001-other.md": ADR}, "3")
    record(G, "planted: an ADR number used twice -> fails", has(f, "never reused"), f[:2])


# ------------------------------------------------------------------ trace-lint
TRACE = {
    "sdlc/00-brd.md": "# BRD\n\n## Business Goals\n\n| ID | Goal |\n|---|---|\n| BG-1 | notes |\n\n### BR-1 One note per "
                      "line\n\nA rule.\n",
    "sdlc/02-prd.md": "# PRD\n\n### US-001 — Save a note\n\n- **BRD goal:** BG-1\n- **AC-1:** The system shall save it.\n",
    "sdlc/03-hld.md": "# HLD\n\n### H-1 One process\n\nServes US-001.\n",
    "sdlc/05-lld.md": "# LLD\n\n### L-1 POST /notes\n\nImplements US-001 within H-1.\n",
    "sdlc/09-security-report.md": "# Report\n\n| ID | Severity |\n|---|---|\n| SEC-001 | low |\n",
    "sdlc/07-tasks.md": "# Tasks\n\n### T-001 — Save route\n\n- **Story:** US-001\n",
}


def test_trace():
    G = "trace-lint"
    f, i, *_ = lint("trace", TRACE, "5")
    record(G, "control: BG-1 -> US-001 -> H-1 -> L-1; a register row (SEC-001) and a v1 task (T-001) -> passes",
           not f and i["defined"] >= 5, f)
    f, *_ = lint("trace", dict(TRACE, **{"sdlc/05-lld.md": TRACE["sdlc/05-lld.md"] + "\nSee H-9.\n"}), "5")
    record(G, "planted: a reference to an ID nothing defines (H-9) -> fails as dangling", has(f, "H-9", "dangling"), f)
    f, *_ = lint("trace", dict(TRACE, **{"sdlc/03-hld.md": TRACE["sdlc/03-hld.md"] + "\n### H-1 Again\n\nUS-001.\n"}), "5")
    record(G, "planted: an ID defined twice (H-1) -> fails", has(f, "H-1 is defined 2 times"), f)
    f, *_ = lint("trace", dict(TRACE, **{"sdlc/03-hld.md": "# HLD\n\n### H-1 One process\n\nA single box.\n"}), "5")
    record(G, "planted: H-1 cites no upstream ID -> fails as an orphan", has(f, "H-1 points at no existing upstream"), f)
    p = mk(TRACE)
    c = git(p, "rev-parse", "HEAD").stdout.strip()
    write(p, {"sdlc/03-hld.md": "# HLD\n\nNothing.\n", "sdlc/05-lld.md": "# LLD\n\n### L-1 POST\n\nUS-001.\n"})
    E.commit(p, "drop H-1")
    f, *_ = contract.trace_lint(p, st_for("5", phases=[{"label": "3", "status": "APPROVED", "commit": c}]))
    record(G, "planted: H-1 was defined when phase 3 was approved and is now gone -> fails (IDs never reused or deleted)",
           has(f, "H-1 was defined when an earlier phase was approved"), f)
    # ruling 1 on increment 7: T- task, SR- shared resource, TH- threat, STR- store-release item; all upstream-checked
    tm = "# TM\n\n### TH-1 Note tampering\n\nAgainst US-001 in H-1.\n\n### SR-1 Shared notes table\n\nWritten by H-1.\n"
    f, *_ = lint("trace", dict(TRACE, **{"sdlc/04-tm.md": tm, "sdlc/11b-store.md": "# Store\n\n### STR-1 Privacy "
                                         "label\n\nFrom RL-1.\n", "sdlc/11-release.md": "# Release\n\n### RL-1 SBOM"
                                         "\n\nFrom L-1.\n"}), "5")
    record(G, "control: TH-1 and SR-1 cite US-001/H-1, STR-1 cites RL-1, T-001 cites US-001 -> passes", not f, f)
    for rel, text, ident in (("sdlc/04-tm.md", "# TM\n\n### SR-1 Shared notes table\n\nNo upstream.\n", "SR-1"),
                             ("sdlc/04-tm.md", "# TM\n\n### TH-1 Tampering\n\nNothing cited.\n", "TH-1"),
                             ("sdlc/07-tasks.md", "# Tasks\n\n### T-001 — Save route\n\nNo story.\n", "T-001"),
                             ("sdlc/11b-store.md", "# Store\n\n### STR-1 Privacy label\n\nNothing.\n", "STR-1")):
        f, *_ = lint("trace", dict(TRACE, **{rel: text}), "5")
        record(G, "planted: %s with no upstream ID -> fails as an orphan (ruling 1: upstream checks on)" % ident,
               has(f, "%s points at no existing upstream" % ident), f)


# ------------------------------------------------------------------ ears-lint
PRD = ("# PRD\n\n## Roles and actions\n\n| Role | Save | Delete others' |\n|---|---|---|\n| Visitor | ✓ | ✗ |\n"
       "| Admin | ✓ | ✓ |\n\n### US-001 — Save a note\n\n- **BRD goal:** BG-1\n"
       "- **AC-1 (event):** When the visitor submits a note, the system shall store it.\n"
       "- **AC-2 (unwanted):** If the note is longer than 2000 characters, then the system shall refuse it.\n\n"
       "### NFR-1 — Save latency\n\nThe p95 save time is under 300 ms.\n")


def test_ears():
    G = "ears-lint"
    rel = "sdlc/02-prd.md"
    f, i, *_ = lint("ears", {rel: PRD}, "2")
    record(G, "control: EARS ACs (event, unwanted), an NFR with a unit, a role x action matrix with a deny -> passes",
           not f and len(i["acs"]) == 2 and i["acs"][1]["template"] == "unwanted", f)
    for text, why, label in (
            (PRD.replace("When the visitor submits a note, the system shall store it.", "Notes get stored."),
             "does not match an EARS template", "an AC in no EARS template"),
            (PRD.replace("shall store it.", "shall store it fast."), "vague term(s) fast", "a vague term (fast)"),
            (PRD.replace("shall store it.", "shall store it and the system shall email it."), "compound",
             "a compound requirement"),
            (PRD.replace("- **AC-2 (unwanted):** If the note is longer than 2000 characters, then the system shall refuse it.\n", ""),
             "no unwanted-behaviour AC", "a story without an unwanted-behaviour AC"),
            (PRD.replace("under 300 ms", "quick enough"), "states no number with a unit", "an NFR without a number and unit"),
            (PRD.replace("| Admin | ✓ | ✓ |", "| Admin | ✓ |  |"), "Admin", "a blank matrix cell"),
            (PRD.replace("| Visitor | ✓ | ✗ |", "| Visitor | ✓ | ✓ |"), "denies nothing", "a matrix that denies nothing"),
            (PRD.replace("## Roles and actions\n\n| Role | Save | Delete others' |\n|---|---|---|\n| Visitor | ✓ | ✗ |\n"
                         "| Admin | ✓ | ✓ |\n", ""), "no role x action matrix", "no matrix at all")):
        f, *_ = lint("ears", {rel: text}, "2")
        record(G, "planted: %s -> fails" % label, has(f, why), f[:3])
    asis = PRD.replace("When the visitor submits a note, the system shall store it.",
                       "Notes are saved by the legacy form handler (as-is, not EARS: behaviour inferred from code).")
    f, *_ = lint("ears", {rel: asis}, "B")
    record(G, "baseline (phase B): an as-is AC marked `(as-is, not EARS: why)` is accepted", not f, f)


# ------------------------------------------------------------------ cite-lint
RES = ("# Research\n\n## Competitors\n\n- Simplenote syncs notes across devices ([site](https://simplenote.com/), "
       "retrieved 2026-11-02)\n- Standard Notes encrypts notes end to end [^sn]\n\n## Legal\n\n- No personal data beyond "
       "an e-mail address ([GDPR](https://gdpr-info.eu/art-4-gdpr/), retrieved 2026-11-03)\n\n"
       "[^sn]: https://standardnotes.com/ retrieved 2026-11-02\n")


def research_repo(text, cov_extra=None, cache=None):
    files = coverage_files("1")
    files["sdlc/01-research.md"] = text
    cov = files["sdlc/1/COVERAGE.md"]
    cov = re.sub(r"(?m)^- R2: .*$", "- R2: [competitors](../01-research.md#competitors)", cov)
    cov = re.sub(r"(?m)^- R4: .*$", "- R4: [legal](../01-research.md#legal)", cov)
    files["sdlc/1/COVERAGE.md"] = cov
    p = mk(files)
    if cache is not None:
        os.makedirs(os.path.join(p, ".sdlc", "cache"), exist_ok=True)
        with open(contract.links_cache(p), "w") as f:
            json.dump({u: {"status": s, "checked": time.time()} for u, s in cache.items()}, f)
    return p


def test_cite():
    G = "cite-lint"
    ok_cache = {"https://simplenote.com/": 200, "https://gdpr-info.eu/art-4-gdpr/": 200, "https://standardnotes.com/": 301}
    p = research_repo(RES, cache=ok_cache)
    f, m, i, unk = contract.cite_lint(p, st_for("1"), "1", today=datetime.date(2026, 11, 14))
    record(G, "control: every claim sourced (inline link or footnote) with a retrieval date, every link resolving -> "
              "passes", not f and not unk and i["claims"] == 3, (f, unk))
    p = research_repo(RES.replace(", \nretrieved 2026-11-02)", ")").replace("), \n", ")"), cache=ok_cache)
    for text, why, label in (
            (RES.replace("([site](https://simplenote.com/), retrieved 2026-11-02)", "([site](https://simplenote.com/))"),
             "has no retrieval date", "a URL without a date"),
            (RES.replace("retrieved 2026-11-03", "retrieved 2027-01-03"), "in the future", "a date in the future"),
            (RES.replace("- No personal data beyond an e-mail address ([GDPR](https://gdpr-info.eu/art-4-gdpr/), retrieved "
                         "2026-11-03)", "- No personal data beyond an e-mail address"),
             "this legal claim has no source", "an uncited legal claim (R4)"),
            (RES.replace("[^sn]: https://standardnotes.com/ retrieved 2026-11-02", "[^sn]: Standard Notes website"),
             "needs a URL and a date", "a footnote source without URL and date")):
        p = research_repo(text, cache=ok_cache)
        f, _m, _i, _u = contract.cite_lint(p, st_for("1"), "1", today=datetime.date(2026, 11, 14))
        record(G, "planted: %s -> fails" % label, has(f, why), f[:3])
    p = research_repo(RES, cache=dict(ok_cache, **{"https://simplenote.com/": 404}))
    f, _m, _i, _u = contract.cite_lint(p, st_for("1"), "1", today=datetime.date(2026, 11, 14))
    record(G, "planted: a link the gate found dead (HTTP 404 in its cache) -> fails", has(f, "does not resolve (HTTP 404)"), f)
    p = research_repo(RES, cache={})
    f, _m, _i, unk = contract.cite_lint(p, st_for("1"), "1", write_cache=False, today=datetime.date(2026, 11, 14))
    record(G, "a link nobody checked yet is UNKNOWN in a feedback run (never a pass)", not f and len(unk) == 3, unk)
    rc = subprocess.run([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                         os.path.join(E.home, "gate", "v1", "check_contract.py"), "--phase", "1"], cwd=p,
                        env=E.env(MOADIX_PRODUCT_ROOT=p), capture_output=True, text=True).returncode
    record(G, "... and check-contract exits 2 (unknown) for it", rc == 2, rc)
    f, _m, _i, _u = contract.cite_lint(mk({"x.md": "x"}), st_for("1", feature="F1"), "1")
    record(G, "a feature cycle with no research additions (optional, Amendment 2 as built) -> passes", not f, f)


# ------------------------------------------------------------------ the gap critic, through the gate
FIX_BRD = open(os.path.join(REPO, "tests", "fixtures", "product", "sdlc", "00-brd.md")).read()


def product(name, brd=FIX_BRD):
    p = E.repo(name, docs=())
    write(p, {"sdlc/00-brd.md": brd})
    E.commit(p, "brd")
    E.init(p, name + "fx")
    return p


def contract_files(p, label):
    st, size, ruling = contract_fixture.scope_of(p, E)
    contract_fixture.write(p, contract_fixture.files(label, st, size, ruling))
    contract_fixture.commit(p, "contract files %s" % label)


def approve(p, label):
    rv = E.review_until_fresh(p, label, contract=False)
    return rv, E.prompt(p, "APPROVE %s %s" % (label, E.fresh()))


def cov_line(p, label, tid):
    rel = "sdlc/%s/COVERAGE.md" % label
    lines = open(os.path.join(p, rel)).read().splitlines()
    n = next(i for i, ln in enumerate(lines, 1) if ln.startswith("- %s:" % tid))
    return rel, n, lines[n - 1]


def finding(p, label, tid, sev, cid="C1"):
    rel, n, text = cov_line(p, label, tid)
    return {"id": cid, "topic": tid, "severity": sev, "quote": text[2:60], "citation": "%s:%d" % (rel, n),
            "fix": "cover %s in the BRD" % tid}


def waive(p, wid, reason="accepted for the toy run"):
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    return E.prompt(p, "WAIVE %s owner=moad scope=phase-0 expiry=%s reason=%s %s" % (wid, exp, reason, E.fresh()))


def test_critic():
    G = "critic"
    p = product("crit")
    contract_files(p, "0")
    rv, ctx = approve(p, "0")
    record(G, "no gap-critic evidence -> APPROVE 0 refused (every gated phase has a critic; missing fails closed)",
           "NOT recorded" in ctx and "gap-critic" in ctx, short(ctx, 400))
    d, why, prompt = contract_fixture.critic(E, p, "0", findings=[])
    record(G, "moadix:gap-critic is scheduled in phase 0; the gate's brief names the role, every topic, the size "
              "defaults, the BLOCKER rules and CRITIC.json",
           d == "allow" and prompt and "senior business analyst" in prompt and "- B27 " in prompt and
           "size S default: N/A" in prompt and "missing money flow" in prompt and "CRITIC.json" in prompt and
           "never pass a phase" in prompt, short(why or prompt, 300))
    d2, w2 = E.pretool(p, "Agent", {"subagent_type": "gap-critic", "prompt": "x", "description": "x"})
    record(G, "the critic launched under another spelling than moadix:gap-critic -> refused", d2 == "deny", short(w2))
    d3, w3 = E.pretool(p, "Write", {"file_path": os.path.join(p, "sdlc", "0", "COVERAGE.md"), "content": "x"})
    rc, out, err = E.hook("pretool", {"hook_event_name": "PreToolUse", "session_id": "c7", "cwd": p, "tool_name": "Write",
                                      "tool_input": {"file_path": os.path.join(p, "sdlc", "00-brd.md"), "content": "x"},
                                      "agent_id": "a1", "agent_type": "moadix:gap-critic"})
    hs = out.get("hookSpecificOutput") or {}
    record(G, "the critic cannot write the documents it judges (only its evidence directory)",
           hs.get("permissionDecision") == "deny" and "evidence" in hs.get("permissionDecisionReason", ""), short(hs))
    rv, ctx = approve(p, "0")
    record(G, "control: clean CRITIC.json (every topic checked, no finding) -> APPROVE 0 recorded", "recorded" in ctx and
           "NOT" not in ctx, short(ctx, 300))

    # phase 1: BLOCKER, MAJOR, MINOR
    fix_res = open(os.path.join(REPO, "tests", "fixtures", "product", "sdlc", "01-research.md")).read()
    write(p, {"sdlc/01-research.md": RES + "\n" + fix_res.split("\n", 1)[1]})
    E.commit(p, "research")
    contract_files(p, "1")
    contract_fixture.seed_links(p, {"current_phase": "1", "feature": None})
    contract_fixture.critic(E, p, "1", findings=[finding(p, "1", "R4", "BLOCKER")])
    rv, ctx = approve(p, "1")
    record(G, "an open BLOCKER -> APPROVE 1 refused, the finding named", "NOT recorded" in ctx and "BLOCKER C1 (R4)" in ctx,
           short(ctx, 400))
    ctx = waive(p, "gap-critic.R4")
    record(G, "WAIVE of a BLOCKER (gap-critic.R4) -> refused: a BLOCKER cannot be waived",
           "NOT recorded" in ctx and "cannot be waived" in ctx, short(ctx, 300))
    contract_fixture.critic(E, p, "1", findings=[finding(p, "1", "R7", "MAJOR")])
    rv, ctx = approve(p, "1")
    record(G, "an unwaived MAJOR -> APPROVE 1 refused, saying how to waive it",
           "NOT recorded" in ctx and "MAJOR C1 (R7)" in ctx and "WAIVE gap-critic.R7" in ctx, short(ctx, 400))
    ctx = waive(p, "gap-critic.R7", "cost model deferred to phase 3 by the operator")
    record(G, "WAIVE gap-critic.R7 with a reason -> recorded", "recorded" in ctx and "NOT" not in ctx, short(ctx, 300))
    contract_fixture.critic(E, p, "1", findings=[finding(p, "1", "R7", "MAJOR"), finding(p, "1", "R13", "MINOR", "C2")])
    rv, ctx = approve(p, "1")
    minor = os.path.join(p, ".sdlc", "cache", "minor", "product-1.md")
    record(G, "with the MAJOR waived and one MINOR -> APPROVE 1 recorded; the MINOR is not in the summary",
           "recorded" in ctx and "NOT" not in ctx and "R13" not in ctx, short(ctx, 300))
    record(G, "the MINOR finding goes to the operator's file (.sdlc/cache/minor/product-1.md), and REVIEW counts it",
           os.path.exists(minor) and "MINOR C2 (R13)" in open(minor).read() and "1 MINOR finding(s), not shown" in rv,
           short(rv, 500))

    # schema and evidence defects (phase 2)
    write(p, {"sdlc/02-prd.md": PRD})
    E.commit(p, "prd")
    contract_files(p, "2")
    base = finding(p, "2", "P10", "MINOR")
    tops = [t for t, _ in contract.topics("2")]
    cases = [
        ("a verdict field (\"approved\": true)", dict(extra={"approved": True}), "schema does not allow"),
        ("a topic left out of topics_checked", dict(topics_checked=tops[:-1]), "topics_checked misses P23"),
        ("a quote that is not at the cited lines", dict(findings=[dict(base, quote="words nobody wrote")]), "quote is not at"),
        ("a citation outside the file", dict(findings=[dict(base, citation="sdlc/2/COVERAGE.md:999")]), "outside"),
        ("a topic of another phase", dict(findings=[dict(base, topic="B1")]), "not a topic of phase 2"),
        ("a severity outside BLOCKER/MAJOR/MINOR", dict(findings=[dict(base, severity="high")]), "not one of BLOCKER"),
        ("a finding without a fix", dict(findings=[{k: v for k, v in base.items() if k != "fix"}]), "has no 'fix'"),
    ]
    for label, kw, why in cases:
        contract_fixture.critic(E, p, "2", **({"findings": []} | kw if "findings" not in kw else kw))
        rc = subprocess.run([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                             os.path.join(E.home, "gate", "v1", "check_verifiers.py"), "--phase", "2"], cwd=p,
                            env=E.env(MOADIX_PRODUCT_ROOT=p), capture_output=True, text=True)
        record(G, "planted CRITIC.json: %s -> the evidence fails" % label, rc.returncode == 1 and why in rc.stdout,
               short(rc.stdout, 400))
    reg = {c["id"] for c in __import__("hlib").load_yaml(os.path.join(REPO, "gate", "config", "registry.yaml"))["components"]}
    record(G, "phase 12 (Retro) is gated (ruling 2): its contract validator and gap-critic check are registered",
           contract.gated("12") and len(contract.topics("12")) == 10 and {"check-contract-12", "check-verifiers-12"} <= reg,
           sorted(x for x in reg if x.endswith("-12")))


# ------------------------------------------------------------------ operator overrides (ADOPT) and the skeleton
def test_overrides():
    G = "overrides"
    p = product("ovr")
    contract_files(p, "0")
    E.stop(p)
    sk = os.path.join(p, ".sdlc", "coverage", "product-0-COVERAGE.md")
    for _ in range(40):
        if os.path.exists(sk):
            break
        time.sleep(0.1)
    record(G, "the Stop hook keeps the pre-filled skeleton in .sdlc/coverage/ (size S defaults with their reason)",
           os.path.exists(sk) and "- B24: N/A: Size S default" in open(sk).read(), sk)
    write(p, {".sdlc-proposals/config/coverage-overrides.yaml": "turn_on: [B24]\nna:\n  - topic: B13\n    reason: \"the "
                                                                 "operator ruled competitors out of scope for the toy\"\n"})
    ctx = E.prompt(p, "ADOPT %s" % E.fresh())
    record(G, "ADOPT of coverage-overrides.yaml (turn_on B24, an N/A ruling for B13) -> recorded", "recorded" in ctx and
           "NOT" not in ctx, short(ctx, 300))
    f, _m, _i = contract.coverage_lint(p, st_for("0"), "0")
    record(G, "after the operator turned B24 on, its `size-default` N/A fails", has(f, "B24", "operator turned it on"), f)
    cov = open(os.path.join(p, "sdlc/0/COVERAGE.md")).read()
    cov = re.sub(r"(?m)^- B24: .*$", "- B24: N/A: single tenant for now, the operator wants it argued here though",
                 cov).replace(re.search(r"(?m)^- B13: .*$", cov).group(0), "- B13: N/A: operator")
    write(p, {"sdlc/0/COVERAGE.md": cov})
    f, _m, _i = contract.coverage_lint(p, st_for("0"), "0")
    record(G, "`N/A: operator` is accepted for the ruled topic (B13); a turned-on topic cannot be N/A at all (B24)",
           not has(f, "B13") and has(f, "B24", "cannot be N/A"), f)
    for text, why in (("colour: blue\n", "may only set turn_on and na"), ("turn_on: [ZZ9]\n", "not a coverage topic"),
                      ("na:\n  - topic: B13\n    reason: none\n", "needs a real reason")):
        write(p, {".sdlc-proposals/config/coverage-overrides.yaml": text})
        ctx = E.prompt(p, "ADOPT %s" % E.fresh())
        record(G, "ADOPT of a bad overrides file (%s) -> refused" % why, "NOT" in ctx and why in ctx, short(ctx, 300))
        os.unlink(os.path.join(p, ".sdlc-proposals/config/coverage-overrides.yaml"))


# ------------------------------------------------------------------ phase 7 rules
def line(p, pid, action, payload):
    import base64
    hd = git(p, "rev-parse", "HEAD").stdout.strip()
    pl = dict(payload, source_commit=hd)
    r = E.checker("record", "--product", pid, "--action", action, "--code", E.fresh(),
                  "--payload-b64", base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
    from gate import state
    state.append_line(p, r.stdout.strip())
    state.write_phase(p, state.replay(pid, [json.loads(x["body"]) for x in E.ledger(p)]))


def test_phase7():
    G = "phase7-rules"
    p = product("rules")
    for lab in ("0", "1", "2", "3", "4", "5", "6", "6b"):
        line(p, "rulesfx", "APPROVE %s" % lab, {"phase": lab, "validation": {"verdict": "pass", "results": [],
                                                                            "digest": "sha256:fixture"}})
    write(p, {"src/notes.py": "def save(notes, n):\n    return notes + [n]\n\n\ndef unused_extra():\n    return 42\n"})
    E.commit(p, "code")
    contract_fixture.critic(E, p, "7")
    rc, out, err = E.hook("pretool", {"hook_event_name": "PreToolUse", "session_id": "c7", "cwd": p, "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "moadix:code-reviewer", "prompt": "x",
                                                     "description": "x"}})
    ui = (out.get("hookSpecificOutput") or {}).get("updatedInput") or {}
    prompt = ui.get("prompt", "")
    record(G, "the code reviewer's brief lists the three phase-7 rules (R7-1..R7-3) and asks for a `rule` on violations",
           "R7-1: Make the smallest change" in prompt and "R7-2: Do not touch code" in prompt and
           "R7-3: Do not add anything nobody asked for" in prompt and "\"rule\"" in prompt, short(prompt[-600:]))
    bh = re.search(r"^brief_sha256: (\w+)$", prompt, re.M).group(1)
    rcp = re.search(r"^receipt: (\w+)$", prompt, re.M).group(1)
    ev = {"role": "code-reviewer", "source_commit": git(p, "rev-parse", "HEAD").stdout.strip(), "brief_sha256": bh,
          "receipt": rcp, "reviewed": ["src/notes.py"],
          "findings": [{"id": "S1", "severity": "medium", "rule": "R7-3", "summary": "unused_extra was not asked for",
                        "citations": ["src/notes.py:5-6"]}]}
    edir = os.path.join(p, ".sdlc", "cache", "verify", "7", "code-reviewer", "evidence")
    with open(os.path.join(edir, "findings.json"), "w") as f:
        json.dump(ev, f)

    def check7():
        r = subprocess.run([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                            os.path.join(E.home, "gate", "v1", "check_verifiers.py"), "--phase", "7"], cwd=p,
                           env=E.env(MOADIX_PRODUCT_ROOT=p), capture_output=True, text=True)
        return r.returncode, r.stdout
    rc, out = check7()
    record(G, "a medium finding tagged R7-3 is a MAJOR: check-verifiers-7 fails, naming the rule and the waiver",
           rc == 1 and "MAJOR S1 (R7-3" in out and "WAIVE code-reviewer.S1" in out, short(out, 400))
    ctx = waive(p, "code-reviewer.S1", "the helper is used by the next task")
    rc, out = check7()
    record(G, "after WAIVE code-reviewer.S1 with a reason -> check-verifiers-7 passes", "recorded" in ctx and rc == 0,
           short(ctx + " | " + out, 400))
    ev["findings"][0]["rule"] = "R9"
    with open(os.path.join(edir, "findings.json"), "w") as f:
        json.dump(ev, f)
    rc, out = check7()
    record(G, "planted: a rule id that does not exist (R9) -> the evidence fails", rc == 1 and "R9" in out, short(out))
    tdd = open(os.path.join(REPO, "skills", "test-driven-development", "SKILL.md")).read()
    record(G, "the phase-7 implementation skill (test-driven-development) carries the three rules, recorded as a "
              "MOADIX change", "Make the smallest change that meets the requirement" in tdd and
           "Do not touch code the task does not need" in tdd and "Do not add anything nobody asked for" in tdd and
           "Increment 7" in open(os.path.join(REPO, "skills", "test-driven-development", "MOADIX-CHANGES.md")).read(), "")


# ------------------------------------------------------------------ hygiene, tools, fixes, operator experience
def test_misc():
    G = "hygiene"
    skills = sorted(d for d in os.listdir(os.path.join(REPO, "skills")) if os.path.isdir(os.path.join(REPO, "skills", d)))
    names = []
    for d in skills:
        m = re.search(r"^name:\s*(\S+)", open(os.path.join(REPO, "skills", d, "SKILL.md")).read(), re.M)
        names.append(m.group(1) if m else d)
    record(G, "no vendored skill's folder or name contains BMad/BMAD", not any(re.search("bmad", x, re.I)
                                                                              for x in skills + names), skills)
    import hlib
    src = hlib.load_yaml(os.path.join(REPO, "skills", "SOURCES.yaml"))["skills"]
    renamed = [s for s in src if s.get("upstream_name", "").startswith("bmad-")]
    record(G, "the four renamed BMAD skills keep their MIT licence file and record their upstream name",
           len(renamed) == 4 and all(os.path.exists(os.path.join(REPO, "skills", s["name"], "LICENSE")) and
                                     "BMad" in open(os.path.join(REPO, "skills", s["name"], "LICENSE")).read()
                                     for s in renamed), [s["name"] for s in renamed])
    record(G, "every vendored skill records source URL, commit, licence and retrieval date",
           all(s.get("source") and s.get("commit") and s.get("licence") and re.match(r"^\d{4}-\d\d-\d\d$",
                                                                                      str(s.get("retrieved"))) for s in src),
           [s["name"] for s in src if not s.get("retrieved")])
    g = subprocess.run([fixtures.PY, os.path.join(REPO, "tests", "skills", "selfapproval_grep.py")], capture_output=True,
                       text=True)
    record(G, "the self-approval grep (now also push and done/ready wording) finds nothing unallowed in the skills",
           "0 NOT allowed" in g.stdout, short(g.stdout[-300:]))

    G = "tools"
    tools = {t["name"]: t for t in hlib.load_yaml(os.path.join(REPO, "gate", "config", "tools.yaml"))["tools"]}
    want = {"oasdiff": "1.35.0", "squawk": "2.71.0", "vacuum": "0.36.1", "likec4": "1.60.0", "dependency-cruiser": "18.7.0",
            "knip": "6.44.1", "pytm": "1.4.0", "schemathesis": "4.32.7", "lhci": "0.15.1", "zizmor": "1.31.1",
            "actionlint": "1.7.12"}
    record(G, "the eleven new gate-run tools are pinned to exact versions (Amendment 3 section 4)",
           all(str(tools.get(n, {}).get("version")) == v for n, v in want.items()),
           {n: tools.get(n, {}).get("version") for n in want})
    ok_assets = all(len(tools[n].get("assets") or {}) == 4 and all(re.match(r"^[0-9a-f]{64}$", a.get("sha256", ""))
                                                                   for a in tools[n]["assets"].values())
                    for n in ("oasdiff", "vacuum", "actionlint"))
    ok_locks = all(os.path.exists(os.path.join(REPO, str(tools[n]["lock"]))) for n in want if tools[n].get("lock"))
    record(G, "binary pins carry a sha256 per platform; npm and PyPI pins point at committed lockfiles", ok_assets and ok_locks,
           "")
    doc = open(os.path.join(REPO, "gate", "config", "tools.yaml")).read()
    rejected = ["spectral", "atlas", "threagile", "threat dragon", "stride gpt", "syft", "grype", "trufflehog", "codeql",
                "snyk", "pact", "chromatic", "argos", "lost pixel", "artillery", "locust", "changesets", "ralph-loop",
                "commit-commands", "frontend-design", "figma", "infracost", "doppler", "infisical", "sops", "appium"]
    names_only = " ".join(re.findall(r"(?m)^\s*-?\s*(?:name|package): \"?([^\"\n]+)", doc)).lower()
    record(G, "nothing from the rejected list is pinned", not [r for r in rejected if r in names_only],
           [r for r in rejected if r in names_only])
    prod = hlib.load_yaml(os.path.join(REPO, "gate", "config", "tools.yaml")).get("product_dependencies") or []
    third = open(os.path.join(REPO, "THIRD-PARTY.md")).read()
    record(G, "ruling 3: axe-core and @axe-core/playwright (MPL-2.0, fetched unmodified) are pinned product dependencies, "
              "and THIRD-PARTY.md records every MPL-2.0 component with its source",
           {"axe-core", "@axe-core/playwright"} <= {str(x.get("package")) for x in prod} and
           all(x.get("license") for x in prod) and len(prod) == 6 and
           all(w in third for w in ("lightningcss", "hypothesis", "certifi", "@axe-core/playwright",
                                    "https://registry.npmjs.org/axe-core")), prod)
    mf = {x["label"]: x for x in hlib.load_yaml(os.path.join(REPO, "gate", "config", "phase-manifest.yaml"))["phases"]}
    record(G, "MCP servers stay phase-scoped: Context7 in 1, 3, 5, 7; Playwright in 10a and 10b; GitHub in 11",
           all("context7" in mf[x]["mcp"] for x in ("1", "3", "5", "7")) and
           all("moadix:playwright" in mf[x]["mcp"] for x in ("10a", "10b")) and
           [x for x in mf if "moadix:github" in mf[x]["mcp"]] == ["11"] and
           [x for x in mf if "context7" in mf[x]["mcp"]] == ["1", "3", "5", "7"], "")
    note = session.pins_due(datetime.date(2027, 3, 1))
    record(G, "the monthly pin proposal: SessionStart says it is due when the pins are over 30 days old, not before",
           note and "propose_pins.py" in note and session.pins_due(datetime.date(2026, 11, 20)) is None, note)

    G = "fixes"
    p = E.repo("f1", docs=("00-brd.md",))
    ctx = E.init(p, "f1fx")
    files = re.findall(r"_bmad/\S+?(?=[,.](?:\s|$))", ctx)
    record(G, "F-1: the INIT message names all 7 files BMad core installs, with the count",
           "(7 files)" in ctx and len(set(files)) == 7 and "_bmad/scripts/resolve_customization.py" in ctx, short(ctx, 400))
    prof = hlib.load_yaml(os.path.join(REPO, "gate", "config", "profiles.yaml"))["profiles"]
    record(G, "F-2: the WEB and WEB→APP profiles declare 6b and 10c, the phases the gate runs for them",
           all("6b" in prof[k]["active_phases"] and "10c" in prof[k]["active_phases"] for k in ("WEB", "WEB→APP")), "")

    G = "operator"
    data = {"results": [{"validator": "check-contract-0", "result": "pass"}], "minor": 2,
            "minor_file": ".sdlc/cache/minor/product-0.md"}
    data_f = {"results": [{"validator": "check-verifiers-0", "result": "fail", "output":
                           "MINOR moadix:gap-critic: MINOR C2 (B5): wording\nFAIL moadix:gap-critic: open finding: BLOCKER C1"}]}
    fl = validation.findings(data_f)
    record(G, "APPROVE/REVIEW summaries show BLOCKER and MAJOR findings only; MINORs are counted with their file",
           "2 MINOR finding(s), not shown: .sdlc/cache/minor/product-0.md" in validation.summary(data)[-1] and
           "BLOCKER C1" in fl[0] and "C2 (B5)" not in fl[0], fl)
    cmd = open(os.path.join(REPO, "commands", "coverage.md")).read()
    record(G, "/moadix:coverage (every phase) is generated from the topic catalogue and matches it",
           cmd == contract.coverage_doc() and "coverage" in hlib.load_yaml(
               os.path.join(REPO, "gate", "config", "phase-manifest.yaml"))["always"]["skills"], "")
    pj = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))
    record(G, "plugin.json is 0.5.1", pj.get("version") == "0.5.1", pj.get("version"))


def main():
    try:
        for t in (test_coverage, test_size, test_discovery, test_adr, test_trace, test_ears, test_cite, test_critic,
                  test_overrides, test_phase7, test_misc):
            try:
                t()
            except Exception as e:  # a crashing group is a failure, never a skip
                import traceback
                record(t.__name__, "group ran to the end", False, "%s: %s\n%s" % (type(e).__name__, e,
                                                                                 traceback.format_exc()[-1500:]))
        viol = E.violations()
        record("guard", "no test read, wrote or started a real product, keychain or ~/.claude", not viol, viol)
    finally:
        E.remove()
    n = len(RESULTS)
    bad = [r for r in RESULTS if not r[2]]
    for g, name, _ok in bad:
        print("FAILED [%s] %s" % (g, name))
    print("\n%d checks, %d passed, %d failed (%d s)" % (n, n - len(bad), len(bad), time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
