#!/usr/bin/env python3
"""check-exec -- the gates that execute or load product code, through the confined runner
(increment 7d; docs/confinement-design.md 3.7, approved with rulings).

    check_exec.py --gate <name> --phase <label>

  pytm (4, B)           tm/model.py runs; the gate reads pytm's JSON (elements, flows, findings)
  likec4 (3, B)         `likec4 validate` and `export json`; JSON configuration only; a model with
                        no elements fails (LikeC4 exports an empty model with exit 0 on a parse error)
  dependency-cruiser (3, 7, B)  .dependency-cruiser.json only; JSON report, 0 errors
  knip (7, B)           JSON report; every issue fails unless product-tools.yaml knip.allow lists it with
                        a reason
  eslint (7)            the product's ESLint and config (executed only inside the container); JSON
                        report, 0 errors
  tsc (7)               the product's TypeScript, --noEmit; every `error TS` line fails
  stryker (8, B)        the product's Stryker (JSON config only), mutation.json; the gate computes the
                        score (killed + timeout over killed + timeout + survived + no coverage) and
                        compares it with the size rule's threshold (TS10: M 70%, L 80%)
  tests (8, B)          the product's test command (product-tools.yaml tests.command) writing JUnit to
                        /out/junit.xml; service containers the gate starts (tests.services: postgres)
                        on an internal network; failures, errors, skipped tests and zero tests fail
  schemathesis (8, 10b) against the app on the live network; JUnit, 0 failures
  zap (9)               passive baseline against the app; any High alert fails
  lhci (10a)            Lighthouse in the pinned Chromium; the gate reads the LHR and checks LCP, CLS
                        and TBT against product-tools.yaml budgets (defaults 2500 ms, 0.1, 200 ms)
  axe (6, 8, 10a)       the gate's own axe runner (gate/exec/axe-run.js) on live.paths; any critical or
                        serious violation fails

A gate applies unless its coverage topic is N/A in the phase's COVERAGE.md (the gap critic judges the
reason). Every run goes through gate/confined.py: Docker is required (UNKNOWN without it), images are
digest-pinned and must be cleared, the product's code runs as uid 10001 with no network (the install
step reaches only the package registries through the allowlisting proxy; live gates use an internal
network with no egress), and everything the run created is removed afterwards.

Exit 0 pass or N/A, 1 fail, 2 unknown.
"""
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET  # noqa: N817,S405 (parses the run's own reports; size-capped first)

GATE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(GATE))
sys.path.insert(0, os.path.join(GATE, "v1"))

from gate import confined, contract, state  # noqa: E402
import toolrun  # noqa: E402

LOCKS = os.path.join(GATE, "config", "locks")
EXEC = os.path.join(GATE, "exec")
PROXY_ENV = {"HTTPS_PROXY": "http://%s:3128" % confined.PROXY_ALIAS, "HTTP_PROXY": "http://%s:3128" % confined.PROXY_ALIAS,
             "https_proxy": "http://%s:3128" % confined.PROXY_ALIAS, "http_proxy": "http://%s:3128" % confined.PROXY_ALIAS,
             "npm_config_proxy": "http://%s:3128" % confined.PROXY_ALIAS,
             "npm_config_https_proxy": "http://%s:3128" % confined.PROXY_ALIAS,
             "npm_config_cache": "/tmp/npm"}  # noqa: S108 (inside the container: its tmpfs)
WORK = "cp -a /src/. /tmp/work/ && cd /tmp/work"  # noqa: S108 (inside the container: its tmpfs)
LINK_PRODUCT = " && ln -s /deps/product/node_modules node_modules"


# ------------------------------------------------------------------ parsers (raw output -> verdict)
def parse_eslint(text):
    fails, notes = [], []
    data = json.loads(text)
    errors = 0
    for f in data:
        errors += int(f.get("errorCount") or 0) + int(f.get("fatalErrorCount") or 0)
        for m in f.get("messages") or []:
            fp = re.sub(r"^/tmp/work/|^/work/", "", str(f.get("filePath") or "?"))
            line = "%s:%s %s: %s" % (fp, m.get("line"), m.get("ruleId"), str(m.get("message"))[:160])
            (fails if m.get("severity") == 2 or m.get("fatal") else notes).append("eslint " + line)
    notes.append("eslint: %d file(s), %d error(s)" % (len(data), errors))
    return fails, notes, {"errors": errors, "files": len(data)}


TSC = re.compile(r"^(?P<file>[^\s(][^(]*)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): (?P<msg>.*)$", re.M)


