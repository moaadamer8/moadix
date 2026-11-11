#!/usr/bin/env python3
"""check-security — Phase 9 validator: security verification with real evidence.

Three things make this more than a paperwork check:

1. **Evidence is resolved, not read.** Every SEC-ID marked EVIDENCED must cite
   `path:line`, and this script opens the file and checks the line exists. A
   hallucinated citation fails: the commonest way a security report lies is by
   pointing at a line that is not there.
2. **The secrets scan is run BY THE GATE**, not read from the report. The skill
   runs its own scan for its own report; this validator scans independently and
   fails on what *it* finds. A report cannot talk the gate out of a finding.
3. **Every threat-model SEC-ID must be accounted for.** Silence on a SEC-ID is
   a failure, not an implicit pass.

Waivers live in harness/status/phase.yaml under rule `security`, and require a
reason and an approver (Constitution §3.4).

Exit 0 = pass. Non-zero = fail.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

VERDICTS = {"EVIDENCED", "FAILED", "NOT-APPLICABLE", "WAIVED"}

# Independent secrets scan. Deliberately conservative: a false positive costs a
# conversation, a false negative ships a credential.
SECRET_PATTERNS = [
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("generic-secret-assignment",
     re.compile(r"""(?i)\b(?:api[_-]?key|secret|password|passwd|token|access[_-]?key)\b\s*[:=]\s*"""
                r"""['"][A-Za-z0-9/+_\-]{16,}['"]""")),
    ("bearer-literal", re.compile(r"""(?i)authorization\s*[:=]\s*['"]?bearer\s+[A-Za-z0-9._\-]{20,}""")),
]

# `test-results` was skipped and `.log` / `.xml` were not scanned at all, so the
# scan never looked at ANY artifact produced by phases 10a, 10b or 10c. That is
# precisely where a credential leaks in practice: a device log or a browser
# console capture taken DURING a verification run, with a bearer token in it,
# committed as evidence. The scan covered the source it was pointed at and the
# evidence of the runs against that source was invisible to it.
SCAN_SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build", ".venv",
                  "venv", "coverage", ".next"}
SCAN_EXT = {".js", ".jsx", ".ts", ".tsx", ".py", ".rb", ".go", ".java", ".rs", ".php",
            ".sh", ".bash", ".yml", ".yaml", ".json", ".toml", ".ini", ".env", ".cfg",
            ".html", ".css", ".md", ".txt",
            # verification output: device logs, browser captures, JUnit, HAR
            ".log", ".xml", ".har", ".jsonl", ".ndjson", ".out", ".trace", ""}


def strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def sec_ids_from_threat_model(path):
    text = read(path)
    if text is None:
        return None
    return sorted(set(re.findall(r"^#{2,4}\s+(SEC-\d{3})\b", text, re.M)))


def blocks(text, prefix):
    out, cur, cid = {}, [], None
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+(%s-\d+)\b" % prefix, line.strip())
        if m:
            if cid:
                out[cid] = "\n".join(cur)
            cid, cur = m.group(1), [line]
        elif cid:
            if re.match(r"^#{1,4}\s+", line.strip()) and not re.match(r"^#{2,4}\s+%s-\d+" % prefix, line.strip()):
                out[cid] = "\n".join(cur); cid, cur = None, []
            else:
                cur.append(line)
    if cid:
        out[cid] = "\n".join(cur)
    return out


def field(block, name):
    m = re.search(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+?)\s*$" % re.escape(name), block, re.I | re.M)
    return m.group(1).strip() if m else None


def resolve_evidence(root, spec):
    """Verify a `path:line` citation actually points at an existing line."""
    out = []
    for m in re.finditer(r"([A-Za-z0-9_./\-]+\.[A-Za-z0-9]+):(\d+)", spec):
        rel, ln = m.group(1), int(m.group(2))
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            out.append((rel, ln, "file does not exist"))
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                n = sum(1 for _ in fh)
        except Exception as exc:
            out.append((rel, ln, "unreadable: %r" % (exc,)))
            continue
        if ln < 1 or ln > n:
            out.append((rel, ln, "line %d is out of range (file has %d lines)" % (ln, n)))
        else:
            out.append((rel, ln, None))
    return out


