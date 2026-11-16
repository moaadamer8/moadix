#!/usr/bin/python3
"""0.7.0 suite (docs/critic-convergence-design.md, approved with rulings Q1-Q6 and additions 1-4).

    /usr/bin/python3 tests/inc8/run.py

Fixtures only: throwaway repos under $TMPDIR, the stub checker, no network. Every rule has a
passing control and a planted violation that must fail.

  catalogue    a depth block per phase; the corrections of Q1 (SEC-n, P6, known issues, no-match rule)
  hard rules   every carry rule, each with a planted violation (Q1c's known-issue rule included)
  convergence  three critic runs on phase 0: fixed?, ruled, carried, waived, late, regression; a
               same_as claim the gate refuses; a waiver that lapses when its text changes; the carry
               recorded on APPROVE 0, required in phase 2's coverage, a "decided too late" MAJOR, and
               closed by APPROVE 2
  uncarry      UNCARRY of a GC id (counts as MAJOR) and of a CARRY id (readdressed), with a code
  proceed      Q5: carries stay open after PROCEED-PAST of their target, block the release, and
               close by WAIVE per item with the carry's text; a privacy carry cannot be waived
  scorecard    Addition 2: a PROCEED-PAST phase is accepted and listed; an open carry blocks
  freshness    Addition 1: an unrelated commit keeps a verifier's result; a one-byte change to a
               phase document makes it stale; the roles tied to HEAD stay tied
  standing     Addition 3: standing instructions adopted, shown at session start, never a gate rule
  migration    Q3: a pre-0.7.0 topic waiver covers only findings on text that existed when recorded
"""
import base64
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

E = fixtures.Env("v8").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import contract, critic, opcmd, pathmap, state, verify  # noqa: E402
import contract_fixture  # noqa: E402

RESULTS = []
T0 = time.time()
GIT = "/usr/bin/git"
FIX = os.path.join(REPO, "tests", "fixtures", "product", "sdlc")
FIX_BRD = open(os.path.join(FIX, "00-brd.md")).read()
RES = ("# Research\n\n## Competitors\n\n- Simplenote syncs notes across devices ([site](https://simplenote.com/), "
       "retrieved 2026-11-02)\n- Standard Notes encrypts notes end to end [^sn]\n\n## Legal\n\n- No personal data beyond "
       "an e-mail address ([GDPR](https://gdpr-info.eu/art-4-gdpr/), retrieved 2026-11-03)\n\n"
       "[^sn]: https://standardnotes.com/ retrieved 2026-11-02\n")


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


def write(p, files):
    for rel, text in files.items():
        full = os.path.join(p, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


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


def finding(p, label, tid, sev, cid="C1", **extra):
    rel, n, text = cov_line(p, label, tid)
    f = {"id": cid, "topic": tid, "severity": sev, "quote": text[2:60], "citation": "%s:%d" % (rel, n),
         "fix": "cover %s in the document" % tid}
    f.update(extra)
    return f


def set_cov(p, label, tid, new_rest):
    rel = "sdlc/%s/COVERAGE.md" % label
    lines = open(os.path.join(p, rel)).read().splitlines()
    lines = [("- %s: %s" % (tid, new_rest)) if ln.startswith("- %s:" % tid) else ln for ln in lines]
    write(p, {rel: "\n".join(lines) + "\n"})


def cur(p):
    st, probs = state.current_state(p)
    return st


def run_of(p, label):
    _ev, run, _sch = verify.current_critic(p, cur(p), label)
    return run or {}


def gc_of(p, label, cid):
    return run_of(p, label).get("map", {}).get(cid, "GC-unknown-0")


def waive(p, wid, reason="accepted by the operator for this fixture"):
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    return E.prompt(p, "WAIVE %s owner=moad scope=fixture expiry=%s reason=%s %s" % (wid, exp, reason, E.fresh()))


def launch(p):
    rc, out, err = E.hook("pretool", {"hook_event_name": "PreToolUse", "session_id": "c8", "cwd": p,
                                      "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "moadix:gap-critic", "prompt": "x",
                                                     "description": "x"}})
    return ((out.get("hookSpecificOutput") or {}).get("updatedInput") or {}).get("prompt", "")


def to_phase1(p):
    write(p, {"sdlc/01-research.md": RES + "\n" + open(os.path.join(FIX, "01-research.md")).read().split("\n", 1)[1]})
    E.commit(p, "research")
    contract_files(p, "1")
    contract_fixture.seed_links(p, {"current_phase": "1", "feature": None})
    contract_fixture.critic(E, p, "1")
    return approve(p, "1")


def prd(p):
    for fn in sorted(os.listdir(FIX)):
        if fn.startswith("02-"):
            shutil.copy(os.path.join(FIX, fn), os.path.join(p, "sdlc", fn))
    E.commit(p, "prd")