def parse_tsc(text, rc):
    errs = ["tsc %s:%s %s %s" % (m.group("file"), m.group("line"), m.group("code"), m.group("msg")[:160])
            for m in TSC.finditer(text or "")]
    if rc not in (0, None) and not errs:
        errs.append("tsc exited %s without a parseable error line: %s" % (rc, (text or "").strip()[-300:]))
    return errs, ["tsc: %d error(s)" % len(errs)], {"errors": len(errs)}


KNIP_KINDS = ("files", "dependencies", "devDependencies", "optionalPeerDependencies", "unlisted", "binaries",
              "unresolved", "exports", "types", "enumMembers", "duplicates", "namespaceMembers")


def parse_knip(text, allow=()):
    data = json.loads(text)
    fails, notes, n = [], [], 0
    ok = {(a.get("file"), a.get("kind"), a.get("name")) for a in allow if len(str(a.get("reason") or "").split()) >= 4}
    for issue in data.get("issues") or []:
        f = issue.get("file")
        for kind in KNIP_KINDS:
            for item in issue.get(kind) or []:
                name = item.get("name") if isinstance(item, dict) else str(item)
                n += 1
                if (f, kind, name) in ok:
                    notes.append("knip %s %s %s: allowed (product-tools.yaml knip.allow, with a reason)" % (f, kind, name))
                else:
                    fails.append("knip %s: unused or unlisted %s %s" % (f, kind, name))
    notes.append("knip: %d issue(s)" % n)
    return fails, notes, {"issues": n}


def parse_depcruise(text):
    data = json.loads(text)
    s = data.get("summary") or {}
    fails = ["dependency-cruiser %s: %s -> %s (%s)" % (v.get("rule", {}).get("severity"), v.get("from"), v.get("to"),
                                                     v.get("rule", {}).get("name"))
             for v in s.get("violations") or [] if (v.get("rule") or {}).get("severity") == "error"]
    if int(s.get("error") or 0) and not fails:
        fails.append("dependency-cruiser reports %s error(s)" % s.get("error"))
    return fails, ["dependency-cruiser: %s module(s), %s error(s), %s warning(s)" % (
        s.get("totalCruised", len(data.get("modules") or [])), s.get("error", 0), s.get("warn", 0))], {
        "errors": int(s.get("error") or 0), "modules": len(data.get("modules") or [])}


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def parse_likec4(validate_log, validate_rc, export_text):
    fails = []
    log = ANSI.sub("", validate_log or "")
    if validate_rc not in (0, "0") or re.search(r"\bInvalid\b|\bERROR\b", log):
        errs = [ln.strip() for ln in log.splitlines() if "Line " in ln or "ERROR" in ln][:6]
        fails.append("likec4 validate failed (exit %s): %s" % (validate_rc, " | ".join(errs) or log.strip()[-300:]))
    try:
        model = json.loads(export_text or "")
    except ValueError:
        return fails + ["likec4 export did not produce JSON"], [], {}
    n = len(model.get("elements") or {})
    if n == 0:
        fails.append("likec4 exported a model with no elements (an unparsable model exports empty with exit 0)")
    return fails, ["likec4: %d element(s), %d relation(s)" % (n, len(model.get("relations") or {}))], {
        "elements": n, "relations": len(model.get("relations") or {})}


def parse_pytm(text, rc):
    if rc not in (0, None):
        return ["pytm: tm/model.py exited %s (the model must run)" % rc], [], {}
    data = json.loads(text)
    els, flows = data.get("elements") or [], data.get("flows") or []
    fails = []
    if not els or not flows:
        fails.append("pytm model has %d element(s) and %d data flow(s); a threat model needs both" % (len(els), len(flows)))
    return fails, ["pytm: %d element(s), %d flow(s), %d finding(s)" % (len(els), len(flows), len(data.get("findings") or []))], {
        "elements": len(els), "flows": len(flows), "findings": len(data.get("findings") or [])}


def mutation_score(data):
    counts = {}
    for f in (data.get("files") or {}).values():
        for m in f.get("mutants") or []:
            counts[m.get("status")] = counts.get(m.get("status"), 0) + 1
    detected = counts.get("Killed", 0) + counts.get("Timeout", 0)
    valid = detected + counts.get("Survived", 0) + counts.get("NoCoverage", 0)
    return (100.0 * detected / valid if valid else None), counts


def parse_mutation(text, threshold):
    data = json.loads(text)
    score, counts = mutation_score(data)
    if score is None:
        return ["stryker: no mutant was tested"], [], {"counts": counts}
    fails = []
    if threshold and score + 1e-9 < threshold:
        fails.append("stryker mutation score %.1f%% is below the threshold %d%% (TS10)" % (score, threshold))
    return fails, ["stryker: score %.1f%% (%s)" % (score, ", ".join("%s %d" % kv for kv in sorted(counts.items())))], {
        "score": round(score, 2), "counts": counts, "threshold": threshold}


