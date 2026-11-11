#!/usr/bin/env python3
"""check-verifiers (MOADIX increment 4; new in v2, not a v1 port).

Run by the gate's validator worker for phases that have verifier roles
(gate/config/verifiers.yaml). For each verifier the gate schedules for the
phase at HEAD, it checks the evidence that verifier wrote: stamped with the
role, HEAD and the gate's brief hash, carrying the prompt's one-time receipt,
every citation resolving at HEAD, every required path reviewed, every
acceptance criterion mapped (AC-coverage critic), and no finding at a failing
severity. See gate/verify.py.

    check_verifiers.py --phase <label>

Exit 0: every required verifier's evidence holds. 1: missing, stale or failing.
2: the check could not run (unknown).
"""
import os
import sys

GATE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(GATE))

from gate import state, verify  # noqa: E402


def main(argv):
    if len(argv) != 2 or argv[0] != "--phase":
        print("UNKNOWN usage: check_verifiers.py --phase <label>")
        return 2
    label = argv[1]
    root = os.environ.get("MOADIX_PRODUCT_ROOT") or os.getcwd()
    try:
        st, problems = state.current_state(root)
        if problems:
            print("UNKNOWN gate state failed its integrity check: %s" % "; ".join(problems))
            return 2
        rows = verify.check_phase(root, st, label)
    except Exception as e:  # unknown, never a pass
        print("UNKNOWN verifier evidence could not be checked: %s: %s" % (type(e).__name__, e))
        return 2
    if not rows:
        print("OK no verifier is scheduled for phase %s at this commit" % label)
        return 0
    bad = 0
    for name, status, probs, info in rows:
        if status == "ok":
            print("OK %s:%s evidence %s (brief %s): %d findings%s, citations resolve, stamped HEAD" % (
                verify.PLUGIN, name, info.get("evidence_sha256", "")[:12], info.get("brief_sha256", "")[:12],
                info.get("findings", 0), ", %d acceptance criteria mapped" % info["acs"] if "acs" in info else ""))
            continue
        bad += 1
        tag = {"missing": "MISSING", "stale": "FAIL stale", "failing": "FAIL"}[status]
        for p in probs[:12]:
            print("%s %s:%s: %s" % (tag, verify.PLUGIN, name, p))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
