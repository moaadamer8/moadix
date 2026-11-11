#!/usr/bin/env python3
"""waivers — one policy, read by the thing that GRANTS and the thing that JUDGES.

A waiver is how a human takes responsibility for shipping with a known hole.
The harness had the instrument and no governance around it: any rule, any path,
no owner, no scope, an optional expiry, and no limit on how many could
accumulate.

WHY THIS IS ONE MODULE AND NOT TWO CHECKS

  `gate.sh waive` decides what may be GRANTED. `build-scorecard` decides what a
  release may REST ON. If those two grow their own copies of the policy they
  drift, and the drift is silent in the worst direction: a waiver the CLI
  refused to grant is not the problem, a waiver the CLI granted and the
  scorecard silently honours is. So both import this.

THE LEGACY RULING (v0.5, operator)

  Expiry is mandatory going forward; waivers predating the field are surfaced
  as FINDINGS rather than grandfathered. The rejected alternative was explicit,
  visible grandfathering. What was never available was silence -- a no-expiry
  waiver that nothing reports is the same failure as a declaration nothing
  reads, wearing a date field.

  `expiry_state()` therefore returns THREE values, not two. A waiver with no
  expiry is UNKNOWN, not "never": rendering it as `never` asserts a permanence
  nobody granted, which is the same class of false statement as an artifact
  that does not describe itself.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

DEFAULTS = {
    "require_expiry": True,
    "max_expiry_days": 180,
    "max_active": 8,
    "unwaivable_severities": ["high", "critical"],
}

REQUIRED_FIELDS = ("rule", "path", "reason", "approver", "owner", "scope")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def policy(root):
    cfg = {}
    try:
        cfg = hlib.load_yaml(hlib.config_path(root, "waivers.yaml")) or {}
    except Exception:
        cfg = {}
    out = dict(DEFAULTS)
    for k, v in DEFAULTS.items():
        got = cfg.get(k)
        if isinstance(got, type(v)) and (not isinstance(v, int) or isinstance(got, int)):
            out[k] = got
    out["unwaivable_severities"] = [str(x).lower() for x in out["unwaivable_severities"]]
    return out


def today():
    import datetime
    return datetime.date.today().isoformat()


def days_until(iso_date):
    try:
        import datetime
        y, m, d = (int(x) for x in str(iso_date).split("-"))
        return (datetime.date(y, m, d) - datetime.date.today()).days
    except Exception:
        return None


def expiry_state(w):
    """('dated'|'unknown'|'expired'|'malformed', detail).

    THREE-VALUED on purpose. `unknown` is a waiver granted before expiry was
    recorded; it is NOT `never`, and the difference is the whole L1 ruling.
    """
    exp = w.get("expires")
    if exp in (None, ""):
        return "unknown", ("granted with no expiry -- predates the mechanism, or was "
                           "recorded without one")
    exp = str(exp).strip()
    if not ISO.match(exp):
        return "malformed", "expires %r is not an ISO date (YYYY-MM-DD)" % exp
    if exp < today():
        return "expired", "lapsed on %s" % exp
    return "dated", exp


def missing_fields(w):
    return [f for f in REQUIRED_FIELDS if not str(w.get(f) or "").strip()]


def severity_of(path, finding_severities):
    """Severity of the finding a waiver path refers to, or None."""
    key = str(path or "").split(":", 1)[0].strip().upper()
    return (finding_severities or {}).get(key)


def _revoked(w):
    """The revocation event if this waiver's last transition was one.

    Local rather than importing hlib: hlib imports nothing from here and the
    reverse would make the dependency circular at every gate invocation. The
    shape is hlib.waiver_revoked's, and R12 asserts the two agree so they
    cannot drift apart silently.
    """
    evs = list((w or {}).get("events") or [])
    last = evs[-1] if evs else None
    return last if (last or {}).get("action") == "revoked" else None


def audit(root, doc, finding_severities=None):
    """(errs, warns, notes, rows) over every waiver in phase.yaml.

    `finding_severities` maps a finding id (SF-1, SEC-003) to its severity, read
    by the caller from the phase-9 report. Absent, the unwaivable-severity rule
    cannot be applied and says so rather than passing.
    """
    pol = policy(root)
    errs, warns, notes, rows = [], [], [], []
    all_w = list((doc or {}).get("waivers") or [])
    live = 0

    if finding_severities is None:
        warns.append("no finding severities were supplied, so the unwaivable-severity rule "
                     "could not be applied. A rule that could not run is not a rule that "
                     "passed.")

    for w in all_w:
        path = str(w.get("path") or "?")
        rule = str(w.get("rule") or "?")
        # A REVOKED waiver is not a live exception and must not be audited as
        # one. Before this it was counted toward max_active, and if its date had
        # passed it was reported as "expired -- renew it or fix the finding",
        # which is advice about a waiver a human has already withdrawn.
        _rv = _revoked(w)
        if _rv:
            notes.append("waiver %s/%s was WITHDRAWN by %s at %s: %s. It grants "
                         "nothing and is not counted as a live exception."
                         % (rule, path, _rv.get("by"), _rv.get("at"), _rv.get("reason")))
            rows.append({"rule": rule, "path": path, "state": "revoked",
                         "detail": str(_rv.get("reason") or ""), "severity": None,
                         "waiver": w, "missing": []})
            continue
        state, detail = expiry_state(w)
        miss = missing_fields(w)
        sev = severity_of(path, finding_severities)
        rows.append({"rule": rule, "path": path, "state": state, "detail": detail,
                     "severity": sev, "waiver": w, "missing": miss})

        if state in ("expired", "malformed"):
            errs.append("waiver %s/%s is %s (%s). It grants nothing and the gate under it is "
                        "failing again; renew it or fix the finding." % (rule, path, state, detail))
            continue
        live += 1

        if state == "unknown":
            if pol["require_expiry"]:
                errs.append("waiver %s/%s carries NO EXPIRY. Expiry is mandatory (operator "
                            "ruling, v0.5): this waiver predates the field, which is not the "
                            "same as someone granting permanence. Set one with `gate.sh waive "
                            "%s --path %s --expires YYYY-MM-DD ...`, or fix the finding."
                            % (rule, path, rule, path))
            else:
                warns.append("waiver %s/%s carries no expiry (grandfathered)." % (rule, path))
        elif state == "dated":
            n = days_until(detail)
            if n is not None and n > pol["max_expiry_days"]:
                errs.append("waiver %s/%s expires in %d days, beyond the %d-day maximum. Past "
                            "that horizon it is not an exception, it is the design, and it "
                            "should be argued for as one."
                            % (rule, path, n, pol["max_expiry_days"]))
            elif n is not None and n <= 30:
                notes.append("waiver %s/%s expires in %d day(s) (%s)." % (rule, path, n, detail))

        if miss:
            errs.append("waiver %s/%s is missing %s. Every exception names who owns the fix "
                        "and how far it reaches; without those it is an anonymous permission "
                        "slip." % (rule, path, ", ".join(miss)))

        if sev and sev.lower() in pol["unwaivable_severities"]:
            errs.append("waiver %s/%s covers a %s-severity finding, which CANNOT be waived. "
                        "There is no --force. This does not say a human may not decide to "
                        "ship; it says that decision may not be recorded as a waiver, because "
                        "a waiver is a routine instrument and this is not a routine decision. "
                        "Fix it, downgrade it with evidence, or let the release stay blocked."
                        % (rule, path, sev))

    if live > pol["max_active"]:
        errs.append("%d live waiver(s), above the maximum of %d. Not because the %dth "
                    "exception is worse than the %dth, but because a release resting on that "
                    "many is resting on a backlog nobody is tracking."
                    % (live, pol["max_active"], live, live - 1))
    notes.append("waivers: %d total, %d live, max %d" % (len(all_w), live, pol["max_active"]))
    return errs, warns, notes, rows


def render_expiry(w):
    """The cell for the scorecard's Expires column.

    It used to render a missing expiry as `never`. That asserted a permanence
    the record does not support: these are waivers whose expiry is UNKNOWN, and
    unknown is not never.
    """
    state, detail = expiry_state(w)
    return {
        "dated": lambda: detail,
        "unknown": lambda: "**UNKNOWN** (no expiry recorded)",
        "expired": lambda: "**EXPIRED** %s" % str(w.get("expires") or "").strip(),
        "malformed": lambda: "**MALFORMED** %s" % str(w.get("expires") or "").strip(),
    }[state]()


def backlog(rows):
    """The carry-forward list: every live exception, soonest deadline first.

    A waiver table says what this release rests on. A backlog says what the NEXT
    version has to clear, which is the thing that otherwise gets rediscovered by
    accident a version later.
    """
    out = []
    for r in rows:
        if r["state"] in ("expired", "malformed"):
            continue
        n = days_until(r["detail"]) if r["state"] == "dated" else None
        out.append({"rule": r["rule"], "path": r["path"],
                    "due": r["detail"] if r["state"] == "dated" else "UNKNOWN",
                    "days": n,
                    "owner": str(r["waiver"].get("owner") or "—"),
                    "scope": str(r["waiver"].get("scope") or "—"),
                    "severity": r["severity"] or "—"})
    # Undated first: an exception with no deadline is the one most likely to
    # outlive everyone who remembers why it exists.
    out.sort(key=lambda x: (x["days"] is not None, x["days"] if x["days"] is not None else 0))
    return out
