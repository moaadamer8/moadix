#!/usr/bin/env python3
"""check-live-contracts -- phase 10a: Arazzo workflows run against the local instance.

MOADIX-native (increment 5). Where the product commits Arazzo descriptions
under sdlc/05-lld/ (linted in phase 5 by check_contracts), the GATE runs each
one as a contract test with the pinned Redocly CLI (`redocly respect`) against
live.base_url from .sdlc/config/product-tools.yaml:

  * live.base_url must be a loopback http(s) URL -- the local test instance,
    never a production URL; every sourceDescription is pointed at it with
    --server, so a server URL written in the description is never used;
  * the run is confined to loopback when the installed gate runs it;
  * any failed step fails the phase; the JSON result is evidence.

No Arazzo description: nothing to run, and that passes with a note (Arazzo is
optional; the OpenAPI contract itself is phase 5's).

Exit 0 pass, 1 fail, 2 UNKNOWN (Redocly missing, or the app does not answer).
"""
import json
import os
import re
import shutil
import sys
import urllib.parse

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import toolrun  # noqa: E402
from check_contracts import ENV, descriptions  # noqa: E402
from check_scanners import export_head  # noqa: E402
from check_surface_coverage import LOOPBACK_HOSTS, probe  # noqa: E402

PHASE = "10a"


def source_names(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return re.findall(r"^\s*-?\s*name:\s*['\"]?([A-Za-z0-9_.-]+)['\"]?\s*$", text.split("workflows:")[0], re.M)


def main():
    root = hlib.project_root()
    notes, errs, unknown = [], [], []
    url = str((toolrun.product_tools(root).get("live") or {}).get("base_url") or "")
    sp = urllib.parse.urlsplit(url)
    out = toolrun.mkdtemp("moadix-arazzo-")
    try:
        tree = os.path.join(out, "tree")
        os.makedirs(tree)
        export_head(root, tree)
        flows = [(rel, v) for rel, kind, v in descriptions(tree) if kind == "arazzo"]
        if not flows:
            notes.append("no Arazzo description under sdlc/05-lld/: no contract workflow to run")
            return toolrun.report("check-live-contracts (phase 10a)", notes, [], errs, unknown)
        if sp.scheme not in ("http", "https") or (sp.hostname or "") not in LOOPBACK_HOSTS:
            errs.append("live.base_url %r is not a loopback http(s) URL; contract tests run only against the local "
                        "test instance, never a production URL" % url)
            return toolrun.report("check-live-contracts (phase 10a)", notes, [], errs, unknown)
        if probe(url, "GET", "/")[0] is None:
            unknown.append("the app does not answer at %s; start the local instance and the gate runs the "
                           "workflows again" % url)
            return toolrun.report("check-live-contracts (phase 10a)", notes, [], errs, unknown)
        results = {}
        try:
            for rel, ver in flows:
                rep = os.path.join(out, re.sub(r"[^A-Za-z0-9]+", "-", rel) + ".json")
                args = ["respect", rel, "--json-output", rep]
                for n in source_names(os.path.join(tree, rel)):
                    args += ["--server", "%s=%s" % (n, url)]
                rc, so, se, info = toolrun.run("redocly", args, cwd=tree, writable=[out], network="loopback",
                                               env=ENV, timeout=900)
                try:
                    with open(rep) as f:
                        results[rel] = json.load(f)
                except (OSError, ValueError):
                    results[rel] = {"exit_code": rc, "output": (so + se)[-2000:]}
                if rc != 0:
                    errs.append("Arazzo %s: a workflow step failed against %s (redocly respect exit %d): %s" % (
                        rel, url, rc, " ".join((se or so).split())[-300:]))
                else:
                    notes.append("Arazzo %s (%s): every workflow passed against %s" % (rel, ver, url))
            _p, pin = toolrun.tool("redocly")
            erel, digest = toolrun.record(root, PHASE, "redocly-respect", str(pin["version"]), "arazzo-respect.json",
                                          json.dumps(results, indent=1, sort_keys=True), "check-live-contracts")
            notes.append("evidence %s (sha256 %s)" % (erel, digest[:12]))
        except toolrun.ToolUnavailable as e:
            unknown.append(str(e))
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return toolrun.report("check-live-contracts (phase 10a)", notes, [], errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