def junit_counts(text):
    root = ET.fromstring(text)  # noqa: S314 (the run's own report, size-capped by confined.check_output)
    cases = list(root.iter("testcase"))
    failed, skipped = [], []
    for c in cases:
        if c.find("failure") is not None or c.find("error") is not None or c.get("failure"):
            failed.append(c.get("name") or "?")
        elif c.find("skipped") is not None:
            skipped.append(c.get("name") or "?")
    comments = {}
    for m in re.finditer(r"<!--\s*(tests|pass|fail|skipped|todo|cancelled)\s+(\d+)\s*-->", text):
        comments[m.group(1)] = int(m.group(2))
    skipped_n = max(len(skipped), comments.get("skipped", 0) + comments.get("todo", 0))
    return {"tests": len(cases), "failed": failed, "skipped": skipped_n, "cancelled": comments.get("cancelled", 0)}


def parse_junit(text, what="tests"):
    c = junit_counts(text)
    fails = []
    if c["tests"] == 0:
        fails.append("%s: the report holds no test case (zero tests is not a pass)" % what)
    for n in c["failed"][:20]:
        fails.append("%s: failed: %s" % (what, n))
    if c["skipped"]:
        fails.append("%s: %d skipped test(s); a skipped test needs a waiver (TS13)" % (what, c["skipped"]))
    if c["cancelled"]:
        fails.append("%s: %d cancelled test(s)" % (what, c["cancelled"]))
    return fails, ["%s: %d case(s), %d failed, %d skipped" % (what, c["tests"], len(c["failed"]), c["skipped"])], c


def parse_zap(text):
    data = json.loads(text)
    fails, notes, n = [], [], 0
    for site in data.get("site") or []:
        for a in site.get("alerts") or []:
            n += 1
            risk = int(a.get("riskcode") or 0)
            line = "zap [%s] %s %s (%s instance(s))" % (a.get("riskdesc"), a.get("pluginid"), a.get("name") or a.get("alert"),
                                                       a.get("count") or len(a.get("instances") or []))
            (fails if risk >= 3 else notes).append(line)
    notes.append("zap: %d alert(s), High fails, Medium and below reported" % n)
    return fails, notes, {"alerts": n}


def parse_lhr(text, budgets=None):
    data = json.loads(text)
    b = {"lcp_ms": 2500, "cls": 0.1, "tbt_ms": 200}
    b.update({k: float(v) for k, v in (budgets or {}).items() if k in b})
    a = data.get("audits") or {}
    got = {"lcp_ms": (a.get("largest-contentful-paint") or {}).get("numericValue"),
           "cls": (a.get("cumulative-layout-shift") or {}).get("numericValue"),
           "tbt_ms": (a.get("total-blocking-time") or {}).get("numericValue")}
    fails = []
    for k, v in got.items():
        if v is None:
            fails.append("lighthouse: no %s in the report" % k)
        elif float(v) > b[k]:
            fails.append("lighthouse: %s %.3g is above the budget %.3g (U16/H6)" % (k, float(v), b[k]))
    return fails, ["lighthouse %s: %s" % (data.get("lighthouseVersion"), ", ".join("%s %.3g" % (k, float(v)) for k, v in got.items()
                                                                                    if v is not None))], {"metrics": got, "budgets": b}


def parse_axe(text):
    data = json.loads(text)
    results = data.get("results") if "results" in data else [{"url": data.get("url"), "violations": data.get("violations")}]
    fails, notes = [], []
    for r in results:
        if r.get("error"):
            fails.append("axe %s: the page could not be checked: %s" % (r.get("url"), r["error"]))
        for v in r.get("violations") or []:
            line = "axe %s [%s] %s (%d node(s))" % (r.get("url"), v.get("impact"), v.get("id"), len(v.get("nodes") or []))
            (fails if v.get("impact") in ("critical", "serious") else notes).append(line)
    notes.append("axe: %d page(s)" % len(results))
    return fails, notes, {"pages": len(results)}


# ------------------------------------------------------------------ the gates
def _pt(root):
    return toolrun.product_tools(root) or {}


