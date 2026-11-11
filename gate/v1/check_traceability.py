#!/usr/bin/env python3
"""check-traceability — Phase 8 validator: the EXECUTABLE traceability matrix.

Builds BRD goal -> PRD story -> task -> test ID -> result, and fails if any PRD
story lacks at least one PASSING test.

The word that matters is *executable*. This script does not read a document that
claims tests exist and does not accept any agent's assertion that they pass. It
parses **real test-runner output** (JUnit XML) produced by an actual run. If the
XML is absent, stale-looking, or empty, the gate fails.

How a test claims a story: the story ID appears in the test's `name` or
`classname`, e.g.

    def test_US_001_converts_miles_to_km():   ->  <testcase name="test_US_001_..."/>
    describe('US-001 conversion', ...)        ->  <testcase classname="US-001 conversion"/>

Both `US-001` and `US_001` are recognised. No mapping file to drift.

The default JUnit glob is exactly what harness/bin/run-product-tests.sh writes
(<governed_root>/test-results/junit.xml), so the sanctioned front door and this
gate share one contract: the door produces the evidence, the gate consumes it.

Writes the matrix to sdlc/08-traceability.md unless --no-write.

Exit 0 = every story has a passing test. Non-zero = fail.
"""

import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

# `\b` after the digits was blocked by a following underscore, so `test_US_001_AC_1`
# -- the EXACT form this file's own remediation message tells you to use -- matched
# nothing, and the story reported "has NO test referencing it" with no way to fix it
# except by discovering the rule by accident. toy-product only ever passed because
# its test names happen to use a different separator.
#
# Same class as a store-asset claim id no producer could legally declare, found
# twice in one version: a tool that rejects the form of its own advice.
ID_RE = re.compile(r"(?<![A-Za-z0-9])((?:US|NFR)[-_ ]?\d{1,4})(?![0-9])", re.I)


# A test may legitimately trace to the FINDING spine rather than the story
# spine: an SF-n regression test or a SEC-NNN verification test is traced, just
# not to a PRD story. Promoting "references no story" to an error without this
# would have made errors of all eight of toy-mobile's SF-* tests -- a gate that
# fires on exactly the behaviour it wants, needing a ninth exemption every time
# a finding gets a test.
FINDING_RE = re.compile(r"(?<![A-Za-z0-9])((?:SF|SEC)[-_ ]?\d{1,4})(?![0-9])", re.I)


def traceability_exemptions(root):
    """{kind: {token: entry}} from harness/config/traceability-exemptions.yaml.

    F63: `untested-story` names a PRD story by `story` (not `token`) that no test can
    verify in this environment. It is accepted only with a non-empty `reason`.
    """
    out = {"unknown-story": {}, "untraced-case": {}, "untested-story": {}}
    p = hlib.config_path(root, "traceability-exemptions.yaml")
    if not os.path.exists(p):
        return out
    try:
        doc = hlib.load_yaml(p) or {}
    except Exception:
        return out
    for e in (doc.get("exemptions") or []):
        kind, tok = str(e.get("kind") or ""), str(e.get("token") or "")
        if kind == "untested-story":
            story = norm_id(str(e.get("story") or "").strip())
            if story and str(e.get("reason") or "").strip():
                out[kind][story] = e
        elif kind in out and tok and e.get("reason") and e.get("owner"):
            out[kind][tok] = e
    return out


def norm_id(s):
    # A space too, now that ID_RE accepts "US 001": a Maestro flow name reads as
    # prose, and normalising only the underscore would put "US 001" in the
    # coverage map as a story that does not exist.
    return s.upper().replace("_", "-").replace(" ", "-")


def strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return strip_comments(fh.read())


def parse_brd(path):
    text = read(path)
    goals = {}
    if not text:
        return goals
    for m in re.finditer(r"^\|\s*(BG-\d+)\s*\|([^|]*)\|", text, re.M):
        goals[m.group(1)] = m.group(2).strip()
    return goals


