#!/usr/bin/python3
"""Fixture stand-in for `claude -p --agent claude-security:claude-security` (increment 5).

The gate's secscan worker finds `claude` in the fixture's trusted directory (the
shim dir) and runs it in its scan clone. This stub records its argv and cwd, then
writes the report Claude Security would: CLAUDE-SECURITY-<ts>/ with the SARIF log
and the revision stamp. What it writes comes from <shim>/claude-scan.json:

  {"findings": [{"severity": "HIGH", "confidence": "HIGH", "panel": {"true": 3, "voters": 3},
                 "path": "src/a.js", "line": 2, "id": "abc", "rule": "CWE-78"}],
   "stamp": "head" | "other" | "dirty", "write_report": true}
"""
import json
import os
import subprocess
import sys
import time

shim = os.environ.get("MOADIX_GUARD_SHIM") or os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(shim, "claude-calls.log"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                        "sdlc_in_clone": os.path.exists(".sdlc")}) + "\n")
try:
    with open(os.path.join(shim, "claude-scan.json")) as f:
        spec = json.load(f)
except (OSError, ValueError):
    spec = {"findings": [], "stamp": "head"}
if not spec.get("write_report", True):
    print(json.dumps({"result": "nothing written"}))
    sys.exit(0)
head = subprocess.run(["/usr/bin/git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
stamp_sha = {"head": head, "other": "0" * 40, "dirty": head}.get(spec.get("stamp", "head"), head)
suffix = "-dirty" if spec.get("stamp") == "dirty" else ""
d = "CLAUDE-SECURITY-%s" % time.strftime("%Y%m%d-%H%M%S")
os.makedirs(d)
results = []
for i, fd in enumerate(spec.get("findings") or []):
    rec = {"claudeSecurityPluginFindingId": fd.get("id") or "v3:%d" % i, "severity": fd.get("severity"),
           "confidence": fd.get("confidence"), "title": fd.get("title", "finding %d" % i)}
    if fd.get("panel"):
        rec["verification"] = {"panel": fd["panel"]}
    results.append({"ruleId": fd.get("rule", "CWE-78"), "level": {"CRITICAL": "error", "HIGH": "error",
                                                                  "MEDIUM": "warning", "LOW": "note"}.get(
        str(fd.get("severity")), "note"), "message": {"text": fd.get("title", "finding %d" % i)},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": fd.get("path", "src/a.js"),
                                                                 "uriBaseId": "%SRCROOT%"},
                                            "region": {"startLine": fd.get("line", 1)}}}],
        "properties": {"claudeSecurityPlugin": rec}})
sarif = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Claude Security Plugin for Claude Code"}},
                                       "results": results}]}
with open(os.path.join(d, "CLAUDE-SECURITY-RESULTS.sarif"), "w") as f:
    json.dump(sarif, f)
with open(os.path.join(d, "CLAUDE-SECURITY-REVISION-%s%s.json" % (stamp_sha[:12], suffix)), "w") as f:
    json.dump({"revision": stamp_sha, "effort": "medium", "verification": {"status": "complete"}}, f)
print(json.dumps({"result": "scan written", "dir": d}))
