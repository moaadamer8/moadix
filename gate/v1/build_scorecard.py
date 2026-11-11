#!/usr/bin/env python3
"""build-scorecard — Phase 11: the release scorecard.

Aggregates every gate into one page and returns TWO verdicts. It is both the
generator of `sdlc/11-scorecard.md` and the phase-11 validator: it exits non-zero
when the release is not fit to ship, so "the scorecard was produced" and "the
scorecard passed" cannot be confused.

  verification  COMPLETE | INCOMPLETE   is what we know, known?
  release       CLEARED  | BLOCKED      given what we know, may this ship?

It returned ONE verdict until v0.9. That single slot carried both claims, and
the GREENFIELD baseline run is what showed the cost: phase 9's honest answer was
"verification complete, and the answer is no", and the only word available was
BLOCKED -- so the first half existed nowhere a reader could see it.

THE HARD RULE
  For a product not flagged `toy: true`, ANY phase with
  `approval_mode: noninteractive` fails the release. **There is no waiver for
  this.** Every other failure here can be waived by a named human with a reason,
  because every other failure is a judgement about the product. This one is a
  judgement about whether a human was in the loop at all, and a waiver for it
  would be a human waiving the requirement that a human was involved.

Also fails on:
  - any SEC-ID without evidence (or without a waiver)
  - any PRD story without a passing test
  - any PRD story without a 10a verdict
  - any open high-severity finding without a waiver
  - any cited evidence whose PROVENANCE is unknown, stale or mis-claimed
  - any APPROVED phase whose approval predates a change to what it verified

The last two are release-strict on purpose. During a phase, unknown provenance
only WARNs, so a product can adopt the mechanism incrementally and a new tree
can be bootstrapped. At the release gate it blocks: "we cannot tell what this
evidence describes" is not a basis for shipping (Constitution 4.5).

Every waiver that appears is printed with its reason, approver and date, so a
release signed off with known holes says so on its face.

Exit 0 = releasable · 1 = blocked · 2 = cannot evaluate. **2 dominates 1**:
verification INCOMPLETE reports 2 whatever the release verdict says, because a
determinate "no" would overstate what was established. See `exit_code`.
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import check_size_profile as _csp  # noqa: E402
import hlib  # noqa: E402


def strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return strip_comments(fh.read())


def ids_with_field(text, prefix, field_name):
    """{ID: field value} for '### PREFIX-n' blocks."""
    out, cur = {}, None
    if not text:
        return out
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+(%s-\d+)\b" % prefix, line.strip())
        if m:
            cur = m.group(1)
            out.setdefault(cur, None)
            continue
        if cur:
            v = re.match(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+)$" % re.escape(field_name), line, re.I)
            if v:
                out[cur] = v.group(1).strip()
                cur = None
    return out


def success_metrics(text):
    """[(SM-id, declared text)] from the BRD's Success Metrics section.

    The template declares each metric as ONE prose field --
    `- **SM-1:** {metric, baseline, target, when measured}` -- so baseline,
    target and measurement date are not separately parseable. They are rendered
    verbatim rather than split into columns the format does not support:
    inventing a `Baseline` column and filling it by guessing at prose would be
    the document asserting a structure it does not have (4.2).
    """
    out, cur = [], None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*[-*]\s*\*\*(SM-\d+):?\*\*\s*(.*)$", line)
        if m:
            cur = [m.group(1), m.group(2)]
            out.append(cur)
            continue
        if cur is None:
            continue
        # CONTINUATION. The template's metric is one prose field and real ones
        # wrap over several lines; taking only the first line truncated SM-1 at
        # "32 clients," and dropped the repeat count and the pass condition.
        # Exactly the v0.4 waiver-table finding -- a cell that loses the clause
        # bounding it -- so the join is deliberate, not incidental.
        if not line.strip() or re.match(r"^\s*([-*]\s|#)", line):
            cur = None
            continue
        cur[1] += " " + line.strip()
    return [(sid, re.sub(r"\s+", " ", txt).strip()) for sid, txt in out]


def days_until(iso_date):
    """Whole days from today to an ISO date, or None if unparseable."""
    try:
        import datetime
        y, m, d = (int(x) for x in iso_date.split("-"))
        return (datetime.date(y, m, d) - datetime.date.today()).days
    except Exception:
        return None


def run(cmd, root):
    try:
        p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 127, "could not run: %r" % (exc,)


# ---------- 4-and-2, step 1: a blocker is a record, not a string ----------
# A string cannot be classified, so nothing downstream can route it to an axis,
# group it, or decide whether it is RECOGNISED. Every later step depends on
# this one, and it is why 4-and-2 is a rewrite rather than a COLLAPSED-style
# widening: COLLAPSED added a token to a vocabulary; this changes what a
# blocker IS.
#
# STEP 1 IS A PURE REFACTOR. The verdict still reads `if not blockers`, and
# rendering still prints the text. Nothing in the assertion surface may move
# here -- anything that breaks at this step is a mis-transcription, not a
# design question.
#
# axis   VERIFICATION  is what we know, known?
#        RELEASE       given what we know, may this ship?
#
# Measured over the 25 sites, by AST rather than by grep (F32):
#   13 INSTRUMENT_ABSENT   could not be computed
#    5 PRODUCT_DEFECT      a verification result about the subject
#    3 INTEGRITY           the RECORD is not trustworthy
#    3 GATE_CHAIN          a subprocess exit code; ran-and-failed and
#                          could-not-run are indistinguishable (P48)
#    1 PROGRESSION
#
# Over half of every blocker in this file is "could not be computed" -- the
# two-axis split already present in the data, and already present in the PROSE
# of the strings ("unknown is not a basis for shipping") and nowhere in their
# type.
KINDS = ("PRODUCT_DEFECT", "INSTRUMENT_ABSENT", "INTEGRITY", "GATE_CHAIN",
         "PROGRESSION")


class B:
    """A blocker: its text, and the kind that text never carried.

    STEP 3 REMOVED THE `str` BASE CLASS. It was a migration shim so step 1
    could convert 26 sites without moving a single assertion, and **removing it
    is part of this step, not optional**: a compatibility shim that outlives
    its migration becomes permanent by default, and then nothing tells you
    which readers still depend on it. With the base gone, any reader that
    treated a blocker as a string fails loudly here rather than silently
    forever.

    STEP 3 ALSO REMOVED THE `axis` FIELD. Step 1 stored kind AND axis at every
    site; measured over all 26, axis turned out to be a strict function of
    kind -- five kinds, five (kind, axis) pairs, no kind mapping to two axes.
    Two sources for one fact is drift waiting to happen, so axis is DERIVED
    now (`axis_of`) and no longer declared.
    """
    __slots__ = ("text", "kind", "phase")

    def __init__(self, text, kind="PRODUCT_DEFECT", phase=None):
        self.text, self.kind, self.phase = str(text), kind, phase

    def __str__(self):
        return self.text

    def __repr__(self):
        return "B(%r, kind=%r)" % (self.text, self.kind)


# Which axis a kind speaks to. An unrecognised kind is deliberately ABSENT:
# `axis_of` returns None for it, and None counts on BOTH axes. That is the
# fail-closed default -- a gate that enumerates the failures it knows about and
# passes the ones it does not is P43 at the release gate.
AXIS_OF = {
    "INSTRUMENT_ABSENT": "VERIFICATION",   # could not be computed
    "GATE_CHAIN":        "VERIFICATION",   # an exit code; P48 says it cannot say which
    "PRODUCT_DEFECT":    "RELEASE",
    "INTEGRITY":         "RELEASE",
    "PROGRESSION":       "RELEASE",
}


def axis_of(b):
    """'VERIFICATION', 'RELEASE', or None for a kind nothing recognises."""
    return AXIS_OF.get(getattr(b, "kind", None))


# ---------- F30: the N/A axis had one slot for six different claims -------
# "Not applicable / suppressed" carried, undifferentiated:
#
#   not-applicable  the platform ruling makes this check irrelevant
#   suppressed      policy switched it off (the toy flag)
#   waived          someone accepted it, with an owner and an expiry
#   compromised     it happened and the RECORD of it is not trustworthy
#   unknown         it could not be computed
#   unmeasured      it is declared, and nothing measures it
#
# Rendering all six identically, under a heading that tells the reader the
# section is safe to skip, is how "phase 8 was approved from a DIRTY working
# tree: its recorded commit is a half-truth about what was actually approved"
# came to sit beside "there is no store release under a WEB ruling".
#
# This is the COLLAPSED remedy on the other axis: add the state rather than
# borrow one. It is deliberately RENDERING ONLY -- no line here moves the
# verdict, and B05 ("it never blocks on outcomes") is the control on that.
NA_KINDS = [
    ("not-applicable", "Not applicable",                        "N/A"),
    ("suppressed",     "Suppressed by policy",                  "SUPP"),
    ("waived",         "Waived",                                "WAIV"),
    ("compromised",    "Compromised -- recorded, not trusted",  "COMP"),
    ("unknown",        "Could not be computed",                 "UNKN"),
    ("unmeasured",     "Declared and not measured",             "UNMS"),
]
NA_TAG = {k: t for k, _h, t in NA_KINDS}


def registered_since(root, vid):
    """(sha, state) for the commit that first introduced this validator id.

    P59. A validator registered AFTER a phase was approved reads as absent from
    that phase's evidence, and item 2B fails closed on absence -- so registering
    one check invalidates every earlier approval at once. That pressure runs
    against registering checks, the behaviour this project most needs cheap.

    DERIVED, NOT DECLARED, and the distinction from F44 is deliberate:
      * F44 refused to derive WHICH PHASE depends on which config file: the only
        source was a heuristic scan of validator source, and the probe that
        tried counted `check-*` regardless of `kind` (F35). Deriving POLICY from
        a guess.
      * This derives a FACT -- when an id first appeared in registry.yaml --
        from git history, the authoritative record of exactly that. A declared
        `since:` could drift from the truth; git cannot drift from itself.

    UNKNOWN IS NEVER COERCED. `git log -S` needs full history, and a shallow
    clone or tarball export has none. An empty result there would read as
    "registered after every approval" and silently excuse every gap, so the
    caller keeps failing closed and says why.
    """
    try:
        ok, out = hlib._git(root, "log", "--reverse", "--format=%H", "-S",
                            "id: " + str(vid), "--", "harness/registry.yaml")
    except Exception:
        return None, "unknown"
    if not ok:
        return None, "unknown"
    lines = [l.strip() for l in (out or "").splitlines() if l.strip()]
    return (lines[0], "known") if lines else (None, "unknown")


def predates(root, sha, approval_sha):
    """True when `sha` is an ancestor of `approval_sha`. None when unknowable."""
    # provenance.UNKNOWN, not hlib.UNKNOWN -- the same invented attribute that
    # crashed P58. Imported HERE because this module imports provenance inside
    # functions, not at module scope: the first fix referenced it at module
    # level and raised NameError, which is the same mistake twice in one hour
    # and the reason this line is verified by running rather than by reading.
    import provenance as _prov
    if not sha or not approval_sha or approval_sha == _prov.UNKNOWN:
        return None
    try:
        ok, _out = hlib._git(root, "merge-base", "--is-ancestor", sha, approval_sha)
    except Exception:
        return None
    return bool(ok)


def recorded_validator_results(root, phase_doc, self_id="build-scorecard"):
    """(blockers, notes) from what each phase RECORDED about its validators.

    ITEM 2B. The release gate re-derives from four validators and a handful of
    artifacts; twenty-seven validators are registered. Progression was the only
    thing covering the rest, and it is a catch-all that says nothing about WHY.
    This consults the record instead.

    NOT re-running them. Eight of them observe a running system -- the app, a
    device, a browser walk, a built bundle -- and a result about a moment cannot
    be reproduced at release time. The gate's job is to read the record
    honestly, not to stage the moment again.

    FAILS CLOSED ON ABSENCE. A registered validator with no recorded result is
    INSTRUMENT_ABSENT, not a pass: "never ran" and "ran and passed" are the
    distinction this whole line of work exists to keep.

    Mirrors `gate.validators_for` EXACTLY -- kind == "validator" and
    str(phase) == label. Any other rule would make the gate enumerate a
    different set from the one that actually runs, which is the defect it is
    fixing.
    """
    blockers, notes = [], []
    try:
        reg = hlib.load_yaml(hlib.config_path(root, "registry.yaml")) or {}
    except Exception as exc:
        return ([B("registry.yaml unreadable (%r): what each phase was supposed to "
                   "verify cannot be established." % (exc,),
                   kind="INSTRUMENT_ABSENT")], notes)

    vals = [c for c in (reg.get("components") or [])
            if str(c.get("kind")) == "validator"]
    byphase, unmapped = {}, []
    for c in vals:
        ph = c.get("phase")
        if ph is None:
            unmapped.append(str(c.get("id")))
        else:
            byphase.setdefault(str(ph), []).append(str(c.get("id")))

    # THE ENUMERATION DECLARES ITS OWN BOUNDARY. Validators with `phase: null`
    # are skipped by gate.validators_for and so run in no gate at all. They are
    # NOT quietly mapped to a phase to make this list look complete -- that
    # would be P43 rebuilt inside its own fix. They are named here and carried
    # as P52's shape: a control that exists, is registered, and has no reader.
    if unmapped:
        notes.append("%d registered validator(s) map to NO phase and therefore run "
                     "in no gate: %s. Not consulted below, and not counted as "
                     "passing." % (len(unmapped), ", ".join(sorted(unmapped))))

    for p in hlib.phases_of(phase_doc):
        lbl = str(p.get("label"))
        ev = {str(e.get("validator")): e for e in (p.get("evidence") or [])}
        for vid in sorted(byphase.get(lbl, [])):
            # The release gate cannot demand a recorded result for ITSELF: it is
            # registered as phase 11's validator and is the thing running. Left
            # in the enumeration and skipped explicitly, so the exemption is
            # visible rather than achieved by omitting it from the registry.
            if vid == self_id:
                notes.append("phase %s validator %r is this program; not consulted "
                             "about its own prior result." % (lbl, vid))
                continue
            rec = ev.get(vid)
            # P58. Approval evidence is authoritative for an APPROVED phase. If
            # there is none, a recorded VALIDATE run still distinguishes
            # "ran and failed" from "never ran" -- which is the middle state the
            # writer used to destroy, and the reason this reader reported both
            # as INSTRUMENT_ABSENT.
            _lv_note = ""
            if rec is None:
                _lv = (p.get("last_validation") or {})
                _lv_rec = next((e for e in (_lv.get("results") or [])
                                if str(e.get("validator")) == vid), None)
                if _lv_rec is not None:
                    rec = dict(_lv_rec)
                    _lv_note = (" Recorded by `gate.sh validate` at %s against %s, "
                                "not by an approval." % (_lv.get("at"),
                                                         str(_lv.get("sha") or "?")[:12]))
            if rec is None:
                # P59. Was this validator even registered when the phase was
                # approved? "Approved before this check existed" and "approved
                # and skipped it" are two claims, and blocking on both makes
                # every registry addition invalidate all history at once.
                _sha, _st = registered_since(root, vid)
                _pre = predates(root, _sha, p.get("approval_sha")) if _st == "known" else None
                if _pre is False:
                    notes.append(
                        "phase %s was approved before validator %r existed "
                        "(registered at %s). Not counted against the approval: the "
                        "phase was not verified against it, and could not have been."
                        % (lbl, vid, str(_sha)[:12]))
                    continue
                _why = ""
                if _st != "known" or _pre is None:
                    _why = (" Whether it predates the approval is UNKNOWN -- the "
                            "registry history could not be read, so this is not "
                            "excused as a later addition.")
                blockers.append(B(
                    "phase %s validator %r has NO recorded result. Absence is not a "
                    "pass -- it records that nothing consulted it, which is a "
                    "different claim from passing.%s" % (lbl, vid, _why),
                    kind="INSTRUMENT_ABSENT", phase=lbl))
            elif str(rec.get("result")) == "unknown":
                # A run whose INSTRUMENT could not be reached is not evidence
                # about the product. Recording it as a verified failure would
                # let a run with the app down stand as "we checked, and it is
                # broken" -- and under decoupling it is worse than wrong, since
                # last_validation is what the ordering gate reads.
                blockers.append(B(
                    "phase %s validator %r recorded result 'unknown' (exit %s) at "
                    "%s: the instrument could not be reached, so this is not a "
                    "result about the product.%s"
                    % (lbl, vid, rec.get("exit_code"), rec.get("checked_at"),
                       _lv_note),
                    kind="INSTRUMENT_ABSENT", phase=lbl))
            elif str(rec.get("result")) != "pass":
                blockers.append(B(
                    "phase %s validator %r recorded result %r (exit %s) at %s.%s"
                    % (lbl, vid, rec.get("result"), rec.get("exit_code"),
                       rec.get("checked_at"), _lv_note),
                    kind="PRODUCT_DEFECT", phase=lbl))
    return blockers, notes


def axis_verdicts(real, derived, derived_all_resolved=False):
    """(verification, release) from the classified blockers. THREE states.

    Extracted so every state can be ASSERTED rather than reasoned about. P56
    was unexercised precisely because this lived inline: no reachable tree
    produces a progression-only blocker set, so the branch that decided it
    could not be reached by a fixture. A rule that cannot be called cannot be
    tested, and the fix for that is to make it callable.

      COMPLETE    every instrument ran and was satisfied
      INCOMPLETE  an instrument ran and could not produce a result
      UNKNOWN     no instrument reported, because nothing consulted one

    `real`    blockers that stand on their own.
    `derived` PROGRESSION blockers -- consequences of the above.
    """
    axes = [axis_of(b) for b in real]
    if any(a in (None, "VERIFICATION") for a in axes):
        verification = "INCOMPLETE"
    elif derived and not derived_all_resolved:
        # CORRECTED. This branch used to read:
        #
        #   "A phase that has not been approved has not had its validators run.
        #    UNKNOWN about the instrument fails rather than passes (3.10)."
        #
        # The inference was SOUND WHEN WRITTEN and P58 made it FALSE. P58
        # records a `gate.sh validate` run on phase.yaml, so an unapproved phase
        # can now carry a result -- and this branch went on reporting UNKNOWN
        # for a phase whose own record says `fail`. Unapproved and unverified
        # are two claims, and treating one as evidence of the other is the
        # conflation this version removed from the scorecard, rebuilt inside the
        # axis built to remove it.
        #
        # It matters most under decoupling, where a phase that ran, FAILED, and
        # is therefore never approved is the NORMAL state.
        #
        # `derived_all_resolved` says every unapproved phase has a recorded
        # result for every validator registered to it. It DEFAULTS TO FALSE, so
        # a caller that cannot tell keeps the old, fail-closed answer -- 3.10
        # still holds, it is just no longer inferred from approval status.
        verification = "UNKNOWN"
    else:
        verification = "COMPLETE"
    release = ("BLOCKED" if (any(a in (None, "RELEASE") for a in axes)
                             or verification != "COMPLETE") else "CLEARED")
    return verification, release


def exit_code(verification, release):
    """The 0/1/2 contract, in one place so it can be asserted directly.

    STEP 5. The docstring has declared `0 = releasable, 1 = blocked,
    2 = cannot evaluate` since this file was written, and `2` was implemented
    for exactly ONE condition -- an unreadable gate config. Every other "could
    not be computed" in the file returned `1`, the code meaning *we evaluated,
    and the answer is no*. Over half the blockers here are INSTRUMENT_ABSENT,
    so the contract has been wrong on its most common branch for as long as it
    has existed, and nothing read it closely enough to notice.

    2 DOMINATES 1. If verification is INCOMPLETE you do not know the release
    state, so reporting a determinate "no" overstates what was established --
    UNKNOWN about the instrument failing DISTINCTLY rather than merely failing.

    Nobody tests `rc == 1`: the audit found one caller asserting `rc != 0`, one
    (CI) treating any non-zero as failure, and four discarding the code. So the
    distinct code costs nothing, and burying "we could not check" in the same
    value as "the product is defective" would recreate this rewrite's own
    target conflation at the one interface a machine consumes.
    """
    if verification != "COMPLETE":
        return 2
    return 0 if release == "CLEARED" else 1


def main():
    ap = argparse.ArgumentParser(prog="build-scorecard.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        paths_doc = hlib.load_paths_doc(root) or {}
        phase_doc = hlib.load_phase_doc(root) or {}
    except Exception as exc:
        print("build-scorecard: cannot load gate config (%r)" % (exc,))
        return 2
    groot = paths_doc.get("governed_root") or ""
    d = os.path.join(root, groot, "sdlc")
    is_toy = bool(phase_doc.get("toy"))

    # The ruling comes from the BRD, which is the single source of truth; the
    # scorecard does not keep a second copy that could drift from it.
    sys.path.insert(0, HERE)
    import check_profile
    profile, prof_err = check_profile.read_ruling(d)
    prof_cfg = {}
    try:
        prof_cfg = ((hlib.load_yaml(hlib.config_path(root, "profiles.yaml"))
                     or {}).get("profiles") or {}).get(profile or "", {}) or {}
    except Exception:
        prof_cfg = {}

    blockers, waived_lines, na_lines, rows = [], [], [], []

    # ---------- 1. phase gate status + THE HARD RULE ----------------------
    phases = hlib.phases_of(phase_doc)

    # ---------- COLLAPSED is a third thing --------------------------------
    # The verdict vocabulary was PASS / FAIL / RELEASABLE / BLOCKED: one slot
    # for three different claims.
    #
    #   COLLAPSED  a decision about PROCESS DEPTH   (S: we chose not to run it)
    #   N/A        a statement about APPLICABILITY  (it does not apply here)
    #   PASS       a claim about the PRODUCT        (it ran and was fine)
    #
    # Reusing PASS would make a collapse indistinguishable from a gate that ran
    # and passed, which is the whole objection to size profiles. So the token is
    # added rather than borrowed, and every collapsed gate names the checks that
    # did not run because of it -- otherwise COLLAPSED is a nicer-looking
    # silence and a size profile is a skip with better paperwork.
    _cstate, _cval = _csp.collapsed_map(root)
    collapsed = _cval if _cstate == "ok" else {}
    collapse_unknown = _cval if _cstate != "ok" else ""

    noninteractive = []
    for p in phases:
        st = str(p.get("status"))
        lbl = str(p.get("label"))
        mode = str(p.get("approval_mode") or "-")
        shown = st
        if lbl in collapsed:
            # A phase both collapsed AND approved was worked anyway. Say both;
            # silently preferring either one hides a disagreement between the
            # declaration and what happened.
            shown = "APPROVED (collapse declared)" if st == "APPROVED" else "COLLAPSED"
        rows.append((lbl, str(p.get("name")), shown, mode,
                     str(p.get("approver") or "-")))
        if st == "APPROVED" and mode == "noninteractive":
            noninteractive.append(p)
    # Exclude the release phase itself. It cannot be APPROVED until the
    # scorecard passes, and the scorecard cannot pass while it is unapproved --
    # a deadlock. Phase 11's readiness is what this script MEASURES, not a
    # precondition of measuring it.
    RELEASE_LABEL = "11"
    # A phase cannot block itself, and it cannot block on a phase that comes
    # AFTER it. RELEASE_LABEL was excluded in v0.3 for exactly that reason; v0.4
    # added 11b (id 13) after 11 (id 12) and did not extend the exclusion, so
    # the phase-11 scorecard demanded 11b be APPROVED while 11b cannot become
    # current until 11 is. Deadlock, and the same class of bug as the v0.3 one.
    #
    # Exclude by ID ORDER rather than by naming another label, so a phase added
    # after 11 in future cannot resurrect this a third time.
    release_id = next((int(p["id"]) for p in phases
                       if str(p.get("label")) == RELEASE_LABEL), None)
    not_approved = [p for p in phases
                    if str(p.get("status")) != "APPROVED"
                    and str(p.get("label")) != RELEASE_LABEL
                    and str(p.get("label")) not in collapsed
                    and not (release_id is not None and int(p["id"]) > release_id)]

    # An unapproved phase is either excused by a declared collapse or it is not,
    # and if the size profile could not be read we cannot tell which. That is
    # UNKNOWN about the INSTRUMENT (3.10) and fails; it is raised only when some
    # phase is actually unapproved, because that is the only state in which the
    # answer changes anything.
    if collapse_unknown and any(str(p.get("status")) != "APPROVED" for p in phases):
        blockers.append(
            B("the size profile could not be determined (%s), so an unapproved phase "
            "cannot be told apart from a phase collapsed on purpose. Not knowing "
            "which is UNKNOWN about the instrument, and that fails rather than "
            "degrades (3.10)." % collapse_unknown,
                        kind='INSTRUMENT_ABSENT'))

    if noninteractive:
        detail = ", ".join("%s" % p.get("label") for p in noninteractive)
        if is_toy:
            na_lines.append(("suppressed", "interactive-approval rule SUPPRESSED: project is flagged `toy: true`. "
                            "%d phase(s) approved non-interactively (%s). Removing the toy flag "
                            "makes this a hard blocker." % (len(noninteractive), detail)))
        else:
            blockers.append(B("HARD RULE: %d phase(s) were approved with approval_mode: "
                            "noninteractive (%s). There is NO waiver for this — the human gate is "
                            "the point of the design. Re-approve them at a terminal: "
                            "`harness/bin/gate.sh reopen <phase> --reason \"re-approve "
                            "interactively\"` then approve." % (len(noninteractive), detail),
                        kind='INTEGRITY'))

    # ---------- 2. tests ---------------------------------------------------
    junit = sorted(glob.glob(os.path.join(root, groot, "test-results", "*.xml")))
    total = passed = failed = skipped = 0
    for f in junit:
        try:
            # S314: the JUnit XML is produced by the product's own test runner
            # inside the governed root, not fetched from anywhere. The residual
            # risk is a hostile PRODUCT planting an entity-expansion bomb to
            # stall its own release gate -- which fails closed and loudly, and
            # is not a path to a false GREEN. Recorded rather than waved away;
            # if the harness ever parses XML it did not cause to be written,
            # this needs defusedxml.
            r = ET.parse(f).getroot()
        except Exception:
            # S112: the artifact is unreadable, which section 2 reports as
            # "no test results found"; logging here would duplicate that.
            continue
        for tc in r.iter("testcase"):
            total += 1
            if tc.find("failure") is not None or tc.find("error") is not None:
                failed += 1
            elif tc.find("skipped") is not None:
                skipped += 1
            else:
                passed += 1
    pass_rate = (100.0 * passed / total) if total else 0.0
    if total == 0:
        blockers.append(B("no test results found under %s/test-results/. Run "
                        "harness/bin/run-product-tests.sh." % groot,
                        kind='INSTRUMENT_ABSENT'))
    elif failed:
        blockers.append(B("%d test case(s) failing." % failed,
                        kind='PRODUCT_DEFECT'))

    # ---------- 3. traceability -------------------------------------------
    rc_tr, out_tr = run([*hlib.validator_argv("check-traceability.sh"),
                         "--no-write", "--quiet"], root)

    # F57. `out_tr` was assigned here and read NOWHERE. Three channels carried
    # check-traceability's warnings to this gate and all three were closed:
    # stdout (suppressed by --quiet), the exit code (`return 1 if errs else 0`
    # -- a warn has never moved it), and this variable. Any one alone would have
    # been survivable.
    #
    # THIS IS THE OPTION I REJECTED, MADE SAFE. The objection to selecting on a
    # text prefix was that it is a string contract between two modules and
    # UNASSERTED -- 3.11 waiting to happen. The remedy for `unasserted` is to
    # assert it, which TR14/TR15 do from both sides, control-stripped. The
    # alternative -- teaching this gate to recompute the coverage rule itself --
    # puts one rule in two files that can disagree, which is P60 by construction.
    #
    # A PASSTHROUGH, NOT AN INTERPRETATION. The child's warning is surfaced
    # verbatim and attributed; this gate does not parse its meaning, and the
    # narrow question it answers -- "did the child warn?" -- is the question it
    # reports. It lands in na_lines, which is RENDERING ONLY: making the warning
    # visible is this change; whether it moves a verdict is the next one.
    for _wl in (out_tr or "").splitlines():
        _wl = _wl.strip()
        if _wl.startswith("WARN "):
            na_lines.append(("unmeasured", "check-traceability warned (invisible at the "
                                           "release gate until F57): %s" % _wl[5:].strip()))

    if rc_tr != 0:
        blockers.append(B("traceability gate fails: every PRD story must have a passing test. "
                        "(check-traceability.sh exit %d)" % rc_tr,
                        kind='GATE_CHAIN'))

    # ---------- 4. security -------------------------------------------------
    sec_text = read(os.path.join(d, "09-security-report.md")) or ""
    verdicts = ids_with_field(sec_text, "SEC", "Verdict")
    sec_waivers = {str(w.get("path")): w for w in hlib.waivers_for(phase_doc, "security")}
    unevidenced = [s for s, v in sorted(verdicts.items())
                   if (v or "").upper() != "EVIDENCED" and s not in sec_waivers
                   and (v or "").upper() != "NOT-APPLICABLE"]
    for s in unevidenced:
        blockers.append(B("SEC-ID %s is %r with no waiver." % (s, verdicts.get(s)),
                        kind='PRODUCT_DEFECT'))
    open_high = []
    for m in re.finditer(r"^\|\s*(SF-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", sec_text, re.M):
        fid, sev, _desc, status = (x.strip() for x in m.groups())
        if sev.lower() in ("high", "critical") and status.lower() not in ("closed", "fixed", "resolved"):
            if fid in sec_waivers:
                open_high.append((fid, sev, True))
            else:
                open_high.append((fid, sev, False))
                blockers.append(B("finding %s (%s) is open with no waiver." % (fid, sev),
                        kind='PRODUCT_DEFECT'))

    # Which ruling-declared N/A checks are superseded by a platform equivalent.
    # profiles.yaml already declared these N/A and the scorecard already PRINTS
    # them -- sections 5, 6 and 7 below then went on to run the web checks
    # anyway, so an APP-FIRST product got "N/A lighthouse: there is no web page"
    # and "BLOCK no Lighthouse report captured" in the same output, and phase 11
    # was unreachable. Consult the declaration instead of hardcoding the web path.
    na_by_id = {str(na.get("id")): na for na in (prof_cfg.get("not_applicable") or [])}

    def superseded(na_id):
        """(is_na, replacement_id). A check the ruling retires, and what replaces it."""
        na = na_by_id.get(na_id)
        if not na:
            return False, None
        return True, na.get("superseded_by")

    # ---------- 5. live verification ---------------------------------------
    # Read the report the ruling actually produces. A mobile ruling verifies on
    # a device and writes 10a-live-verification-mobile.md; requiring the web
    # report there is not a stricter gate, it is the wrong gate.
    # Defined before first use: the NA-ENVIRONMENT check below consults it.
    live_waivers = {str(w.get("path")): w for w in hlib.waivers_for(phase_doc, "live-verification")}
    na_live, live_sub = superseded("live-verification-web")
    live_report = ("10a-live-verification-mobile.md"
                   if (na_live and live_sub) else "10a-live-verification.md")
    live_text = read(os.path.join(d, live_report)) or ""
    if na_live and live_sub:
        # The two reports have genuinely different shapes: the web one is
        # '### US-001' + '- **Verdict:**' prose blocks, the mobile one a
        # per-story-per-PLATFORM table. Reuse the mobile checker's own parser
        # rather than reimplementing it here -- a second copy of a table parser
        # is how the two drift apart, and this file already proved that by
        # hardcoding the web path in three places.
        sys.path.insert(0, HERE)
        import check_live_verification_mobile as clvm
        mobile_rows = clvm.rows(live_text)
        live = {}
        for r_ in mobile_rows:
            prev = live.get(r_["story"])
            v = r_["verdict"]
            if prev is None or (prev != "PASS" and v == "PASS"):
                live[r_["story"]] = v

        # Constitution §6.3: "a platform the host cannot run is NA-ENVIRONMENT,
        # which blocks rather than passes." check_live_verification_mobile even
        # PRINTS that the scorecard enforces this. It did not -- the scorecard
        # had no NA-ENVIRONMENT handling of any kind, so an APP-FIRST product
        # with a platform it could not verify came out RELEASABLE.
        #
        # This was invisible until the web-check blockers above were fixed: the
        # scorecard was BLOCKED for the wrong reasons, which masked that it was
        # not blocking for the right one. Removing false blockers without adding
        # this one would turn a false red into a false green.
        #
        # Waivable, like every other release blocker, so an operator can ship
        # one platform deliberately -- but it must be a recorded decision, not
        # a silent omission.
        na_env = sorted({r_["platform"] for r_ in mobile_rows
                         if r_["verdict"] == "NA-ENVIRONMENT"})
        for plat in na_env:
            if ("NA-ENVIRONMENT:%s" % plat) not in live_waivers:
                blockers.append(
                    B("platform %r reported NA-ENVIRONMENT in %s: under ruling %s the host could "
                    "not verify it, so the release cannot be signed off for it (Constitution "
                    "§6.3). Waive with `gate.sh waive live-verification --path "
                    "NA-ENVIRONMENT:%s --reason \"...\" --approver \"...\"` to ship the "
                    "verified platform(s) only."
                    % (plat, live_report, profile, plat),
                        kind='INSTRUMENT_ABSENT'))
    else:
        live = ids_with_field(live_text, r"(?:US|NFR)", "Verdict")
    prd_text = read(os.path.join(d, "02-prd.md")) or ""
    stories = sorted(set(re.findall(r"^#{2,4}\s+((?:US|NFR)-\d+)\b", prd_text, re.M)))
    for sid in stories:
        v = (live.get(sid) or "").upper()
        if not v:
            blockers.append(B("story %s has no 10a live-verification verdict in %s."
                            % (sid, live_report),
                        kind='INSTRUMENT_ABSENT'))
        elif v in ("FAIL", "BLOCKED") and sid not in live_waivers:
            blockers.append(B("story %s is %s in live verification with no waiver." % (sid, v),
                        kind='PRODUCT_DEFECT'))

    # ---------- 6. regression ----------------------------------------------
    # Run the suite the ruling actually produces. Substitution, NOT a skip: an
    # APP-FIRST product must still face a regression gate, just Maestro's rather
    # than Playwright's. Skipping outright would leave the release with no
    # regression gate at all, which is a worse failure than the one being fixed.
    na_reg, reg_sub = superseded("regression-suite-web")
    reg_script = ("check-regression-mobile.sh" if (na_reg and reg_sub)
                  else "check-regression.sh")
    rc_rg, _ = run([*hlib.validator_argv(reg_script), "--quiet"], root)
    if rc_rg != 0:
        blockers.append(B("regression gate fails: a live-verified story has no committed spec, or a "
                        "quarantined spec is untracked. (%s exit %d)" % (reg_script, rc_rg),
                        kind='GATE_CHAIN'))

    # ---------- 7. lighthouse, against configured thresholds ----------------
    sys.path.insert(0, HERE)
    import check_live_verification as clv
    lh, lh_thresholds = {}, {}
    lh_files = sorted(glob.glob(os.path.join(root, groot, "evidence", "live", "**",
                                             "*lighthouse*.json"), recursive=True))
    if lh_files:
        lh = clv.lighthouse_scores(lh_files[-1]) or {}
    try:
        qcfg = (hlib.load_yaml(hlib.config_path(root, "quality-thresholds.yaml")) or {}).get("lighthouse") or {}
    except Exception:
        qcfg = {}
    lh_waivers = {str(w.get("path")): w for w in hlib.waivers_for(phase_doc, "live-verification")}
    if qcfg:
        # quality-thresholds.yaml says "required for a WEB product"; the ruling
        # says whether this IS one. Without this the scorecard printed
        # "N/A lighthouse: there is no web page" and blocked for a missing
        # Lighthouse run in the same report.
        na_lh, _ = superseded("lighthouse")
        if not lh_files and qcfg.get("required") and not na_lh:
            blockers.append(B("no Lighthouse report captured, but quality-thresholds.yaml marks it "
                            "required for a web product.",
                        kind='INSTRUMENT_ABSENT'))
        for cat, spec in (qcfg.get("categories") or {}).items():
            thr = spec.get("threshold") if isinstance(spec, dict) else spec
            enforced = spec.get("enforced", True) if isinstance(spec, dict) else True
            got = lh.get(str(cat))
            lh_thresholds[str(cat)] = (thr, enforced, got)
            if got is None or thr is None or not enforced:
                continue
            if got < int(thr) and ("lighthouse:%s" % cat) not in lh_waivers:
                blockers.append(B("Lighthouse %s = %d, below the threshold of %s, with no waiver."
                                % (cat, got, thr),
                        kind='PRODUCT_DEFECT'))

    # ---------- 8. evidence provenance, RELEASE-STRICT ----------------------
    # The citation lists come from the phase validators' own parsers. This file
    # already carries the lesson in section 5 -- "a second copy of a table
    # parser is how the two drift apart" -- so the scorecard imports
    # `citations()` rather than re-walking the reports.
    #
    # Waivable per evidence path, rule `evidence-provenance`. A waived citation
    # is DROPPED from the audit rather than matched against the message text:
    # a control that works by substring-matching its own error strings breaks
    # the first time the wording improves.
    sys.path.insert(0, HERE)
    import provenance
    prov_cites, prov_src = [], []
    try:
        if na_live and live_sub:
            prov_cites += clvm.citations(root, groot, d, live_text)
            prov_src.append("10a-mobile")
        else:
            prov_cites += clv.citations(root, groot, d, live_text)
            prov_src.append("10a-web")
    except Exception as exc:
        blockers.append(B("cannot collect 10a evidence citations for the provenance audit (%r). "
                        "The release gate will not pass on evidence it could not read." % (exc,),
                        kind='INSTRUMENT_ABSENT'))
    try:
        import check_security as _csec
        prov_cites += _csec.citations(root, groot)
        prov_src.append("9")
    except Exception as exc:
        blockers.append(B("cannot collect phase-9 artifact citations (%r)." % (exc,),
                        kind='INSTRUMENT_ABSENT'))
    if check_profile.has_mobile_surface(profile):
        try:
            import check_store_readiness as _csr
            prov_cites += _csr.citations(root, groot, d)
            prov_src.append("11b")
        except Exception as exc:
            blockers.append(B("cannot collect phase-11b asset citations (%r)." % (exc,),
                        kind='INSTRUMENT_ABSENT'))

    prov_wv = {str(w.get("path")): w for w in hlib.waivers_for(phase_doc, "evidence-provenance")}
    prov_active = [(c, r) for c, r in prov_cites if r not in prov_wv]
    prov_skipped = [(c, r) for c, r in prov_cites if r in prov_wv]
    prov_errs, _pw, prov_notes = provenance.audit(root, groot, prov_active, strict_unknown=True)
    for e in prov_errs:
        blockers.append(B("evidence provenance: %s" % e,
                        kind='INSTRUMENT_ABSENT'))
    for _c, _r in prov_skipped:
        na_lines.append(("waived", "evidence provenance waived for %s (cited as %s)" % (_r, _c)))

    # ---------- 9. approval freshness -- does the approval still hold? ------
    # C11. The motivating case: a PASSING 10a report sat in the approval queue
    # across two rounds of fixes, describing a binary that no longer existed.
    # Every artifact opened cleanly, because they were real captures of a real
    # PAST build. Nothing compared the approval to the tree.
    #
    # A phase's own allow-globs are not the right question -- 10a verifies
    # phase 7's OUTPUT, not its own report. The registry `verifies:` map is
    # what each validator actually looks at, so that is what staleness is
    # measured against.
    fresh_rows, appr_wv = [], {str(w.get("path")): w
                               for w in hlib.waivers_for(phase_doc, "approval-staleness")}
    try:
        _reg = hlib.load_yaml(hlib.config_path(root, "registry.yaml")) or {}
    except Exception as exc:
        _reg = {}
        blockers.append(B("registry.yaml unreadable (%r): approval freshness cannot be "
                        "evaluated, and unknown is not a basis for shipping." % (exc,),
                        kind='INSTRUMENT_ABSENT'))
    verifies_by_phase = provenance.verifies_map(_reg)

    # F44. Approval staleness compared a phase's `verifies:` globs against its
    # approval commit, and gate.py joins every one of those under the governed
    # root -- so no verifies glob can ever name a harness/ path. Staleness saw
    # product artifacts and nothing else, while ten of twenty-one phase-mapped
    # validators depend on harness state it could not see.
    #
    # These paths are repo-relative and are deliberately NOT joined with groot.
    _cdeps, _cexcl, _cderr = {}, [], None
    try:
        _cd = hlib.load_yaml(hlib.config_path(root, "control-deps.yaml")) or {}
        _cdeps = {str(k): list(v or []) for k, v in (_cd.get("phases") or {}).items()}
        _cexcl = list(_cd.get("excluded") or [])
    except Exception as exc:
        # UNKNOWN about the instrument. Say so; do not silently watch nothing.
        _cderr = "%r" % (exc,)
        blockers.append(B("control-deps.yaml unreadable (%s): which harness config a "
                          "phase depends on cannot be established, so approval "
                          "staleness is narrower than it claims."
                          % _cderr, kind="INSTRUMENT_ABSENT"))

    # THE EXCLUSION IS STATED, NOT IMPLICIT. A reader must be able to tell a
    # decision from an oversight, and an enumeration that omits its own gaps is
    # the defect this mechanism exists to fix.
    for _x in _cexcl:
        na_lines.append(("not-applicable",
                         "approval staleness does NOT watch %s: %s"
                         % (_x.get("path"), re.sub(r"\s+", " ",
                                                   str(_x.get("reason") or "")).strip())))

    REMEDY = ("Reopen and re-approve it (`gate.sh reopen %s` then approve), or waive with "
              "`gate.sh waive approval-staleness --path %s --reason \"...\" --approver \"...\"`.")
    for p in phases:
        lbl = str(p.get("label"))
        if str(p.get("status")) != "APPROVED":
            continue
        if release_id is not None and int(p["id"]) > release_id:
            continue          # a later phase cannot constrain this one
        globs = verifies_by_phase.get(lbl) or []
        _cdep = _cdeps.get(lbl) or []
        if not globs and not _cdep:
            continue          # nothing declared; not a finding to invent here
        # verifies globs are PRODUCT paths and are joined under the governed
        # root; control deps are REPO-relative and must not be.
        specs = [os.path.join(groot, g) if groot else g for g in globs] + list(_cdep)

        state, why = provenance.approval_status(root, p, specs)
        at = (str(p.get("approval_sha") or "unknown"))[:12]
        fresh_rows.append((lbl, at, {"current": "current", "dirty": "**UNCOMMITTED CHANGES**",
                                     "stale": "**STALE**"}.get(state, "**UNKNOWN**"), why))
        if state != "current" and lbl not in appr_wv:
            blockers.append(B(("phase %s approval freshness: %s. " % (lbl, why))
                            + (REMEDY % (lbl, lbl)),
                        kind='INTEGRITY'))
        elif state != "current":
            na_lines.append(("waived", "phase %s approval freshness waived (%s): %s"
                            % (lbl, state, why)))

        if p.get("approval_dirty") is True:
            na_lines.append(("compromised", "phase %s was approved from a DIRTY working tree: its recorded "
                            "commit %s is a half-truth about what was actually approved." % (lbl, at)))
        elif p.get("approval_dirty") == "unknown":
            na_lines.append(("unknown", "phase %s did not record whether its working tree was clean at "
                            "approval." % lbl))

    # ---------- collect every waiver for the report -------------------------
    # This table is the whole point of the document: "a release signed off with
    # known holes says so on its face." It previously showed each hole and lost
    # its boundary, in two ways.
    #
    # 1. The reason was cut at 90 characters, and a waiver's SCOPE is where the
    #    approver puts the limitation -- so the truncation removed exactly the
    #    clause that bounds it. On this run SEC-005 rendered as
    #    "...; scope: SEC-005 only, not evidence f", losing
    #    "or 11b store readiness" -- the clause that stops a signing waiver
    #    being read as store-release evidence, in the release document read
    #    immediately before phase 11b. Markdown cells wrap; the cap was
    #    protecting a fixed-width terminal this file is not read in. Only
    #    newlines and pipes need escaping to keep the table intact.
    #
    # 2. There was no Expires column. Every waiver on this release lapses
    #    2026-11-30. `gate.sh current` annotates that, hlib.waiver_expired()
    #    enforces it, and the artifact a human reads months later to understand
    #    what was signed off presented time-boxed exceptions as permanent. The
    #    record was right and the human-facing view was wrong -- the same shape
    #    as the N/A-reported-then-blocked and stale-artifact findings.
    # ---- 10. waiver GOVERNANCE ------------------------------------------
    # The table used to render a missing expiry as `never`. That asserted a
    # permanence the record does not support: those waivers predate the field,
    # and unknown is not never. Rendering and judging both come from
    # harness/lib/waivers.py now, so the thing that GRANTS a waiver and the
    # thing a release RESTS ON cannot drift apart.
    sys.path.insert(0, HERE)
    import waivers as W
    _sevs = {}
    for _m in re.finditer(r"^\|\s*((?:SF|SEC)-\d+)\s*\|([^|]*)\|", sec_text, re.M):
        _sevs[_m.group(1).upper()] = _m.group(2).strip().lower()
    if not sec_text.strip():
        _sevs = None            # unreadable, not empty: audit() must say so
    w_errs, w_warns, w_notes, w_rows = W.audit(root, phase_doc, _sevs)
    # THE 26th SITE, and a bulk `+=` rather than an `.append` -- so the AST
    # enumeration that found the other 25 did not see it either. It was found
    # by the step-2 recognition boundary firing on a clean tree, which is the
    # fail-closed default doing exactly its job on its first run.
    #
    # Classified in bulk, and that IS honest here because it was MEASURED:
    # every one of waivers.audit's five errs says the waiver ledger does not
    # hold -- expired, no expiry, past the horizon, missing required fields,
    # or covering an unwaivable severity. One claim, five wordings. (The
    # warns and notes on the N/A axis were heterogeneous and were split; the
    # difference is evidence, not convenience.)
    blockers += [B(e, kind="INTEGRITY") for e in w_errs]
    # The ninth emit site, and the only bulk one -- which is why enumerating
    # `.append(` calls missed it. w_warns are things the waiver machinery could
    # NOT establish (an unreadable severity; an expiry nobody set, which
    # waivers.py itself renders as UNKNOWN rather than `never`). w_notes are
    # facts about waivers it DID establish. Two kinds, not one list.
    na_lines += [("unknown", x) for x in w_warns]
    na_lines += [("waived", x) for x in w_notes]

    for r_ in w_rows:
        w = r_["waiver"]
        reason = re.sub(r"\s+", " ", str(w.get("reason") or "")).replace("|", "\\|").strip()
        waived_lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            w.get("rule"), w.get("path"), reason,
            str(w.get("owner") or "**—**").replace("|", "\\|"),
            str(w.get("scope") or "**—**").replace("|", "\\|"),
            w.get("approver"), (w.get("timestamp") or "")[:10],
            ("**REVOKED**" if r_["state"] == "revoked" else W.render_expiry(w))))

    # Profile-driven N/A: never silent. A check the ruling makes irrelevant is
    # reported, with its reason, and may still block the release.
    if prof_err:
        blockers.append(B("platform ruling unreadable: %s" % prof_err,
                        kind='INSTRUMENT_ABSENT'))
    for na in (prof_cfg.get("not_applicable") or []):
        line = "%s (phase %s): %s" % (na.get("id"), na.get("phase"), (na.get("reason") or "").strip())
        na_lines.append(("not-applicable", line))
        if na.get("blocks_release"):
            blockers.append(B("N/A AND BLOCKING: %s — under ruling %s this check cannot be "
                            "performed in v0.3, so the release cannot honestly be signed off."
                            % (na.get("id"), profile),
                        kind='INSTRUMENT_ABSENT'))

    if not_approved:
        blockers.append(B("phase(s) not APPROVED: %s"
                        % ", ".join(str(p.get("label")) for p in not_approved),
                        kind='PROGRESSION'))

    # ---------- ORDER: an approval cannot precede its own predecessors ------
    # `not_approved` above says "10c is not approved yet". It does NOT say that
    # 11 and 11b are APPROVED while 10c is not -- and those are different
    # findings. The first is a step still to take; the second is an approval
    # that was granted against a lifecycle which had not completed, and it
    # stays wrong after 10c is approved, because the 11 sign-off never
    # considered 10c's output.
    #
    # It is the v0.3 deadlock shape inverted, and it is reachable in exactly
    # one way at runtime: gate.sh refuses a non-cascade reopen while later
    # phases are APPROVED, and --cascade resets them, so ordinary operation
    # maintains the invariant. INSERTING A PHASE beneath a completed run does
    # not -- which is what phase 10c did. This is the backstop for that.
    #
    # The release phase is excluded above as a CAUSE (it cannot be approved
    # until this script passes) but is included here as a SUBJECT: "11 is
    # approved though 10c is not" is precisely the thing to say.
    # A collapsed phase is dropped from the order check entirely: the collapse
    # IS the ruling that it does not run, so it must neither be reported as an
    # out-of-order approval nor make every phase after it look like one.
    ordered = [q for q in sorted(phases, key=lambda p: int(p["id"]))
               if str(q.get("label")) not in collapsed]
    pending = []
    for p in ordered:
        lbl, st = str(p.get("label")), str(p.get("status"))
        if st == "APPROVED" and pending:
            blockers.append(
                B("phase %s is APPROVED but its predecessor(s) %s are not. That approval was "
                "granted against a lifecycle that had not completed, and approving %s now "
                "does not repair it -- the %s sign-off never saw %s's output. Reopen from "
                "the earliest of them (`gate.sh reopen %s --cascade`) and re-approve in "
                "order." % (lbl, ", ".join(pending), pending[0], lbl, pending[0], pending[0]),
                        kind='INTEGRITY'))
        elif st != "APPROVED":
            pending.append(lbl)

    # ---------- 4-and-2, step 2: the recognition boundary ------------------
    # Built BEFORE the verdict depends on kind, so the enum is known good by
    # the time step 3 routes on it.
    #
    # AN UNRECOGNISED KIND IS DISQUALIFYING. This is the fail-closed default
    # sub-question 3's release gate rests on: a phase-11 check that enumerates
    # the verification failures it knows about and passes the ones it does not
    # is P43 at the release gate, which is the worst place for it.
    #
    # HONESTY ABOUT WHAT THIS CAN PROVE TODAY. At step 2 the verdict is still
    # `if not blockers`, so an unrecognised blocker already blocks -- by being
    # in the list, not by being unrecognised. A case asserting "an unrecognised
    # kind blocks" would PASS FOR THE WRONG REASON and keep passing with this
    # block deleted. So what is asserted here is the NAMING, which is real and
    # control-strippable now; the disqualifying assertion belongs to step 3,
    # where it can fail.
    #
    # It earned its place immediately: on its first run it named `blockers +=
    # w_errs`, a bulk addition the AST enumeration of `.append` calls missed.
    _unrec = sorted({str(getattr(b, "kind", None)) for b in blockers
                     if getattr(b, "kind", None) not in KINDS})
    if _unrec:
        blockers.append(B(
            "blocker kind(s) %s are not in KINDS. An unrecognised classification "
            "is DISQUALIFYING, not ignorable -- a gate that enumerates the "
            "failures it knows about and passes the ones it does not has the "
            "defect it exists to catch. Fix the emitter, not this check."
            % ", ".join(_unrec), kind="INTEGRITY"))

    # ---------- 4-and-2, step 3: TWO verdicts ------------------------------
    # One slot carried two claims: "is this product's security/quality
    # VERIFIED?" and "may it PROCEED?". Phase 9 of the GREENFIELD run answered
    # PASS to the first and NO to the second, and the harness could only say
    # BLOCKED -- so the first half existed nowhere a reader could see it.
    #
    #   verification  COMPLETE | INCOMPLETE   is what we know, known?
    #   release       CLEARED  | BLOCKED      given what we know, may this ship?
    #
    # An unrecognised kind has no axis, and `None` counts on BOTH -- so it
    # forces INCOMPLETE and BLOCKED. THIS is where K03's restraint pays off:
    # at step 2 that property could not fail, so it was not asserted. Here it
    # can, and K05/K06 assert it with a control-stripped pair.
    # STEP 4: PROGRESSION is a CONSEQUENCE, not a peer.
    #
    # `phase(s) not APPROVED: 9, 10a, 10b, 10c` sat in the blocker list beside
    # `SF-1 is open`, and a reader could not tell that the second PRODUCED the
    # first. That is a causal fact the document flattened. Phases 10a-10c are
    # unapproved BECAUSE phase 9 refused; listing the two as peers invites the
    # reading that four independent things went wrong.
    #
    # So progression is removed from the verdict computation and rendered
    # below the blockers as derived, naming what it follows from. It stays
    # VISIBLE: a consequence that disappears is how a reader concludes the
    # phases were skipped for no reason.
    _derived = [b for b in blockers if getattr(b, "kind", None) == "PROGRESSION"]
    _real = [b for b in blockers if getattr(b, "kind", None) != "PROGRESSION"]

    # P56. THREE STATES, not two.
    #
    #   COMPLETE    every instrument ran and was satisfied
    #   INCOMPLETE  an instrument ran and could not produce a result
    #   UNKNOWN     no instrument reported, because nothing consulted one
    #
    # v0.9 had two slots. `COMPLETE` meant "no VERIFICATION-axis blocker fired",
    # and `any([])` is False -- so a tree with nothing to say about verification
    # computed COMPLETE, which reads as "everything this gate can check, it
    # checked". Verified-and-passed and never-ran are different claims and the
    # axis could only make one of them.
    #
    # PROGRESSION NOW SPEAKS TO BOTH AXES, which is the substance of the fix: a
    # phase that has not been approved has not had its validators run, so
    # verification is not COMPLETE -- it is UNKNOWN, and UNKNOWN about the
    # instrument fails rather than passes (3.10).
    #
    # This REPLACES the `if _derived and not _real` carve-out rather than
    # testing it. That branch existed to make a progression-only tree block on
    # the release axis; with progression setting verification, the general rule
    # below does that work, and the branch nothing could reach is gone instead
    # of being given a fixture.
    # P49, COARSE BY RULING. A revoked waiver may have been load-bearing for an
    # approval already granted -- phase 6b's check-provisioning PASSES only
    # because two variables are waived, and says so in its own output.
    #
    # The gate CANNOT tell which approvals depended on which waiver: `evidence`
    # records validator RESULTS, not which waivers a validator consulted. So it
    # does not guess. It blocks and names the revocation, and a human states the
    # impact. A precise mechanism resting on a writer that does not record the
    # dependency would be P58 rebuilt inside P49.
    #
    # The approval itself is NOT mutated. The decision was correct and no longer
    # holds are two claims; auto-invalidating collapses them and rewrites an
    # approval as though the human had erred.
    for _w in (phase_doc.get("waivers") or []):
        _rev = hlib.waiver_revoked(_w)
        if not _rev:
            continue
        _real.append(B(
            "waiver %s/%s was REVOKED by %s at %s (%s). Any phase approved while it "
            "was live rested on a check that may no longer pass, and the ledger does "
            "not record which. State the impact and waive this, or re-approve the "
            "phases concerned."
            % (_w.get("rule"), _w.get("path"), _rev.get("by"), _rev.get("at"),
               _rev.get("reason")),
            kind="INSTRUMENT_ABSENT"))

    # ITEM 2B: consult what each phase RECORDED, before the verdict is formed.
    _rec_blockers, _rec_notes = recorded_validator_results(root, phase_doc)
    _real += _rec_blockers
    for _n in _rec_notes:
        na_lines.append(("unknown", _n))

    # Item 2B raises INSTRUMENT_ABSENT per phase for a validator with NO record
    # at all, and those blockers carry `phase`. So "which unapproved phases are
    # still unknown" is already in hand: no new signature, and no second source
    # that could disagree with the first.
    _unapproved = {str(q.get("label")) for q in phases
                   if str(q.get("status")) != "APPROVED"}
    _still_unknown = {getattr(b, "phase", None) for b in _rec_blockers
                      if getattr(b, "kind", None) == "INSTRUMENT_ABSENT"}
    _all_resolved = bool(_unapproved) and not (_unapproved & _still_unknown)

    verification, release = axis_verdicts(_real, _derived,
                                          derived_all_resolved=_all_resolved)

    # The single RELEASABLE/BLOCKED token is GONE. Step 3 kept it "for the exit
    # code and for readers not yet moved"; step 5 replaced the exit code with
    # `exit_code(verification, release)`, and there were no other readers -- so
    # it survived one step as dead code and ruff caught it (F841).
    #
    # That is the last of the one-slot-for-two-claims token in this file: the
    # thing the whole rewrite was about no longer exists to be read by accident.

    # ---------- write --------------------------------------------------------
    L = []
    L += ["# Release Scorecard — %s" % (phase_doc.get("project") or "product"), "",
          "Generated by `harness/bin/build-scorecard.sh`. Regenerated on every phase-11",
          "validation; do not hand-edit.", "",
          "- **Verification:** **%s** — %s" % (verification, {
              "COMPLETE": "everything this gate can check, it checked",
              "INCOMPLETE": "something could not be computed; see Blockers",
              "UNKNOWN": "phases below have not been approved, so their "
                         "validators never ran; this is not a pass",
          }[verification]),
          "- **Release:** %s%s" % (
              "**CLEARED**" if release == "CLEARED" else "**BLOCKED**",
              (" — with %d COLLAPSED gate(s); see below for what did not run"
               % len(collapsed)) if collapsed else ""),
          "- **Platform profile:** %s" % (profile or "not recorded"),
          "- **Toy project:** %s" % ("yes — the interactive-approval rule is suppressed"
                                     if is_toy else "no"), ""]
    # Steers are counted, not quoted. The count answers the question an approval
    # cannot: was this artifact produced unaided, or after guidance? The content
    # of the guidance lives in phase.yaml; putting it here would turn a release
    # document into a transcript.
    _steers = {str(p.get("label")): len(p.get("steers") or []) for p in phases}
    _tot = sum(_steers.values())
    L += ["## Phase gates", "",
          "| Phase | Name | Status | Approval | Approver | Steers |",
          "|---|---|---|---|---|---|"]
    for lbl, nm, st, mode, appr in rows:
        flag = " ⚠" if mode == "noninteractive" else ""
        L.append("| %s | %s | %s | %s%s | %s | %s |"
                 % (lbl, nm, st, mode, flag, appr, _steers.get(lbl, 0) or "—"))
    if _tot:
        L += ["", "%d recorded steer(s) across %d phase(s): a human gave mid-phase guidance "
              "that shaped these artifacts. Recorded so an approval cannot read as unaided "
              "work." % (_tot, sum(1 for v in _steers.values() if v))]
    if collapsed:
        _sz = next(iter(collapsed.values())).get("size")
        L += ["", "## Collapsed gates (size %s)" % _sz, "",
              "COLLAPSED is not PASS and it is not N/A. It is a recorded decision "
              "about how deep the process went (Constitution 6.1: only S may "
              "collapse, and only with an explicit ruling). Nothing below was "
              "checked against this product.", "",
              "| Phase | Reason | Checks that did NOT run |", "|---|---|---|"]
        for lbl in sorted(collapsed, key=lambda x: (len(x), x)):
            c = collapsed[lbl]
            L.append("| %s | %s | %s |"
                     % (lbl, c.get("reason") or "**no reason recorded**",
                        ", ".join("`%s`" % n for n in c.get("checks_not_run") or [])
                        or "**none named — this collapse is a silence**"))
    L += ["", "## Tests", "",
          "- cases: **%d** · passed **%d** · failed **%d** · skipped **%d**" % (total, passed, failed, skipped),
          "- pass rate: **%.1f%%**" % pass_rate,
          "- traceability gate: **%s**" % ("PASS" if rc_tr == 0 else "FAIL"), ""]
    L += ["## Security", "",
          "- SEC-IDs: **%d** · evidenced **%d** · unevidenced-and-unwaived **%d**"
          % (len(verdicts), sum(1 for v in verdicts.values() if (v or "").upper() == "EVIDENCED"),
             len(unevidenced))]
    if open_high:
        for fid, sev, wv in open_high:
            L.append("- finding **%s** (%s): open, %s" % (fid, sev, "waived" if wv else "**NOT waived**"))
    else:
        L.append("- no open high/critical findings")
    L += ["", "## Live verification (10a)", "", "| Story | Verdict |", "|---|---|"]
    for sid in stories:
        L.append("| %s | %s |" % (sid, (live.get(sid) or "—").upper()))
    L += ["", "## Regression suite (10b)", "",
          "- regression gate: **%s**" % ("PASS" if rc_rg == 0 else "FAIL"), ""]
    L += ["## Lighthouse", ""]
    if lh:
        L += ["| Category | Score | Threshold | Enforced | Verdict |", "|---|---|---|---|---|"]
        for cat in sorted(set(list(lh) + list(lh_thresholds))):
            thr, enf, _ = lh_thresholds.get(cat, (None, True, None))
            got = lh.get(cat)
            if got is None:
                cat_verdict = "**NOT CAPTURED**"
            elif thr is None:
                cat_verdict = "reported"
            elif got >= int(thr):
                cat_verdict = "pass"
            elif ("lighthouse:%s" % cat) in lh_waivers:
                cat_verdict = "**below — waived**"
            elif not enf:
                cat_verdict = "below (not enforced)"
            else:
                cat_verdict = "**FAIL**"
            L.append("| %s | %s | %s | %s | %s |" % (cat, got if got is not None else "—",
                                                     thr if thr is not None else "—",
                                                     "yes" if enf else "no", cat_verdict))
    else:
        L += ["- not captured (no lighthouse JSON under evidence/live/)"]
    # ---- phase 11b: only under a mobile ruling, otherwise explicitly N/A ----
    L += ["", "## Store release (11b)", ""]
    if check_profile.has_mobile_surface(profile):
        rc_sr, _ = run([*hlib.validator_argv("check-store-readiness.sh"),
                        "--quiet"], root)
        L.append("- store-readiness gate: **%s**" % ("PASS" if rc_sr == 0 else "FAIL"))
        # Reported here, but NOT a phase-11 blocker. check-store-readiness is a
        # registered phase-11b validator and runs there on its own artifact
        # (sdlc/11b-store-release.md), which by definition does not exist yet
        # when phase 11 is being assessed -- 11b comes after 11. Blocking on it
        # here duplicated 11b's own gate and was the other half of the deadlock.
        store_phase = next((p for p in phases if str(p.get("label")) == "11b"), None)
        if rc_sr != 0 and store_phase and str(store_phase.get("status")) == "APPROVED":
            blockers.append(B("store-readiness gate fails (check-store-readiness.sh exit %d) "
                            "even though 11b is APPROVED -- the approved store release no "
                            "longer satisfies its own gate." % rc_sr,
                        kind='GATE_CHAIN'))
        elif rc_sr != 0:
            L.append("  - not a phase-11 blocker: 11b has not been approved yet, and "
                     "check-store-readiness is 11b's own registered validator.")
        has11b = any(str(p.get("label")) == "11b" for p in phases)
        if not has11b:
            blockers.append(B("ruling is %s but phase.yaml carries no 11b phase; store release "
                            "cannot be gated." % profile,
                        kind='INSTRUMENT_ABSENT'))
    else:
        L.append("- **N/A** — the platform ruling is %s, so there is no store release."
                 % (profile or "unset"))
        na_lines.append(("not-applicable", "phase 11b (store release): N/A under ruling %s" % (profile or "unset")))

    L += ["", "## Evidence provenance", "",
          "- citations audited: **%d** (from %s) · waived: **%d**"
          % (len(prov_active), ", ".join(prov_src) or "nothing", len(prov_skipped)),
          "- release-strict: unknown provenance BLOCKS here, where a phase validator only warns."]
    if prov_errs:
        L += ["", "| Finding |", "|---|"] + ["| %s |" % e.replace("|", "\\|") for e in prov_errs]
    else:
        L += ["- no provenance findings"]
    for n in prov_notes:
        L.append("- note: %s" % n)

    L += ["", "## Approval freshness", ""]
    if fresh_rows:
        L += ["Each APPROVED phase against the paths its registered validators declare they",
              "verify (`verifies:` in registry.yaml), not against its own allow-list.", "",
              "| Phase | Approved at | Verdict | Detail |", "|---|---|---|---|"]
        L += ["| %s | `%s` | %s | %s |" % (a, b, c, dd.replace("|", "\\|"))
              for a, b, c, dd in fresh_rows]
    else:
        L += ["- no approved phase declares a `verifies:` set"]

    # ---- business outcomes: named, and explicitly NOT measured -------------
    # The BRD justifies the work with success metrics carrying baselines and
    # targets. Nothing in the harness has ever read them: no file under
    # harness/lib or harness/bin contained the string "SM-" before this. The
    # lifecycle terminates at release, so there is no state in which
    # post-release evidence could be attached either.
    #
    # This section does not measure anything and must never block. It exists so
    # that "we did not measure the outcome" is a STATEMENT ON THE RELEASE
    # DOCUMENT rather than a silence -- the same move as the 10c template's
    # "What this does NOT establish". An absent section and "no metrics
    # declared" must not look alike, so the section is always emitted.
    _sm = success_metrics(read(os.path.join(d, "00-brd.md")) or "")
    L += ["", "## Business outcomes", "",
          "**The harness does not measure these.** It verifies conformance — tests pass, "
          "evidence resolves, invariants hold — and has no mechanism, and no phase after "
          "release, in which to observe whether the outcome was achieved. They are listed "
          "so the omission is visible on the release document.", ""]
    if _sm:
        L += ["Declared as one prose field per metric in the BRD, so baseline, target and "
              "measurement date are shown as written rather than split into columns the "
              "format does not support.", "",
              "| Metric | Declared | Measured by the harness |", "|---|---|---|"]
        for sid, txt in _sm:
            L.append("| %s | %s | no |" % (sid, txt.replace("|", "\\|")))
        notes_line = ("%d business outcome metric(s) declared in the BRD; the harness measures "
                      "none of them." % len(_sm))
    else:
        L += ["_The BRD declares no `SM-*` success metrics._", "",
              "That is a finding about the BRD, not about this release: work justified by no "
              "stated outcome cannot be assessed against one later. It is reported here and "
              "does not block."]
        notes_line = ("the BRD declares no SM-* success metrics; there is no stated outcome to "
                      "measure this release against.")
    na_lines.append(("unmeasured", notes_line))

    L += ["", "## Waivers", "",
          "Every hole this release is signed off with, on its face. A missing expiry "
          "renders as **UNKNOWN**, never as `never`: those waivers predate the field, "
          "and nobody granted permanence. A **REVOKED** row is NOT a hole this release "
          "is signed off with -- it was withdrawn, and it is shown so the grant stays "
          "readable rather than vanishing from the record.", "",
          "| Rule | Path | Reason | Owner | Scope | Approver | Date | Expires |",
          "|---|---|---|---|---|---|---|---|"] + (waived_lines or
                                                  ["| _none_ | | | | | | | |"])

    # ---- the carry-forward backlog ---------------------------------------
    # The table above says what THIS release rests on. The backlog says what the
    # NEXT version has to clear, which is the thing that otherwise gets
    # rediscovered by accident a version later.
    _bl = W.backlog(w_rows)
    L += ["", "## Waiver backlog — carried into the next version", ""]
    if _bl:
        L += ["Undated first: an exception with no deadline is the one most likely to "
              "outlive everyone who remembers why it exists.", "",
              "| Due | Days | Rule | Path | Owner | Scope | Severity |",
              "|---|---|---|---|---|---|---|"]
        for b in _bl:
            L.append("| %s | %s | %s | %s | %s | %s | %s |"
                     % (b["due"], "—" if b["days"] is None else b["days"], b["rule"],
                        b["path"], b["owner"], b["scope"], b["severity"]))
    else:
        L += ["_nothing carried forward._"]
    if na_lines:
        for _k, _head, _tag in NA_KINDS:
            _rows = [t for k, t in na_lines if k == _k]
            if _rows:
                L += ["", "## %s" % _head, ""] + ["- %s" % x for x in _rows]
        # An unrecognised kind is NOT grouped away quietly. The default for a
        # classification this version does not know is loud: a line nobody
        # classified is a defect in the emitter, and filing it under a tidy
        # heading is the exact failure F30 exists to remove.
        _unk = [(k, t) for k, t in na_lines if k not in NA_TAG]
        if _unk:
            L += ["", "## UNCLASSIFIED", "",
                  "Emitted with a kind this report does not recognise. Shown rather than "
                  "grouped, because an unknown classification is a defect in whatever "
                  "produced it, not a category to file things under.", ""]
            L += ["- (kind %r) %s" % (k, t) for k, t in _unk]
    L += ["", "## Blockers", ""]
    L += (["- %s" % b for b in _real] if _real else ["_none_"])
    if _derived:
        L += ["", "## Follows from the above", "",
              "Not independent findings. These are consequences of the blockers "
              "listed above -- shown because a consequence that disappears is how a "
              "reader concludes the phases were skipped for no reason.", ""]
        _cause = (_real[0].text if _real else None)
        for b in _derived:
            L.append("- %s%s" % (b, ("\n  - follows from: %s" % _cause) if _cause
                                 else "\n  - follows from: nothing above; these phases "
                                      "are unapproved in their own right"))
    L += [""]

    if not args.no_write:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "11-scorecard.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(L) + "\n")

    if not args.quiet:
        print("build-scorecard: %s/11-scorecard.md" % d)
        print("  verification: %s · release: %s" % (verification, release))
        print("  tests %d/%d pass (%.1f%%) · SEC %d · stories %d"
              % (passed, total, pass_rate, len(verdicts), len(stories)))
        for _k, _x in na_lines:
            print("  %-5s %s" % (NA_TAG.get(_k, "?????"), _x))
        for b in _real:
            print("  BLOCK %s" % b)
        for b in _derived:
            print("  FOLLOWS %s" % b)
    return exit_code(verification, release)


if __name__ == "__main__":
    sys.exit(main())