GATES = {
    "pytm": {"phases": {"4": "T3", "B": "BL11"}, "image": "python", "tier": "E-lint", "tool": ("py", "pytm"),
             "needs": ["tm/model.py"]},
    "likec4": {"phases": {"3": "H2", "B": "BL2"}, "image": "node", "tier": "E-lint", "tool": ("npm", "likec4"),
               "needs_glob": r"\.(c4|likec4)$", "refuse": r"(^|/)likec4\.config\.(js|mjs|cjs|ts|mts|cts)$"},
    "dependency-cruiser": {"phases": {"3": "H20", "7": "I6", "B": "BL3"}, "image": "node", "tier": "E-lint",
                           "tool": ("npm", "dependency-cruiser"), "needs": [".dependency-cruiser.json"],
                           "refuse": r"(^|/)\.dependency-cruiser\.(js|mjs|cjs|ts)$"},
    "knip": {"phases": {"7": "I7", "B": "BL4"}, "image": "node", "tier": "E-lint", "tool": ("npm", "knip"),
             "product": True, "needs": ["package.json"]},
    "eslint": {"phases": {"7": "I5"}, "image": "node", "tier": "E-lint", "product": True, "needs": ["package.json"]},
    "tsc": {"phases": {"7": "I4"}, "image": "node", "tier": "E-lint", "product": True, "needs": ["tsconfig.json"]},
    "stryker": {"phases": {"8": "TS10", "B": "BL8"}, "image": "node-full", "tier": "E-mutation", "product": True,
                "needs": ["stryker.config.json"], "refuse": r"(^|/)stryker\.(conf|config)\.(js|mjs|cjs|ts)$"},
    "tests": {"phases": {"8": "TS11", "B": "BL8"}, "image": "node", "tier": "E-test", "product": True,
              "needs": ["package.json"]},
    "schemathesis": {"phases": {"8": "TS8", "10b": "RG3"}, "image": "python", "tier": "L", "tool": ("py", "schemathesis"),
                     "live": True},
    "zap": {"phases": {"9": "SV7"}, "image": "zap", "tier": "L", "live": True},
    "lhci": {"phases": {"10a": "LV8"}, "image": "chromium", "tier": "L", "tool": ("npm", "lhci"), "live": True},
    "axe": {"phases": {"6": "U6", "8": "TS14", "10a": "LV7"}, "image": "chromium", "tier": "L", "tool": ("npm", "axe-runner"),
            "live": True},
}


def applies(root, st, gate, label):
    """(True, why) when the gate must run; (False, reason) when its topic is N/A in COVERAGE.md."""
    topic = GATES[gate]["phases"].get(str(label))
    if not topic:
        return False, "gate %s has no phase %s" % (gate, label)
    ents = contract.coverage_entries(root, st, label) or {}
    e = ents.get(topic)
    if e is not None and e.get("na") is not None:
        return False, "%s is N/A in %s (%s); the gap critic judges that reason" % (
            topic, contract.coverage_rel(st, label), (e.get("na") or "")[:120])
    return True, "%s is covered in the phase, so the gate runs" % topic


def tracked(root):
    p = subprocess.run([state.GIT, "-C", root, "ls-files", "-z"], capture_output=True)
    return [x for x in p.stdout.decode("utf-8", "replace").split("\0") if x]


def preflight(root, gate, files):
    g = GATES[gate]
    fails = []
    if g.get("refuse"):
        bad = [f for f in files if re.search(g["refuse"], f)]
        if bad:
            fails.append("%s: a JS or TS configuration (%s) is refused; use the JSON form (ruling 4 on increment 7b)" % (
                gate, ", ".join(bad)))
    for n in g.get("needs") or []:
        if n not in files:
            fails.append("%s needs %s at HEAD" % (gate, n))
    if g.get("needs_glob") and not any(re.search(g["needs_glob"], f) for f in files):
        fails.append("%s needs model sources (%s) at HEAD" % (gate, g["needs_glob"]))
    if g.get("product") and "package.json" in files and "package-lock.json" not in files:
        fails.append("%s: package-lock.json is required (the install step runs npm ci from it)" % gate)
    return fails


def threshold(root, st):
    size, _ruling = contract.size_and_ruling(root, st)
    t = 0
    for item in contract.turned_on(size):
        if item.get("topic") == "TS10" and item.get("check") == "min_percent":
            t = max(t, int(float(item.get("arg"))))
    want = (_pt(root).get("mutation") or {}).get("threshold")
    if isinstance(want, int) or (isinstance(want, str) and want.isdigit()):
        t = max(t, int(want))
    return t