def parse_prd(path):
    """{story_id: {'goal': BG-n, 'title': str, 'acs': [{'id','tags'}]}}

    An acceptance criterion may carry tags in parentheses:

        - **AC-3 (ui-state-transition):** When the user edits the value, ...

    `ui-state-transition` means the criterion is about the product REACTING --
    a binding, a lifecycle callback, a navigation. No unit test can observe
    that, however thorough: v0.4 covered `applyConversion` with 17 cases and
    could not see whether a keystroke called it.
    """
    text = read(path)
    out = {}
    if not text:
        return out
    cur = None
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+((?:US|NFR)-\d+)\s*[—:-]?\s*(.*)$", line.strip())
        if m:
            cur = m.group(1)
            out[cur] = {"goal": None, "title": m.group(2).strip(), "acs": []}
            continue
        if cur:
            g = re.match(r"^\s*[-*]\s*\*\*BRD goal:?\*\*\s*(.+)$", line, re.I)
            if g:
                refs = re.findall(r"\bBG-\d+\b", g.group(1))
                out[cur]["goal"] = ", ".join(refs) if refs else g.group(1).strip()
                continue
            a = AC_RE.match(line)
            if a:
                tags = {t.strip().lower() for t in (a.group(2) or "").split(",") if t.strip()}
                out[cur]["acs"].append({"id": a.group(1).upper(), "tags": tags})
    return out


def parse_tasks(path):
    """{task_id: {'title', 'stories', 'design', 'secs'}}

    `design` and `secs` are the phase-7 CONTEXT PACK, added in v0.5 Stage C.
    A task used to carry story ids alone: the design layer knew which module
    covered which story and which SEC-IDs it discharged (check_lld enforces
    both), and none of it reached the bundle the implementing agent works from.
    That seam is where v0.4's Convert button came from -- built into a gap the
    LLD had left, against a UX doc that had explicitly forbidden it.
    """
    text = read(path)
    out = {}
    if not text:
        return out
    cur = None
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+(T-\d+)\s*[—:-]?\s*(.*)$", line.strip())
        if m:
            cur = m.group(1)
            if cur in out:
                continue  # F61: a later heading with the same id must not reset the task
            out[cur] = {"title": m.group(2).strip(), "stories": [],
                        "design": None, "secs": None}
            continue
        if not cur:
            continue
        st = re.match(r"^\s*[-*]\s*\*\*Implements stories:?\*\*\s*(.+)$", line, re.I)
        if st:
            out[cur]["stories"] = [norm_id(x) for x in ID_RE.findall(st.group(1))]
            continue
        dg = re.match(r"^\s*[-*]\s*\*\*Design:?\*\*\s*(.+)$", line, re.I)
        if dg:
            out[cur]["design"] = dg.group(1).strip().strip("`").strip()
            continue
        sc = re.match(r"^\s*[-*]\s*\*\*Satisfies SEC-IDs:?\*\*\s*(.+)$", line, re.I)
        if sc:
            out[cur]["secs"] = sc.group(1).strip()
    return out


def parse_targets(root):
    """{artifact_basename: {'id','level','strips'}} from product-tests.yaml.

    Read through product_tests.normalise() rather than re-parsed here, so the
    thing that RUNS the suites and the thing that JUDGES them cannot disagree
    about what a target is.
    """
    try:
        sys.path.insert(0, HERE)
        import product_tests
        cfg = hlib.load_yaml(hlib.config_path(root, "product-tests.yaml")) or {}
        out = {}
        for t in product_tests.normalise(cfg):
            tid = str(t.get("id") or "unit")
            out[product_tests.artifact_name(tid)] = {
                "id": tid,
                "level": str(t.get("level") or "unit"),
                "strips": bool(t.get("strips_source")),
            }
        return out
    except Exception:
        # Unknown, not "everything is a unit target": the caller reports it.
        return None


def parse_strip_manifest(path):
    """{'absent': [str], 'dropped': [str]} from test-results/strip-manifest.txt.

    toy-mobile has generated this file accurately since v0.4 and NOTHING read
    it (Constitution 3.9). It is the only place that records which SwiftUI
    bindings are absent from the compiled test binary -- which is precisely the
    region where both of that run's device-only defects lived.
    """
    if not os.path.exists(path):
        return None
    out = {"absent": [], "dropped": []}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("[binding-absent]"):
                    out["absent"].append(line.split("]", 1)[1].strip())
                elif line.startswith("[dropped-top-level-construct]"):
                    out["dropped"].append(line.split("]", 1)[1].strip())
    except OSError:
        return None
    return out


AC_RE = re.compile(r"^\s*[-*]\s*\*\*(AC-\d+)\s*(?:\(([^)]*)\))?\s*:?\*\*", re.I)
UI_TAG = "ui-state-transition"


