#!/usr/bin/env python3
"""check-scanners -- phase 9 gate-run scanners (increment 5; MOADIX-native).

    check_scanners.py --tool gitleaks|osv-scanner|trivy|semgrep

The GATE runs the pinned tool (gate/config/tools.yaml, from <MOADIX_HOME>/tools)
against the commit, never the agent; the agent may run its own copy for
feedback, but only this run counts. Each run writes its SARIF/JSON to
.sdlc/evidence/9/ with the source commit (toolrun.record).

What it scans
  gitleaks     history: `gitleaks git` over every commit; tree: `gitleaks dir`
               over an export of HEAD. Every leak is HIGH (a secret).
  osv-scanner  every lockfile in the HEAD export (`scan source -r`); severity
               from the advisory group's max CVSS score; none -> unknown.
  trivy        `trivy fs` (vuln, misconfig, secret) over the HEAD export, plus
               `trivy image` for each image .sdlc/config/product-tools.yaml
               declares under `images:`. Trivy's own severity.
  semgrep      the gate's local rules (gate/config/semgrep/) plus the product's
               own security/semgrep/*.yml at HEAD; --metrics=off, no registry,
               no account. metadata.moadix_severity, else ERROR=high,
               WARNING=medium, INFO=low.

Suppression is the gate's alone. The scan runs on `git archive HEAD` with the
product's ignore files removed (.gitleaksignore, .trivyignore, .semgrepignore,
osv-scanner.toml, .redocly.lint-ignore.yaml), with the gate's own configs, and
with inline suppressions off (--ignore-gitleaks-allow, --disable-nosem). An
exception is a ledger waiver, and high/critical findings cannot be waived (v1).

Exit: 0 pass; 1 a finding at critical/high/unknown, or the tool failed on the
product; 2 UNKNOWN (the instrument is missing or could not run).
"""
import argparse
import io
import json
import re
import os
import shutil
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import toolrun  # noqa: E402

PHASE = "9"
CONFIG = os.path.join(toolrun.GATE, "config")
IGNORE_FILES = {".gitleaksignore", ".trivyignore", ".trivyignore.yaml", ".semgrepignore", "osv-scanner.toml",
                ".redocly.lint-ignore.yaml", ".gitleaks.toml", "trivy.yaml"}
# Go tools verify TLS through the system trust store; naming the system bundle keeps them
# working where the trust daemon is not reachable (measured: inside a sandbox).
TLS_ENV = {"SSL_CERT_FILE": "/etc/ssl/cert.pem"}


