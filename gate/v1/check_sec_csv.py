#!/usr/bin/env python3
"""check-sec-csv -- shape checks of SEC-CONTROLS.csv (phase 4) and SEC-VERIFICATION.csv (phase 9)
(increment 7b; Amendment 3 phases 4 and 9). Reads committed files only.

    check_sec_csv.py --phase 4|9

Phase 4: <scope>/4/SEC-CONTROLS.csv with columns sec_id, th_id, asvs_id, verification.
  - every SEC-ID the scope's threat model defines has a row; every TH- threat has a row (a
    control, or `accepted-risk` in sec_id with the record named in verification);
  - IDs well formed and defined; ASVS IDs shaped as ASVS 5.0.0 requirement IDs, chapters V1-V17
    (shape only: the ASVS text is CC BY-SA and is not vendored, so existence is not checked);
  - a verification method in words; no duplicate row.
Phase 9: <scope>/9/SEC-VERIFICATION.csv with columns sec_id, method, evidence, result.
  - every SEC-ID of the phase-4 controls has a row; result verified | failed | accepted-risk;
  - evidence named; a path is a file at HEAD; a failed SEC-ID fails the phase; accepted-risk
    names the residual-risk acceptance record (SV16).

Exit 0 pass, 1 fail, 2 UNKNOWN.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import readonly  # noqa: E402
import toolrun  # noqa: E402

ASVS = re.compile(r"^V(?:[1-9]|1[0-7])\.\d{1,2}\.\d{1,2}$")
SEC = re.compile(r"^SEC-\d+$")
TH = re.compile(r"^TH-\d+$")
RESULTS = ("verified", "failed", "accepted-risk")


def threat_docs(root, base):
    d = os.path.join(root, base)
    texts = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if re.match(r"^04-.*\.md$", f):
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    texts.append(fh.read())
    return texts


def phase4(root, base, errs, notes):
    rel = "%s/4/SEC-CONTROLS.csv" % base
    rows, probs = readonly.read_csv(os.path.join(root, rel), ["sec_id", "th_id", "asvs_id", "verification"])
    if rows is None:
        errs.append("%s is missing: SEC-ID -> TH-ID -> ASVS ID -> verification method (phase 4 gate)" % rel)
        return
    errs += probs
    texts = threat_docs(root, base)
    secs, ths = readonly.defined_ids(texts, "SEC"), readonly.defined_ids(texts, "TH")
    seen, got_sec, got_th = set(), set(), set()
    for r in rows:
        where = "%s line %d" % (rel, r["_line"])
        sid, tid, aid, ver = r["sec_id"], r["th_id"], r["asvs_id"], r["verification"]
        key = (sid, tid, aid)
        if key in seen:
            errs.append("%s: duplicate row %s / %s / %s" % (where, sid, tid, aid))
        seen.add(key)
        if not TH.match(tid):
            errs.append("%s: th_id %r is not TH-n" % (where, tid))
        elif tid not in ths:
            errs.append("%s: %s is not a threat the threat model defines" % (where, tid))
        got_th.add(tid)
        if sid.lower() == "accepted-risk":
            if len(re.findall(r"[A-Za-z]{2,}", ver)) < 3:
                errs.append("%s: an accepted-risk row names its acceptance record in verification" % where)
            continue
        if not SEC.match(sid):
            errs.append("%s: sec_id %r is not SEC-n (or accepted-risk)" % (where, sid))
        elif sid not in secs:
            errs.append("%s: %s is not a SEC-ID the threat model defines" % (where, sid))
        got_sec.add(sid)
        if not ASVS.match(aid):
            errs.append("%s: asvs_id %r is not an ASVS 5.0.0 requirement ID (V1-V17, e.g. V8.2.1)" % (where, aid))
        if len(re.findall(r"[A-Za-z]{2,}", ver)) < 2:
            errs.append("%s: verification method for %s is empty or a single word" % (where, sid))
    for s in sorted(secs - got_sec):
        errs.append("%s: %s has no control row" % (rel, s))
    for t in sorted(ths - got_th):
        errs.append("%s: threat %s has neither a SEC-ID nor an accepted-risk record" % (rel, t))
    notes.append("%s: %d row(s); %d SEC-ID(s), %d threat(s) in the threat model" % (rel, len(rows), len(secs), len(ths)))


def phase9(root, base, errs, notes):
    crel = "%s/4/SEC-CONTROLS.csv" % base
    controls, _p = readonly.read_csv(os.path.join(root, crel), ["sec_id"])
    want = {r["sec_id"] for r in controls or [] if SEC.match(r["sec_id"])}
    rel = "%s/9/SEC-VERIFICATION.csv" % base
    rows, probs = readonly.read_csv(os.path.join(root, rel), ["sec_id", "method", "evidence", "result"])
    if rows is None:
        errs.append("%s is missing: SEC-ID -> method -> evidence -> result (phase 9 gate)" % rel)
        return
    errs += probs
    if controls is None:
        errs.append("%s is missing, so the SEC-IDs to verify are unknown" % crel)
    got = set()
    for r in rows:
        where = "%s line %d" % (rel, r["_line"])
        sid, res, ev = r["sec_id"], r["result"].lower(), r["evidence"]
        if not SEC.match(sid):
            errs.append("%s: sec_id %r is not SEC-n" % (where, sid))
            continue
        if sid in got:
            errs.append("%s: %s is listed twice" % (where, sid))
        got.add(sid)
        if want and sid not in want:
            errs.append("%s: %s is not in %s" % (where, sid, crel))
        if res not in RESULTS:
            errs.append("%s: result %r is not one of %s" % (where, r["result"], ", ".join(RESULTS)))
        if len(r["method"].split()) < 1:
            errs.append("%s: %s names no verification method" % (where, sid))
        if not ev:
            errs.append("%s: %s names no evidence" % (where, sid))
        elif "/" in ev and " " not in ev and not readonly.tracked_at_head(root, ev.split("#", 1)[0]):
            errs.append("%s: evidence %s for %s is not a file at HEAD" % (where, ev, sid))
        if res == "failed":
            errs.append("%s: %s failed verification" % (where, sid))
        if res == "accepted-risk" and len(re.findall(r"[A-Za-z]{2,}", ev)) < 2:
            errs.append("%s: accepted-risk for %s must name the operator's residual-risk acceptance (SV16)" % (
                where, sid))
    for s in sorted(want - got):
        errs.append("%s: %s (a phase-4 control) has no verification row" % (rel, s))
    notes.append("%s: %d row(s) for %d controlled SEC-ID(s)" % (rel, len(rows), len(want)))


def main(argv):
    if len(argv) != 2 or argv[0] != "--phase" or argv[1] not in ("4", "9"):
        print("UNKNOWN usage: check_sec_csv.py --phase 4|9")
        return 2
    root = hlib.project_root()
    notes, errs, unknown = [], [], []
    try:
        (phase4 if argv[1] == "4" else phase9)(root, readonly.doc_dir(), errs, notes)
    except Exception as e:  # unknown, never a pass
        unknown.append("%s: %s" % (type(e).__name__, e))
    name = "SEC-CONTROLS.csv" if argv[1] == "4" else "SEC-VERIFICATION.csv"
    return toolrun.report("check-sec-csv (phase %s: %s shape)" % (argv[1], name), notes, [], errs, unknown)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
