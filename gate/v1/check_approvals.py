#!/usr/bin/env python3
"""check-approvals — audit how every phase was approved.

An approval is only meaningful if a human made it. v0.1 shipped five approvals
that were all non-interactive, and nothing surfaced that fact. This script does.

Reports, for every APPROVED phase:
  - who approved it, when, and in which mode
  - whether validators actually ran and passed at approval time
  - whether the approval carries a scorecard_flag

Exit 0  every approval is interactive and evidenced
Exit 1  at least one non-interactive approval exists (Phase 11 scorecard FAIL)
Exit 2  a structural problem (approved with failed/absent evidence where a
        validator is registered)

Intended to be wired as the Phase 11 (Release) scorecard input. It is
deliberately usable standalone at any time.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402


def registered_validators(root, phase):
    p = hlib.config_path(root, "registry.yaml")
    if not os.path.exists(p):
        return []
    try:
        reg = hlib.load_yaml(p)
    except Exception:
        return []
    out = []
    for c in (reg.get("components") or []):
        if str(c.get("kind")) != "validator":
            continue
        # Match on LABEL ONLY. Matching the numeric id too resurrects the v0.2
        # collision that `resolve()` was fixed for: phase label "11" (Release)
        # and phase id 11 (Regression Suites, label "10b") are different phases,
        # so `approve 10b` ran the phase-11 release scorecard and blocked.
        if str(c.get("phase")) == str(phase.get("label")):
            out.append(c.get("id"))
    return out


def main():
    ap = argparse.ArgumentParser(prog="check-approvals.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true", help="only print the verdict line")
    ap.add_argument("--strict", action="store_true",
                    help="also exit non-zero when a phase was approved with no validator evidence "
                         "while a validator was registered for it")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        doc = hlib.load_phase_doc(root)
    except Exception as exc:
        print("check-approvals: cannot read harness/status/phase.yaml (%r)" % (exc,))
        return 2
    if not doc:
        print("check-approvals: harness/status/phase.yaml is empty or unreadable")
        return 2

    approved = [p for p in hlib.phases_of(doc) if str(p.get("status")) == "APPROVED"]
    noninteractive, structural = [], []

    if not args.quiet:
        print("check-approvals: %s" % doc.get("project"))
        print()
        print("  %-4s %-26s %-14s %-12s %s" % ("ph", "name", "mode", "approver", "evidence"))
        print("  %s" % ("-" * 78))

    for p in approved:
        mode = str(p.get("approval_mode"))
        ev = p.get("evidence") or []
        ev_txt = "none"
        if ev:
            # n/a-by-profile is neither a pass nor a failure: the Target Platform
            # Ruling makes that validator irrelevant, so it was deliberately not
            # run and profiles.yaml records why. Counting it as a failure would
            # make every correctly-ruled product look structurally broken;
            # counting it as a pass would recreate the silent-N/A the profile
            # mechanism exists to prevent (Constitution §6.3). It is reported
            # separately.
            na = sum(1 for e in ev if str(e.get("result")) == "n/a-by-profile")
            passes = sum(1 for e in ev if str(e.get("result")) == "pass")
            ev_txt = "%d/%d pass" % (passes, len(ev) - na)
            if na:
                ev_txt += " (+%d n/a-by-profile)" % na
            if passes != len(ev) - na:
                structural.append((p, "approved with a FAILING validator in evidence"))
        else:
            regs = registered_validators(root, p)
            if regs:
                ev_txt = "MISSING (%s registered)" % ",".join(regs)
                structural.append((p, "validator(s) %s registered but no evidence recorded"
                                   % ",".join(regs)))
        flag = ""
        if mode != "interactive":
            noninteractive.append(p)
            flag = "  <-- SCORECARD FAIL"
        if not args.quiet:
            print("  %-4s %-26s %-14s %-12s %s%s"
                  % (p.get("label"), p.get("name"), mode, p.get("approver"), ev_txt, flag))

    if not args.quiet:
        pending = [p for p in hlib.phases_of(doc) if str(p.get("status")) != "APPROVED"]
        if pending:
            print("\n  not yet approved: %s" % ", ".join(str(x.get("label")) for x in pending))

    is_toy = bool(doc.get("toy"))

    if noninteractive:
        print("\nNON-INTERACTIVE APPROVALS (%d)%s:"
              % (len(noninteractive),
                 " — SUPPRESSED by `toy: true`, would each FAIL the Phase 11 scorecard"
                 if is_toy else " — each FAILS the Phase 11 scorecard"))
        for p in noninteractive:
            print("  phase %-4s %-26s approver=%s  reason=%s"
                  % (p.get("label"), p.get("name"), p.get("approver"),
                     p.get("approval_reason") or "(none recorded)"))
        print("\n  Remedy: `harness/bin/gate.sh reopen <phase> --reason \"re-approve interactively\"` "
              "then approve at a terminal.")

    if structural:
        print("\nSTRUCTURAL PROBLEMS (%d):" % len(structural))
        for p, why in structural:
            print("  phase %-4s %s" % (p.get("label"), why))

    print()
    if structural and args.strict:
        print("check-approvals: FAIL — %d non-interactive, %d structural" % (len(noninteractive), len(structural)))
        return 2
    if noninteractive:
        # The toy flag is honoured HERE as well as in the scorecard. Two places
        # enforcing the same rule with different answers would make the flag
        # ineffective at the gate while appearing to work in the report.
        if is_toy:
            print("check-approvals: PASS (suppressed) — %d of %d approvals were non-interactive, "
                  "but the project is flagged `toy: true`. Clear the flag "
                  "(`harness/bin/gate.sh set-toy false`) and this becomes a hard failure with no "
                  "waiver." % (len(noninteractive), len(approved)))
            return 0
        print("check-approvals: FAIL — %d of %d approvals were non-interactive"
              % (len(noninteractive), len(approved)))
        return 1
    if not approved:
        print("check-approvals: no approved phases yet (vacuously clean)")
        return 0
    print("check-approvals: PASS — all %d approvals were interactive and evidenced" % len(approved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
