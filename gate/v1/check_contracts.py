#!/usr/bin/env python3
"""check-contracts -- phase 5 gate-run contract lint (increment 5; MOADIX-native).

The GATE runs the pinned Redocly CLI (gate/config/tools.yaml) over every API
description committed under sdlc/05-lld/ at HEAD:

  OpenAPI   any .yaml/.yml/.json whose top-level key `openapi:` is present
  Arazzo    any whose top-level key `arazzo:` is present (workflow descriptions;
            they are linted here, and executed against the running app as
            contract tests in phase 10a by check_live_contracts)

`redocly lint --config gate/config/redocly/redocly.yaml` (the `recommended`
ruleset): the product's redocly.yaml and .redocly.lint-ignore.yaml are never
read, because the lint runs on an export of HEAD with them removed and with the
gate's config. ANY error fails; warnings are reported. Telemetry is off.

No API description at all fails: phase 5 ships a contract. A product with no API
records that through its Target Platform Ruling (profiles.yaml not_applicable),
not by leaving the folder empty.

Exit 0 pass, 1 fail, 2 UNKNOWN (Redocly missing or could not run).
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import toolrun  # noqa: E402
from check_scanners import export_head  # noqa: E402

PHASE = "5"
CONFIG = os.path.join(toolrun.GATE, "config", "redocly", "redocly.yaml")
KIND = re.compile(r'^\s*"?(openapi|arazzo)"?\s*:\s*"?([0-9][^"\s,]*)', re.M)
ENV = {"REDOCLY_TELEMETRY": "off", "REDOCLY_SUPPRESS_UPDATE_NOTICE": "true"}


def descriptions(tree):
    """[(relpath, kind, version)] under sdlc/05-lld/ in the exported tree."""
    base = os.path.join(tree, "sdlc", "05-lld")
    out = []
    for d, dirs, fs in os.walk(base):
        dirs.sort()
        for f in sorted(fs):
            if not f.endswith((".yaml", ".yml", ".json")):
                continue
            p = os.path.join(d, f)
            with open(p, encoding="utf-8", errors="replace") as fh:
                head = fh.read(4000)
            m = KIND.search(head)
            if m:
                out.append((os.path.relpath(p, tree), m.group(1), m.group(2)))
    return out


def main():
    root = hlib.project_root()
    notes, errs, unknown, findings = [], [], [], []
    out = toolrun.mkdtemp("moadix-contracts-")
    try:
        tree = os.path.join(out, "tree")
        os.makedirs(tree)
        try:
            removed = export_head(root, tree)
            docs = descriptions(tree)
            if not docs:
                errs.append("no OpenAPI or Arazzo description is committed under sdlc/05-lld/ (a top-level "
                            "`openapi:` or `arazzo:` key). Phase 5 ships the contract the code is built against")
            results = {}
            for rel, kind, ver in docs:
                rc, so, se, info = toolrun.run("redocly", ["lint", rel, "--config", CONFIG, "--format", "json"],
                                               cwd=tree, writable=[out], network="none", env=ENV, timeout=300)
                try:
                    doc = json.loads(so)
                except ValueError:
                    errs.append("redocly lint %s exited %d without a JSON report: %s" % (
                        rel, rc, (se or so).strip()[-300:]))
                    continue
                results[rel] = {"kind": kind, "version": ver, "exit_code": rc, "report": doc}
                for p in doc.get("problems") or []:
                    sev = str(p.get("severity") or "error")
                    loc = (p.get("location") or [{}])[0]
                    where = "%s %s" % (rel, (loc.get("pointer") or "")[:80])
                    line = "%s: %s (%s)" % (where, str(p.get("message") or "")[:160], p.get("ruleId"))
                    (errs.append if sev == "error" else notes.append)(("lint error " if sev == "error"
                                                                        else "lint warning ") + line)
                tot = doc.get("totals") or {}
                if rc != 0 and not tot.get("errors"):
                    errs.append("redocly lint %s exited %d: %s" % (rel, rc, (se or "").strip()[-200:]))
                notes.append("%s %s %s: %d error(s), %d warning(s)" % (
                    kind, ver, rel, tot.get("errors", 0), tot.get("warnings", 0)))
            if docs:
                _p, pin = toolrun.tool("redocly")
                rel, digest = toolrun.record(root, PHASE, "redocly", str(pin["version"]), "redocly-lint.json",
                                             json.dumps(results, indent=1, sort_keys=True), "check-contracts")
                notes.append("evidence %s (sha256 %s, redocly %s)" % (rel, digest[:12], pin["version"]))
            if removed:
                notes.append("not read (product ignore/config files): %s" % ", ".join(removed))
        except toolrun.ToolUnavailable as e:
            unknown.append(str(e))
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return toolrun.report("check-contracts (phase 5, gate-run Redocly lint)", notes, findings, errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