# ------------------------------------------------------------------ catalogue
def test_catalogue():
    G = "catalogue"
    cat = contract.catalogue()
    labels = [lab for _i, lab, _n, _g in pathmap.PHASES] + ["B"]
    missing = [lab for lab in labels if contract.gated(lab) and contract.topics(lab) and
               not (cat["phases"][lab].get("depth") or {}).get("decides")]
    ids = [r["id"] for lab in cat["phases"] for k in ("decides", "defers")
           for r in (cat["phases"][lab].get("depth") or {}).get(k) or []]
    record(G, "every gated phase has a depth block (decides, defers); rule ids are unique",
           not missing and len(ids) == len(set(ids)), (missing, [i for i in ids if ids.count(i) > 1]))
    bad = []
    for lab in cat["phases"]:
        for r in critic.depth(lab)["defers"]:
            st = {"mode": "onboarding" if lab == "B" else "greenfield", "feature": None}
            if r["to"] != "feature" and not (critic.order(st, r["to"]) or 0) > (critic.order(st, lab) or 0):
                bad.append((lab, r["id"], r["to"]))
    record(G, "every defers rule names a later phase (or, for B, the next feature cycle)", not bad, bad)
    d4 = {r["id"]: r["what"] for r in critic.depth("4")["decides"]}
    record(G, "Q1a: D4.4 names the SEC-n security requirements (SR- is shared resources)",
           "SEC-n" in d4.get("D4.4", "") and "SR-n" not in json.dumps(critic.depth("4")), d4.get("D4.4"))
    d2 = {r["id"]: r["what"] for r in critic.depth("2")["decides"]}
    x2 = {r["id"]: r["what"] for r in critic.depth("2")["defers"]}
    record(G, "Q1b: phase 2 decides business validation (P6, what counts as valid); X2.3 defers only its encoding "
              "(formats, patterns, error codes) to 5",
           "P6" in d2.get("D2.6", "") and "what counts as valid" in d2.get("D2.6", "") and
           "never what counts as valid" in x2.get("X2.3", "") and "error codes" in x2.get("X2.3", "") and
           next(r for r in critic.depth("2")["defers"] if r["id"] == "X2.3")["to"] == "5", (d2, x2))
    ki = [r for lab in ("10a", "10b", "10c") for r in critic.depth(lab)["defers"]]
    record(G, "Q1c: 10a/10b/10c defer only known issues, to 11", ki and all(r.get("known_issue") and r["to"] == "11"
                                                                           for r in ki), ki)
    p = product("cat")
    contract_files(p, "0")
    prompt = launch(p)
    record(G, "Q1d: the brief says a gap matching no defers rule is judged at the phase exactly as before, and lists "
              "the depth, earlier runs and carries sections",
           "A gap that matches no defers rule is judged at this phase exactly as before" in prompt and
           "## Depth of phase 0" in prompt and "## Earlier runs on this phase" in prompt and
           "## Carried into this phase" in prompt and "X0.1" in prompt and "D0.3" in prompt, short(prompt[-800:]))
    doc = open(os.path.join(REPO, "commands", "coverage.md")).read()
    record(G, "/moadix:coverage (generated) explains depth, carries, GC ids, UNCARRY and the no-match rule",
           doc == contract.coverage_doc() and "judged at the current phase exactly as before" in doc and
           "UNCARRY" in doc and "GC-<phase>-<n>" in doc and "Defers: X0.1" in doc, "")


# ------------------------------------------------------------------ hard rules
def st_of(statuses=None, mode="greenfield", current="0"):
    table = pathmap.BASELINE if mode == "onboarding" else pathmap.PHASES
    phases = [{"id": pid, "label": lab, "name": n, "status": (statuses or {}).get(lab, "draft")}
              for pid, lab, n, _g in table]
    return {"mode": mode, "feature": None, "phases": phases, "product_phases": phases, "current_phase": current,
            "waivers": []}


