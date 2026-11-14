#!/usr/bin/env python3
"""check-api-tools -- phase 5 gate-run API and migration checks (increment 7b; Amendment 3 phase 5).

The GATE runs, on an export of HEAD with the product's tool config removed, never executing
product code:

  vacuum   the OWASP ruleset only (gate/config/vacuum/owasp.yaml) over every OpenAPI
           description in the scope's 05-lld/ folder. Any error or warning fails (the
           amendment's "vacuum OWASP ruleset clean"); info and hints are reported.
  oasdiff  `breaking` from the last released spec (the same file at the commit the product's
           phase 11 was approved on) to HEAD, external $refs refused. Each ERR must be covered
           by an accepted ADR that names the changed path and says breaking and deprecation
           (FC5). No release yet: reported, nothing to compare.
  squawk   over the Postgres migrations .sdlc/config/product-tools.yaml declares
           (migrations: {dialect: postgres, paths: [globs]}), with the gate's empty config.
           Any violation fails. dialect sqlite or none: N/A, reported. Undeclared while SQL
           files are committed: fails (declare the dialect).

Exit 0 pass, 1 fail, 2 UNKNOWN (a tool missing or unable to run).
"""
import glob
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import readonly  # noqa: E402
import toolrun  # noqa: E402
from check_contracts import KIND  # noqa: E402

PHASE = "5"
RULESET = os.path.join(toolrun.GATE, "config", "vacuum", "owasp.yaml")
SQUAWK_CONFIG = os.path.join(toolrun.GATE, "config", "squawk", "squawk.toml")
TLS = {"SSL_CERT_FILE": "/etc/ssl/cert.pem"}


def specs(tree, base):
    out = []
    d0 = os.path.join(tree, base, "05-lld")
    for d, dirs, fs in os.walk(d0):
        dirs.sort()
        for f in sorted(fs):
            if f.endswith((".yaml", ".yml", ".json")):
                p = os.path.join(d, f)
                with open(p, encoding="utf-8", errors="replace") as fh:
                    m = KIND.search(fh.read(4000))
                if m and m.group(1) == "openapi":
                    out.append(os.path.relpath(p, tree))
    return out


def vacuum(tree, out, rel, errs, notes, results):
    rc, so, se, _info = toolrun.run("vacuum", ["lint", "-r", RULESET, "--format", "json", rel], cwd=tree,
                                    writable=[out], network="none", env=TLS, timeout=300)
    try:
        doc = json.loads(so) if so.strip() else []
    except ValueError:
        errs.append("vacuum %s exited %d without a JSON report: %s" % (rel, rc, (se or so).strip()[-300:]))
        return
    results[rel] = doc
    bad = 0
    for f in doc or []:
        sev = int(f.get("severity", 0))
        line = "%s:%s %s: %s" % (rel, ((f.get("range") or {}).get("start") or {}).get("line"), f.get("code"),
                                 str(f.get("message"))[:160])
        if sev <= 1:
            bad += 1
            errs.append("vacuum OWASP %s %s" % ("error" if sev == 0 else "warning", line))
        else:
            notes.append("vacuum OWASP info %s" % line)
    notes.append("vacuum OWASP %s: %d finding(s), %d blocking" % (rel, len(doc or []), bad))


def released_commit(st):
    for ph in st.get("product_phases") or []:
        if ph.get("label") == "11" and ph.get("status") in ("APPROVED", "PROCEED-PAST") and ph.get("commit"):
            return ph["commit"]
    return None


def adr_texts(tree, base):
    out = []
    for d, _dirs, fs in os.walk(os.path.join(tree, "sdlc")):
        if os.path.basename(d) != "adr":
            continue
        for f in fs:
            if f.startswith("ADR-") and f.endswith(".md"):
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    out.append((os.path.relpath(os.path.join(d, f), tree), fh.read()))
    return out


