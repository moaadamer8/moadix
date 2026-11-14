#!/usr/bin/env python3
"""check-contract (MOADIX increment 7; docs/AMENDMENT-3.md section 1, not a v1 port).

Run by the gate's validator worker for every gated phase, in product and feature scope.
It runs the cross-phase contract's linters on the scope's documents (gate/contract.py):
coverage-lint (with the size rule), discovery-lint, adr-lint and trace-lint everywhere,
ears-lint in phases 2 and B, cite-lint in phase 1.

    check_contract.py --phase <label>

Exit 0: every linter holds. 1: a linter failed. 2: the check could not run, or a link's
status could not be learned (unknown, never a pass).

Output: FAIL lines block APPROVE; MINOR lines go to the operator's minor-findings file.
In a gate run (MOADIX_GATE_RUN) the phase-2 acceptance criteria are written to
.sdlc/cache/contract/<scope>/AC.json (gate-owned evidence) and checked links are cached
in .sdlc/cache/links.json.
"""
import json
import os
import sys

GATE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(GATE))

from gate import contract, state  # noqa: E402


def main(argv):
    if len(argv) != 2 or argv[0] != "--phase":
        print("UNKNOWN usage: check_contract.py --phase <label>")
        return 2
    label = argv[1]
    root = os.environ.get("MOADIX_PRODUCT_ROOT") or os.getcwd()
    gate_run = bool(os.environ.get("MOADIX_GATE_RUN"))
    try:
        st, problems = state.current_state(root)
        if problems:
            print("UNKNOWN gate state failed its integrity check: %s" % "; ".join(problems))
            return 2
        rows = contract.run(root, st, label, write_cache=gate_run)
    except Exception as e:  # unknown, never a pass
        print("UNKNOWN the contract could not be checked: %s: %s" % (type(e).__name__, e))
        return 2
    bad = unknown = 0
    for lint, fails, minors, info, unk in rows:
        for x in fails:
            print("FAIL %s-lint: %s" % (lint, x))
        for x in minors:
            print("MINOR %s-lint: %s" % (lint, x))
        for x in unk:
            print("UNKNOWN %s-lint: could not reach %s to check that it resolves" % (lint, x))
        bad += len(fails)
        unknown += len(unk)
        if not fails and not unk:
            detail = ", ".join("%s %s" % (v, k) for k, v in sorted(info.items())
                               if isinstance(v, (int, str)) and v not in ("", None))
            print("OK %s-lint: phase %s%s" % (lint, label, " (%s)" % detail if detail else ""))
        if lint == "ears" and gate_run and info.get("acs") is not None:
            scope = st.get("feature") or "product"
            d = os.path.join(root, state.SDLC, "cache", "contract", scope)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "AC.json.tmp"), "w") as f:
                json.dump({"phase": label, "scope": scope, "acs": info["acs"]}, f, indent=1, sort_keys=True)
            os.replace(os.path.join(d, "AC.json.tmp"), os.path.join(d, "AC.json"))
    if bad:
        return 1
    return 2 if unknown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