def tool_script(gate, root, pt):
    if gate == "pytm":
        return WORK + " && PYTHONPATH=/deps/tool python tm/model.py --json /out/tm.json > /out/run.log 2>&1; echo $? > /out/run.rc"
    if gate == "likec4":
        cli = "node /deps/tool/node_modules/likec4/bin/likec4.mjs"
        return (WORK + " && %s validate . > /out/validate.log 2>&1; echo $? > /out/validate.rc; "
                "%s export json -o /out/model.json . > /out/export.log 2>&1; true" % (cli, cli))
    if gate == "dependency-cruiser":
        paths = " ".join(str(p) for p in ((pt.get("depcruise") or {}).get("paths") or ["src"]) if re.match(r"^[\w./-]+$", str(p)))
        return (WORK + " && node /deps/tool/node_modules/dependency-cruiser/bin/dependency-cruiser.mjs --config "
                ".dependency-cruiser.json --output-type json --output-to /out/depcruise.json %s > /out/run.log 2>&1; "
                "echo $? > /out/run.rc" % paths)
    if gate == "knip":
        return (WORK + LINK_PRODUCT + " && node /deps/tool/node_modules/knip/bin/knip.js --reporter json > /out/knip.json "
                "2> /out/run.log; echo $? > /out/run.rc")
    if gate == "eslint":
        return (WORK + LINK_PRODUCT + " && node node_modules/eslint/bin/eslint.js -f json -o /out/eslint.json . > /out/run.log "
                "2>&1; echo $? > /out/run.rc")
    if gate == "tsc":
        return (WORK + LINK_PRODUCT + " && node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json --pretty false "
                "> /out/tsc.txt 2>&1; echo $? > /out/run.rc")
    if gate == "stryker":
        return (WORK + LINK_PRODUCT + " && node node_modules/@stryker-mutator/core/bin/stryker.js run --reporters json "
                "--tempDirName /tmp/stryker-tmp > /out/run.log 2>&1; echo $? > /out/run.rc; "
                "cp reports/mutation/mutation.json /out/mutation.json 2>/dev/null; true")
    if gate == "tests":
        cmd = (pt.get("tests") or {}).get("command")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
            raise confined.Refused("product-tools.yaml tests.command must be a list of words (the test command)")
        import shlex
        return (WORK + LINK_PRODUCT + " && %s > /out/run.log 2>&1; echo $? > /out/run.rc" % " ".join(shlex.quote(x) for x in cmd))
    raise ValueError(gate)


def wait_for(port):
    return ("i=0; until (echo > /dev/tcp/%s/%d) 2>/dev/null; do i=$((i+1)); [ $i -gt 90 ] && echo 'the app never "
            "listened on port %d' > /out/wait.log && exit 3; sleep 1; done; " % (confined.SUT_ALIAS, port, port))


def live_script(gate, port, spec_rel, paths):
    url = "http://%s:%d" % (confined.SUT_ALIAS, port)
    if gate == "schemathesis":
        return (wait_for(port) + "PYTHONPATH=/deps/tool python -m schemathesis.cli run /src/%s --url %s --report junit "
                "--report-dir /out/st > /out/run.log 2>&1; echo $? > /out/run.rc" % (spec_rel, url))
    if gate == "zap":
        return wait_for(port) + "zap-baseline.py -t %s -J zap.json -I -m 1 > /zap/wrk/run.log 2>&1; echo $? > /zap/wrk/run.rc" % url
    if gate == "lhci":
        return (wait_for(port) + "export CHROME_PATH=$(ls -d /ms-playwright/chromium-*/chrome-linux*/chrome | head -1) && "
                "cd /tmp && node /deps/tool/node_modules/@lhci/cli/src/cli.js collect --url=%s/ --numberOfRuns=1 "
                "--settings.chromeFlags='--no-sandbox --headless=new' > /out/run.log 2>&1; echo $? > /out/run.rc; "
                "cp /tmp/.lighthouseci/lhr-*.json /out/ 2>/dev/null; true" % url)
    if gate == "axe":
        ps = " ".join(p for p in paths if re.match(r"^/[\w./-]*$", p)) or "/"
        return wait_for(port) + "node /gx/axe-run.js %s /out/axe.json %s > /out/run.log 2>&1; echo $? > /out/run.rc" % (url, ps)
    raise ValueError(gate)


def install_script(kind, name, scripts):
    if kind == "npm-product":
        s = ("mkdir -p /deps/product && cp /src/package.json /src/package-lock.json /deps/product/ && cd /deps/product && "
             "npm ci --ignore-scripts --no-audit --no-fund")
        for p in scripts:
            s += " && npm rebuild %s" % p
        return s
    if kind == "npm":
        return ("mkdir -p /deps/tool && cp /tools/package.json /tools/package-lock.json /deps/tool/ && cd /deps/tool && "
                "npm ci --ignore-scripts --no-audit --no-fund")
    if kind == "py":
        return "pip install --no-cache-dir --require-hashes --only-binary :all: --target /deps/tool -r /tools/requirements.txt"
    raise ValueError(kind)