def oasdiff(root, tree, out, rel, base, st, errs, notes, results):
    rc_commit = released_commit(st)
    if not rc_commit:
        notes.append("oasdiff %s: no release yet (phase 11 never approved), nothing to compare" % rel)
        return
    prod_rel = rel
    if base != "sdlc":  # a feature's spec is compared with the product's file of the same name
        prod_rel = "sdlc/" + rel[len(base) + 1:]
    old = readonly.git_show(root, rc_commit, prod_rel)
    if old is None:
        notes.append("oasdiff %s: %s did not exist at the release (%s): a new API, nothing to compare" % (
            rel, prod_rel, rc_commit[:12]))
        return
    bp = os.path.join(out, "released-" + os.path.basename(rel))
    with open(bp, "wb") as f:
        f.write(old)
    rc, so, se, _info = toolrun.run("oasdiff", ["breaking", bp, os.path.join(tree, rel), "--format", "json",
                                                "--allow-external-refs=false"], cwd=tree, writable=[out],
                                    network="none", env=TLS, timeout=300)
    try:
        doc = json.loads(so) if so.strip() else []
    except ValueError:
        errs.append("oasdiff %s exited %d without a JSON report: %s" % (rel, rc, (se or so).strip()[-300:]))
        return
    if rc != 0 and not doc:
        errs.append("oasdiff %s exited %d: %s" % (rel, rc, (se or so).strip()[-300:]))
        return
    results[rel] = doc
    adrs = adr_texts(tree, base)
    for ch in doc or []:
        level = ch.get("level")
        is_err = level in (3, "error", "ERR")
        path = str(ch.get("path") or "")
        line = "%s %s %s: %s" % (ch.get("id"), ch.get("operation") or "", path, str(ch.get("text"))[:160])
        if not is_err:
            notes.append("oasdiff warning %s" % line)
            continue
        cover = [a for a, t in adrs if path and path in t and re.search(r"(?i)\bbreaking\b", t) and
                 re.search(r"(?i)deprecat", t) and re.search(r"(?im)^\s*[-*]?\s*\**Status:?\**:?\s*accepted", t)]
        if cover:
            notes.append("oasdiff ERR %s approved by %s" % (line, ", ".join(cover)))
        else:
            errs.append("oasdiff ERR (breaking change since release %s) %s: no accepted ADR names %s with a deprecation "
                        "plan (FC5)" % (rc_commit[:12], line, path or "the change"))


def squawk(root, tree, out, errs, notes, results):
    cfg = (toolrun.product_tools(root) or {}).get("migrations") or {}
    dialect = str(cfg.get("dialect") or "").lower()
    sqls = sorted(os.path.relpath(p, tree) for p in glob.glob(os.path.join(tree, "**", "*.sql"), recursive=True)
                  if "/node_modules/" not in p)
    if not dialect:
        if sqls:
            errs.append("SQL files are committed (%s) but .sdlc/config/product-tools.yaml declares no migrations.dialect "
                        "(postgres, sqlite or none); squawk cannot know whether they are Postgres" % ", ".join(sqls[:4]))
        else:
            notes.append("squawk: no migrations declared and no SQL committed")
        return
    if dialect != "postgres":
        notes.append("squawk: N/A, migrations are %s (squawk lints Postgres only)" % dialect)
        return
    files = sorted({os.path.relpath(p, tree) for g in (cfg.get("paths") or []) for p in
                    glob.glob(os.path.join(tree, str(g)), recursive=True)})
    if not files:
        errs.append("migrations.dialect is postgres but migrations.paths match no committed file")
        return
    rc, so, se, _info = toolrun.run("squawk", ["-c", SQUAWK_CONFIG, "--reporter", "json"] + files, cwd=tree,
                                    writable=[out], network="none", timeout=300)
    try:
        doc = json.loads(so) if so.strip() else []
    except ValueError:
        errs.append("squawk exited %d without a JSON report: %s" % (rc, (se or so).strip()[-300:]))
        return
    results["squawk"] = doc
    for v in doc or []:
        errs.append("squawk %s:%s %s: %s" % (v.get("file"), v.get("line"), v.get("rule_name") or v.get("rule"),
                                             str(v.get("message"))[:160]))
    if rc != 0 and not doc:
        errs.append("squawk exited %d: %s" % (rc, (se or so).strip()[-300:]))
    notes.append("squawk: %d migration file(s), %d violation(s)" % (len(files), len(doc or [])))


def main():
    root = hlib.project_root()
    notes, errs, unknown = [], [], []
    out = toolrun.mkdtemp("moadix-api-")
    try:
        tree = os.path.join(out, "tree")
        os.makedirs(tree)
        try:
            removed = readonly.export(root, tree)
            st = readonly.state(root)
            base = readonly.doc_dir()
            docs = specs(tree, base)
            if not docs:
                errs.append("no OpenAPI description is committed under %s/05-lld/" % base)
            results = {"vacuum": {}, "oasdiff": {}}
            for rel in docs:
                vacuum(tree, out, rel, errs, notes, results["vacuum"])
                oasdiff(root, tree, out, rel, base, st, errs, notes, results["oasdiff"])
            squawk(root, tree, out, errs, notes, results)
            versions = {n: str(toolrun.tool(n)[1]["version"]) for n in ("vacuum", "oasdiff", "squawk")}
            rel_ev, digest = toolrun.record(root, PHASE, "vacuum+oasdiff+squawk", json.dumps(versions, sort_keys=True),
                                            "api-tools.json", json.dumps(results, indent=1, sort_keys=True),
                                            "check-api-tools")
            notes.append("evidence %s (sha256 %s; %s)" % (rel_ev, digest[:12], ", ".join(
                "%s %s" % kv for kv in sorted(versions.items()))))
            if removed:
                notes.append("not read (product ignore/config files): %s" % ", ".join(removed))
        except toolrun.ToolUnavailable as e:
            unknown.append(str(e))
        except Exception as e:  # unknown, never a pass
            unknown.append("%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return toolrun.report("check-api-tools (phase 5, gate-run vacuum OWASP, oasdiff, squawk)", notes, [], errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
