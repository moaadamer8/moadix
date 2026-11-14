#!/usr/bin/env python3
"""check-lv-inventory -- phase 10a LV-INVENTORY.csv (increment 7b; Amendment 3 phase 10a, LV1).

Reads committed files only. <scope>/10a/LV-INVENTORY.csv has columns lv_id, target, state,
result, artifact:

  - it covers 100% of the designed rows of design/screen-states.csv and
    design/component-states.csv (U4/U13): every target / state pair;
  - lv_id is LV-n and unique; result pass | fail | n/a;
  - a pass names its artifact (trace, video, screenshot); an n/a gives a reason; a fail
    fails the phase.

The live verifier's evidence (check-verifiers-10a) proves the browser run; this file is the
inventory the operator reads. Exit 0 pass, 1 fail, 2 UNKNOWN.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import readonly  # noqa: E402
import toolrun  # noqa: E402
from check_ux_files import COMPONENTS, SCREENS  # noqa: E402

LV = re.compile(r"^LV-\d+$")


def designed(root):
    out = set()
    for rel, key in ((SCREENS, "screen"), (COMPONENTS, "component")):
        rows, _p = readonly.read_csv(os.path.join(root, rel), [key, "state", "status"])
        for r in rows or []:
            if r["status"].lower() == "designed":
                out.add((r[key].lower(), r["state"].lower()))
    return out


def main():
    root = hlib.project_root()
    notes, errs, unknown = [], [], []
    try:
        rel = "%s/10a/LV-INVENTORY.csv" % readonly.doc_dir()
        rows, probs = readonly.read_csv(os.path.join(root, rel), ["lv_id", "target", "state", "result", "artifact"])
        if rows is None:
            errs.append("%s is missing: every designed screen and component state, exercised live (LV1)" % rel)
            rows = []
        errs += probs
        want = designed(root)
        if not want:
            errs.append("design/screen-states.csv and design/component-states.csv name no designed state to verify")
        ids, got = set(), set()
        for r in rows:
            where = "%s line %d" % (rel, r["_line"])
            if not LV.match(r["lv_id"]):
                errs.append("%s: lv_id %r is not LV-n" % (where, r["lv_id"]))
            elif r["lv_id"] in ids:
                errs.append("%s: %s is used twice" % (where, r["lv_id"]))
            ids.add(r["lv_id"])
            got.add((r["target"].lower(), r["state"].lower()))
            res = r["result"].lower()
            if res == "pass":
                if not r["artifact"]:
                    errs.append("%s: %s passed without an artifact (trace, video or screenshot)" % (where, r["lv_id"]))
            elif res == "n/a":
                if len(re.findall(r"[A-Za-z]{2,}", r["artifact"])) < 4:
                    errs.append("%s: %s is n/a without a reason" % (where, r["lv_id"]))
            elif res == "fail":
                errs.append("%s: %s (%s / %s) failed live verification" % (where, r["lv_id"], r["target"], r["state"]))
            else:
                errs.append("%s: result %r is not pass, fail or n/a" % (where, r["result"]))
        for t, s in sorted(want - got):
            errs.append("%s does not cover %s / %s (designed in phase 6)" % (rel, t, s))
        notes.append("%s: %d row(s) covering %d of %d designed state(s)" % (rel, len(rows), len(want & got), len(want)))
    except Exception as e:  # unknown, never a pass
        unknown.append("%s: %s" % (type(e).__name__, e))
    return toolrun.report("check-lv-inventory (phase 10a: LV-INVENTORY.csv covers every designed state)", notes, [],
                          errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
