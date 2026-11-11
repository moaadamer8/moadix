#!/usr/bin/env python3
"""check-handoff — validator for the phase 0/1/2 handoff artifacts.

Phases 0-2 are authored in Claude chat and imported. Nothing about that flow is
trustworthy on its own: the documents arrive as prose and the harness has no way
to know whether they are complete. This script reads them off disk and decides.

Scope is phase-aware, because phase 0 must be approvable before phase 2 exists:

  --phase 0   BRD only        platform ruling, size, >=1 BG goal, no placeholders
  --phase 1   + research      every DECIDED entry has alternatives AND a primary
                              source; if the ruling is WEB->APP, also a
                              stack-portability score and a migration cost
  --phase 2   + PRD           every story has a BRD goal and >=1 EARS criterion;
                              orphan detection BOTH ways (story -> missing goal,
                              goal -> no story)

Exit 0 = pass. Non-zero = fail, with every reason printed.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

def _rulings():
    """Accepted spellings, derived from check_profile.CANON plus the ASCII alias.

    This was a literal set and had drifted from CANON by exactly one entry. The
    vocabulary has ONE owner; the alias is a parsing affordance, declared here as
    an alias rather than as a fourth ruling.
    """
    import check_profile
    canon = {str(v) for v in check_profile.CANON.values()}
    return canon | {"WEB->APP"}          # ASCII spelling of WEB→APP, accepted on input


RULINGS = _rulings()
SIZES = {"S", "M", "L"}
PRIORITIES = {"must", "should", "could", "wont"}

# An unfilled template placeholder. Catches an imported document that was never
# actually written -- the most common failure of a copy-paste handoff.
PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_ .\-/]*\}")

EARS_LEAD = re.compile(r"^(The|When|While|Where|If)\b", re.I)


def field(block, name):
    m = re.search(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+?)\s*$" % re.escape(name), block, re.I | re.M)
    return m.group(1).strip() if m else None


def blocks(text, prefix):
    """Split into '### <PREFIX>-NNN' sections keyed by id."""
    out, cur, cid = {}, [], None
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+(%s-\d+)\b" % prefix, line.strip())
        if m:
            if cid:
                out[cid] = "\n".join(cur)
            cid, cur = m.group(1), [line]
        elif cid:
            if re.match(r"^#{1,4}\s+", line.strip()) and not re.match(r"^#{2,4}\s+%s-\d+" % prefix, line.strip()):
                out[cid] = "\n".join(cur); cid, cur = None, []
            else:
                cur.append(line)
    if cid:
        out[cid] = "\n".join(cur)
    return out


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return strip_comments(fh.read())


def is_ears(s):
    s = s.strip().rstrip(".")
    if not EARS_LEAD.match(s):
        return False, "must begin with The / When / While / Where / If"
    if not re.search(r"\bshall\b", s, re.I):
        return False, "must contain 'shall'"
    lead = EARS_LEAD.match(s).group(1).lower()
    if lead == "if" and not re.search(r"\bthen\b", s, re.I):
        return False, "unwanted-behaviour form is 'If <condition>, then the <system> shall <response>'"
    if lead in ("when", "while", "where") and "," not in s:
        return False, "%s-form needs a comma before the system clause" % lead
    return True, ""


# --------------------------------------------------------------------------

def check_brd(path, errs, warns):
    text = read(path)
    if text is None:
        errs.append("BRD not found at '%s'. Phase 0 cannot be approved without it." % path)
        return None, None
    ruling = field(text, "Target Platform Ruling")
    if not ruling:
        errs.append("BRD: missing '**Target Platform Ruling:**'. This is mandatory and binds every "
                    "downstream phase.")
    elif ruling not in RULINGS:
        errs.append("BRD: Target Platform Ruling %r is not one of WEB | WEB→APP | APP-FIRST." % ruling)
    if not field(text, "Ruling rationale"):
        warns.append("BRD: Target Platform Ruling has no '**Ruling rationale:**'. A ruling with no "
                     "reason cannot be re-evaluated later.")
    size = field(text, "Size")
    if not size:
        errs.append("BRD: missing '**Size:**' (S | M | L).")
    elif size not in SIZES:
        errs.append("BRD: Size %r is not one of S | M | L." % size)

    goals = {}
    for m in re.finditer(r"^\|\s*(BG-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", text, re.M):
        gid, goal, metric, prio = (x.strip() for x in m.groups())
        goals[gid] = {"goal": goal, "metric": metric, "priority": prio}
        if not goal:
            errs.append("BRD: %s has an empty Goal cell." % gid)
        if not metric:
            errs.append("BRD: %s has no success metric. A goal with no metric cannot be verified." % gid)
    if not goals:
        errs.append("BRD: no business goals found. Expected rows '| BG-1 | goal | metric | priority |' "
                    "under '## Business Goals'.")

    for sec in ("Constraints", "Success Metrics", "Business Risks", "Out of Scope"):
        if not re.search(r"^##\s+%s" % re.escape(sec), text, re.M | re.I):
            errs.append("BRD: missing required section '## %s'." % sec)
    if re.search(r"^##\s+Out of Scope\s*$", text, re.M | re.I):
        tail = text.split("## Out of Scope", 1)[1]
        if not re.search(r"^\s*[-*]\s+\S", tail, re.M):
            errs.append("BRD: '## Out of Scope' is empty. Nothing ruled out means nothing was decided.")

    ph = [p for p in PLACEHOLDER.findall(text) if p not in ("{governed_root}",)]
    if ph:
        errs.append("BRD: unfilled template placeholders remain: %s" % sorted(set(ph))[:6])
    return ruling, goals


def check_research(path, ruling, errs, warns):
    text = read(path)
    if text is None:
        errs.append("Research/decision log not found at '%s'. Phase 1 cannot be approved without it." % path)
        return
    rds = blocks(text, "RD")
    if not rds:
        errs.append("Research: no decision-log entries found. Expected '### RD-001 — <title>' sections.")
        return
    portable_required = ruling in ("WEB→APP", "WEB->APP")
    decided = 0
    for rid in sorted(rds):
        blk = rds[rid]
        status = (field(blk, "Status") or "").strip().upper()
        if status not in ("DECIDED", "OPEN", "SUPERSEDED"):
            errs.append("%s: Status %r is not DECIDED | OPEN | SUPERSEDED." % (rid, status or "(missing)"))
            continue
        if status != "DECIDED":
            continue
        decided += 1
        alts = field(blk, "Alternatives considered")
        if not alts:
            errs.append("%s is DECIDED but records no '**Alternatives considered:**'. A decision with "
                        "no alternatives is a preference." % rid)
        src = field(blk, "Primary source")
        if not src:
            errs.append("%s is DECIDED but cites no '**Primary source:**' (Constitution §5.1)." % rid)
        elif not re.match(r"^(https?://|/|\.{0,2}/|[A-Za-z0-9_.\-]+/)", src):
            warns.append("%s: primary source %r does not look like a URL or a path." % (rid, src))
        if not field(blk, "Decision"):
            errs.append("%s is DECIDED but has no '**Decision:**' statement." % rid)
        if portable_required:
            score = field(blk, "Stack portability score")
            cost = field(blk, "Migration cost estimate")
            if not score:
                errs.append("%s: the platform ruling is WEB→APP, so every DECIDED entry needs a "
                            "'**Stack portability score:**' (1-5)." % rid)
            else:
                m = re.match(r"^\s*([1-5])\s*(?:/\s*5)?\s*$", score)
                if not m:
                    errs.append("%s: stack portability score %r must be an integer 1-5 (e.g. '4/5')."
                                % (rid, score))
            if not cost:
                errs.append("%s: the platform ruling is WEB→APP, so every DECIDED entry needs a "
                            "'**Migration cost estimate:**'. A portability score with no cost attached "
                            "has no consequence." % rid)
    if decided == 0:
        warns.append("Research: no DECIDED entries. Phase 1 approval with only OPEN questions means "
                     "nothing was actually settled.")
    ph = PLACEHOLDER.findall(text)
    if ph:
        errs.append("Research: unfilled template placeholders remain: %s" % sorted(set(ph))[:6])


def check_prd(path, goals, errs, warns):
    text = read(path)
    if text is None:
        errs.append("PRD not found at '%s'. Phase 2 cannot be approved without it." % path)
        return
    stories = {}
    stories.update(blocks(text, "US"))
    stories.update(blocks(text, "NFR"))
    if not stories:
        errs.append("PRD: no user stories found. Expected '### US-001 — <title>' sections.")
        return

    covered = set()
    for sid in sorted(stories):
        blk = stories[sid]
        goal = field(blk, "BRD goal")
        if not goal:
            errs.append("%s: missing '**BRD goal:**'. Every story must trace to a BRD goal ID." % sid)
        else:
            refs = re.findall(r"\bBG-\d+\b", goal)
            if not refs:
                errs.append("%s: '**BRD goal:**' %r names no BG-<n>." % (sid, goal))
            for ref in refs:
                if goals is not None and ref not in goals:
                    errs.append("%s references BRD goal %s, which does not exist in the BRD "
                                "(orphan story)." % (sid, ref))
                else:
                    covered.add(ref)
        prio = (field(blk, "Priority") or "").strip().lower()
        if not prio:
            errs.append("%s: missing '**Priority:**'." % sid)
        elif prio not in PRIORITIES:
            errs.append("%s: Priority %r is not one of %s." % (sid, prio, sorted(PRIORITIES)))

        acs = re.findall(r"^\s*[-*]\s*\*\*AC-\d+:?\*\*\s*(.+?)\s*$", blk, re.M)
        if not acs:
            errs.append("%s: no acceptance criteria. Expected '- **AC-1:** <EARS sentence>'." % sid)
        for i, ac in enumerate(acs, 1):
            ok, why = is_ears(ac)
            if not ok:
                errs.append("%s AC-%d is not EARS (%s): %r" % (sid, i, why, ac[:90]))

    if goals:
        for gid in sorted(goals):
            if gid not in covered:
                errs.append("BRD goal %s (%s) has no PRD story covering it (orphan goal)."
                            % (gid, goals[gid]["goal"][:50]))
    ph = PLACEHOLDER.findall(text)
    if ph:
        errs.append("PRD: unfilled template placeholders remain: %s" % sorted(set(ph))[:6])


def main():
    ap = argparse.ArgumentParser(prog="check-handoff.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", default="2", choices=["0", "1", "2"],
                    help="how much of the handoff to validate (default 2 = all of it)")
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    d = args.dir
    if not d:
        try:
            groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
        except Exception:
            groot = ""
        d = os.path.join(root, groot, "sdlc")

    errs, warns = [], []
    ruling, goals = check_brd(os.path.join(d, "00-brd.md"), errs, warns)
    if args.phase in ("1", "2"):
        check_research(os.path.join(d, "01-research.md"), ruling, errs, warns)
    if args.phase == "2":
        check_prd(os.path.join(d, "02-prd.md"), goals, errs, warns)

    if not args.quiet:
        print("check-handoff (phase %s): %s" % (args.phase, d))
        if ruling:
            print("  ruling: %s" % ruling)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            n = len(goals or {})
            print("  PASS  %d BRD goal(s), handoff consistent through phase %s." % (n, args.phase))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