def test_hard_rules():
    G = "hard rules"
    root = tempfile.mkdtemp(prefix="prd-", dir=E.base)
    git(root, "init", "-q")
    write(root, {"sdlc/02-prd.md": "# PRD\n\n### US-001 — Save a note\n\n- **Priority:** must\n- **AC-1:** When x, "
                                   "the system shall y.\n\n### US-002 — Tag a note\n\n- **Priority:** should\n"
                                   "- **AC-3:** When a, the system shall b.\n"})
    st = st_of()
    base = {"id": "C1", "topic": "B7", "severity": "CARRY", "quote": "the order list shows recent orders first",
            "citation": "sdlc/00-brd.md:3", "fix": "state the sort order", "defer_rule": "X0.1", "to": "2",
            "class": "other"}

    def probs(f, label="0", s=None):
        return critic.carry_problems(root, s or st, label, f)

    record(G, "control: a field-list detail carried to phase 2 by X0.1 (class other) -> may carry", probs(base) == [],
           probs(base))
    cases = [
        ("a rule that is not a defers rule of the phase", dict(defer_rule="X1.1"), "not a defers rule of phase 0"),
        ("a target other than the rule's", dict(to="3"), "X0.1 carries to phase 2"),
        ("a class outside the list", dict(**{"class": "cost"}), "is not one of"),
        ("a quote touching a decides rule (D0.3 money flow: refund policy)",
         dict(quote="the refund policy for damaged items"), "touches D0.3"),
        ("a quote touching the phase's BLOCKER rule (D0.B legal regime)", dict(quote="which legal regime applies"),
         "touches D0.B"),
        ("security terms classed `other`", dict(quote="the order list order", fix="add a rate limit on login"),
         "class it security"),
    ]
    for name, over, why in cases:
        f = dict(base, **over)
        record(G, "planted: %s -> refused" % name, any(why in x for x in probs(f)), probs(f))
    closed = st_of({"0": "draft", "1": "APPROVED", "2": "APPROVED"}, current="0")
    record(G, "planted: a target phase already closed -> refused",
           any("already closed" in x for x in probs(base, s=closed)), probs(base, s=closed))
    f8 = dict(base, topic="T1", defer_rule="X8.1", to="10a", quote="exploratory checks of the checkout",
              fix="explore the login screen for authorization gaps", **{"class": "security"})
    record(G, "planted: a security carry past phase 9 (phase 8 -> 10a) -> refused",
           any("never carried past phase 9" in x for x in probs(f8, "8")), probs(f8, "8"))
    f4 = dict(base, topic="TH1", defer_rule="X4.3", to="9", quote="how the token check is verified",
              fix="verify the session token check", **{"class": "security"})
    record(G, "control: a security carry from phase 4 to phase 9 -> may carry", probs(f4, "4") == [], probs(f4, "4"))
    ki = dict(base, topic="LV1", defer_rule="X10a.1", to="11", quote="the tag chip wraps on narrow screens",
              fix="list it as a known issue", ac="US-002/AC-3")
    record(G, "Q1c control: a known issue on a non-P1 AC (US-002/AC-3, should) -> may carry", probs(ki, "10a") == [],
           probs(ki, "10a"))
    for name, over, why in (
            ("a known issue breaking a P1 AC (US-001/AC-1, must)", dict(ac="US-001/AC-1"), "breaks P1"),
            ("a known issue naming no AC", dict(ac=""), "names the acceptance criterion"),
            ("a privacy defect as a known issue", dict(ac="none", **{"class": "privacy"}), "cannot be a known issue"),
            ("a tenant-isolation defect as a known issue", dict(ac="none", **{"class": "tenant-isolation"}),
             "cannot be a known issue")):
        f = dict(ki, **over)
        record(G, "Q1c planted: %s -> refused" % name, any(why in x for x in probs(f, "10a")), probs(f, "10a"))
    fb = dict(base, topic="BL1", defer_rule="XB.1", to="feature", quote="a planned export to CSV")
    record(G, "control: an onboarded baseline carries a to-be item to the next feature cycle",
           probs(fb, "B", st_of(mode="onboarding", current="B")) == [], probs(fb, "B", st_of(mode="onboarding")))