def squash(s_):
    return re.sub(r"[^A-Z0-9]", "", (s_ or "").upper())


def names_ac(case_name, sid, acid):
    """Does this test case name claim BOTH the story and the acceptance criterion?

    Story-level naming is enough for ordinary coverage. A UI state transition is
    gated per AC, because 'US-001 has a passing UI test' was true of the v0.4
    build for the whole period AC-3 was broken -- the passing UI-ish test
    exercised a different criterion.
    """
    h = squash(case_name)
    return squash(sid) in h and squash(acid) in h


def parse_junit(paths):
    """[{'name','classname','status','file'}] from real runner output."""
    cases = []
    for p in paths:
        try:
            tree = ET.parse(p)
            # in-tree XML; a bomb stalls the product's own gate and fails closed
        except Exception as exc:
            cases.append({"name": "<unparseable>", "classname": os.path.basename(p),
                          "status": "error", "file": p, "detail": repr(exc)})
            continue
        root = tree.getroot()
        # Iterate testcases at ANY depth. Node's built-in junit reporter can emit
        # <testcase> directly under <testsuites> with no <testsuite> wrapper; the
        # earlier suite-scoped walk reported 0 cases for a suite that had 9
        # passing tests. Failing closed was correct, but the parser was wrong.
        seen = set()
        for tc in root.iter("testcase"):
            if id(tc) in seen:
                continue
            seen.add(id(tc))
            if True:
                status = "passed"
                if tc.find("failure") is not None:
                    status = "failed"
                elif tc.find("error") is not None:
                    status = "error"
                elif tc.find("skipped") is not None:
                    status = "skipped"
                cases.append({"name": tc.get("name") or "", "classname": tc.get("classname") or "",
                              "status": status, "file": p,
                              "artifact": os.path.basename(p)})
    return cases