def _tar_of(files):
    """A tar (bytes) of {name: bytes}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _rb(path):
    with open(path, "rb") as f:
        return f.read()


def _write(tmp, name, data):
    p = os.path.join(tmp, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def lock_files(kind, name):
    d = os.path.join(LOCKS, name)
    want = ("package.json", "package-lock.json") if kind == "npm" else ("requirements.txt",)
    return {n: _rb(os.path.join(d, n)) for n in want}


def compose_doc(root, pt):
    live = pt.get("live") or {}
    rel = str(live.get("compose") or "")
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        raise confined.Refused("product-tools.yaml live.compose must name the product's compose file (repo-relative)")
    import hlib
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        raise confined.Refused("the compose file %s is not committed" % rel)
    try:
        return hlib.load_yaml(p)
    except Exception as e:
        raise confined.Refused("the compose file %s uses YAML the gate does not read (%s)" % (rel, e)) from None


def start_live(r, root, pt, export_tar, tmp, net):
    """Build and start the app's services from the gate-generated project (3.8) on the live network."""
    live = pt.get("live") or {}
    target, port = str(live.get("service") or ""), int(live.get("port") or 0)
    if not target or not port:
        raise confined.Refused("product-tools.yaml live.service and live.port name the app to scan")
    lim = confined.limits("L", pt)
    proj, notes = confined.compose_project(compose_doc(root, pt), r.id, lim, internal_network=net)
    if target not in proj["services"]:
        raise confined.Refused("live.service %s is not a service of the compose file" % target)
    doc = compose_doc(root, pt)
    for name, svc in proj["services"].items():
        src = doc["services"][name]
        if "build" in src:
            b = src["build"] if isinstance(src["build"], dict) else {"context": src["build"]}
            ctx, dockerfile = str(b.get("context") or "."), str(b.get("dockerfile") or "Dockerfile")
            ctx_tar = _context_tar(export_tar, ctx, tmp)
            text = _member(export_tar, os.path.normpath(os.path.join(ctx, dockerfile)))
            probs = confined.dockerfile_problems(text, pt)
            if probs:
                raise confined.Refused("%s's Dockerfile: %s" % (name, "; ".join(probs)))
            args, envb = confined.build_argv(r.id, svc["image"], dockerfile, confined.limits("build", pt), pt)
            with open(ctx_tar, "rb") as f:
                p = subprocess.run([r.d] + args, stdin=f, capture_output=True, timeout=confined.limits("build", pt)["wall_s"],
                                   env=dict(os.environ, **envb))
            if p.returncode != 0:
                raise confined.Refused("building %s failed: %s" % (name, p.stderr.decode(errors="replace")[-400:]))
        argv = svc.get("command") or []
        argv = argv if isinstance(argv, list) else str(argv).split()
        r.execute(svc["image"], [str(x) for x in argv], "L", [], network=net, env=svc.get("environment") or {},
                  aliases=[confined.SUT_ALIAS] if name == target else [name], name="moadix-%s-svc-%s" % (r.id, name),
                  detach=True)
    return port, notes


def _member(tar_path, rel):
    with tarfile.open(tar_path) as tf:
        m = tf.getmember(rel)
        return tf.extractfile(m).read().decode("utf-8", errors="replace")


def _context_tar(tar_path, ctx, tmp):
    ctx = os.path.normpath(ctx)
    out = os.path.join(tmp, "context.tar")
    with tarfile.open(tar_path) as src, tarfile.open(out, "w") as dst:
        for m in src.getmembers():
            name = os.path.normpath(m.name)
            if ctx != "." and not (name == ctx or name.startswith(ctx + "/")):
                continue
            if m.issym() or m.islnk() or name.startswith("/") or ".." in name.split("/"):
                continue
            rel = name if ctx == "." else os.path.relpath(name, ctx)
            m.name = rel
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
    return out


def start_services(r, pt, net):
    env = {}
    for name in (pt.get("tests") or {}).get("services") or []:
        svc = (confined.config().get("services") or {}).get(str(name))
        if not svc:
            raise confined.Refused("tests.services names %r, which is not one of the gate's service containers" % name)
        img = confined.image(svc["image"])
        senv = dict(svc.get("env") or {})
        mounts = []
        if svc.get("data"):
            dv = r.volume("svc-%s" % re.sub(r"[^a-z0-9]", "", str(name)))
            r.own(dv, img, uid=int(str(svc.get("user") or "10001").split(":")[0]))
            mounts.append((dv, svc["data"], False))
        r.execute(img, [], "L", mounts, network=net, env=senv, user=svc.get("user"), aliases=[svc["alias"]],
                  name="moadix-%s-svc-%s" % (r.id, name), detach=True, tmpfs=svc.get("tmpfs") or [])
        env[svc["env_url"]] = "postgres://%s@%s:%d/%s" % (senv.get("POSTGRES_USER"), svc["alias"], svc["port"],
                                                          senv.get("POSTGRES_DB"))
    return env