def export_head(root, dest):
    """Extract `git archive HEAD` into dest, minus the product's scanner ignore files."""
    p = subprocess.run([toolrun.GIT, "-C", root, "archive", "--format=tar", "HEAD"], capture_output=True)
    if p.returncode != 0:
        raise toolrun.ToolUnavailable("git archive HEAD failed: %s" % p.stderr.decode(errors="replace")[:200])
    removed = []
    with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
        members = []
        for m in tf.getmembers():
            name = m.name
            if name.startswith("/") or ".." in name.split("/") or m.issym() or m.islnk():
                continue
            if name.rsplit("/", 1)[-1] in IGNORE_FILES:
                removed.append(name)
                continue
            members.append(m)
        tf.extractall(dest, members=members)  # noqa: S202  (names checked above: no absolute, no .., no links)
    return removed


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- gitleaks
def run_gitleaks(root, out, notes):
    findings, files = [], []
    empty = os.path.join(out, "no-ignore")
    os.makedirs(empty)
    common = ["--config", os.path.join(CONFIG, "gitleaks.toml"), "--gitleaks-ignore-path", empty,
              "--ignore-gitleaks-allow", "--redact", "--no-banner", "--exit-code", "0", "--report-format", "sarif"]
    for mode, target, name in (("git", root, "gitleaks-history.sarif"), ("dir", None, "gitleaks-tree.sarif")):
        rep = os.path.join(out, name)
        if mode == "dir":
            tree = os.path.join(out, "tree")
            os.makedirs(tree)
            export_head(root, tree)
            target = tree
        rc, so, se, info = toolrun.run("gitleaks", [mode, target, "--report-path", rep] + common, cwd=out,
                                       writable=[out])
        if rc != 0 or not os.path.exists(rep):
            raise RuntimeError("gitleaks %s exited %d: %s" % (mode, rc, (se or so).strip()[-300:]))
        if mode == "git":
            # A history scan that read no commit is not a clean history: git failed under it.
            m = re.search(r"(\d+) commits? scanned", (se or "") + (so or ""))
            if not m or int(m.group(1)) == 0:
                raise RuntimeError("gitleaks read no commit of the history (%s); a scan that read nothing is "
                                   "not a clean result" % ((se or so).strip().splitlines() or ["no output"])[-1][-200:])
            notes.append("gitleaks history: %s commits scanned" % m.group(1))
        files.append((name, rep, info))
        for r in sarif_results(read_json(rep)):
            loc = r["loc"]
            for base in (target.rstrip("/") + "/", os.path.realpath(target).rstrip("/") + "/"):
                loc = loc[len(base):] if loc.startswith(base) else loc  # repo-relative, not the scratch export
            # A secret in the history or the tree is HIGH: remove it and rotate it.
            findings.append(("high", "gitleaks:%s" % r["rule"], "%s %s (%s)" % (
                mode == "git" and "history" or "tree", loc, r.get("commit") or "HEAD")))
    notes.append("gitleaks scanned the full history and the HEAD tree with the gate's config; inline "
                 "gitleaks:allow and .gitleaksignore are ignored")
    return findings, files


def sarif_results(doc):
    out = []
    for run in doc.get("runs") or []:
        for r in run.get("results") or []:
            locs = r.get("locations") or [{}]
            pl = (locs[0].get("physicalLocation") or {})
            path = ((pl.get("artifactLocation") or {}).get("uri")) or "?"
            line = (pl.get("region") or {}).get("startLine")
            props = r.get("properties") or {}
            out.append({"rule": r.get("ruleId") or "?", "loc": "%s:%s" % (path, line) if line else path,
                        "commit": (props.get("commitSha") or "")[:12], "level": r.get("level"), "props": props,
                        "message": ((r.get("message") or {}).get("text") or "")[:160]})
    return out


# ---------------------------------------------------------------- osv-scanner
def run_osv(root, out, notes):
    tree = os.path.join(out, "tree")
    os.makedirs(tree)
    export_head(root, tree)
    rep = os.path.join(out, "osv-scanner.json")
    cfg = os.path.join(out, "osv-scanner-gate.toml")
    with open(cfg, "w") as f:
        f.write("# gate: no ignored vulnerabilities\n")
    rc, so, se, info = toolrun.run("osv-scanner", ["scan", "source", "-r", "--config", cfg, "--format", "json",
                                                   "--output-file", rep, "--verbosity", "error", tree],
                                   cwd=out, writable=[out], network="any", env=TLS_ENV, timeout=900)
    # 0 = no vulnerabilities, 1 = vulnerabilities found, 128 = no packages found.
    if rc == 128:
        notes.append("osv-scanner found no lockfile in the HEAD tree (nothing to scan)")
        with open(rep, "w") as f:
            json.dump({"results": [], "note": "no packages found"}, f)
        return [], [("osv-scanner.json", rep, info)]
    if rc not in (0, 1) or not os.path.exists(rep):
        raise RuntimeError("osv-scanner exited %d: %s" % (rc, (se or so).strip()[-300:]))
    findings = []
    for res in read_json(rep).get("results") or []:
        src = os.path.relpath(((res.get("source") or {}).get("path") or "?"), tree)
        for pkg in res.get("packages") or []:
            pk = pkg.get("package") or {}
            for g in pkg.get("groups") or []:
                ids = g.get("ids") or []
                sev = toolrun.score_severity(g.get("max_severity")) if str(g.get("max_severity") or "") else "unknown"
                findings.append((sev, ids[0] if ids else "?", "%s@%s in %s (cvss %s)" % (
                    pk.get("name"), pk.get("version"), src, g.get("max_severity") or "none")))
    notes.append("osv-scanner checked every lockfile in the HEAD tree against osv.dev")
    return findings, [("osv-scanner.json", rep, info)]