# ------------------------------------------------------------------ convergence
def test_convergence():
    G = "convergence"
    p = product("conv")
    contract_files(p, "0")
    # run 1
    carry = finding(p, "0", "B7", "CARRY", "C4", defer_rule="X0.1", to="2", **{"class": "other"})
    contract_fixture.critic(E, p, "0", findings=[finding(p, "0", "B9", "MAJOR", "C1"),
                                                 finding(p, "0", "B12", "MAJOR", "C2"),
                                                 finding(p, "0", "B13", "MAJOR", "C3"), carry])
    rv, ctx = approve(p, "0")
    m1, m2, m3, c1 = (gc_of(p, "0", c) for c in ("C1", "C2", "C3", "C4"))
    record(G, "run 1: every finding gets a stable id (GC-0-n); the MAJORs block APPROVE 0 and name the GC id to "
              "waive; the CARRY does not block",
           all(re.match(r"^GC-0-\d+$", x) for x in (m1, m2, m3, c1)) and len({m1, m2, m3, c1}) == 4 and
           "NOT recorded" in ctx and "WAIVE gap-critic.%s" % m1 in ctx and c1 not in ctx.split("Findings:")[-1],
           short(ctx, 500))
    # between runs: waive m3 (while the run-1 evidence is current), then fix m1 (its text changes) and
    # rule on m2 in the discovery log
    ctx = waive(p, "gap-critic." + m3, "deferred by the operator")
    body, pl = E.payload(p, len(E.ledger(p)))
    fp = (pl.get("fingerprints") or {}).get("gap-critic." + m3) or {}
    set_cov(p, "0", "B9", "N/A: notifications are out of this fixture product entirely, so the BRD names no channel")
    write(p, {"sdlc/0/DISCOVERY.md": "# Discovery\n\n## Q-1: How long is data kept?\n- A: one year\n- B: until "
                                     "deleted\nRecommendation: B, the product keeps nothing it does not need\n"
                                     "Chosen: B\nRules: %s\n" % m2})
    E.commit(p, "fix run 1")
    stale = waive(p, "gap-critic." + m1, "too late")
    record(G, "a waiver needs current evidence: after a commit that changed the documents, WAIVE is refused until "
              "the critic runs again", "NOT recorded" in stale and "no current evidence" in stale, short(stale))
    record(G, "WAIVE gap-critic.<GC id> records the finding's fingerprint (topic, path, section, text sha256)",
           "recorded" in ctx and fp.get("topic") == "B13" and fp.get("path") == "sdlc/0/COVERAGE.md" and
           len(fp.get("text_sha") or "") == 64, short(ctx) + " " + short(fp))
    prompt = launch(p)
    earlier = prompt.split("## Earlier runs on this phase")[1].split("\n## ")[0]

    def disp(g):
        m = re.search(r"^- %s \[([^\]]+)\]" % re.escape(g), earlier, re.M)
        return m.group(1) if m else None
    record(G, "run 2's brief lists every earlier finding with the gate's disposition: fixed?, ruled, waived, carried",
           (disp(m1), disp(m2), disp(m3), disp(c1)) == ("fixed?", "ruled", "waived", "carried"),
           (disp(m1), disp(m2), disp(m3), disp(c1), short(earlier, 600)))
    # run 2: m3 raised again (waived), the carry again, a regression of m2, a late finding on unchanged text
    contract_fixture.critic(E, p, "0", findings=[
        finding(p, "0", "B13", "MAJOR", "C1", same_as=m3),
        finding(p, "0", "B7", "CARRY", "C2", same_as=c1, defer_rule="X0.1", to="2", **{"class": "other"}),
        finding(p, "0", "B12", "MAJOR", "C3", regression_of=m2),
        finding(p, "0", "B14", "MAJOR", "C4")])
    rv, ctx = approve(p, "0")
    run = run_of(p, "0")
    late = run.get("map", {}).get("C4")
    record(G, "run 2: same_as keeps the ids; the waived MAJOR stays waived; the regression of the ruled finding "
              "blocks; the new finding on unchanged text is late and blocks at its severity (never downgraded)",
           run["map"].get("C1") == m3 and run["map"].get("C2") == c1 and run["map"].get("C3") == m2 and
           late in run.get("late", []) and m2 in run.get("regressions", []) and "NOT recorded" in ctx and
           "[%s] [regression]" % m2 in ctx and "[%s] [late]" % late in ctx and "[%s]" % m3 not in ctx,
           short(ctx, 700) + " " + short(run))
    # a same_as the gate refuses
    contract_fixture.critic(E, p, "0", findings=[finding(p, "0", "B14", "MAJOR", "C1", same_as=m3)])
    rv, ctx = approve(p, "0")
    record(G, "planted: same_as naming a finding on another topic -> the evidence fails",
           "NOT recorded" in ctx and "was on topic B13" in ctx, short(ctx, 400))
    # the waiver lapses when the cited text changes
    set_cov(p, "0", "B13", "N/A: this fixture has no competitors worth naming, reworded after the waiver")
    E.commit(p, "reword B13")
    ctx = E.prompt(p, "STATUS")
    record(G, "a waiver lapses when its cited text changes (STATUS names it)",
           "Lapsed waivers" in ctx and "gap-critic.%s" % m3 in ctx.split("Lapsed waivers")[-1], short(ctx[-600:]))
    contract_fixture.critic(E, p, "0", findings=[finding(p, "0", "B13", "MAJOR", "C1", same_as=m3)])
    rv, ctx = approve(p, "0")
    record(G, "after the lapse, the same finding on the new text blocks again (the waiver no longer covers it)",
           "NOT recorded" in ctx and "[%s]" % m3 in ctx, short(ctx, 400))
    # final run: only the carry -> APPROVE 0 records it
    contract_fixture.critic(E, p, "0", findings=[
        finding(p, "0", "B7", "CARRY", "C1", same_as=c1, defer_rule="X0.1", to="2", **{"class": "other"})])
    rv, ctx = approve(p, "0")
    body, pl = E.payload(p, len(E.ledger(p)))
    cs = pl.get("carries") or []
    record(G, "APPROVE 0 records the carry in its ledger line (CARRY-0-1 -> phase 2, X0.1, with its quote)",
           "recorded" in ctx and "NOT" not in ctx and cs and cs[0]["id"] == "CARRY-0-1" and cs[0]["to"] == "2" and
           cs[0]["gc"] == c1 and cs[0]["quote"], short(ctx, 400) + " " + short(cs))
    rv, ctx = to_phase1(p)
    record(G, "phase 1 approves with the carry still addressed to phase 2", "recorded" in ctx and "NOT" not in ctx,
           short(ctx, 300))
    prd(p)
    st = cur(p)
    record(G, "phase 2's skeleton pre-lists the carried item", "- CARRY-0-1: TODO" in contract.skeleton(p, st, "2"), "")
    contract_files(p, "2")
    f, _m, _i = contract.coverage_lint(p, cur(p), "2")
    record(G, "a carry never settled: coverage-lint of phase 2 fails, naming it", any("CARRY-0-1" in x and "missing" in x
                                                                                    for x in f), f)
    with open(os.path.join(p, "sdlc", "2", "COVERAGE.md"), "a") as fh:
        fh.write("- CARRY-0-1: N/A: the PRD's story US-001 fixes the list order, so nothing is left to settle\n")
    contract_fixture.commit(p, "settle the carry")
    f, _m, _i = contract.coverage_lint(p, cur(p), "2")
    record(G, "settled in COVERAGE.md -> coverage-lint of phase 2 passes the carry", not any("CARRY" in x for x in f), f)
    d, why, prompt = contract_fixture.critic(E, p, "2", findings=[{
        "id": "C1", "topic": "CARRY-0-1", "severity": "MAJOR", "quote": "CARRY-0-1: N/A: the PRD's story US-001",
        "citation": "sdlc/2/COVERAGE.md:%d" % len(open(os.path.join(p, "sdlc", "2", "COVERAGE.md")).read().splitlines()),
        "fix": "decided too late: the sort order is a release-scope decision (D0.6) for phase 0"}])
    rv, ctx = approve(p, "2")
    record(G, "the target phase's critic lists the carry; a \"decided too late\" MAJOR on it blocks APPROVE 2",
           "## Carried into this phase" in (prompt or "") and "CARRY-0-1 (from phase 0" in (prompt or "") and
           "NOT recorded" in ctx and "MAJOR C1 (CARRY-0-1)" in ctx, short(ctx, 400))
    contract_fixture.critic(E, p, "2")
    rv, ctx = approve(p, "2")
    body, pl = E.payload(p, len(E.ledger(p)))
    c = critic.carries(cur(p)).get("CARRY-0-1") or {}
    record(G, "settled and raised nothing on -> APPROVE 2 closes it (carries_closed, register status closed)",
           "recorded" in ctx and pl.get("carries_closed") == ["CARRY-0-1"] and c.get("status") == "closed",
           short(ctx, 300) + " " + short(c))