def main():
    ap = argparse.ArgumentParser(prog="check-traceability.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--junit", default=None,
                    help="glob for JUnit XML (default <governed_root>/test-results/*.xml)")
    ap.add_argument("--no-write", action="store_true", help="do not write sdlc/08-traceability.md")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    d = args.dir or os.path.join(root, groot, "sdlc")
    junit_glob = args.junit or os.path.join(root, groot, "test-results", "*.xml")

    errs, warns = [], []
    # Informational channel: a finding-traced test and an exempted case are
    # facts the reader needs, and neither a warning nor a failure. Named `info`
    # rather than `notes` because THIS FUNCTION ALREADY HAS a `notes`, holding
    # the text of 08-coverage-notes.md -- shadowing it printed the whole file
    # one character per line.
    info = []

    goals = parse_brd(os.path.join(d, "00-brd.md"))
    stories = parse_prd(os.path.join(d, "02-prd.md"))
    tasks = parse_tasks(os.path.join(d, "07-tasks.md"))

    if not stories:
        errs.append("no PRD stories found at %s/02-prd.md; nothing to trace." % d)

    xmls = sorted(glob.glob(junit_glob))
    if not xmls:
        errs.append("no test-runner output matched %r. Phase 8 requires REAL test results: run the "
                    "suite with a JUnit reporter first. An agent's claim that tests pass is not "
                    "accepted." % junit_glob)
    cases = parse_junit(xmls)
    if xmls and not cases:
        errs.append("test-runner output at %r contains no <testcase> elements." % junit_glob)

    for c in cases:
        if c["status"] == "error" and c["name"] == "<unparseable>":
            errs.append("unparseable test output %s: %s" % (c["file"], c.get("detail")))

    # story -> tests
    story_tests = {sid: [] for sid in stories}
    unmapped = []
    for c in cases:
        if c["name"] == "<unparseable>":
            continue
        hay = "%s %s" % (c["classname"], c["name"])
        ids = {norm_id(x) for x in ID_RE.findall(hay)}
        if not ids:
            unmapped.append(c)
            continue
        for sid in ids:
            story_tests.setdefault(sid, []).append(c)

    # task -> stories
    story_tasks = {sid: [] for sid in stories}
    for tid, t in tasks.items():
        for sid in t["stories"]:
            story_tasks.setdefault(sid, []).append(tid)

    # ---- targets, levels and the strip manifest ---------------------------
    targets = parse_targets(root)
    if targets is None:
        errs.append("harness/config/product-tests.yaml could not be read, so no test result "
                    "can be attributed to a LEVEL. Coverage would have to be assumed, and "
                    "assumed coverage is what phase 8 exists to replace.")
        targets = {}
    level_of = {name: t["level"] for name, t in targets.items()}
    strips_any = [t for t in targets.values() if t["strips"]]

    # Derived from the junit glob, not from groot: --junit and the manifest
    # describe the same test run, so pointing one elsewhere must move the other.
    # Hardcoding groot here would make `--junit <other product>` read the
    # CURRENT product's manifest and report the wrong exclusions -- the same
    # hardcoded-state class as 3.7, one axis over.
    manifest_path = os.path.join(os.path.dirname(junit_glob), "strip-manifest.txt")
    manifest = parse_strip_manifest(manifest_path)
    if strips_any and manifest is None:
        errs.append("target(s) %s declare `strips_source: true` but there is no "
                    "test-results/strip-manifest.txt. A build that compiles a MODIFIED copy "
                    "of the product must record what it removed, or its green result claims "
                    "coverage of code that was never compiled."
                    % ", ".join(sorted(t["id"] for t in strips_any)))
    absent = (manifest or {}).get("absent") or []
    if absent:
        warns.append("the test build strips %d binding(s) from the compiled binary: %s. Any "
                     "behaviour that depends on them is invisible to a unit-level result."
                     % (len(absent), ", ".join(absent[:6])))

    ui_wv = {}
    try:
        _doc = hlib.load_phase_doc(root) or {}
        ui_wv = {str(w.get("path")): w for w in hlib.waivers_for(_doc, "ui-coverage")
                 if w.get("reason") and w.get("approver")}
    except Exception:
        ui_wv = {}

    tex = traceability_exemptions(root)
    coverage = {}
    for sid in sorted(stories):
        tests = story_tests.get(sid, [])
        passing = [t for t in tests if t["status"] == "passed"]
        if not tests and sid in tex["untested-story"]:
            ex = tex["untested-story"][sid]
            info.append("PRD story %s has no test -- exempt as untested-story (%s): %s"
                        % (sid, ex.get("owner") or "no owner", str(ex.get("reason")).strip()))
        elif not tests:
            errs.append("PRD story %s has NO test referencing it. Name a test after the story "
                        "(e.g. test_%s_...) so coverage is mechanical." % (sid, sid.replace("-", "_")))
        elif not passing:
            statuses = sorted({t["status"] for t in tests})
            errs.append("PRD story %s has %d test(s) but none PASSING (statuses: %s)."
                        % (sid, len(tests), ", ".join(statuses)))
        skipped = [t for t in tests if t["status"] == "skipped"]
        if skipped and passing:
            warns.append("%s has %d skipped test(s) alongside passing ones." % (sid, len(skipped)))
        if not story_tasks.get(sid):
            # Promoted from a warning in Stage C. A PRD story that no task
            # implements is a story nobody was asked to build, and it reached
            # phase 8 as a line of grey text.
            errs.append("PRD story %s is implemented by no task in 07-tasks.md. Add a task "
                        "naming it under '**Implements stories:**', or remove the story: a "
                        "story nobody was asked to build is not a story." % sid)

        # ---- the UI-state-transition gate --------------------------------
        ui_acs = [a for a in (stories[sid].get("acs") or []) if UI_TAG in a["tags"]]
        ui_passing = [t for t in passing if level_of.get(t["artifact"]) == "ui"]
        unmet = []
        for a in ui_acs:
            key = "%s:%s" % (sid, a["id"])
            if any(names_ac(t["name"] + " " + t["classname"], sid, a["id"]) for t in ui_passing):
                continue
            if key in ui_wv or sid in ui_wv:
                warns.append("%s is a UI state transition with no UI-level test, WAIVED by %s."
                             % (key, (ui_wv.get(key) or ui_wv.get(sid)).get("approver")))
                continue
            unmet.append(a["id"])
            errs.append(
                "%s %s is tagged `%s` and has no PASSING test at level `ui`. A unit test "
                "cannot observe a binding: v0.4 covered the conversion function with 17 "
                "cases while a keystroke failed to call it, and the suite stayed green for "
                "four approved phases. Add a UI-level test naming both ids (e.g. "
                "`%s_%s_...`), or waive with `gate.sh waive ui-coverage --path %s`."
                % (sid, a["id"], UI_TAG, sid.replace("-", "_"), a["id"].replace("-", "_"), key))

        # ---- FULL / PARTIAL / NONE ---------------------------------------
        why = ""
        if not tests and sid in tex["untested-story"]:
            verdict = "NONE"
            why = "exempt: untested-story"
        elif not passing:
            verdict = "NONE"
            why = "no passing test"
        elif unmet:
            verdict = "PARTIAL"
            why = "%s tagged %s, not covered at level `ui`" % (", ".join(unmet), UI_TAG)
        elif ui_acs and not ui_passing:
            verdict = "PARTIAL"
            why = "UI criteria covered only by waiver"
        elif absent and not ui_passing and any(
                level_of.get(t["artifact"]) == "unit" for t in passing):
            verdict = "PARTIAL"
            why = ("evidenced only by a build that strips %d binding(s) from the compiled "
                   "binary" % len(absent))
        else:
            verdict = "FULL"
            why = "%d passing case(s) across level(s) %s" % (
                len(passing),
                ", ".join(sorted({level_of.get(t["artifact"], "?") for t in passing})) or "?")
        coverage[sid] = (verdict, why)

    # ---- C1: the task bundle must carry the design slice -------------------
    # `Design` and `Satisfies SEC-IDs` both exist and are validated one phase
    # earlier (check_lld requires every module doc to declare Covers stories and
    # Satisfies SEC-IDs). This is the link that carries them into the work.
    #
    # A task with NO `Satisfies SEC-IDs` line is refused even though `none` is
    # accepted: silence and "none" render identically to a reader, and only one
    # of them was decided.
    lld_mod_dir = os.path.join(root, groot, "sdlc", "05-lld", "modules")
    for tid in sorted(tasks):
        t = tasks[tid]
        if not t.get("design"):
            errs.append("task %s names no '**Design:**'. Every task states the LLD module "
                        "doc it implements -- the seam where v0.4's Convert button was built "
                        "into a gap the design had left." % tid)
        else:
            dpath = t["design"]
            cand = [os.path.join(root, groot, dpath), os.path.join(root, dpath),
                    os.path.join(lld_mod_dir, os.path.basename(dpath))]
            if not any(os.path.exists(c) for c in cand):
                errs.append("task %s names design %r, which does not exist. A bundle "
                            "pointing at a design that is not there is worse than one "
                            "pointing at nothing: it reads as checked." % (tid, dpath))
        if t.get("secs") is None:
            errs.append("task %s has no '**Satisfies SEC-IDs:**' line. Write `none` if it "
                        "discharges none -- silence and `none` look identical, and only one "
                        "of them was decided." % tid)

    # ---- B2: a test that traces to nothing is the feature-creep signal -----
    # Both of these were warnings. A test exercising undeclared functionality is
    # the cheapest available evidence of R3 feature creep, and a warning cannot
    # fail a gate. Promoted, with an exemption path so a deliberate case is a
    # recorded decision rather than a reason to turn the check off.
    for sid in sorted(set(story_tests) - set(stories)):
        if sid in tex["unknown-story"]:
            info.append("tests reference %s, which is not a PRD story -- exempt (%s)."
                         % (sid, tex["unknown-story"][sid].get("owner")))
            continue
        errs.append("tests reference %s, which is not a PRD story. Either the story was "
                    "removed and its test was not, or the test names a story that never "
                    "existed; both mean a test asserting something the PRD does not claim. "
                    "Fix the reference, or record it in "
                    "harness/config/traceability-exemptions.yaml with a reason and an owner."
                    % sid)

    anon = [c for c in unmapped
            if not FINDING_RE.search("%s %s" % (c["classname"], c["name"]))
            and c["name"] not in tex["untraced-case"]]
    exempted = [c for c in unmapped if c["name"] in tex["untraced-case"]]
    findings_traced = len(unmapped) - len(anon) - len(exempted)
    if findings_traced:
        info.append("%d test case(s) trace to a finding (SF-*/SEC-*) rather than a PRD "
                     "story. That is the other traceability spine, not an untraced test."
                     % findings_traced)
    for c in exempted:
        info.append("untraced case %r -- exempt (%s)."
                     % (c["name"][:60], tex["untraced-case"][c["name"]].get("owner")))
    for c in anon:
        errs.append("test case %r references no PRD story and no finding. A test that traces "
                    "to nothing is either dead or exercising functionality nobody asked for -- "
                    "the cheapest signal of feature creep the harness has. Name it after what "
                    "it verifies, or record it in harness/config/traceability-exemptions.yaml "
                    "with a reason and an owner." % (c["name"][:70],))

    # ---- hand-authored coverage notes -------------------------------------
    #
    # Read OUTSIDE the write guard on purpose. The generated matrix maps
    # US-*/NFR-* only, has no notion of PARTIAL coverage, and does not track
    # findings (SF-*/SEC-*) at all, so a green suite reads as full coverage of
    # behaviour the tests may structurally be unable to observe. The notes are
    # where that gap is stated -- so their ABSENCE is a finding about the
    # artifact set, not a detail of document generation.
    #
    # The first version of this check lived inside `if not args.no_write:`,
    # which meant the phase-11 scorecard -- which invokes this as
    # `check-traceability.sh --no-write --quiet` -- could never see the warning.
    # A warning the release gate cannot reach is a declaration nothing reads.
    notes_path = os.path.join(d, "08-coverage-notes.md")
    notes = None
    if os.path.exists(notes_path):
        try:
            with open(notes_path, "r", encoding="utf-8") as fh:
                notes = fh.read().strip()
        except Exception as exc:
            warns.append("08-coverage-notes.md exists but could not be read (%s); "
                         "the generated table stands alone and may overstate coverage." % exc)
    else:
        warns.append("no 08-coverage-notes.md alongside the matrix. The table maps US-*/NFR-* "
                     "only and cannot express partial coverage or findings, so it may read as "
                     "fuller than it is. Add one if any test cannot observe what it is named for.")

    # ---- write the matrix -------------------------------------------------
    if not args.no_write:
        lines = ["# Traceability Matrix", "",
                 "Generated by `harness/bin/check-traceability.sh` from real test-runner output.",
                 "Do not hand-edit: it is regenerated on every phase-8 validation.", "",
                 "- **Test output:** `%s` (%d file(s), %d case(s))"
                 % (junit_glob.replace(root + "/", ""), len(xmls), len(cases)), "",
                 "| BRD goal | PRD story | Task | Test | Level | Result |",
                 "|---|---|---|---|---|---|"]
        for sid in sorted(stories):
            g = stories[sid].get("goal") or "—"
            tk = ", ".join(story_tasks.get(sid) or []) or "—"
            tests = story_tests.get(sid, [])
            if not tests and sid in tex["untested-story"]:
                lines.append("| %s | %s | %s | — | — | **EXEMPT** (untested-story) |" % (g, sid, tk))
                continue
            if not tests:
                lines.append("| %s | %s | %s | — | — | **NO TEST** |" % (g, sid, tk))
                continue
            for t in tests:
                nm = (t["name"] or "?")[:70]
                res = {"passed": "pass", "failed": "**FAIL**",
                       "error": "**ERROR**", "skipped": "_skipped_"}[t["status"]]
                lines.append("| %s | %s | %s | `%s` | %s | %s |"
                             % (g, sid, tk, nm, level_of.get(t["artifact"], "?"), res))

        # The column the v0.4 matrix could not express. "17/17" said nothing
        # about whether the tests could SEE what they were named for.
        lines += ["", "## Coverage", "",
                  "`FULL` every criterion has a passing test at a level that can observe it.",
                  "`PARTIAL` something is structurally invisible to the tests that pass.", "",
                  "| PRD story | Coverage | Basis |", "|---|---|---|"]
        for sid in sorted(stories):
            v, why = coverage.get(sid, ("NONE", "not evaluated"))
            lines.append("| %s | %s | %s |"
                         % (sid, v if v == "FULL" else "**%s**" % v, why.replace("|", "\\|")))
        if manifest is not None:
            lines += ["", "### Stripped by the test build", "",
                      "Read from `test-results/strip-manifest.txt`, which the test build "
                      "generates from the real source.", ""]
            for x in (manifest.get("dropped") or []):
                lines.append("- dropped: `%s`" % x)
            for x in (manifest.get("absent") or []):
                lines.append("- binding ABSENT from the compiled binary: `%s`" % x)
            if not (manifest.get("dropped") or manifest.get("absent")):
                lines.append("- the manifest records no exclusions")
        uncovered = [g for g in goals if not any(g in (stories[s].get("goal") or "") for s in stories)]
        if uncovered:
            lines += ["", "**BRD goals with no story:** " + ", ".join(sorted(uncovered))]
        lines += ["", "## Summary", "",
                  "- stories: %d" % len(stories),
                  "- coverage: %d FULL, %d PARTIAL, %d NONE"
                  % (sum(1 for v, _ in coverage.values() if v == "FULL"),
                     sum(1 for v, _ in coverage.values() if v == "PARTIAL"),
                     sum(1 for v, _ in coverage.values() if v == "NONE")),
                  "- stories with >=1 passing test: %d"
                  % sum(1 for s in stories if any(t["status"] == "passed" for t in story_tests.get(s, []))),
                  "- test cases parsed: %d" % len(cases), ""]
        # Hand-authored coverage notes, appended verbatim.
        #
        # This file is regenerated with mode "w" on every phase-8 validation --
        # including the one `gate.sh approve` runs -- so anything a human adds to
        # it is destroyed by the act of approving the phase. The generated table
        # also maps US-*/NFR-* only, has no notion of PARTIAL coverage, and does
        # not track findings (SF-*/SEC-*) at all, so a green suite reads as full
        # coverage of behaviour the tests may structurally be unable to observe.
        #
        # Rather than merge into generated output (fragile) or teach this checker
        # a coverage taxonomy (out of its scope), read an optional sibling the
        # checker never writes. Generated content stays generated; authored
        # content stays authored; the reader gets one document.
        # `notes` was read above, outside the write guard, so the missing-notes
        # warning reaches --no-write callers. Only the APPEND belongs here.
        if notes:
            lines += ["", "---", "",
                      "<!-- appended verbatim from 08-coverage-notes.md; edit that file, not this one -->",
                      "", notes, ""]
        # A validator must not become a write primitive. --dir could otherwise
        # be pointed at a protected directory to create files there (bypass N13).
        out_path = os.path.abspath(os.path.join(d, "08-traceability.md"))
        governed = os.path.abspath(os.path.join(root, groot)) if groot else os.path.abspath(root)
        if not (out_path == governed or out_path.startswith(governed + os.sep)):
            print("check-traceability: refusing to write %s -- outside the governed root %s. "
                  "Use --no-write, or point --dir inside the product tree."
                  % (out_path, governed), file=sys.stderr)
            return 2
        os.makedirs(d, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    if not args.quiet:
        print("check-traceability: %s" % d)
        print("  test output: %s -> %d file(s), %d case(s)" % (junit_glob, len(xmls), len(cases)))
        for n in info:
            print("  note  %s" % n)

    # F57. `--quiet` suppresses ROUTINE DETAIL, not warnings. This loop used to
    # sit inside the guard above, and the phase-11 scorecard invokes this check
    # as `--no-write --quiet`, so it never saw one. v0.5 moved the coverage-notes
    # READ out of the `--no-write` guard for exactly this reason and left the
    # PRINT behind the other flag named in the same comment; measured on the
    # gate's own command line, the result was exit 0 and ZERO BYTES of output.
    #
    # Position is unchanged in non-quiet mode -- after `note`, before `FAIL` --
    # so no existing reader moves. `errs` deliberately stay inside the guard:
    # they already reach every caller through the exit code, which is the
    # channel a warn has never had.
    for w in warns:
        print("  WARN  %s" % w)

    if not args.quiet:
        for e in errs:
            print("  FAIL  %s" % e)
        nfull = sum(1 for v, _ in coverage.values() if v == "FULL")
        npart = sum(1 for v, _ in coverage.values() if v == "PARTIAL")
        print("  coverage: %d FULL, %d PARTIAL, %d NONE"
              % (nfull, npart, len(coverage) - nfull - npart))
        for sid in sorted(coverage):
            if coverage[sid][0] != "FULL":
                print("  %-7s %s -- %s" % (coverage[sid][0], sid, coverage[sid][1]))
        if not errs:
            print("  PASS  all %d PRD story/stories have at least one passing test at a level "
                  "that can observe it." % len(stories))
        if not args.no_write:
            print("  wrote %s/08-traceability.md" % d)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