# ---------------------------------------------------------------- trivy
def trivy_findings(doc, label):
    out = []
    for res in doc.get("Results") or []:
        tgt = res.get("Target") or "?"
        for v in res.get("Vulnerabilities") or []:
            out.append((str(v.get("Severity") or "UNKNOWN").lower(), v.get("VulnerabilityID") or "?",
                        "%s %s@%s in %s%s" % (label, v.get("PkgName"), v.get("InstalledVersion"), tgt,
                                              " (fixed in %s)" % v["FixedVersion"] if v.get("FixedVersion") else "")))
        for m in res.get("Misconfigurations") or []:
            if str(m.get("Status") or "FAIL") != "FAIL":
                continue
            out.append((str(m.get("Severity") or "UNKNOWN").lower(), m.get("ID") or "?",
                        "%s misconfiguration in %s: %s" % (label, tgt, (m.get("Title") or "")[:100])))
        for s in res.get("Secrets") or []:
            out.append((str(s.get("Severity") or "UNKNOWN").lower(), s.get("RuleID") or "?",
                        "%s secret in %s:%s" % (label, tgt, s.get("StartLine"))))
    return [(s if s in toolrun.SEVERITIES else "unknown", i, t) for s, i, t in out]


def run_trivy(root, out, notes):
    toolrun.tool("trivy")  # missing instrument: UNKNOWN before anything else
    try:
        cache = toolrun.cache_dir("trivy")
    except OSError as e:
        raise toolrun.ToolUnavailable("trivy's DB cache cannot be created (%s)" % e) from None
    base = ["--cache-dir", cache, "--skip-version-check", "--disable-telemetry", "--quiet"]
    # 1. the vulnerability DB (network); 2. the scans themselves (no DB update).
    rc, so, se, info = toolrun.run("trivy", ["image", "--download-db-only"] + base, cwd=out,
                                   writable=[out, cache], network="any", env=TLS_ENV, timeout=900)
    if rc != 0:
        raise toolrun.ToolUnavailable("trivy could not update its vulnerability DB: %s" % (se or so).strip()[-300:])
    tree = os.path.join(out, "tree")
    os.makedirs(tree)
    export_head(root, tree)
    files, findings = [], []
    scan = ["--scanners", "vuln,misconfig,secret", "--format", "json", "--ignorefile", "/dev/null",
            "--skip-db-update", "--skip-java-db-update", "--skip-check-update", "--exit-code", "0"] + base
    rep = os.path.join(out, "trivy-fs.json")
    rc, so, se, info = toolrun.run("trivy", ["fs"] + scan + ["--output", rep, tree], cwd=out,
                                   writable=[out, cache], network="none", timeout=900)
    if rc != 0 or not os.path.exists(rep):
        raise RuntimeError("trivy fs exited %d: %s" % (rc, (se or so).strip()[-300:]))
    files.append(("trivy-fs.json", rep, info))
    findings += trivy_findings(read_json(rep), "fs")
    images = [str(i) for i in (toolrun.product_tools(root).get("images") or [])]
    for i, img in enumerate(images):
        rep = os.path.join(out, "trivy-image-%d.json" % (i + 1))
        rc, so, se, info = toolrun.run("trivy", ["image"] + scan + ["--output", rep, "--image-src", "docker,remote", img],
                                       cwd=out, writable=[out, cache], network="any", env=TLS_ENV, timeout=900)
        if rc != 0 or not os.path.exists(rep):
            raise RuntimeError("trivy image %s exited %d: %s" % (img, rc, (se or so).strip()[-300:]))
        files.append(("trivy-image-%d.json" % (i + 1), rep, info))
        findings += trivy_findings(read_json(rep), "image %s" % img)
    notes.append("trivy scanned the HEAD tree (vuln, misconfig, secret) and %d declared image(s)%s" % (
        len(images), ": " + ", ".join(images) if images else ""))
    return findings, files