# ------------------------------------------------------------------ uncarry, proceed past, waive a carry
def test_uncarry_and_proceed():
    G = "uncarry/Q5"
    p = product("unc")
    contract_files(p, "0")
    a = finding(p, "0", "B7", "CARRY", "C1", defer_rule="X0.1", to="2", **{"class": "other"})
    b = finding(p, "0", "B8", "CARRY", "C2", defer_rule="X0.1", to="2", **{"class": "other"})
    pv = finding(p, "0", "B17", "CARRY", "C3", defer_rule="X0.3", to="5", **{"class": "privacy"})
    pv["quote"] = cov_line(p, "0", "B17")[2][2:60]
    contract_fixture.critic(E, p, "0", findings=[a, b, pv])
    ga = gc_of(p, "0", "C1")
    ctx = E.prompt(p, "UNCARRY %s %s" % (ga, E.fresh()))
    record(G, "UNCARRY <GC id> with a code -> recorded; it now counts as a MAJOR", "recorded" in ctx and "MAJOR" in ctx,
           short(ctx))
    rv, ctx = approve(p, "0")
    record(G, "the uncarried finding blocks APPROVE 0 as a MAJOR", "NOT recorded" in ctx and "uncarried" in ctx,
           short(ctx, 400))
    ctx = E.prompt(p, "UNCARRY %s 123456" % ga)
    record(G, "UNCARRY without a valid code -> nothing recorded", "NOT recorded" in ctx, short(ctx))
    contract_fixture.critic(E, p, "0", findings=[dict(b, same_as=gc_of(p, "0", "C2")),
                                                 dict(pv, same_as=gc_of(p, "0", "C3"))])
    rv, ctx = approve(p, "0")
    body, pl = E.payload(p, len(E.ledger(p)))
    record(G, "APPROVE 0 records the two carries (CARRY-0-1 to 2, CARRY-0-2 privacy to 5)",
           "recorded" in ctx and [c["id"] for c in pl.get("carries") or []] == ["CARRY-0-1", "CARRY-0-2"],
           short(ctx, 300))
    ctx = E.prompt(p, "UNCARRY CARRY-0-2 %s" % E.fresh())
    st = cur(p)
    record(G, "UNCARRY <CARRY id> readdresses it to the current phase (1), whose coverage must settle it",
           "recorded" in ctx and critic.carries(st)["CARRY-0-2"]["to"] == "1" and
           [c for c, _x in critic.carries_in(st, "1", verify.active_waivers(st))] == ["CARRY-0-2"] and
           "- CARRY-0-2: TODO" in contract.skeleton(p, st, "1"), short(ctx))
    write(p, {"sdlc/01-research.md": RES + "\n" + open(os.path.join(FIX, "01-research.md")).read().split("\n", 1)[1]})
    E.commit(p, "research")
    contract_files(p, "1")
    with open(os.path.join(p, "sdlc", "1", "COVERAGE.md"), "a") as fh:
        fh.write("- CARRY-0-2: N/A: research found no personal data beyond an e-mail address, so retention is moot\n")
    contract_fixture.commit(p, "settle CARRY-0-2")
    contract_fixture.seed_links(p, {"current_phase": "1", "feature": None})
    contract_fixture.critic(E, p, "1")
    rv, ctx = approve(p, "1")
    record(G, "phase 1 settles the readdressed carry and approves", "recorded" in ctx and
           critic.carries(cur(p))["CARRY-0-2"]["status"] == "closed", short(ctx, 300))
    prd(p)
    contract_files(p, "2")  # without the CARRY-0-1 line: coverage-lint fails, a determinate failure
    contract_fixture.critic(E, p, "2")
    E.review_until_fresh(p, "2", contract=False)
    ctx = E.prompt(p, "PROCEED-PAST 2 the carried list order is accepted as is for now %s" % E.fresh())
    record(G, "Q5: PROCEED-PAST of the target phase -> recorded; the carry stays OPEN and is named as a release "
              "blocker", "recorded" in ctx and "stay OPEN" in ctx and "CARRY-0-1" in ctx, short(ctx, 500))
    ctx = E.prompt(p, "STATUS")
    record(G, "STATUS lists the open carry as a release blocker", "release blockers: CARRY-0-1" in ctx, short(ctx[-500:]))
    ctx = waive(p, "CARRY-0-1", "the list order is cosmetic and the operator accepts it")
    body, pl = E.payload(p, len(E.ledger(p)))
    cw = (pl.get("carries_waived") or {}).get("CARRY-0-1") or {}
    record(G, "Q5: WAIVE CARRY-0-1 with a reason closes it; the ledger line carries the carry's text",
           "recorded" in ctx and cw.get("quote") and cw.get("rule") == "X0.1" and
           not critic.overdue_carries(cur(p), verify.active_waivers(cur(p))), short(ctx) + " " + short(cw))


