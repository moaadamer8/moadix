#!/usr/bin/env python3
"""check-workflows -- phase 11 CI workflow security and lint (increment 7b; Amendment 3 RL2).

The GATE runs the pinned zizmor and actionlint over every workflow committed under
.github/workflows/ at HEAD, on an export with the product's zizmor/actionlint config removed:

  zizmor      --no-config --no-online-audits --format json (no token is given to it). Any
              finding at low severity or above fails; informational ones are reported.
  actionlint  with the gate's empty config and shellcheck/pyflakes integration off (the gate
              runs no other program on the product's scripts). Any error fails.

No workflow at all fails: RL1/RL2 ask CI to re-run the gate tools with pinned actions.
Exit 0 pass, 1 fail, 2 UNKNOWN.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import readonly  # noqa: E402
import toolrun  # noqa: E402

PHASE = "11"
ACTIONLINT_CONFIG = os.path.join(toolrun.GATE, "config", "actionlint", "actionlint.yaml")
BLOCKING = ("low", "medium", "high")


def workflows(tree):
    d = os.path.join(tree, ".github", "workflows")
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(".github", "workflows", f) for f in os.listdir(d) if f.endswith((".yml", ".yaml")))


def zizmor(tree, out, files, errs, notes, results):
    rc, so, se, _info = toolrun.run("zizmor", ["--no-config", "--no-online-audits", "--format", "json"] + files,
                                    cwd=tree, writable=[out], network="none", timeout=300)
    try:
        doc = json.loads(so) if so.strip() else []
    except ValueError:
        errs.append("zizmor exited %d without a JSON report: %s" % (rc, (se or so).strip()[-300:]))
        return
    results["zizmor"] = doc
    for f in doc or []:
        sev = str(((f.get("determinations") or {}).get("severity")) or "unknown").lower()
        loc = ((f.get("locations") or [{}])[0].get("symbolic") or {})
        where = (loc.get("key") or {}).get("Local", {}).get("given_path") or ""
        line = "%s %s: %s" % (f.get("ident"), where, str(f.get("desc") or "")[:160])
        if sev in BLOCKING or sev == "unknown":
            errs.append("zizmor [%s] %s" % (sev, line))
        else:
            notes.append("zizmor [%s] %s" % (sev, line))
    notes.append("zizmor: %d finding(s) over %d workflow(s)" % (len(doc or []), len(files)))


def actionlint(tree, out, files, errs, notes, results):
    rc, so, se, _info = toolrun.run("actionlint", ["-config-file", ACTIONLINT_CONFIG, "-shellcheck=", "-pyflakes=",
                                                   "-format", "{{json .}}"] + files, cwd=tree, writable=[out],
                                    network="none", timeout=300)
    try:
        doc = json.loads(so) if so.strip() else []
    except ValueError:
        errs.append("actionlint exited %d without a JSON report: %s" % (rc, (se or so).strip()[-300:]))
        return
    results["actionlint"] = doc
    for e in doc or []:
        errs.append("actionlint %s:%s:%s %s [%s]" % (e.get("filepath"), e.get("line"), e.get("column"),
                                                     str(e.get("message"))[:160], e.get("kind")))
    if rc not in (0, 1) and not doc:
        errs.append("actionlint exited %d: %s" % (rc, (se or so).strip()[-300:]))
    notes.append("actionlint: %d error(s)" % len(doc or []))


def main():
    root = hlib.project_root()
    notes, errs, unknown = [], [], []
    out = toolrun.mkdtemp("moadix-workflows-")
    try:
        tree = os.path.join(out, "tree")
        os.makedirs(tree)
        try:
            removed = readonly.export(root, tree)
            files = workflows(tree)
            results = {}
            if not files:
                errs.append("no workflow is committed under .github/workflows/ (RL1/RL2: CI re-runs every gate tool "
                            "with actions pinned by SHA)")
            else:
                zizmor(tree, out, files, errs, notes, results)
                actionlint(tree, out, files, errs, notes, results)
                versions = {n: str(toolrun.tool(n)[1]["version"]) for n in ("zizmor", "actionlint")}
                rel, digest = toolrun.record(root, PHASE, "zizmor+actionlint", json.dumps(versions, sort_keys=True),
                                             "workflows.json", json.dumps(results, indent=1, sort_keys=True),
                                             "check-workflows")
                notes.append("evidence %s (sha256 %s)" % (rel, digest[:12]))
            if removed:
                notes.append("not read (product ignore/config files): %s" % ", ".join(removed))
        except toolrun.ToolUnavailable as e:
            unknown.append(str(e))
        except Exception as e:  # unknown, never a pass
            unknown.append("%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return toolrun.report("check-workflows (phase 11, gate-run zizmor and actionlint)", notes, [], errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