# ---------------------------------------------------------------- semgrep
SEMGREP_SEV = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}


def run_semgrep(root, out, notes):
    tree = os.path.join(out, "tree")
    os.makedirs(tree)
    removed = export_head(root, tree)
    configs = ["--config", os.path.join(CONFIG, "semgrep")]
    own = list(toolrun.tracked(root, "security/semgrep/*.yml", "security/semgrep/*.yaml"))
    for p in own:
        configs += ["--config", os.path.join(tree, p)]
    rep = os.path.join(out, "semgrep.json")
    rc, so, se, info = toolrun.run("semgrep", ["scan"] + configs + [
        "--metrics=off", "--disable-version-check", "--disable-nosem", "--json", "--output", rep, "--quiet",
        "--exclude", "security/semgrep", "."], cwd=tree, writable=[out], network="none", timeout=900)
    if rc not in (0, 1) or not os.path.exists(rep):
        raise RuntimeError("semgrep exited %d: %s" % (rc, (se or so).strip()[-300:]))
    doc = read_json(rep)
    errors = [e for e in doc.get("errors") or [] if str(e.get("level") or "error") == "error"]
    if errors:
        raise RuntimeError("semgrep reported %d error(s), first: %s" % (
            len(errors), str(errors[0].get("message") or errors[0])[:200]))
    unparsed = sorted({str(e.get("path")) for e in doc.get("errors") or [] if e.get("path")})
    if unparsed:
        # Semgrep skips a file it cannot parse (a warning, not an error): say so, so a
        # clean result is never mistaken for a scan of that file.
        notes.append("semgrep could NOT parse and did not scan %d file(s): %s" % (len(unparsed), ", ".join(unparsed[:8])))
    findings = []
    for r in doc.get("results") or []:
        ex = r.get("extra") or {}
        md = ex.get("metadata") or {}
        sev = str(md.get("moadix_severity") or SEMGREP_SEV.get(str(ex.get("severity")), "unknown")).lower()
        rid = str(r.get("check_id") or "?")
        rid = rid[rid.find("moadix."):] if "moadix." in rid else rid
        findings.append((sev if sev in toolrun.SEVERITIES else "unknown", rid, "%s:%s %s" % (
            r.get("path"), (r.get("start") or {}).get("line"), str(ex.get("message") or "")[:120])))
    notes.append("semgrep ran the gate's local rules%s; nosem comments and .semgrepignore ignored%s" % (
        " plus %d product rule file(s)" % len(own) if own else "",
        " (removed from the scan: %s)" % ", ".join(removed) if removed else ""))
    return findings, [("semgrep.json", rep, info)]


RUNNERS = {"gitleaks": run_gitleaks, "osv-scanner": run_osv, "trivy": run_trivy, "semgrep": run_semgrep}


def main():
    ap = argparse.ArgumentParser(prog="check-scanners", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tool", required=True, choices=sorted(RUNNERS))
    args = ap.parse_args()
    root = hlib.project_root()
    notes, errs, unknown, findings = [], [], [], []
    title = "check-scanners --tool %s (phase 9, gate-run)" % args.tool
    out = toolrun.mkdtemp("moadix-scan-")
    try:
        try:
            findings, files = RUNNERS[args.tool](root, out, notes)
            for name, path, info in files:
                with open(path, "rb") as f:
                    data = f.read()
                rel, digest = toolrun.record(root, PHASE, args.tool, info["version"], name, data,
                                             "check-scanners --tool %s" % args.tool,
                                             {"confined": info["confined"]})
                notes.append("evidence %s (sha256 %s, %s %s%s)" % (rel, digest[:12], args.tool, info["version"],
                                                                  "" if info["confined"] else ", unconfined fixture run"))
        except toolrun.ToolUnavailable as e:
            unknown.append(str(e))
        except RuntimeError as e:
            errs.append(str(e))
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return toolrun.report(title, notes, findings, errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