def run_gate(root, st, gate, label):
    g, pt = GATES[gate], _pt(root)
    run_id = "x" + secrets.token_hex(5)
    tmp = toolrun.mkdtemp("moadix-exec-")
    r = None
    try:
        export = os.path.join(tmp, "export.tar")
        p = subprocess.run([state.GIT, "-C", root, "archive", "--format=tar", "-o", export, "HEAD"], capture_output=True)
        if p.returncode != 0:
            raise confined.Unavailable("git archive HEAD failed")
        img = confined.image(g["image"])
        user = (confined.config().get("images") or {}).get(g["image"], {}).get("user")
        r = confined.Run(run_id, pt)
        src = r.volume("src")
        r.load(src, export, img)
        out = r.volume("out")
        out_path = "/zap/wrk" if gate == "zap" else "/out"
        r.own(out, img, uid=int(user.split(":")[0]) if user else None)
        mounts = [(src, "/src", True), (out, out_path, False)]
        if g.get("tool") or g.get("product"):
            deps = r.volume("deps")
            r.own(deps, img)
            inet, enet = r.network("install"), r.network("egress", internal=False)
            pyimg = confined.image("python")
            pvol = r.volume("proxy")
            r.load(pvol, _write(tmp, "proxy.tar", _tar_of({"egress_proxy.py": _rb(os.path.join(GATE, "egress_proxy.py"))})), pyimg)
            r.proxy(inet, enet, pvol)
            steps = []
            if g.get("product"):
                steps.append(("npm-product", None))
            if g.get("tool"):
                steps.append(g["tool"])
            for kind, name in steps:
                imounts = [(src, "/src", True), (deps, "/deps", False)]
                if name:
                    tvol = r.volume("lock-%s" % re.sub(r"[^a-z0-9]", "", name))
                    r.load(tvol, _write(tmp, "lock.tar", _tar_of(lock_files(kind, name))), img)
                    imounts.append((tvol, "/tools", True))
                rc, so, se = r.execute(img, ["sh", "-c", install_script(kind if name else kind, name,
                                                                        confined.install_scripts(pt))],
                                       "install", imounts, network=inet, env=PROXY_ENV,
                                       name="moadix-%s-install-%s" % (run_id, (name or "product").replace("-", "")))
                if rc != 0:
                    tail = (se or so)[-400:]
                    if re.search(r"ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|403 Not on the MOADIX|ProxyError", tail):
                        raise confined.Unavailable("the install step could not reach the registry: %s" % tail)
                    return ["%s: the install step failed (npm ci / pip from the lockfile): %s" % (gate, tail)], [], {}, None
            mounts.append((deps, "/deps", True))
        net, env = "none", {}
        if g.get("live"):
            net = r.network("live")
            port, _notes = start_live(r, root, pt, export, tmp, net)
            spec = next((f for f in tracked(root) if re.match(r"^%s/05-lld/.*\.(ya?ml|json)$" % re.escape(contract.doc_dir(st)), f)), None)
            if gate == "schemathesis" and not spec:
                return ["schemathesis needs the OpenAPI description under %s/05-lld/" % contract.doc_dir(st)], [], {}, None
            if gate == "axe":
                gx = r.volume("gx")
                r.load(gx, _write(tmp, "gx.tar", _tar_of({"axe-run.js": _rb(os.path.join(EXEC, "axe-run.js"))})), img)
                mounts.append((gx, "/gx", True))
            script = live_script(gate, port, spec, (pt.get("live") or {}).get("paths") or ["/"])
        else:
            if gate == "tests" and (pt.get("tests") or {}).get("services"):
                net = r.network("svc")
                env.update(start_services(r, pt, net))
            env["MOADIX_JUNIT"] = "/out/junit.xml"
            script = tool_script(gate, root, pt)
        rc, so, se = r.execute(img, ["sh", "-c", script], g["tier"], mounts, network=net, env=env, user=user,
                               name="moadix-%s-%s" % (run_id, gate.replace("-", "")))
        dest = os.path.join(tmp, "out")
        r.copy_out(out, dest, img)
        probs = confined.check_output(dest, confined.limits(g["tier"], pt)["out_mb"] << 20)
        if probs:
            return ["%s: the run's output was refused: %s" % (gate, "; ".join(probs))], [], {}, None
        f, n, data = verdict(gate, dest, pt, root, st)
        return f, n, data, dest
    finally:
        if r is not None:
            r.close()
        shutil.rmtree(tmp, ignore_errors=True)