def test_protected_carry_waiver():
    G = "uncarry/Q5"
    p = product("prot")
    contract_files(p, "0")
    pv = finding(p, "0", "B7", "CARRY", "C1", defer_rule="X0.1", to="2", **{"class": "privacy"})
    contract_fixture.critic(E, p, "0", findings=[pv])
    rv, ctx = approve(p, "0")
    rv, ctx = to_phase1(p)
    prd(p)
    contract_files(p, "2")
    contract_fixture.critic(E, p, "2")
    E.review_until_fresh(p, "2", contract=False)
    ctx = E.prompt(p, "PROCEED-PAST 2 accepted by the operator for this fixture %s" % E.fresh())
    ctx = waive(p, "CARRY-0-1", "the operator wants it gone")
    record(G, "Q5: a privacy carry cannot be waived, even after its target phase was proceeded past",
           "NOT recorded" in ctx and "CANNOT be waived" in ctx, short(ctx, 300))
    ctx = waive(p, "CARRY-0-9", "no such carry")
    record(G, "WAIVE of an unknown carry id -> refused", "NOT recorded" in ctx and "not an open carried item" in ctx,
           short(ctx))


# ------------------------------------------------------------------ scorecard
def scorecard(doc):
    d = tempfile.mkdtemp(prefix="sc-", dir=E.base)
    git(d, "init", "-q")
    os.makedirs(os.path.join(d, "sdlc"))
    f = os.path.join(d, "pd.json")
    with open(f, "w") as fh:
        json.dump(doc, fh)
    r = subprocess.run([fixtures.PY, os.path.join(E.home, "gate", "v1", "build_scorecard.py"), "--no-write"], cwd=d,
                       env=E.env(MOADIX_PHASE_DOC=f, MOADIX_PRODUCT_ROOT=d), capture_output=True, text=True)
    return r.stdout + r.stderr