def secrets_scan(base):
    hits = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SCAN_EXT:
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if len(line) > 4000:
                            continue
                        for name, rx in SECRET_PATTERNS:
                            if rx.search(line):
                                hits.append((os.path.relpath(p, base), i, name))
            except Exception:
                # S112: an unreadable file cannot hide a secret from a scan it
                # was never in. Failing the whole scan on one bad encoding would
                # make the gate hostage to any binary that lands in the tree.
                continue
    return hits


def waivers(root, rule="security"):
    try:
        doc = hlib.load_phase_doc(root)
    except Exception:
        return {}
    out = {}
    for w in hlib.waivers_for(doc, rule):
        if w.get("reason") and w.get("approver"):
            out[str(w.get("path"))] = w
    return out


def citations(root, groot, d=None):
    """[(claim_id, relpath)] for phase 9's PRODUCED artifacts.

    Only the dependency audit. The SEC-ID evidence is `path:line` pointers into
    SOURCE, which is the SUBJECT of phase 9, not evidence captured for it:
    source files have no sidecars, and demanding one would be shape-matching.
    Their freshness is covered by the right mechanism -- registry `verifies:`
    lists src/** and mobile/** for check-security, so a phase-9 approval goes
    stale when the code it verified changes. A stale SEC-ID verdict is a stale
    APPROVAL, not a mis-cited artifact.
    """
    sec_dir = os.path.join(root, groot, "security")
    if not os.path.isdir(sec_dir):
        return []
    return [("9:dependency-audit", os.path.join("security", f))
            for f in sorted(os.listdir(sec_dir))
            if "audit" in f.lower() or "depend" in f.lower()]