def _read(d, name, limit=20 << 20):
    p = os.path.join(d, name)
    if not os.path.isfile(p) or os.path.islink(p):
        raise confined.Refused("the run wrote no %s" % name)
    if os.path.getsize(p) > limit:
        raise confined.Refused("%s is larger than %d bytes" % (name, limit))
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _rc(d, name="run.rc"):
    try:
        return int(_read(d, name).strip() or "0")
    except (confined.Refused, ValueError):
        return None


def verdict(gate, d, pt, root, st):
    """The gate's own verdict from the raw output in d (a forged summary line is never believed)."""
    try:
        if gate == "pytm":
            return parse_pytm(_read(d, "tm.json") if _rc(d) == 0 else "{}", _rc(d))
        if gate == "likec4":
            return parse_likec4(_read(d, "validate.log"), _rc(d, "validate.rc"), _read(d, "model.json"))
        if gate == "dependency-cruiser":
            return parse_depcruise(_read(d, "depcruise.json"))
        if gate == "knip":
            return parse_knip(_read(d, "knip.json"), (pt.get("knip") or {}).get("allow") or [])
        if gate == "eslint":
            return parse_eslint(_read(d, "eslint.json"))
        if gate == "tsc":
            return parse_tsc(_read(d, "tsc.txt"), _rc(d))
        if gate == "stryker":
            return parse_mutation(_read(d, "mutation.json"), threshold(root, st))
        if gate == "tests":
            return parse_junit(_read(d, "junit.xml"))
        if gate == "schemathesis":
            sd = os.path.join(d, "st")
            reports = sorted(x for x in os.listdir(sd) if x.startswith("junit")) if os.path.isdir(sd) else []
            if len(reports) != 1:
                raise confined.Refused("schemathesis wrote %d JUnit report(s), expected 1" % len(reports))
            return parse_junit(_read(sd, reports[0]), "schemathesis")
        if gate == "zap":
            return parse_zap(_read(d, "zap.json"))
        if gate == "lhci":
            reports = sorted(x for x in os.listdir(d) if re.match(r"^lhr-\d+\.json$", x))
            if not reports:
                raise confined.Refused("lighthouse wrote no LHR report")
            return parse_lhr(_read(d, reports[0]), pt.get("budgets") or {})
        if gate == "axe":
            return parse_axe(_read(d, "axe.json"))
    except ValueError as e:
        return ["%s: its report is not the tool's format (%s): never believed" % (gate, e)], [], {}
    raise ValueError(gate)


def main(argv):
    if len(argv) != 4 or argv[0] != "--gate" or argv[2] != "--phase" or argv[1] not in GATES:
        print("UNKNOWN usage: check_exec.py --gate <%s> --phase <label>" % "|".join(sorted(GATES)))
        return 2
    gate, label = argv[1], argv[3]
    root = os.environ.get("MOADIX_PRODUCT_ROOT") or os.getcwd()
    notes, errs, unknown = [], [], []
    try:
        st, problems = state.current_state(root)
        if problems:
            print("UNKNOWN gate state failed its integrity check: %s" % "; ".join(problems))
            return 2
        ok, why = applies(root, st, gate, label)
        if not ok:
            print("OK N/A: %s" % why)
            return 0
        notes.append(why)
        pre = preflight(root, gate, tracked(root))
        if pre:
            errs += pre
        else:
            f, n, data, _dest = run_gate(root, st, gate, label)
            errs += f
            notes += n
            if data:
                rel, digest = toolrun.record(root, label, "exec-%s" % gate, "confined", "exec-%s.json" % gate,
                                             json.dumps({"gate": gate, "phase": label, "fails": f, "notes": n, "data": data},
                                                        indent=1, sort_keys=True), "check-exec-%s" % gate)
                notes.append("evidence %s (sha256 %s)" % (rel, digest[:12]))
    except confined.Unavailable as e:
        unknown.append("%s cannot run confined: %s" % (gate, e))
    except confined.Refused as e:
        errs.append("%s: %s" % (gate, e))
    except Exception as e:  # unknown, never a pass
        unknown.append("%s: %s: %s" % (gate, type(e).__name__, e))
    return toolrun.report("check-exec-%s (phase %s, confined)" % (gate, label), notes, [], errs, unknown)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
