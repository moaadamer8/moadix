#!/usr/bin/env python3
"""check-claude-security -- phase 9: Claude Security's findings for HEAD (increment 5).

MOADIX-native. Claude Security is a FINDING SOURCE, never a verdict
(DESIGN.md §5). The gate schedules its scan (gate/secscan.py, on
/moadix:request-review in phase 9) and ingests its SARIF; this validator only
reads the gate's result file (.sdlc/cache/verify/9/claude-security/result.json):

  * the scan exists, finished without error, and is for HEAD (its revision
    stamp names HEAD's commit and is not -dirty);
  * every finding has a gate-assigned SF-n id; a CONFIRMED one at critical, high
    or unknown fails (unknown = severity unreadable);
  * increment 6 (ruling 1): a finding the plugin could NOT confirm fails until
    the fresh-context verifier moadix:sf-triager (scheduled by the gate in phase
    9 while such findings exist) assesses it, with path:line evidence at HEAD, as
    rejected (it stops blocking) or confirmed (it is then judged by severity), or
    until the operator waives it with a reason (WAIVE SF-n ... reason=...);
  * every SF-n appears in sdlc/09-security-report.md's findings table
    (`| SF-n | severity | ... | status |`) at a severity no lower than the
    gate's: the register is the gate's, the report accounts for it.

A confirmed finding at medium or low, and any unconfirmed finding, may be waived
through the ledger (WAIVE SF-n ...); a confirmed critical, high or unknown one
cannot be (gate/config/waivers.yaml).

Exit 0 pass, 1 fail, 2 UNKNOWN (a scan for HEAD is still running).
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import hlib  # noqa: E402
import toolrun  # noqa: E402
from gate import secscan  # noqa: E402

RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4, "unknown": 5}


def scan_running(lock):
    """gate/secscan.running, read-only: a live worker pid, or pid 0 (starting) for 120 s."""
    try:
        with open(lock) as f:
            pid, started = f.read().split()
        if int(pid) == 0:
            return time.time() - float(started) < 120
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def report_rows(root):
    try:
        with open(os.path.join(root, "sdlc", "09-security-report.md"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    return {m.group(1).upper(): m.group(2).strip().lower()
            for m in re.finditer(r"^\|\s*(SF-\d+)\s*\|([^|]*)\|", text, re.M)}


def waived(root):
    try:
        doc = hlib.load_phase_doc(root)
        return {str(w.get("path")).upper() for w in hlib.waivers_for(doc, "waiver") if w.get("path")} | \
               {str(w.get("path")).upper() for w in (doc.get("waivers") or []) if w.get("path")}
    except Exception:
        return set()


def triage_results(root):
    """{SF-n: entry} from moadix:sf-triager's evidence, when it holds at HEAD (gate/verify.py)."""
    try:
        from gate import state, verify
        st, problems = state.current_state(root)
        return {} if problems else verify.triage_of(root, st)
    except Exception:  # no triage evidence counts: the findings keep blocking (fail closed)
        return {}


def main():
    root = hlib.project_root()
    notes, errs, unknown, findings = [], [], [], []
    head = toolrun.head(root)
    title = "check-claude-security (phase 9, Claude Security findings)"
    p = os.path.join(root, ".sdlc", "cache", "verify", "9", "claude-security", "result.json")
    lock = os.path.join(os.path.dirname(p), "scan.lock")
    try:
        with open(p) as f:
            res = json.load(f)
    except (OSError, ValueError):
        res = None
    if res is None or res.get("head") != head:
        if scan_running(lock):
            unknown.append("a Claude Security scan is running; its findings are not in yet")
        else:
            errs.append("no Claude Security scan for HEAD %s: the gate starts one when the agent calls "
                        "/moadix:request-review in phase 9 with a clean tree%s" % (
                            (head or "none")[:12], " (the last was for %s)" % str(res.get("head"))[:12] if res else ""))
        return toolrun.report(title, notes, findings, errs, unknown)
    if res.get("error"):
        errs.append("the Claude Security scan for %s failed: %s" % (head[:12], res["error"]))
        return toolrun.report(title, notes, findings, errs, unknown)
    rows = report_rows(root)
    wv = waived(root)
    if rows is None:
        errs.append("sdlc/09-security-report.md is missing: it must account for every SF-n in the register")
        rows = {}
    triage = triage_results(root)
    for f in res.get("findings") or []:
        sid = str(f.get("id"))
        stt, sev = secscan.judge(f, triage.get(sid.upper()))
        sev = sev if sev in RANK else "unknown"
        tag = {"confirmed": "" if f.get("confirmed") else " [confirmed by moadix:sf-triager]",
               "unconfirmed": " [UNCONFIRMED by its verifier panel]",
               "rejected": " [REJECTED by moadix:sf-triager]"}[stt]
        text = "%s %s%s (plugin %s, %s)" % (f.get("location"), f.get("summary", "")[:140], tag,
                                           f.get("plugin_severity") or "?", f.get("rule"))
        if stt == "rejected":
            t = triage[sid.upper()]
            notes.append("%s rejected by moadix:sf-triager (%s): %s" % (sid, ", ".join(t["citations"][:3]), text))
        elif stt == "unconfirmed":
            if sid.upper() in wv:
                notes.append("%s (unconfirmed) waived through the ledger: %s" % (sid, text))
            else:
                errs.append("%s %s: unconfirmed, so it blocks until moadix:sf-triager confirms or rejects it with "
                            "path:line evidence, or the operator waives it (WAIVE %s ... reason=<why>)" % (sid, text, sid))
        elif sid.upper() in wv and sev in ("medium", "low", "info"):
            notes.append("%s (%s) waived through the ledger: %s" % (sid, sev, text))
        else:
            findings.append((sev, sid, text))
        got = rows.get(sid.upper())
        if got is None:
            errs.append("%s (%s) is in the gate's register but not in sdlc/09-security-report.md's findings table"
                        % (sid, sev))
        elif RANK.get(got, -1) < RANK[sev] and not (sev == "unknown" and got in ("unknown", "unconfirmed")):
            errs.append("%s: the report rates it %r, below the gate's %s; a report cannot lower a finding" % (
                sid, got, sev))
    notes.append("scan of %s at %s effort, stamp %s, SARIF %s (sha256 %s), %d finding(s)" % (
        head[:12], res.get("effort"), res.get("stamp"), res.get("sarif"), str(res.get("sarif_sha256"))[:12],
        len(res.get("findings") or [])))
    return toolrun.report(title, notes, findings, errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
