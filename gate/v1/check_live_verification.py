#!/usr/bin/env python3
"""check-live-verification — Phase 10a validator.

Phase 10a is where the harness stops reading documents about the system and
looks at the system running. This validator exists because a live-verification
report is trivially fakeable in prose: the only thing that distinguishes a real
run from a plausible narrative is **evidence files that exist on disk**.

So it checks three things, none of which a report can talk its way out of:

  1. **Every PRD story has a verdict.** Silence on a story is a failure, not a
     pass — the same rule as SEC-IDs in Phase 9.
  2. **Every verdict cites evidence that RESOLVES.** Each referenced path is
     opened; a missing file, an empty file, or a screenshot that is not actually
     an image fails. A citation to a file that is not there is the commonest way
     a verification report lies.
  3. **Every mandatory checklist item is covered.** Negative inputs,
     double-submit, back-button, refresh mid-flow, unauthorized access and
     mobile viewport are checked for every product regardless of what the
     stories happen to mention, because these are the flows teams skip.

A FAIL verdict is allowed only with a waiver in phase.yaml (rule
`live-verification`) carrying a reason and an approver. BLOCKED needs one too:
"we could not test it" is not a pass.

Exit 0 = pass, non-zero = fail.
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

VERDICTS = {"PASS", "FAIL", "BLOCKED", "NA", "N/A"}

# Checked for every product, whatever the stories say.
MANDATORY = [
    ("negative-inputs", r"negative[ -]inputs?"),
    ("double-submit", r"double[ -]submit"),
    ("back-button", r"back[ -]button"),
    ("refresh-mid-flow", r"refresh[ -]mid[ -]flow"),
    # v0.7: this ROW still exists, but it is no longer where authorization
    # is decided. It was ONE global checkbox, satisfied in v0.3 by a
    # page-load screenshot -- an artifact identical whether or not authz
    # existed. check-authz-matrix now requires a verdict per role x
    # resource on evidence that could have differed; this row remains as
    # the pointer to it, so a 10a report answering only this one is no
    # longer answering the question.
    ("unauthorized-access", r"unauthori[sz]ed[ -]access"),
    ("mobile-viewport", r"mobile[ -]viewport"),
]

IMAGE_MAGIC = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg", b"GIF8": "gif", b"RIFF": "webp"}


def strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return strip_comments(fh.read())


def prd_story_ids(path):
    text = read(path)
    if text is None:
        return None
    return sorted(set(re.findall(r"^#{2,4}\s+((?:US|NFR)-\d+)\b", text, re.M)))


def blocks(text, pattern):
    out, cur, cid = {}, [], None
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+(%s)\b" % pattern, line.strip())
        if m:
            if cid:
                out[cid] = "\n".join(cur)
            cid, cur = m.group(1), [line]
        elif cid:
            if re.match(r"^#{1,4}\s+", line.strip()) and not re.match(r"^#{2,4}\s+%s\b" % pattern,
                                                                     line.strip()):
                out[cid] = "\n".join(cur); cid, cur = None, []
            else:
                cur.append(line)
    if cid:
        out[cid] = "\n".join(cur)
    return out


def field(block, name):
    m = re.search(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+?)\s*$" % re.escape(name), block, re.I | re.M)
    return m.group(1).strip() if m else None


def evidence_paths(spec):
    """Extract candidate file paths from an Evidence field."""
    out = []
    for tok in re.split(r"[,\s]+", spec or ""):
        tok = tok.strip().strip("`'\"()[]")
        if not tok:
            continue
        if re.search(r"\.(png|jpg|jpeg|gif|webp|txt|log|json|md|har)$", tok, re.I):
            out.append(tok)
    return out


def verify_file(root, rel):
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        return "does not exist"
    if os.path.getsize(p) == 0:
        return "is empty"
    if re.search(r"\.(png|jpg|jpeg|gif|webp)$", rel, re.I):
        with open(p, "rb") as fh:
            head = fh.read(8)
        if not any(head.startswith(m) for m in IMAGE_MAGIC):
            return "is not a real image (bad magic bytes)"
    return None


def lighthouse_scores(path):
    """Normalise a Lighthouse report to {category: 0-100}.

    Accepts the raw LHR shape (categories.<id>.score as 0..1) and the flat shape
    a tool wrapper may emit ({"performance": 92}). Being tolerant here matters:
    the MCP's exact output shape is not a contract we control, and a validator
    that only understands one shape would silently report "not captured".
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    out = {}
    cats = data.get("categories") if isinstance(data, dict) else None
    if isinstance(cats, dict):
        for k, v in cats.items():
            sc = v.get("score") if isinstance(v, dict) else v
            if isinstance(sc, (int, float)):
                out[str(k)] = round(float(sc) * 100) if sc <= 1 else round(float(sc))
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (int, float)):
                out[str(k)] = round(float(v) * 100) if v <= 1 else round(float(v))
    return out or None


