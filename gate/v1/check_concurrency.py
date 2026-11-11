#!/usr/bin/env python3
"""check-concurrency — Phase 10c validator.

Phase 10a asks whether the product works when one person uses it. 10c asks
whether it still works when several do at once. Those are different questions
and the harness could answer only the first: every gate up to v0.4 exercised
the product serially, so a lost update, a double-charged submit or an
interleaving that violates an invariant would pass every one of them.

WHAT IT CHECKS

  1. Every CON-ID from the phase-4 threat model marked `Contention: true` has a
     verdict here. Silence on a declared contention point is a failure, exactly
     as silence on a SEC-ID is in phase 9.
  2. The run actually raced. A "concurrency test" with one client is a
     sequential test with an ambitious name, so the recorded client count must
     meet the configured minimum.
  3. THE RACE WAS REPEATED. This is the check that matters most and the one
     teams skip. A race that passes once proves nothing: interleavings are
     sampled, not enumerated, and the failing schedule may simply not have
     occurred. A single green run is evidence about that run, not about the
     product. The report must record repeats, and the minimum is configured.
  4. Idempotency is verified wherever phase 4 declared it. A CON-ID whose
     `Idempotency:` is `client-key` or `natural` claims a property that only a
     duplicate-delivery test can demonstrate.
  5. Every cited evidence file resolves on disk and is non-empty, and its
     provenance is audited (Constitution 4.5) -- a concurrency log is exactly
     the kind of artifact that looks the same whether or not the race ran.
  6. FAIL or BLOCKED needs a waiver with a reason and an approver. "We could
     not test it under load" is not a pass.

Exit 0 = pass, non-zero = fail.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

VERDICTS = {"PASS", "FAIL", "BLOCKED", "NA", "NA-ENVIRONMENT"}

# Required of every product that has any contended resource at all. These are
# the concurrency failure modes that reach users, in the order they usually do.
MANDATORY = [
    ("lost-update", "two writers, last-write-wins: the invariant must survive"),
    ("duplicate-submit", "the same request delivered twice must not take effect twice"),
    ("race-repeat", "the race is REPEATED; a schedule that did not occur is not a schedule "
                    "that cannot occur"),
    ("saturation", "the product under more load than it is sized for degrades, not corrupts"),
]

DEFAULTS = {"min_clients": 8, "min_repeats": 5}


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)


def field(text, name):
    m = re.search(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+?)\s*$" % re.escape(name), text or "",
                  re.I | re.M)
    return m.group(1).strip() if m else None


def first_int(s):
    m = re.search(r"\d+", str(s or ""))
    return int(m.group(0)) if m else None


def table_rows(text, section_title, ncols):
    """Rows of the table under '## <section_title>', as lists of cells."""
    if not text:
        return []
    m = re.search(r"^##\s+%s\s*$" % re.escape(section_title), text, re.I | re.M)
    if not m:
        return []
    body = re.split(r"^##\s+(?!#)", text[m.end():], maxsplit=1, flags=re.M)[0]
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- :"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < ncols:
            continue
        if cells[0].lower() in ("con-id", "check", "id"):
            continue
        out.append(cells)
    return out


def evidence_paths(spec):
    out = []
    for tok in re.split(r"[,\s]+", spec or ""):
        tok = tok.strip().strip("`").strip()
        if tok and tok not in ("-", "—") and "/" in tok:
            out.append(tok)
    return out


def contention_points(sdlc_dir):
    """{CON-ID: {'contended': bool, 'idempotency': str}} from the phase-4 model."""
    text = read(os.path.join(sdlc_dir, "04-threat-model.md"))
    if text is None:
        return None
    sys.path.insert(0, HERE)
    import check_threat_model as ctm
    out = {}
    for cid, blk in ctm.parse_blocks(text, "CON").items():
        val = (ctm.field(blk, "Contention") or "").strip().lower().rstrip(".")
        idem = (ctm.field(blk, "Idempotency") or "").strip().lower().rstrip(".")
        out[cid] = {"contended": val.split()[0] in ("true", "yes") if val else False,
                    "idempotency": idem.split()[0] if idem else "none"}
    return out


def waivers(root, rule="concurrency"):
    try:
        doc = hlib.load_phase_doc(root) or {}
    except Exception:
        return {}
    return {str(w.get("path")): w for w in hlib.waivers_for(doc, rule)
            if w.get("reason") and w.get("approver")}


def thresholds(root):
    cfg = {}
    try:
        cfg = (hlib.load_yaml(hlib.config_path(root, "concurrency.yaml")) or {})
    except Exception:
        cfg = {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        v = cfg.get(k)
        if isinstance(v, int) and v > 0:
            out[k] = v
    return out


def verify_file(root, groot, rel):
    for cand in (os.path.join(root, groot, rel), os.path.join(root, rel)):
        if os.path.exists(cand):
            return None if os.path.getsize(cand) > 0 else "is empty"
    return "does not exist on disk"


def main():
    ap = argparse.ArgumentParser(prog="check-concurrency.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    d = args.dir or os.path.join(root, groot, "sdlc")

    errs, warns, notes = [], [], []
    wv = waivers(root)
    thr = thresholds(root)

    points = contention_points(d)
    if points is None:
        errs.append("phase-4 threat model not found at %s/04-threat-model.md; there is nothing "
                    "to verify contention against." % d)
        points = {}
    contended = sorted(c for c, v in points.items() if v["contended"])
    notes.append("phase 4 declares %d CON-ID(s), %d contended" % (len(points), len(contended)))

    report = os.path.join(d, "10c-concurrency.md")
    text = read(report)
    if text is None:
        text = ""
        if contended:
            errs.append("concurrency report not found at %s. Phase 10c cannot be approved "
                        "without it." % report)
        else:
            # Nothing is contended and nothing was claimed. Phase 4 already
            # forced that claim to be WRITTEN and checked it, so 10c has no work
            # here -- demanding a report anyway would be shape-matching, and it
            # would push products toward inventing contention to have something
            # to fill it with.
            notes.append("the threat model declares no contended resource; 10c is a no-op "
                         "for this product. Phase 4 is where that claim was made and "
                         "checked, and it is not re-litigated here.")

    target = field(text, "Target")
    if contended and not target:
        errs.append("report records no '**Target:**'. A load run with no recorded target is "
                    "not reproducible.")

    clients = first_int(field(text, "Clients"))
    repeats = first_int(field(text, "Repeats"))
    if contended:
        if clients is None:
            errs.append("report records no '**Clients:**' count.")
        elif clients < thr["min_clients"]:
            errs.append("the run used %d concurrent client(s); the configured minimum is %d. "
                        "A concurrency test with one client is a sequential test with an "
                        "ambitious name." % (clients, thr["min_clients"]))
        else:
            notes.append("clients: %d" % clients)
        if repeats is None:
            errs.append("report records no '**Repeats:**' count. A race that passes ONCE "
                        "proves nothing: interleavings are sampled, not enumerated, and the "
                        "failing schedule may simply not have occurred.")
        elif repeats < thr["min_repeats"]:
            errs.append("the race was repeated %d time(s); the configured minimum is %d. One "
                        "green run is evidence about that run, not about the product."
                        % (repeats, thr["min_repeats"]))
        else:
            notes.append("repeats: %d" % repeats)

    citations = []

    # ---- contention verdicts ----------------------------------------------
    rows = {r[0].upper(): r for r in table_rows(text, "Contention verdicts", 4)}
    for cid in contended:
        r = rows.get(cid)
        if r is None:
            errs.append("%s is marked `Contention: true` in the threat model and has NO verdict "
                        "here. Silence on a declared contention point is a failure, exactly as "
                        "silence on a SEC-ID is in phase 9." % cid)
            continue
        verdict = r[2].strip().upper() if len(r) > 2 else ""
        if verdict not in VERDICTS:
            errs.append("%s: verdict %r is not one of %s." % (cid, verdict, sorted(VERDICTS)))
            continue
        paths = evidence_paths(r[3] if len(r) > 3 else "")
        if verdict in ("PASS", "FAIL") and not paths:
            errs.append("%s is %s but cites no evidence file. A verdict with no artefact is a "
                        "claim." % (cid, verdict))
        for rel in paths:
            citations.append(("10c:%s" % cid, rel))
            why = verify_file(root, groot, rel)
            if why:
                errs.append("%s evidence %s %s." % (cid, rel, why))
        if verdict in ("FAIL", "BLOCKED") and cid not in wv:
            errs.append("%s is %s with no waiver. Record one with `harness/bin/gate.sh waive "
                        "concurrency --path %s --reason \"...\" --approver \"...\"`, or fix the "
                        "product." % (cid, verdict, cid))

    for cid in sorted(set(rows) - set(points)):
        warns.append("report carries a verdict for %s, which is not a CON-ID in the threat "
                     "model." % cid)

    # ---- idempotency, where phase 4 claimed it ----------------------------
    irows = {r[0].upper(): r for r in table_rows(text, "Idempotency verdicts", 4)}
    for cid, v in sorted(points.items()):
        mode = v["idempotency"]
        if mode not in ("client-key", "natural"):
            continue
        r = irows.get(cid)
        if r is None:
            errs.append("%s declares idempotency %r in the threat model and has no idempotency "
                        "verdict here. A claimed idempotency that no duplicate-delivery test "
                        "exercises is a claim." % (cid, mode))
            continue
        verdict = r[2].strip().upper() if len(r) > 2 else ""
        if verdict not in VERDICTS:
            errs.append("%s idempotency: verdict %r is not one of %s."
                        % (cid, verdict, sorted(VERDICTS)))
            continue
        for rel in evidence_paths(r[3] if len(r) > 3 else ""):
            citations.append(("10c:%s:idempotency" % cid, rel))
            why = verify_file(root, groot, rel)
            if why:
                errs.append("%s idempotency evidence %s %s." % (cid, rel, why))
        if verdict in ("FAIL", "BLOCKED") and ("%s:idempotency" % cid) not in wv:
            errs.append("%s idempotency is %s with no waiver." % (cid, verdict))

    # ---- the mandatory checklist ------------------------------------------
    if contended:
        mrows = {r[0].lower(): r for r in table_rows(text, "Mandatory checks", 3)}
        for name, why in MANDATORY:
            r = mrows.get(name)
            if r is None:
                errs.append("mandatory concurrency check %r is missing from the report (%s)."
                            % (name, why))
                continue
            verdict = r[1].strip().upper() if len(r) > 1 else ""
            if verdict not in VERDICTS:
                errs.append("mandatory check %r has verdict %r, not one of %s."
                            % (name, verdict, sorted(VERDICTS)))
                continue
            for rel in evidence_paths(r[2] if len(r) > 2 else ""):
                citations.append(("10c:%s" % name, rel))
                why2 = verify_file(root, groot, rel)
                if why2:
                    errs.append("mandatory %r evidence %s %s." % (name, rel, why2))
            if verdict in ("FAIL", "BLOCKED") and ("mandatory:%s" % name) not in wv:
                errs.append("mandatory check %r is %s with no waiver." % (name, verdict))

    # ---- provenance (Constitution 4.5) ------------------------------------
    # A concurrency log is exactly the artifact that looks the same whether or
    # not the race ran, so it is audited like any other evidence.
    try:
        import provenance
        pe, pw, pn = provenance.audit(root, groot, citations)
        errs += pe
        warns += pw
        notes += pn
    except Exception as exc:
        warns.append("provenance audit unavailable (%r)" % (exc,))

    if not args.quiet:
        print("check-concurrency: %s" % report)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            if contended:
                print("  PASS  %d contended resource(s) raced by %s client(s), %s time(s), "
                      "with evidence that resolves." % (len(contended), clients, repeats))
            else:
                print("  PASS  the threat model declares no contended resource; nothing to race.")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