def test_scorecard():
    G = "scorecard"
    import hlib

    def doc(first, carries=()):
        phases = []
        for pid, lab, n, _g in pathmap.PHASES:
            s = "APPROVED" if lab not in ("11", "11b", "12") else "draft"
            phases.append({"id": pid, "label": lab, "name": n, "status": first if lab == "0" else s, "commit": "abc",
                           "note": "discovery-lint defect F-4" if first == "PROCEED-PAST" and lab == "0" else None})
        d = hlib.v1_phase_doc({"product": "p", "phases": phases, "waivers": []})
        if first == "PROCEED-PAST":
            d["phases"][0].update(proceeded_reason="discovery-lint defect F-4", proceeded_open_findings=[
                {"severity": "MAJOR", "id": "C2", "gc": "GC-0-7", "topic": "B6", "citation": "sdlc/00-brd.md:40"}])
        d["open_carries"] = list(carries)
        return d
    out = scorecard(doc("PROCEED-PAST"))
    record(G, "Addition 2: a phase closed by PROCEED-PAST is accepted (no 'not APPROVED', no predecessor blocker)",
           "not APPROVED: 0" not in out and "predecessor(s) 0" not in out, short(out[-800:]))
    record(G, "... and listed with its reason and every finding it passed that is still open",
           "PPST  phase 0 closed by PROCEED-PAST: discovery-lint defect F-4" in out and "GC-0-7" in out,
           short(out[-800:]))
    out2 = scorecard(doc("draft"))
    record(G, "control: a phase that is merely draft still blocks", "not APPROVED: 0" in out2, short(out2[-400:]))
    out3 = scorecard(doc("PROCEED-PAST", [{"id": "CARRY-0-1", "from": "0", "to": "2", "rule": "X0.1",
                                           "class": "other", "quote": "list order"}]))
    record(G, "Q5: an open carry past its target phase blocks the release",
           "carried item CARRY-0-1" in out3 and "BLOCK" in out3, short(out3[-600:]))
    st = {"phases": [{"label": "0", "status": "PROCEED-PAST", "note": "F-4"}], "waivers": [], "feature": None,
          "_entries": [{"seq": 9, "ts": "t", "action": "PROCEED-PAST 0 F-4",
                        "payload_b64": base64.b64encode(json.dumps({"phase": "0", "passed_findings": [
                            {"severity": "BLOCKER", "id": "C1", "gc": "GC-0-3", "topic": "B4",
                             "citation": "x:1"}]}).encode()).decode()}]}
    t = opcmd.proceeded_summary(st)
    record(G, "the APPROVE 11 summary lists the PROCEED-PAST phase, its reason and its still-open findings",
           "phase 0 (F-4)" in t and "GC-0-3" in t, t)


# ------------------------------------------------------------------ freshness
def test_freshness():
    G = "freshness"
    p = product("fresh")
    contract_files(p, "0")
    contract_fixture.critic(E, p, "0")
    rows = verify.check_phase(p, cur(p), "0")
    record(G, "control: the critic's result is current at its own commit", rows and rows[0][1] == "ok", rows)
    write(p, {"README.md": "an unrelated change\n"})
    E.commit(p, "readme")
    rows = verify.check_phase(p, cur(p), "0")
    record(G, "Addition 1: a commit that changes only an unrelated file keeps the result current",
           rows and rows[0][1] == "ok", rows)
    rv, ctx = approve(p, "0")
    record(G, "... and APPROVE 0 is recorded on it without relaunching the critic", "recorded" in ctx and "NOT" not in ctx,
           short(ctx, 300))
    q = product("fresh2")
    contract_files(q, "0")
    contract_fixture.critic(E, q, "0")
    brd = open(os.path.join(q, "sdlc", "00-brd.md")).read()
    write(q, {"sdlc/00-brd.md": brd.replace("note", "Note", 1)})
    E.commit(q, "one byte")
    rows = verify.check_phase(q, cur(q), "0")
    record(G, "Addition 1: a one-byte change to a phase document makes the result stale",
           rows and rows[0][1] == "stale" and "changed since" in rows[0][2][0], rows)
    tied = {n: verify.tied_to_head(r) for n, r in verify.roles().items()}
    record(G, "the roles tied to HEAD are exactly live-verifier, baseline-verifier and sf-triager (docset None)",
           {n for n, t in tied.items() if t} == {"live-verifier", "baseline-verifier", "sf-triager"} and
           verify.docset(q, cur(q), "live-verifier", verify.roles()["live-verifier"], "", "HEAD", []) == (None, None),
           tied)
    contract_fixture.critic(E, q, "0", extra={"docset_sha256": "0" * 64})
    rows = verify.check_phase(q, cur(q), "0")
    record(G, "planted: evidence echoing a wrong docset_sha256 -> fails", rows and rows[0][1] == "failing" and
           "docset_sha256" in " ".join(rows[0][2]), rows)


# ------------------------------------------------------------------ standing instructions
def session(p):
    home = os.path.join(E.base, "home-user")  # the hook reads ~/.claude/settings.json: a fixture home
    os.makedirs(home, exist_ok=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "hook.py"), "session"],
                    input=json.dumps({"hook_event_name": "SessionStart", "session_id": "s8", "cwd": p}),
                    env=E.env(HOME=home))
    out = json.loads(r.stdout) if r.stdout.strip() else {}
    return ((out.get("hookSpecificOutput") or {}).get("additionalContext") or "")