def check_lighthouse(root, groot, errs, warns, notes, wv):
    cfgp = hlib.config_path(root, "quality-thresholds.yaml")
    if not os.path.exists(cfgp):
        return
    try:
        cfg = (hlib.load_yaml(cfgp) or {}).get("lighthouse") or {}
    except Exception as exc:
        errs.append("quality-thresholds.yaml does not parse (%r)" % (exc,))
        return
    if not cfg:
        return
    found = sorted(glob.glob(os.path.join(root, groot, "evidence", "live", "**",
                                          "*lighthouse*.json"), recursive=True))
    if not found:
        msg = ("no Lighthouse report found under evidence/live/**. The MCP exposes "
               "`lighthouse_audit`; capture it during the 10a run and save the JSON "
               "into the run's evidence directory.")
        (errs if cfg.get("required") else warns).append(msg)
        return
    scores = lighthouse_scores(found[-1])
    if not scores:
        errs.append("Lighthouse report %s has no readable category scores."
                    % os.path.relpath(found[-1], root))
        return
    notes.append("lighthouse: %s" % ", ".join("%s=%d" % (k, v) for k, v in sorted(scores.items())))
    for cat, spec in (cfg.get("categories") or {}).items():
        thr = spec.get("threshold") if isinstance(spec, dict) else spec
        enforced = spec.get("enforced", True) if isinstance(spec, dict) else True
        got = scores.get(str(cat))
        if got is None:
            (errs if enforced else warns).append(
                "Lighthouse category %r was not captured (threshold %s)." % (cat, thr))
            continue
        if thr is not None and got < int(thr):
            key = "lighthouse:%s" % cat
            if key in wv:
                notes.append("lighthouse %s=%d below %s but waived by %s"
                             % (cat, got, thr, wv[key].get("approver")))
            elif enforced:
                errs.append("Lighthouse %s = %d, below the threshold of %s. Fix it, or waive with "
                            "`harness/bin/gate.sh waive live-verification --path %s "
                            "--reason \"...\" --approver \"...\"`." % (cat, got, thr, key))
            else:
                warns.append("Lighthouse %s = %d, below %s (not enforced)." % (cat, got, thr))


def waivers(root, rule="live-verification"):
    try:
        doc = hlib.load_phase_doc(root)
    except Exception:
        return {}
    return {str(w.get("path")): w for w in hlib.waivers_for(doc, rule)
            if w.get("reason") and w.get("approver")}


def citations(root, groot, d, text=None):
    """[(claim_id, relpath)] this report cites, for the provenance audit.

    ONE parser, two callers: this validator (during phase 10a, where unknown
    provenance WARNs) and the phase-11 scorecard (at release, where it BLOCKS).
    A second copy of this walk in build_scorecard is exactly how two parsers
    drift apart -- build_scorecard already carries a comment saying so.
    """
    if text is None:
        text = read(os.path.join(d, "10a-live-verification.md")) or ""
    out = []
    for sid, blk in sorted(blocks(text, r"(?:US|NFR)-\d+").items()):
        for rel in evidence_paths(field(blk, "Evidence") or ""):
            out.append(("10a:%s" % sid, rel))
    lines = text.splitlines()
    for name, pat in MANDATORY:
        row = next((ln for ln in lines
                    if re.search(pat, ln, re.I) and ln.strip().startswith("|")), "")
        for rel in evidence_paths(row):
            out.append(("10a:%s" % name, rel))
    return out