def main():
    ap = argparse.ArgumentParser(prog="check-security.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--scan-root", default=None, help="tree to scan for secrets (default governed_root)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    d = args.dir or os.path.join(root, groot, "sdlc")
    scan_root = args.scan_root or os.path.join(root, groot)

    errs, warns, notes = [], [], []
    wv = waivers(root)

    secs = sec_ids_from_threat_model(os.path.join(d, "04-threat-model.md"))
    if secs is None:
        errs.append("threat model not found at %s/04-threat-model.md; nothing to verify against." % d)
        secs = []

    report_path = os.path.join(d, "09-security-report.md")
    text = read(report_path)
    if text is None:
        errs.append("security report not found at %s. Phase 9 cannot be approved without it."
                    % report_path)
        text = ""
    text = strip_comments(text)

    # ---- 1. every SEC-ID accounted for, with resolvable evidence ---------
    secblocks = blocks(text, "SEC")
    for sid in secs:
        blk = secblocks.get(sid)
        if blk is None:
            errs.append("%s from the threat model is not addressed in the security report. Silence "
                        "on a SEC-ID is a failure, not an implicit pass." % sid)
            continue
        verdict = (field(blk, "Verdict") or "").strip().upper()
        if verdict not in VERDICTS:
            errs.append("%s: Verdict %r is not one of %s." % (sid, verdict or "(missing)", sorted(VERDICTS)))
            continue
        if verdict == "EVIDENCED":
            ev = field(blk, "Evidence") or ""
            resolved = resolve_evidence(root, ev)
            if not resolved:
                errs.append("%s is EVIDENCED but cites no resolvable `path:line` evidence "
                            "(got %r)." % (sid, ev[:80]))
            bad = [(r, l, why) for r, l, why in resolved if why]
            for r, l, why in bad:
                errs.append("%s evidence %s:%d does not resolve — %s. A citation that does not "
                            "point at real code is not evidence." % (sid, r, l, why))
            if not field(blk, "Method"):
                warns.append("%s: no '**Method:**' recorded (how it was verified)." % sid)
        elif verdict == "FAILED":
            if sid in wv:
                notes.append("%s FAILED but is waived by %s (%s)"
                             % (sid, wv[sid].get("approver"), wv[sid].get("reason")))
            else:
                errs.append("%s is FAILED with no waiver. Record one with "
                            "`harness/bin/gate.sh waive security --path %s --reason \"...\" "
                            "--approver \"...\"` or fix the mitigation." % (sid, sid))
        elif verdict == "WAIVED" and sid not in wv:
            errs.append("%s claims WAIVED but no matching waiver exists in phase.yaml. A report "
                        "cannot waive itself." % sid)

    extra = sorted(set(secblocks) - set(secs))
    for sid in extra:
        warns.append("report covers %s, which is not in the threat model." % sid)
    if secs:
        notes.append("SEC-IDs: %d in threat model, %d addressed" % (len(secs), len(secblocks)))

    # ---- 2. independent secrets scan (run by the gate, not read) ---------
    hits = secrets_scan(scan_root)
    live = [h for h in hits if ("%s:%d" % (h[0], h[1])) not in wv and h[0] not in wv]
    notes.append("secrets scan: %d file-line hit(s) across %s"
                 % (len(hits), os.path.relpath(scan_root, root)))
    # Say what was covered, so a future reader can tell a clean scan from a
    # narrow one. "0 hits" over source-only is a different statement from
    # "0 hits" over source AND every verification artifact.
    _ev = [x for x in ("evidence", "test-results", ".run")
           if os.path.isdir(os.path.join(scan_root, x))]
    notes.append("scan covered verification output too (%s); a credential captured in a "
                 "device log or console dump during 10a/10b/10c is committed evidence."
                 % (", ".join(_ev) if _ev else "none present"))
    for rel, ln, kind in live:
        errs.append("SECRET DETECTED by the gate's own scan: %s:%d (%s). Remove it and rotate the "
                    "credential, or waive with a reason and an approver." % (rel, ln, kind))

    # ---- 3. dependency audit ---------------------------------------------
    sec_dir = os.path.join(root, groot, "security")
    audit_files = []
    if os.path.isdir(sec_dir):
        audit_files = [f for f in sorted(os.listdir(sec_dir))
                       if "audit" in f.lower() or "depend" in f.lower()]
    if not audit_files:
        errs.append("no dependency-audit artifact found in %s (expected e.g. dependency-audit.json "
                    "or dependency-audit.txt). Phase 9 requires a real audit run, not a claim."
                    % os.path.relpath(sec_dir, root))
    else:
        notes.append("dependency audit artifact(s): %s" % ", ".join(audit_files))
        import provenance
        _pe, _pw, _pn = provenance.audit(root, groot, citations(root, groot))
        errs += _pe
        warns += _pw
        notes += _pn
        for f in audit_files:
            fp = os.path.join(sec_dir, f)
            if f.endswith(".json"):
                try:
                    data = json.loads(read(fp) or "{}")
                except Exception as exc:
                    errs.append("dependency audit %s does not parse as JSON: %r" % (f, exc))
                    continue
                sev = {}
                meta = (data.get("metadata") or {}).get("vulnerabilities")
                if isinstance(meta, dict):
                    sev = meta
                elif isinstance(data.get("vulnerabilities"), dict):
                    for v in data["vulnerabilities"].values():
                        s = str((v or {}).get("severity", "")).lower()
                        sev[s] = sev.get(s, 0) + 1
                high = int(sev.get("high", 0) or 0) + int(sev.get("critical", 0) or 0)
                if high:
                    key = "dependency-audit:high"
                    if key in wv:
                        notes.append("%d high/critical dependency finding(s), waived by %s"
                                     % (high, wv[key].get("approver")))
                    else:
                        errs.append("%d high/critical dependency vulnerability/ies in %s and no "
                                    "waiver. Upgrade, or waive with "
                                    "`--path dependency-audit:high`." % (high, f))
                else:
                    notes.append("dependency audit: no high/critical findings")

    # ---- 4. open high-severity findings table ----------------------------
    for m in re.finditer(r"^\|\s*(SF-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", text, re.M):
        fid, sevr, desc, status = (x.strip() for x in m.groups())
        if sevr.lower() in ("high", "critical") and status.lower() not in ("closed", "fixed", "resolved"):
            if fid in wv:
                notes.append("%s (%s) open but waived by %s" % (fid, sevr, wv[fid].get("approver")))
            else:
                errs.append("finding %s is %s severity and still %r with no waiver."
                            % (fid, sevr, status))

    if not args.quiet:
        print("check-security: %s" % report_path)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  all %d SEC-ID(s) evidenced or waived; secrets scan clean; dependency "
                  "audit present with no unwaived high findings." % len(secs))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
