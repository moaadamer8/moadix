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
               declares under `images:`. Trivy's own severity. 0.8.2: an image's
               high/critical vulnerability with NO fixed version does not fail by
               itself: it goes to trivy-unfixed.json (CVE, package, image digest,
               scan date) and passes only when it is in the set the last APPROVE 9
               recorded in its ledger line (the operator's acceptance; REVIEW 9
               lists the set, APPROVE 9 records it). Any other fails until the
               next APPROVE 9, which may accept it (UNFIXED-ONLY). Text in the
               security report never counts as acceptance. One with a fixed
               version still fails and cannot be waived or accepted.
               0.8.2: also every image the gate builds from the product's
               Dockerfiles (root Dockerfile, live.compose builds, tests/gate/*),
               built confined as the live gates build it, scanned from `docker
               save` before the run's cleanup, recorded by image ID
               (trivy-built.json). The same rules apply.
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
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import gitleaks_allow  # noqa: E402
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
TOOLS_REL = os.path.join(".sdlc", "config", "product-tools.yaml")
ALLOWLISTED: list = []  # 0.8.0: "ALLOWLISTED ..." lines, printed for REVIEW (gate/validate.py collects them)


def gitleaks_allowlist(root):
    """0.8.0 (task-tracker MF-59): ({fingerprint: entry}, findings). The operator's test-fixture allowlist
    (gitleaks_allow), applied only when every entry passes and product-tools.yaml is as ADOPT recorded it; otherwise
    nothing is allowlisted and each reason is a high finding. 0.8.1: shared with check-security
    (gitleaks_allow.adopted_allowlist)."""
    allow, probs = gitleaks_allow.adopted_allowlist(root, toolrun.product_tools)
    return allow, [("high", "gitleaks:allowlist", p) for p in probs]


def _repo_rel(loc, target):
    for base in (target.rstrip("/") + "/", os.path.realpath(target).rstrip("/") + "/"):
        loc = loc[len(base):] if loc.startswith(base) else loc  # repo-relative, not the scratch export
    return loc


def secret_digests(mode, target, out, common):
    """0.8.1 (task-tracker MF-63): {fingerprint: sha256 of the matched secret} for one scan, from a second, unredacted
    gitleaks run whose JSON report stays in a private scratch directory and is deleted at once. Run only when the
    allowlist has a same-value-as entry; the values are compared, never printed or kept."""
    import hashlib
    priv = os.path.join(out, "values-%s" % mode)
    os.makedirs(priv, mode=0o700)
    rep = os.path.join(priv, "values.json")
    args = [a for a in common if a != "--redact"]
    i = args.index("--report-format")
    args[i + 1] = "json"
    try:
        rc, so, se, _info = toolrun.run("gitleaks", [mode, target, "--report-path", rep] + args, cwd=out,
                                        writable=[out])
        if rc != 0 or not os.path.exists(rep):
            raise RuntimeError("gitleaks %s (value check) exited %d: %s" % (mode, rc, (se or so).strip()[-300:]))
        out_map = {}
        for f in read_json(rep) or []:
            path = _repo_rel(str(f.get("File") or ""), target)
            fp = gitleaks_allow.fingerprint(mode, str(f.get("Commit") or ""), path, str(f.get("RuleID") or ""),
                                            f.get("StartLine"))
            out_map[fp] = hashlib.sha256(str(f.get("Secret") or "").encode("utf-8", "replace")).hexdigest()
        return out_map
    finally:
        shutil.rmtree(priv, ignore_errors=True)


def run_gitleaks(root, out, notes):
    findings, files = [], []
    allow, refused = gitleaks_allowlist(root)
    findings += refused
    used = set()
    same = any("same-value-as" in e for e in allow.values())  # 0.8.1 (MF-63)
    values, pending = {}, []
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
        if same:
            values.update(secret_digests(mode, target, out, common))
        for r in sarif_results(read_json(rep)):
            loc = _repo_rel(r["loc"], target)
            path, line = (loc.rsplit(":", 1) + [""])[:2] if re.search(r":\d+$", loc) else (loc, "")
            fp = gitleaks_allow.fingerprint(mode, r.get("commit_full") or "", path, r["rule"], line)
            where = "%s %s (%s)" % (mode == "git" and "history" or "tree", loc, r.get("commit") or "HEAD")
            e = allow.get(fp)
            if e is not None and e.get("path") == path and "same-value-as" in e:
                pending.append((fp, where, r["rule"], e))  # judged once both scans' values are known
                continue
            if e is not None and e.get("path") == path and gitleaks_allow.fixture_path(path) and e.get("fixture") is True:
                used.add(fp)
                ALLOWLISTED.append("ALLOWLISTED %s %s: gitleaks:%s, a test fixture by the operator's adopted allowlist "
                                   "(%s)" % (fp, where, r["rule"], " ".join(str(e.get("reason")).split())[:200]))
                continue
            # A secret in the history or the tree is HIGH: remove it and rotate it.
            findings.append(("high", "gitleaks:%s" % r["rule"], "%s [fingerprint %s]" % (where, fp)))
    for fp, where, rule, e in pending:
        ref = str(e.get("same-value-as"))
        why = None
        if not gitleaks_allow.tests_fixture(allow.get(ref)) or not gitleaks_allow.quote_path(e.get("path")):
            why = "its entry's same-value-as %s is not an adopted test fixture under tests/" % ref
        elif ref not in values:
            why = "the fixture finding %s it names was not found by this scan, so its value cannot be compared" % ref
        elif fp not in values or values[fp] != values[ref]:
            why = "its matched value is not the value of the fixture finding %s" % ref
        if why:
            findings.append(("high", "gitleaks:%s" % rule, "%s [fingerprint %s] (not allowlisted: %s)" % (
                where, fp, why)))
            continue
        used.add(fp)
        ALLOWLISTED.append("ALLOWLISTED %s %s: gitleaks:%s, the same value as the adopted test fixture %s, by the "
                           "operator's adopted allowlist (%s)" % (fp, where, rule, ref,
                                                                 " ".join(str(e.get("reason")).split())[:200]))
    notes.append("gitleaks scanned the full history and the HEAD tree with the gate's config; inline "
                 "gitleaks:allow and .gitleaksignore are ignored")
    if allow:
        unused = sorted(set(allow) - used)
        notes.append("gitleaks: %d finding(s) allowlisted by the adopted allowlist (%d entries)%s" % (
            len(ALLOWLISTED), len(allow), "; %d entries match no finding: %s" % (len(unused), ", ".join(unused[:5]))
            if unused else ""))
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
            # 0.8.0: gitleaks puts the commit in partialFingerprints (properties hold none, so history hits said HEAD)
            commit = (r.get("partialFingerprints") or {}).get("commitSha") or props.get("commitSha") or ""
            out.append({"rule": r.get("ruleId") or "?", "loc": "%s:%s" % (path, line) if line else path,
                        "commit": commit[:12], "commit_full": commit, "level": r.get("level"), "props": props,
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


# 0.8.2: an image's High or Critical vulnerability with no fixed version is residual risk. It is listed in the
# evidence (trivy-unfixed.json) and passes only when the operator accepted it: it is in the set the last APPROVE 9
# recorded in the ledger. The security report's Residual risk lines are documentation, never acceptance. A fixed
# version keeps it a failure (never waivable); every scan reads the fresh trivy result, so a finding that gets a fix
# fails from that scan on.
UNFIXED_SEV = ("critical", "high")
REPORT_NAME = "09-security-report.md"
UNFIXED_LINES: list = []   # 0.8.2: "UNFIXED <json>" lines, one per unfixed finding (gate/validate.py collects them)
PENDING_UNFIXED: list = []  # 0.8.2: the findings that are unfixed and not in the set the last APPROVE 9 accepted


def image_identity(doc):
    """(digest, scan date) of one `trivy image` JSON report: the first repo digest (else the image ID) and
    trivy's CreatedAt."""
    md = doc.get("Metadata") or {}
    digests = [str(d) for d in md.get("RepoDigests") or [] if d]
    digest = digests[0] if digests else str(md.get("ImageID") or "") or "unknown"
    return digest, str(doc.get("CreatedAt") or "") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def split_unfixed(doc, img, digest=None, dockerfile=None):
    """(findings, unfixed) for one image report: every High/Critical vulnerability without a FixedVersion moves out
    of the findings into unfixed, with its CVE, package, installed version, image, digest and scan date. `digest`
    (a built image's ID, from the engine) overrides the report's; `dockerfile` (a built image's Dockerfile path,
    from the repository root) is what its acceptance binds to (validation.unfixed_key)."""
    found, when = image_identity(doc)
    digest = digest or found
    findings, unfixed = [], []
    for res in doc.get("Results") or []:
        keep = dict(res)
        vulns = []
        for v in res.get("Vulnerabilities") or []:
            sev = str(v.get("Severity") or "").lower()
            if sev in UNFIXED_SEV and not str(v.get("FixedVersion") or "").strip():
                unfixed.append({"cve": str(v.get("VulnerabilityID") or "?"), "severity": sev,
                                "package": str(v.get("PkgName") or "?"),
                                "installed": str(v.get("InstalledVersion") or ""), "image": img,
                                "digest": digest, "target": str(res.get("Target") or "?"), "scan_date": when})
                if dockerfile:
                    unfixed[-1]["dockerfile"] = dockerfile
            else:
                vulns.append(v)
        keep["Vulnerabilities"] = vulns
        findings += trivy_findings({"Results": [keep]}, "image %s" % img)
    return findings, unfixed


def residual_section(text):
    """[(line number, line)] under every heading that names residual risk, to the next heading of the same or a
    higher level. HTML comments are blanked (line numbers kept)."""
    text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    out, level = [], None
    for n, line in enumerate(text.splitlines(), 1):
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            if re.search(r"(?i)\bresidual[\s-]+risks?\b", h.group(2)):
                level = len(h.group(1))
                continue
            if level is not None and len(h.group(1)) <= level:
                level = None
        if level is not None:
            out.append((n, line))
    return out


def _gate_pkg():
    gate = os.path.dirname(toolrun.GATE)
    if gate not in sys.path:
        sys.path.insert(0, gate)


def approved_unfixed(root):
    """({acceptance key}, ledger seq) of the unfixed set the last APPROVE 9 recorded in the verified ledger
    (`unfixed_accepted`; keys as validation.unfixed_key), or (set(), None) when no APPROVE 9 exists. A ledger that
    fails its check is UNKNOWN."""
    _gate_pkg()
    from gate import state, validation  # noqa: E402 (late: the gate package, as check_exec imports it)
    try:
        prod = state.load_product(root)
        ok, probs, entries = state.verify_ledger(root, prod["product"])
    except Exception as e:  # no product, unreadable ledger
        raise toolrun.ToolUnavailable("the ledger cannot be read to find the last APPROVE %s: %s" % (PHASE, e)) from None
    if not ok:
        raise toolrun.ToolUnavailable("the ledger fails its check, so the unfixed set the last APPROVE %s accepted "
                                      "cannot be read: %s" % (PHASE, "; ".join(probs[:3])))
    last = None
    for ent in entries:
        if str(ent.get("action") or "").split(" ", 1)[0] == "APPROVE":
            pl = state.decode_payload(ent)
            if str(pl.get("phase")) == PHASE:
                last = (ent.get("seq"), pl)
    if last is None:
        return set(), None
    acc = (last[1].get("unfixed_accepted") or {}).get("findings") or []
    return {validation.unfixed_key(a) for a in acc if isinstance(a, dict)}, last[0]


def check_unfixed(root, unfixed, notes):
    """0.8.2: acceptance is the operator's APPROVE 9, never text. Each unfixed High/Critical passes only when it is in
    the set the last APPROVE 9 recorded in its ledger line (validation.unfixed_key: CVE, package and the declared
    image's digest; for a built image CVE, package, installed version and Dockerfile path); any other fails until
    the next APPROVE 9, which records the set REVIEW 9 listed. The security report's Residual risk lines are
    documentation: noted, never counted as acceptance. Returns the failing findings."""
    if not unfixed:
        return []
    accepted, seq = approved_unfixed(root)
    from gate import validation  # noqa: E402 (on the path: approved_unfixed put it there)
    base = "sdlc/features/%s" % os.environ["MOADIX_FEATURE"] if os.environ.get("MOADIX_FEATURE") else "sdlc"
    rel = "%s/%s" % (base, REPORT_NAME)
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
            lines = residual_section(f.read())
    except OSError:
        lines = []
    findings = []
    for u in unfixed:
        ok = validation.unfixed_key(u) in accepted
        UNFIXED_LINES.append("UNFIXED " + json.dumps(dict(
            {k: u[k] for k in ("cve", "severity", "package", "installed", "image", "digest", "dockerfile", "scan_date")
             if k in u}, accepted_seq=seq if ok else None), sort_keys=True))
        what = "image %s %s@%s (%s, scanned %s): no fixed version" % (
            u["image"], u["package"], u["installed"],
            "Dockerfile %s, this build %s" % (u["dockerfile"], u["digest"]) if u.get("dockerfile") else u["digest"],
            u["scan_date"])
        cve = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(u["cve"]), re.I)
        doc = next((n for n, ln in lines if cve.search(ln) and u["package"] in ln), None)
        docs = "; documented in %s:%d" % (rel, doc) if doc else ""
        if ok:
            notes.append("RESIDUAL [%s] %s %s; accepted by APPROVE %s (ledger seq %s)%s" % (
                u["severity"], u["cve"], what, PHASE, seq, docs))
            continue
        f = (u["severity"], u["cve"], "%s; not in the set the operator accepted with %s: REVIEW %s lists it, and "
             "APPROVE %s records the set%s" % (
                 what, "the last APPROVE %s (ledger seq %s)" % (PHASE, seq) if seq else "an APPROVE %s (none yet)" % PHASE,
                 PHASE, PHASE, docs + " (documentation only, not acceptance)" if docs else ""))
        PENDING_UNFIXED.append(f)
        findings.append(f)
    return findings


# 0.8.2: the images the gate builds from the product's Dockerfiles are scanned too: the shipped image (the root
# Dockerfile), each `build:` of the live compose file (live.compose), and each Dockerfile under tests/gate/. Each is
# built in a confined run exactly as the live gates build it (check_exec.build_image: same limits, same build
# network and proxy), saved with `docker save`, scanned offline from that tar, and recorded by its image ID, all
# before the run's cleanup. `images:` (bases) is still scanned as declared; declaring a base never exempts what is
# built on it.
def _is_dockerfile(rel):
    b = rel.rsplit("/", 1)[-1]
    return b == "Dockerfile" or b.startswith("Dockerfile.") or b.endswith(".Dockerfile")


def built_targets(root, pt):
    """[(what, context, dockerfile)] at HEAD, without repeats (a compose build of the root Dockerfile is the
    shipped image)."""
    files = set(toolrun.tracked(root))
    out, seen = [], set()

    def add(what, ctx, df):
        key = (os.path.normpath(ctx), os.path.normpath(df))
        if key not in seen and os.path.normpath(os.path.join(ctx, df)) in files:
            seen.add(key)
            out.append((what, ctx, df))
    add("shipped image (Dockerfile)", ".", "Dockerfile")
    rel = str((pt.get("live") or {}).get("compose") or "")
    if rel and rel in files and not rel.startswith("/") and ".." not in rel.split("/"):
        import hlib
        try:
            doc = hlib.load_yaml(os.path.join(root, rel)) or {}
        except Exception:
            doc = {}
        for name, svc in sorted(((doc.get("services") or {}) if isinstance(doc, dict) else {}).items()):
            if isinstance(svc, dict) and "build" in svc:
                b = svc["build"] if isinstance(svc["build"], dict) else {"context": svc["build"]}
                ctx, df = str(b.get("context") or "."), str(b.get("dockerfile") or "Dockerfile")
                if not ctx.startswith("/") and ".." not in ctx.split("/") and "://" not in ctx:
                    add("compose build %s (%s)" % (name, os.path.normpath(os.path.join(ctx, df))), ctx, df)
    for f in sorted(files):
        if f.startswith("tests/gate/") and _is_dockerfile(f):
            add("gate test image (%s)" % f, ".", f)
    return out


def scan_built(root, out, cache, scan, pt, targets, notes, run_id=None):
    """(findings, unfixed, files) for the images the gate builds. The engine is required (UNKNOWN without it).
    `run_id`: the engine suite labels the run with its own id (the gate's is x + 10 hex digits)."""
    sys.path.insert(0, os.path.dirname(toolrun.GATE))
    import check_exec
    from gate import confined
    import secrets
    findings, unfixed, files, built = [], [], [], []
    run_id = run_id or "x" + secrets.token_hex(5)
    tmp = os.path.join(out, "build")
    os.makedirs(tmp)
    export = os.path.join(tmp, "export.tar")
    p = subprocess.run([toolrun.GIT, "-C", root, "archive", "--format=tar", "-o", export, "HEAD"], capture_output=True)
    if p.returncode != 0:
        raise toolrun.ToolUnavailable("git archive HEAD failed: %s" % p.stderr.decode(errors="replace")[:200])
    r = None
    try:
        try:
            r = confined.Run(run_id, pt)
            r.sweep_stale()
        except confined.Unavailable as e:
            raise toolrun.ToolUnavailable("the images the gate builds cannot be scanned: %s" % e) from None
        for i, (what, ctx, df) in enumerate(targets):
            tag = "moadix/%s-scan%d:%s" % (run_id, i + 1, run_id)
            try:
                check_exec.build_image(r, pt, export, tmp, what, ctx, df, tag)
            except confined.Refused as e:
                tail = ""
                if getattr(e, "log", None):
                    tail = ": %s" % check_exec.redact((e.log[1] or e.log[0]).strip())[-300:]
                findings.append(("high", "trivy:build", "%s could not be built, so it was not scanned: %s%s" % (
                    what, e, tail)))
                continue
            except confined.Unavailable as e:
                raise toolrun.ToolUnavailable("building %s: %s" % (what, e)) from None
            try:
                digest = r._d(["image", "inspect", "--format", "{{.Id}}", tag]).stdout.decode().strip()
                saved = os.path.join(out, "built-%d.tar" % (i + 1))
                with open(saved, "wb") as f:
                    sp = subprocess.run([r.d, "save", tag], stdout=f, stderr=subprocess.PIPE, timeout=900)
                if sp.returncode != 0:
                    raise confined.Unavailable("docker save failed: %s" % sp.stderr.decode(errors="replace")[:300])
            except (confined.Unavailable, subprocess.TimeoutExpired) as e:
                raise toolrun.ToolUnavailable("%s was built but could not be read from the engine: %s" % (
                    what, e)) from None
            rep = os.path.join(out, "trivy-built-%d.json" % (i + 1))
            rc, so, se, info = toolrun.run("trivy", ["image"] + scan + ["--output", rep, "--input", saved], cwd=out,
                                           writable=[out, cache], network="none", timeout=900)
            os.unlink(saved)
            if rc != 0 or not os.path.exists(rep):
                raise RuntimeError("trivy image (built %s) exited %d: %s" % (what, rc, (se or so).strip()[-300:]))
            files.append(("trivy-built-%d.json" % (i + 1), rep, info))
            found, unf = split_unfixed(read_json(rep), "built " + what, digest=digest,
                                       dockerfile=os.path.normpath(os.path.join(ctx, df)))
            findings += found
            unfixed += unf
            built.append({"image": what, "context": ctx, "dockerfile": df, "digest": digest,
                          "scan_date": image_identity(read_json(rep))[1], "report": "trivy-built-%d.json" % (i + 1)})
        rep = os.path.join(out, "trivy-built.json")
        with open(rep, "w") as f:
            json.dump({"built": built}, f, indent=2, sort_keys=True)
        files.append(("trivy-built.json", rep, {"version": str(toolrun.pins()["trivy"]["version"]),
                                                "confined": bool(files and files[0][2].get("confined"))}))
        notes.append("trivy scanned %d image(s) the gate built: %s" % (len(built), "; ".join(
            "%s %s" % (b["image"], b["digest"]) for b in built) or "none"))
    finally:
        if r is not None:
            r.close()
    return findings, unfixed, files


def trivy_prepare(out):
    """(cache, scan args): the pinned trivy, its DB downloaded into the per-user cache (the only step with network);
    every scan after it runs offline with these arguments."""
    toolrun.tool("trivy")  # missing instrument: UNKNOWN before anything else
    try:
        cache = toolrun.cache_dir("trivy")
    except OSError as e:
        raise toolrun.ToolUnavailable("trivy's DB cache cannot be created (%s)" % e) from None
    base = ["--cache-dir", cache, "--skip-version-check", "--disable-telemetry", "--quiet"]
    rc, so, se, _info = toolrun.run("trivy", ["image", "--download-db-only"] + base, cwd=out,
                                    writable=[out, cache], network="any", env=TLS_ENV, timeout=900)
    if rc != 0:
        raise toolrun.ToolUnavailable("trivy could not update its vulnerability DB: %s" % (se or so).strip()[-300:])
    return cache, ["--scanners", "vuln,misconfig,secret", "--format", "json", "--ignorefile", "/dev/null",
                   "--skip-db-update", "--skip-java-db-update", "--skip-check-update", "--exit-code", "0"] + base


def run_trivy(root, out, notes):
    cache, scan = trivy_prepare(out)
    tree = os.path.join(out, "tree")
    os.makedirs(tree)
    export_head(root, tree)
    files, findings = [], []
    rep = os.path.join(out, "trivy-fs.json")
    rc, so, se, info = toolrun.run("trivy", ["fs"] + scan + ["--output", rep, tree], cwd=out,
                                   writable=[out, cache], network="none", timeout=900)
    if rc != 0 or not os.path.exists(rep):
        raise RuntimeError("trivy fs exited %d: %s" % (rc, (se or so).strip()[-300:]))
    files.append(("trivy-fs.json", rep, info))
    findings += trivy_findings(read_json(rep), "fs")
    images = [str(i) for i in (toolrun.product_tools(root).get("images") or [])]
    unfixed = []
    for i, img in enumerate(images):
        rep = os.path.join(out, "trivy-image-%d.json" % (i + 1))
        rc, so, se, info = toolrun.run("trivy", ["image"] + scan + ["--output", rep, "--image-src", "docker,remote", img],
                                       cwd=out, writable=[out, cache], network="any", env=TLS_ENV, timeout=900)
        if rc != 0 or not os.path.exists(rep):
            raise RuntimeError("trivy image %s exited %d: %s" % (img, rc, (se or so).strip()[-300:]))
        files.append(("trivy-image-%d.json" % (i + 1), rep, info))
        found, unf = split_unfixed(read_json(rep), img)
        findings += found
        unfixed += unf
    notes.append("trivy scanned the HEAD tree (vuln, misconfig, secret) and %d declared image(s)%s" % (
        len(images), ": " + ", ".join(images) if images else ""))
    pt = toolrun.product_tools(root)
    targets = built_targets(root, pt)
    if targets:
        found, unf, bfiles = scan_built(root, out, cache, scan, pt, targets, notes)
        findings += found
        unfixed += unf
        files += bfiles
    if images or targets:
        rep = os.path.join(out, "trivy-unfixed.json")
        with open(rep, "w") as f:
            json.dump({"unfixed": unfixed}, f, indent=2, sort_keys=True)
        files.append(("trivy-unfixed.json", rep, info))
        notes.append("%d high/critical image vulnerability(ies) with no fixed version (residual risk, listed in "
                     "trivy-unfixed.json)" % len(unfixed))
        findings += check_unfixed(root, unfixed, notes)
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
    for ln in ALLOWLISTED:  # 0.8.0: shown in REVIEW (gate/validate.py collects them); never the first line
        print(ln)
    rc = toolrun.report(title, notes, findings, errs, unknown)
    for ln in UNFIXED_LINES:  # 0.8.2: the unfixed set, for REVIEW and APPROVE (gate/validate.py collects it)
        print(ln)
    blocking = [f for f in findings if f[0] in toolrun.BLOCKING]
    if rc == 1 and not errs and not unknown and blocking and all(f in PENDING_UNFIXED for f in blocking):
        print("UNFIXED-ONLY")  # every failure is an unfixed finding the operator has not accepted yet
    return rc


if __name__ == "__main__":
    sys.exit(main())