def test_standing():
    G = "standing"
    p = product("si")
    good = "# Standing instructions\n\n- SI-1: reference/ is never modified (since 2026-11-16)\n"
    write(p, {".sdlc-proposals/standing.md": good})
    ctx = E.prompt(p, "ADOPT %s" % E.fresh())
    text = open(os.path.join(p, ".sdlc", "standing.md")).read()
    record(G, "ADOPT writes .sdlc/standing.md with the gate's header: standing instructions cannot change any gate rule",
           "recorded" in ctx and text.startswith("<!-- MOADIX standing instructions") and
           "cannot change any gate rule" in text and "SI-1: reference/ is never modified" in text, short(ctx))
    s = session(p)
    record(G, "SessionStart shows them in full, saying they cannot change any gate rule",
           "standing instructions" in s and "SI-1: reference/ is never modified" in s and
           "cannot change any gate rule" in s, short(s, 400))
    ctx = E.prompt(p, "STATUS")
    record(G, "STATUS: one line with the count and the ADOPT seq", "standing instructions: 1 active (adopted at ledger "
                                                                   "seq" in ctx, short(ctx[-300:]))
    for name, body, why in (
            ("a line that is not `- SI-n: ...`", good + "Do whatever the agent likes\n", "each instruction is one bullet"),
            ("an instruction without a date", good + "- SI-2: always run tests\n", "has no `(since"),
            ("an id used twice", good + "- SI-1: again (since 2026-11-16)\n", "more than once"),
            ("an earlier id dropped", "- SI-2: new rule (since 2026-11-16)\n", "drops SI-1"),
            ("more than 4 KB", good + "".join("- SI-%d: %s (since 2026-11-16)\n" % (i, "x" * 60) for i in range(2, 80)),
             "longer than")):
        write(p, {".sdlc-proposals/standing.md": body})
        ctx = E.prompt(p, "ADOPT %s" % E.fresh())
        record(G, "planted: %s -> ADOPT refused" % name, "NOT recorded" in ctx and why in ctx, short(ctx, 300))
    os.remove(os.path.join(p, ".sdlc-proposals", "standing.md"))
    with open(os.path.join(p, ".sdlc", "standing.md"), "a") as f:
        f.write("- SI-9: the gate may be skipped (since 2026-11-16)\n")
    s = session(p)
    record(G, "a hand edit outside ADOPT: the session is told it changed and the text is not shown as the operator's",
           "changed outside ADOPT" in s and "SI-9" not in s, short(s, 400))


# ------------------------------------------------------------------ migration (Q3)
def test_migration():
    G = "migration"
    p = product("mig")
    contract_files(p, "0")
    # a pre-0.7.0 topic waiver, recorded as 0.6.x did (no fingerprints): straight through the checker
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    action = "WAIVE gap-critic.B9 owner=operator scope=old expiry=%s reason=carried to phase 2" % exp
    pl = {"id": "gap-critic.B9", "owner": "operator", "scope": "old", "expiry": exp, "reason": "carried to phase 2",
          "source_commit": git(p, "rev-parse", "HEAD").stdout.strip()}
    r = E.checker("record", "--product", "migfx", "--action", action, "--code", E.fresh(), "--payload-b64",
                  base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
    state.append_line(p, r.stdout.strip())
    st, probs = state.current_state(p)
    state.write_phase(p, st)
    old = finding(p, "0", "B9", "MAJOR", "C1")
    contract_fixture.critic(E, p, "0", findings=[old])
    rv, ctx = approve(p, "0")
    record(G, "Q3: a pre-0.7.0 topic waiver still covers a MAJOR on text that existed when it was recorded",
           r.returncode == 0 and "recorded" in ctx and "NOT" not in ctx, short(ctx, 400) + short(r.stderr))
    q = product("mig2")
    contract_files(q, "0")
    pl["source_commit"] = git(q, "rev-parse", "HEAD").stdout.strip()
    r = E.checker("record", "--product", "mig2fx", "--action", action, "--code", E.fresh(), "--payload-b64",
                  base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
    state.append_line(q, r.stdout.strip())
    st, probs = state.current_state(q)
    state.write_phase(q, st)
    set_cov(q, "0", "B9", "N/A: notification channels were written after the waiver was recorded")
    E.commit(q, "new text")
    contract_fixture.critic(E, q, "0", findings=[finding(q, "0", "B9", "MAJOR", "C1")])
    rv, ctx = approve(q, "0")
    record(G, "Q3: ... but not a new finding on text written after it (it cannot hide a new finding)",
           "NOT recorded" in ctx and "MAJOR C1 (B9)" in ctx, short(ctx, 400))


def main():
    try:
        for t in (test_catalogue, test_hard_rules, test_convergence, test_uncarry_and_proceed,
                  test_protected_carry_waiver, test_scorecard, test_freshness, test_standing, test_migration):
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