def main():
    ap = argparse.ArgumentParser(prog="check-live-verification.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        paths_doc = hlib.load_paths_doc(root) or {}
    except Exception:
        paths_doc = {}
    groot = paths_doc.get("governed_root") or ""
    d = args.dir or os.path.join(root, groot, "sdlc")

    errs, warns, notes = [], [], []
    wv = waivers(root)

    prd_path = os.path.join(d, "02-prd.md")
    stories = prd_story_ids(prd_path)
    if stories is None:
        errs.append("PRD not found at %s/02-prd.md; nothing to verify against." % d)
        stories = []
    else:
        # A PRD that EXISTS and parses to zero stories is a THIRD state. The
        # per-story loop below then never runs, so every story-level check is
        # vacuously satisfied -- and the summary line was guarded by
        # `if stories:`, so the zero case printed nothing at all.
        stories = hlib.parsed_set(stories, True, "the story heading parse",
                                  os.path.relpath(prd_path, root), errs)

    report_path = os.path.join(d, "10a-live-verification.md")
    text = read(report_path)
    if text is None:
        errs.append("live-verification report not found at %s. Phase 10a cannot be approved "
                    "without it." % report_path)
        text = ""

    base_url = field(text, "Target URL") or field(text, "Base URL")
    if not base_url:
        errs.append("report records no '**Target URL:**'. A live verification with no recorded "
                    "target is not reproducible.")
    else:
        notes.append("target: %s" % base_url)

    total_ev, bad_ev = 0, 0

    # ---- 1 + 2: per-story verdicts with resolving evidence ---------------
    sblocks = blocks(text, r"(?:US|NFR)-\d+")
    for sid in stories:
        blk = sblocks.get(sid)
        if blk is None:
            errs.append("PRD story %s has no verdict in the live-verification report. Silence on "
                        "a story is a failure, not a pass." % sid)
            continue
        verdict = (field(blk, "Verdict") or "").strip().upper()
        if verdict not in VERDICTS:
            errs.append("%s: Verdict %r is not one of %s." % (sid, verdict or "(missing)",
                                                              sorted(VERDICTS)))
            continue
        ev = field(blk, "Evidence") or ""
        paths = evidence_paths(ev)
        if verdict in ("PASS", "FAIL") and not paths:
            errs.append("%s is %s but cites no evidence files. A verdict with no artefact is a "
                        "claim." % (sid, verdict))
        for rel in paths:
            total_ev += 1
            why = verify_file(root, rel)
            if why:
                bad_ev += 1
                errs.append("%s evidence %s %s. Evidence that is not on disk is not evidence."
                            % (sid, rel, why))
        if verdict in ("FAIL", "BLOCKED") and sid not in wv:
            errs.append("%s is %s with no waiver. Record one with `harness/bin/gate.sh waive "
                        "live-verification --path %s --reason \"...\" --approver \"...\"`, or fix "
                        "the product." % (sid, verdict, sid))
        elif verdict in ("FAIL", "BLOCKED"):
            notes.append("%s %s but waived by %s" % (sid, verdict, wv[sid].get("approver")))

    # ---- 3: the mandatory checklist --------------------------------------
    low = text.lower()
    for name, pat in MANDATORY:
        m = re.search(r"^\|\s*%s\s*\|([^|]*)\|([^|]*)\|" % pat, low, re.M)
        if not m:
            errs.append("mandatory check %r is missing from the report. It is required for every "
                        "product regardless of what the stories mention." % name)
            continue
        verdict = m.group(1).strip().upper()
        if verdict not in {v.lower().upper() for v in VERDICTS}:
            errs.append("mandatory check %r has verdict %r, not one of %s."
                        % (name, verdict, sorted(VERDICTS)))
            continue
        # evidence column
        seg = text.splitlines()
        row = next((l for l in seg if re.search(pat, l, re.I) and l.strip().startswith("|")), "")
        paths = evidence_paths(row)
        if verdict in ("PASS", "FAIL") and not paths:
            errs.append("mandatory check %r has verdict %s but cites no evidence file."
                        % (name, verdict))
        for rel in paths:
            total_ev += 1
            why = verify_file(root, rel)
            if why:
                bad_ev += 1
                errs.append("mandatory check %r evidence %s %s." % (name, rel, why))
        if verdict in ("FAIL", "BLOCKED") and ("mandatory:" + name) not in wv:
            errs.append("mandatory check %r is %s with no waiver (use --path mandatory:%s)."
                        % (name, verdict, name))

    check_lighthouse(root, groot, errs, warns, notes, wv)

    # Provenance audit -- the shared implementation (Constitution 4.5). The
    # loops above asked whether each file EXISTS; this asks the two questions
    # existence cannot: does it still describe this tree, and was it produced
    # for the claim it is cited for.
    import provenance
    _pe, _pw, _pn = provenance.audit(root, groot, citations(root, groot, d, text))
    errs += _pe
    warns += _pw
    notes += _pn

    if total_ev:
        notes.append("evidence files referenced: %d, resolved: %d" % (total_ev, total_ev - bad_ev))
    # ALWAYS printed, including the zero case. The `if stories:` guard is what
    # made the vacuous pass silent: no stories, no line, nothing to notice.
    notes.append("stories: %d, with a verdict: %d" % (len(stories), len(sblocks & set(stories))
                                                      if isinstance(sblocks, set)
                                                      else len([s for s in stories if s in sblocks])))

    if not args.quiet:
        print("check-live-verification: %s" % report_path)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  %d story verdict(s) and %d mandatory check(s), all with evidence that "
                  "resolves on disk." % (len(stories), len(MANDATORY)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
