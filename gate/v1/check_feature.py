#!/usr/bin/env python3
"""check-feature -- a feature cycle's additions against the frozen product (increment 6).

MOADIX-native (Amendment 2). Registered once per phase with scope `feature`, so the
gate's worker runs it only while a feature cycle is active (MOADIX_FEATURE names
it). It checks the feature's documents in sdlc/features/<id>/ up to this phase:
present, traceable, no ID that conflicts with the product's approved documents
(SEC-IDs included), and no acceptance criterion that contradicts an approved
requirement. At phase 11 it also previews the merge into the product documents.
See gate/feature.py.

    check_feature.py --phase <label>

Exit 0 pass, 1 fail, 2 unknown (not in a feature cycle, or state unreadable).
"""
import os
import sys

GATE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(GATE))

from gate import feature, pathmap  # noqa: E402


def main(argv):
    if len(argv) != 2 or argv[0] != "--phase" or argv[1] not in pathmap.LABELS:
        print("UNKNOWN usage: check_feature.py --phase <label>")
        return 2
    label = argv[1]
    root = os.environ.get("MOADIX_PRODUCT_ROOT") or os.getcwd()
    fid = os.environ.get("MOADIX_FEATURE") or ""
    print("check-feature (feature %s, phase %s: additions against the frozen product documents)" % (fid or "-", label))
    if not fid:
        print("  UNKNOWN  no feature cycle is active, so there are no additions to check")
        return 2
    try:
        errs, notes = feature.check_phase(root, fid, label)
    except Exception as exc:  # unknown, never a pass
        print("  UNKNOWN  the additions could not be checked: %s: %s" % (type(exc).__name__, exc))
        return 2
    for n in notes:
        print("  note  %s" % n)
    for line in errs:
        print("  FAIL  %s" % line)
    if errs:
        return 1
    print("  PASS  feature %s's additions up to phase %s trace, conflict with no approved ID and contradict no "
          "approved requirement" % (fid, label))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
