#!/usr/bin/python3
"""Increment-7d suite: the executing gates (gate/v1/check_exec.py) through the confined runner.

Runs in the sandbox, with no Docker: the fixture gate copy points the runner at the engine double
(tests/lib/engine_double.py), which runs nothing and writes canned tool output (real captured output,
tests/exec/raw, and the pass set derived from it, tests/exec/double/pass). What it proves:

  * each gate's verdict comes from the tool's raw output, pass and fail, on real outputs;
  * forged or malformed output is never believed;
  * a gate whose coverage topic is N/A reports N/A; missing inputs and JS/TS configurations fail;
  * the repository's configuration (images blocked by the licence ruling) and a missing engine give UNKNOWN;
  * the argv the runner hands the engine carries no host path or socket, the run label, the limits,
    --network none for product code and an internal network for the live app;
  * nothing labelled is left behind;
  * the installer copies what the gates need, and the gate's lock copies equal tools/.

What the double cannot prove (that the engine enforces those flags) is tests/confined-engine, run in Terminal.
"""
import json
import os
import re
import shutil
import sys
import time

sys.dont_write_bytecode = True  # the guard counts a .pyc written into the repository as a write outside the fixture

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("v7d").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined  # noqa: E402

RESULTS = []
T0 = time.time()
RAW = os.path.join(REPO, "tests", "exec", "raw")
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
DBL = os.path.join(E.base, "engine-double")
D = "a" * 64
FIRST = {g: next(iter(X.GATES[g]["phases"])) for g in X.GATES}


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1200])


def raw(name):
    with open(os.path.join(RAW, name)) as f:
        return f.read()


def put(base, rel, text):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def suffix(gate):
    return gate.replace("-", "")


# ------------------------------------------------------------------ the fixture product
PRODUCT_FILES = {
    "package.json": json.dumps({"name": "execfx", "version": "1.0.0", "scripts": {"test": "node --test"}}) + "\n",
    "package-lock.json": json.dumps({"name": "execfx", "lockfileVersion": 3, "packages": {}}) + "\n",
    "tsconfig.json": "{\"compilerOptions\": {\"strict\": true, \"noEmit\": true}}\n",
    ".dependency-cruiser.json": "{\"forbidden\": []}\n",
    "stryker.config.json": "{\"testRunner\": \"command\"}\n",
    "tm/model.py": "from pytm import TM\n\ntm = TM('notes')\ntm.process()\n",
    "arch/model.c4": "specification { element system }\nmodel { notes = system 'Notes' }\n",
    "src/server.js": "require('http').createServer((q, s) => s.end('ok')).listen(3000)\n",
    "Dockerfile": "FROM node@sha256:%s\nCOPY src /app\nCMD [\"node\", \"/app/server.js\"]\n" % D,
    "compose.yaml": "services:\n  app:\n    build:\n      context: .\n      dockerfile: Dockerfile\n"
                    "    command: [\"node\", \"/app/server.js\"]\n    expose: [\"3000\"]\n",
    "sdlc/05-lld/api.yaml": "openapi: 3.0.3\ninfo: {title: notes, version: '1'}\npaths: {}\n",
}
PT = "tests:\n  command: [npm, test]\nlive:\n  compose: compose.yaml\n  service: app\n  port: 3000\n  paths: [\"/\"]\n"
PT_STRICT = PT + "mutation:\n  threshold: 80\nbudgets:\n  lcp_ms: 500\n"


def product(name, files=PRODUCT_FILES, pt=PT):
    p = E.repo(name, docs=("00-brd.md",))
    for rel, text in files.items():
        put(p, rel, text)
    E.commit(p, "product files")
    E.init(p, name + "fx")
    put(p, ".sdlc/config/product-tools.yaml", pt)
    return p


def run(p, gate, label=None, outputs=PASS, **extra):
    """check_exec.py through the gate's launcher, as the worker runs it, with the engine double."""
    shutil.rmtree(DBL, ignore_errors=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", gate, "--phase", label or FIRST[gate]],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=outputs, **extra),
                    timeout=300)
    return r.returncode, r.stdout + r.stderr


def calls():
    p = os.path.join(DBL, "calls.log")
    return [json.loads(x) for x in open(p).read().splitlines() if x.strip()] if os.path.exists(p) else []


def leftovers():
    try:
        with open(os.path.join(DBL, "state.json")) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return []
    return ["%s %s" % (kind, n) for kind in ("containers", "volumes", "networks") for n, v in s[kind].items()
            if str(v.get("label") if isinstance(v, dict) else v or "").startswith("moadix.run=")]


# ------------------------------------------------------------------ the failing output set (real where it fails)
def fail_set():
    d = os.path.join(E.base, "double-fail")
    put(d, "pytm/tm.json", raw("pytm.json"))
    put(d, "pytm/run.rc", "1\n")
    put(d, "likec4/validate.log", raw("likec4-validate-invalid.log"))
    put(d, "likec4/validate.rc", "1\n")
    put(d, "likec4/model.json", raw("likec4-export-invalid-model.json"))
    dc = json.loads(raw("depcruise.json"))
    dc["summary"]["error"] = 1
    dc["summary"]["violations"] = [{"from": "src/a.js", "to": "src/b.js", "rule": {"name": "no-circular",
                                                                                     "severity": "error"}}]
    put(d, "dependencycruiser/depcruise.json", json.dumps(dc))
    put(d, "knip/knip.json", raw("knip.json"))
    put(d, "eslint/eslint.json", raw("eslint.json"))
    put(d, "tsc/tsc.txt", raw("tsc.txt"))
    put(d, "tsc/run.rc", "2\n")
    put(d, "stryker/mutation.json", raw("stryker-mutation.json"))
    put(d, "tests/junit.xml", raw("node-test-junit-fail.xml"))
    put(d, "schemathesis/st/junit-20261114T211606Z.xml", raw("schemathesis-junit.xml"))
    z = json.loads(raw("zap.json"))
    z["site"][0]["alerts"][0].update(riskcode="3", riskdesc="High (Medium)")
    put(d, "zap/zap.json", json.dumps(z))
    put(d, "lhci/lhr-1794691180404.json", raw("lhr.json"))
    put(d, "axe/axe.json", raw("axe.json"))
    for g in os.listdir(d):
        if not os.path.exists(os.path.join(d, g, "run.rc")):
            put(d, g + "/run.rc", "0\n")
    return d


# ------------------------------------------------------------------ parsers on the real raw output
def test_parsers():
    G = "verdict from raw output"
    t = raw
    cases = [
        ("eslint: 1 error in the real report fails", X.parse_eslint(t("eslint.json")), 1),
        ("tsc: TS2322 in the real output fails", X.parse_tsc(t("tsc.txt"), 2), 1),
        ("tsc: exit 2 with no parsable line still fails", X.parse_tsc("", 2), 1),
        ("knip: 4 issues in the real report fail", X.parse_knip(t("knip.json")), 4),
        ("dependency-cruiser: the real report (0 errors) passes", X.parse_depcruise(t("depcruise.json")), 0),
        ("likec4: the real invalid model fails (validate exit 1, empty export)",
         X.parse_likec4(t("likec4-validate-invalid.log"), 1, t("likec4-export-invalid-model.json")), 2),
        ("likec4: an empty export with validate exit 0 still fails (LikeC4 exits 0 on a parse error)",
         X.parse_likec4(t("likec4-validate-ok.log"), 0, t("likec4-export-invalid-model.json")), None),
        ("likec4: the real valid model passes", X.parse_likec4(t("likec4-validate-ok.log"), 0, t("likec4-export.json")), 0),
        ("pytm: the real model passes (elements and flows)", X.parse_pytm(t("pytm.json"), 0), 0),
        ("pytm: a model that exits non-zero fails", X.parse_pytm("{}", 1), 1),
        ("pytm: a model with no flows fails", X.parse_pytm(json.dumps({"elements": [{}], "flows": []}), 0), 1),
        ("stryker: 70% passes a 70% threshold", X.parse_mutation(t("stryker-mutation.json"), 70), 0),
        ("stryker: 70% fails an 80% threshold", X.parse_mutation(t("stryker-mutation.json"), 80), 1),
        ("tests: the real failing JUnit fails", X.parse_junit(t("node-test-junit-fail.xml")), 1),
        ("tests: the real passing JUnit passes", X.parse_junit(t("node-test-junit-pass.xml")), 0),
        ("schemathesis: the real failing check fails", X.parse_junit(t("schemathesis-junit.xml"), "schemathesis"), 1),
        ("zap: the real report (no High) passes, its Mediums reported", X.parse_zap(t("zap.json")), 0),
        ("lighthouse: the real LHR passes the default budgets", X.parse_lhr(t("lhr.json")), 0),
        ("lighthouse: the real LHR fails a 500 ms LCP budget", X.parse_lhr(t("lhr.json"), {"lcp_ms": 500}), 1),
        ("axe: the real critical and serious violations fail", X.parse_axe(t("axe.json")), 3),
    ]
    for name, res, want in cases:
        n = len(res[0])
        record(G, name, n >= 1 if want is None else n == want, res[:2])
    z = json.loads(t("zap.json"))
    z["site"][0]["alerts"][0]["riskcode"] = "3"
    record(G, "zap: a High alert fails", len(X.parse_zap(json.dumps(z))[0]) == 1, "")
    for xml, why in (('<testsuites tests="0"><testsuite name="s" tests="0"/></testsuites>', "zero tests"),
                     ('<testsuites><testsuite name="s" tests="1"><testcase name="a"><skipped/></testcase></testsuite>'
                      '</testsuites>', "a skipped test")):
        record(G, "tests: %s never passes" % why, len(X.parse_junit(xml)[0]) >= 1, X.parse_junit(xml)[:1])


# ------------------------------------------------------------------ every gate through the runner, with the double
def test_gates(p, fail_dir):
    G = "gates through the runner"
    for gate in X.GATES:
        rc, out = run(p, gate)
        record(G, "%s (phase %s): the real passing output passes" % (gate, FIRST[gate]), rc == 0 and "PASS" in out, out)
        lo = leftovers()
        record(G, "%s: nothing labelled is left after the run" % gate, not lo, lo)
    put(p, ".sdlc/config/product-tools.yaml", PT_STRICT)
    for gate in X.GATES:
        rc, out = run(p, gate, outputs=fail_dir)
        record(G, "%s: the failing output fails the gate" % gate, rc == 1 and "FAIL" in out, out)
    put(p, ".sdlc/config/product-tools.yaml", PT)
    for gate in X.GATES:
        for label in X.GATES[gate]["phases"]:
            if label == FIRST[gate] or label == "B":
                continue
            rc, out = run(p, gate, label)
            record(G, "%s also runs at phase %s (evidence filed under it)" % (gate, label),
                   rc == 0 and "phase %s" % label in out, out)


def test_argv(p):
    G = "argv the engine receives"
    rc, out = run(p, "eslint")
    cs = calls()
    runs = [c for c in cs if c and c[0] == "run"]
    joined = [" ".join(c) for c in cs]
    record(G, "control: the eslint run went through the double (%d calls, %d runs)" % (len(cs), len(runs)),
           rc == 0 and len(runs) >= 3, out)
    record(G, "no call carries a host path, a bind mount or the Docker socket",
           not [j for j in joined if "docker.sock" in j or "type=bind" in j or re.search(r"(^| )(-v|--volume)( |=)", j)],
           joined)
    record(G, "every run, create, volume and network carries the run's label",
           all("moadix.run=" in j for j, c in zip(joined, cs) if c[0] in ("run", "create") or c[:2] in
               (["volume", "create"], ["network", "create"])), joined)
    record(G, "every run drops all capabilities and sets no-new-privileges",
           all("--cap-drop ALL" in " ".join(c) for c in runs) and
           all("no-new-privileges" in " ".join(c) for c in runs if "--rm" not in c), runs)
    tool = [c for c in runs if (c[c.index("--name") + 1] if "--name" in c else "").endswith("-eslint")]
    tj = " ".join(tool[0]) if tool else ""
    record(G, "the product-code run: --network none, read-only, uid 65534, the E-lint limits, /src read-only, /deps read-only",
           bool(tool) and "--network none" in tj and "--read-only" in tj and "--user 65534:65534" in tj and
           "--cpus 2" in tj and "--memory 2048m" in tj and "--memory-swap 2048m" in tj and "--pids-limit 256" in tj and
           "fsize=%d" % (50 << 20) in tj and re.search(r"dst=/src,readonly", tj) and re.search(r"dst=/deps,readonly", tj),
           tj)
    inst = [c for c in runs if "-install-" in (c[c.index("--name") + 1] if "--name" in c else "")]
    nets = {c[-1]: "--internal" in c for c in cs if c[:2] == ["network", "create"]}
    ij = " ".join(inst[0]) if inst else ""
    inet = inst[0][inst[0].index("--network") + 1] if inst else ""
    record(G, "the install step runs on an internal network, through the proxy only (HTTPS_PROXY), never the egress network",
           bool(inst) and nets.get(inet) is True and "HTTPS_PROXY=http://moadix-proxy:" in ij, (ij, nets))
    record(G, "the only non-internal network is the proxy's egress network",
           [n for n, internal in nets.items() if not internal] == [n for n in nets if n.endswith("-egress")], nets)
    rc, out = run(p, "axe")
    cs = calls()
    nets = {c[-1]: "--internal" in c for c in cs if c[:2] == ["network", "create"]}
    gate_run = [c for c in cs if c and c[0] == "run" and "--name" in c and c[c.index("--name") + 1].endswith("-axe")]
    gnet = gate_run[0][gate_run[0].index("--network") + 1] if gate_run else ""
    svc = [c for c in cs if c and c[0] == "run" and "-d" in c and "--name" in c and "-svc-app" in c[c.index("--name") + 1]]
    sj = " ".join(svc[0]) if svc else ""
    record(G, "live gate: the scanner and the app share only the run's internal live network",
           rc == 0 and gnet.endswith("-live") and nets.get(gnet) is True and ("--network %s" % gnet) in sj, (gnet, nets, sj))
    record(G, "live gate: the app answers as sut.moadix.test (never a name Chromium upgrades to HTTPS)",
           "--network-alias sut.moadix.test" in sj, sj)
    record(G, "live gate: the app image is built from the committed Dockerfile, with no network and the build limits",
           any(c[0] == "build" and "--network" in c and c[c.index("--network") + 1] == "none" for c in cs),
           [c for c in cs if c[0] == "build"])
    record(G, "the gate's own axe runner is loaded into a read-only volume, never from the product",
           "dst=/gx,readonly" in " ".join(gate_run[0]) if gate_run else False, gate_run)


def test_forged(p):
    G = "forged output"
    d = os.path.join(E.base, "double-forged")
    put(d, "tests/junit.xml", '<testsuites tests="0"><testsuite name="all" tests="0"/></testsuites>\n')
    put(d, "tests/run.rc", "0\n")
    put(d, "eslint/eslint.json", json.dumps({"result": "PASS", "errors": 0}))
    put(d, "eslint/run.rc", "0\n")
    put(d, "schemathesis/st/junit-1.xml", raw("schemathesis-junit.xml"))
    put(d, "schemathesis/st/junit-2.xml", raw("schemathesis-junit.xml"))
    put(d, "zap/zap.json", "PASS: no alerts\n")
    put(d, "lhci/lhr-1.json", json.dumps({"categories": {"performance": {"score": 1}}}))
    put(d, "axe/run.rc", "0\n")
    put(d, "knip/knip.json", "\n".join(["{\"issues\": []}", "garbage"]))
    for gate, why in (("tests", "a JUnit report with zero tests"),
                      ("eslint", "a summary object in place of ESLint's report"),
                      ("schemathesis", "two JUnit reports where one is expected"),
                      ("zap", "a text line claiming PASS in place of ZAP's JSON"),
                      ("lhci", "an LHR without the audits"),
                      ("axe", "no report at all (exit 0)"),
                      ("knip", "a report with trailing garbage")):
        rc, out = run(p, gate, outputs=d)
        record(G, "%s: %s is never believed" % (gate, why), rc != 0 and "PASS check-exec" not in out and
               not re.search(r"(?m)^PASS", out), out)


def test_applicability_and_inputs():
    G = "applicability and inputs"
    q = product("execna")
    put(q, "sdlc/7/COVERAGE.md", "# Coverage\n\n- I5: N/A: the product has no JavaScript (a static HTML page only)\n")
    E.commit(q, "coverage")
    rc, out = run(q, "eslint", "7")
    record(G, "a gate whose topic is N/A in the phase's COVERAGE.md reports N/A and runs nothing",
           rc == 0 and "N/A" in out and "I5" in out and not calls(), out)
    files = dict(PRODUCT_FILES)
    del files["tm/model.py"], files["package-lock.json"], files[".dependency-cruiser.json"], files["arch/model.c4"]
    files["stryker.conf.js"] = "module.exports = {}\n"
    files["likec4.config.ts"] = "export default {}\n"
    m = product("execmissing", files)
    for gate, want in (("pytm", "needs tm/model.py"), ("eslint", "package-lock.json is required"),
                       ("dependency-cruiser", "needs .dependency-cruiser.json"), ("likec4", "needs model sources"),
                       ("stryker", "stryker.conf.js) is refused"), ("likec4", "likec4.config.ts) is refused")):
        rc, out = run(m, gate)
        record(G, "%s: %s" % (gate, want), rc == 1 and want in out and not calls(), out)
    s = product("execnospec", {k: v for k, v in PRODUCT_FILES.items() if not k.startswith("sdlc/05-lld")})
    rc, out = run(s, "schemathesis")
    record(G, "schemathesis without an OpenAPI description under sdlc/05-lld fails", rc == 1 and "OpenAPI" in out, out)
    n = product("execnolive", pt="tests: {}\n")
    rc, out = run(n, "zap")
    record(G, "a live gate without live.compose in product-tools.yaml fails (the gate never guesses the app)",
           rc == 1 and "product-tools.yaml live." in out, out)
    rc, out = run(n, "nosuch", "9")
    record(G, "an unknown gate name is a usage error, never a pass", rc == 2 and "UNKNOWN" in out, out)


def test_fail_closed(p):
    G = "fail closed"
    rc, out = run(p, "tests")
    record(G, "control: the fixture copy (images cleared for the double) passes", rc == 0, out)
    cfg = os.path.join(E.home, "gate", "config", "confinement.yaml")
    saved = open(cfg).read()
    try:
        with open(cfg, "w") as f:
            f.write(re.sub(r"(?m)^    status: cleared$", "    status: blocked\n    reason: \"blocked for the fail-closed test\"", saved))
        for gate in X.GATES:
            rc, out = run(p, gate)
            record(G, "%s with its image blocked: UNKNOWN, nothing run" % gate, rc == 2 and "UNKNOWN" in out and "blocked" in out and not [c for c in calls() if c[0] == "run"],
                   out)
    finally:
        with open(cfg, "w") as f:
            f.write(saved)
    # an engine that is installed but not reachable (the daemon is down); "not installed" is tests/inc7c
    down = os.path.join(E.base, "engine-down")
    with open(down, "w") as f:
        f.write("#!/bin/sh\necho 'Cannot connect to the Docker daemon' >&2\nexit 1\n")
    os.chmod(down, 0o755)
    rc, out = run(p, "tests", MOADIX_TEST_ENGINE=down)
    record(G, "the engine is not reachable: UNKNOWN (never a run on the host)",
           rc == 2 and "UNKNOWN" in out and "not reachable" in out, out)


def test_axe_urls():
    G = "axe URLs (ruling 4)"
    ST = X.state
    q = product("execaxe")
    put(q, "design/screen-states.csv", "screen,state,status,reference,url\nNotes,default,designed,design/a.md,/notes\n"
                                        "Notes,empty,designed,design/a.md,/notes?empty=1\nNotes,loading,n/a,slow api,\n"
                                        "/settings,default,designed,design/a.md,\n")
    put(q, "sdlc/10a/LV-INVENTORY.csv", "lv_id,target,state,result,artifact,url\nLV-1,Notes,default,pass,t.zip,/notes\n"
                                         "LV-2,Login,default,pass,t.zip,/login\nLV-3,Help,default,n/a,not built,\n")
    E.commit(q, "design states with urls")
    st = ST.current_state(q)[0]
    pt = {"live": {"paths": ["/"]}}
    paths, probs = X.axe_urls(q, st, pt, "8")
    record(G, "phase 8: live.paths plus every designed screen-states row, by its url column or a path-like name; "
              "n/a rows skipped", paths == ["/", "/notes", "/notes?empty=1", "/settings"] and not probs, (paths, probs))
    paths, probs = X.axe_urls(q, st, pt, "10a")
    record(G, "phase 10a: LV-INVENTORY.csv rows that are not n/a are added (/login)",
           paths == ["/", "/notes", "/notes?empty=1", "/settings", "/login"] and not probs, (paths, probs))
    rc, out = run(q, "axe", "10a")
    record(G, "control: axe at 10a with every row resolvable runs and passes", rc == 0 and "PASS" in out, out)
    put(q, "design/screen-states.csv", "screen,state,status,reference\nNotes,default,designed,design/a.md\n")
    E.commit(q, "a designed screen without a url")
    rc, out = run(q, "axe", "8")
    record(G, "a designed screen with no URL fails the gate and names the row (the gate never guesses an address)",
           rc == 1 and "screen-states.csv line 2" in out and "no URL" in out and not [c for c in calls() if c[0] == "run"],
           out)
    for bad in ("http://evil.example/x", "//evil.example/x", "/a/../../b"):
        put(q, "design/screen-states.csv", "screen,state,status,reference,url\nNotes,default,designed,design/a.md,%s\n" % bad)
        E.commit(q, "hostile url")
        _p, probs = X.axe_urls(q, ST.current_state(q)[0], pt, "8")
        record(G, "hostile: a url %r that leaves the app is refused" % bad, probs and "app-relative" in probs[0], probs)
    js = open(os.path.join(REPO, "gate", "exec", "axe-run.js")).read()
    record(G, "the axe runner reads the gate's paths file and refuses a path whose origin is not the app's",
           "--paths-file" in js and "refusing a path that leaves the app" in js, "")


def test_zap_rules(p):
    G = "ZAP rules (ruling 4)"
    rules = X.load_zap_rules()
    record(G, "the gate-owned rules file parses (%d rules, actions IGNORE/INFO/WARN/FAIL)" % len(rules),
           len(rules) >= 10 and set(rules.values()) <= set(X.ZAP_ACTIONS) and "FAIL" in rules.values(), rules)
    z = json.loads(raw("zap.json"))
    f, n, _d = X.parse_zap(json.dumps(z), rules)
    record(G, "control: the real report passes with the rules (Mediums reported, 10049 ignored)",
           not f and "1 ignored" in n[-1], (f, n[-1:]))
    z["site"][0]["alerts"][0].update(pluginid="10010", riskcode="1", name="Cookie No HttpOnly Flag")
    record(G, "a Low alert of a rule set to FAIL (10010) fails", len(X.parse_zap(json.dumps(z), rules)[0]) == 1, "")
    z["site"][0]["alerts"][0].update(pluginid="10049", riskcode="3")
    record(G, "a High alert fails even when its rule is IGNORE", len(X.parse_zap(json.dumps(z), rules)[0]) == 1, "")
    bad = os.path.join(E.base, "zap-bad.tsv")
    for text, why in (("10010\tBLOCK\t(x)\n", "an unknown action"), ("abc\tFAIL\t(x)\n", "a non-numeric id"),
                      ("10010\tFAIL\t(x)\n10010\tIGNORE\t(x)\n", "a repeated rule")):
        with open(bad, "w") as f:
            f.write(text)
        try:
            X.load_zap_rules(bad)
            ok = False
        except ValueError:
            ok = True
        record(G, "a rules file with %s is refused (the gate is UNKNOWN, never a pass)" % why, ok, text)
    rc, out = run(p, "zap")
    cs = calls()
    zrun = [c for c in cs if c and c[0] == "run" and "--name" in c and c[c.index("--name") + 1].endswith("-zap")]
    loaded = [c for c in cs if c and c[0] == "create" and c[c.index("--name") + 1].endswith("-load-out")]
    record(G, "the ZAP run loads the rules into /zap/wrk and passes -c zap-rules.tsv",
           rc == 0 and loaded and zrun and "-c zap-rules.tsv" in " ".join(zrun[0]), (out, loaded, zrun))


def test_runner_kill_and_mounts():
    """0.6.2 (the operator's engine run on 0.6.1): an OOM kill is always a refusal naming the memory limit, even
    when the engine's OOMKilled flag is false or inspect fails; the host-mount check covers the engine options
    only, so a command that merely names the socket (or `node -v`) is not refused, while a bind, -v or the
    socket as a mount still is."""
    G = "runner: OOM kill and mount check"
    stub = os.path.join(E.base, "engine-stub")
    with open(stub, "w") as f:
        f.write("#!/bin/sh\necho \"$*\" >> \"$0.log\"\ncase \"$1\" in\n  version) echo stub-1 ;;\n"
                "  run) case \"$*\" in *getent*) exit 0 ;; esac; exit \"${STUB_RC:-0}\" ;;\n"  # 0.7.3: passwd check
                "  ps) echo 0123456789abcdef ;;\n"
                "  inspect) [ -n \"$STUB_INSPECT_FAILS\" ] && exit 1; echo \"${STUB_OOM:-false}\" ;;\nesac\nexit 0\n")
    os.chmod(stub, 0o755)
    saved_engine = confined.engine
    confined.engine = lambda: stub
    lim = confined.limits("E-lint")
    try:
        r = confined.Run("kill-test")
        for rc, oom, fails, what in ((137, "false", "", "exit 137 with OOMKilled false"),
                                     (137, "", "yes", "exit 137 with inspect failing"),
                                     (0, "true", "", "OOMKilled true with exit 0")):
            os.environ.update(STUB_RC=str(rc), STUB_OOM=oom)
            os.environ.pop("STUB_INSPECT_FAILS", None)
            if fails:
                os.environ["STUB_INSPECT_FAILS"] = fails
            try:
                res, why = r.execute("img@sha256:" + "0" * 64, ["node", "x.js"], "E-lint", []), None
            except confined.Refused as e:
                res, why = None, str(e)
            record(G, "%s: refused, naming the limit (never a result, never None)" % what,
                   res is None and why and "memory limit (%d MiB)" % lim["memory_mb"] in why, (res, why))
        os.environ.update(STUB_RC="1", STUB_OOM="false")
        os.environ.pop("STUB_INSPECT_FAILS", None)
        res = r.execute("img@sha256:" + "0" * 64, ["node", "x.js"], "E-lint", [])
        record(G, "control: an ordinary failing exit (1, not OOM-killed) is returned as a result", res[0] == 1, res)
        os.environ["STUB_RC"] = "0"
        ok = []
        for argv in (["sh", "-c", "test -S /var/run/docker.sock && echo SOCKET"], ["node", "-v"], ["ls", "--volume"]):
            try:
                ok.append(r.execute("img@sha256:" + "0" * 64, argv, "E-lint", [])[0] == 0)
            except confined.Refused as e:
                ok.append(str(e))
        record(G, "a command that only names the socket, `node -v` or `--volume` runs (the check covers the engine options)",
               ok == [True, True, True], ok)
        why = []
        for opts in (["--mount", "type=bind,src=/,dst=/h"], ["-v", "/:/h"], ["--volume=/x:/y"],
                     ["--mount", "type=volume,src=/var/run/docker.sock,dst=/s"]):
            try:
                confined._refuse_host_mounts(["run"] + opts)
                why.append(None)
            except confined.Refused as e:
                why.append(str(e))
        try:
            r.execute("img@sha256:" + "0" * 64, ["true"], "E-lint", [("/var/run/docker.sock", "/s", True)])
            why.append(None)
        except confined.Refused as e:
            why.append(str(e))
        record(G, "a bind mount, -v, --volume= or the socket in the engine options is still refused",
               all(why), why)
    finally:
        confined.engine = saved_engine
        for k in ("STUB_RC", "STUB_OOM", "STUB_INSPECT_FAILS"):
            os.environ.pop(k, None)


def test_safeguards():
    G = "engine-suite safeguards (ruling 3)"
    import no_prune
    hits = no_prune.scan(REPO)
    record(G, "static: no pruning, no compose down with volumes, no image removal in the runner, the gates or the "
              "engine suite (%d files)" % len(no_prune.SCANNED), not hits, hits)
    fake = os.path.join(E.base, "fake-repo")
    planted = {"system": 'docker(["system", "pr' + 'une", "-f"])', "volume": "docker volume pr" + "une -f",
               "compose": "docker compose -p x do" + "wn -v", "compose2": "docker compose do" + "wn --vol" + "umes",
               "rmi": 'docker(["rm' + 'i", img])'}
    for k, line in planted.items():
        put(fake, "gate/confined.py", "x = 1\n%s\n" % line)
        for rel in no_prune.SCANNED[1:]:
            put(fake, rel, "x = 1\n")
        h = no_prune.scan(fake)
        record(G, "negative control: a planted %r is caught" % line, h and h[0][1] == 2, h)
    sys.path.insert(0, os.path.join(REPO, "tests", "confined-engine"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("engine_suite", os.path.join(REPO, "tests", "confined-engine", "run.py"))
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    record(G, "only its own label counts as its own (es + 10 hex digits; a gate run x..., a look-alike es-1 are not)",
           es.ours("es0123456789") and not es.ours("x0123456789") and not es.ours("es-1") and not es.ours("") and
           not es.ours("es0123456789a"), "")
    a = {"containers": ["c1 onlinemarket-app-1 exited"], "volumes": ["v1"], "networks": ["n1 bridge"],
         "images": ["sha256:1 postgres:17"]}
    b = {"containers": ["c1 onlinemarket-app-1 running"], "volumes": [], "networks": ["n1 bridge"],
         "images": ["sha256:1 postgres:17", "sha256:2 x:1"]}
    d = es.difference(a, b)
    record(G, "the before/after records print every difference (a state change, a volume gone, an image new)",
           "containers gone: c1 onlinemarket-app-1 exited" in d and "containers new: c1 onlinemarket-app-1 running" in d
           and "volumes gone: v1" in d and "images new: sha256:2 x:1" in d and not es.difference(a, a), d)

    class P(object):
        def __init__(self, out, rc=0):
            self.stdout, self.returncode, self.stderr = out, rc, ""

    def fake_docker(rows):
        def f(args, timeout=120, stdin=None):
            if args[0] == "version":
                return P("29.0.0\n")
            if args[0] == "ps":
                return P("".join("\t".join(r) + "\n" for r in rows))
            return P("")
        return f

    saved = (es.docker, es.confined.docker_path)
    es.confined.docker_path = lambda: "/fake/docker"
    try:
        es.docker = fake_docker([("c1", "onlinemarket-app-1", "exited", "", "onlinemarket"),
                                 ("c2", "momento-app", "exited", "", "momento")])
        why, stopped = es.preflight()
        record(G, "stopped foreign compose projects do not block; they are listed as found", not why and
               stopped == ["momento", "onlinemarket"], (why, stopped))
        es.docker = fake_docker([("c1", "onlinemarket-app-1", "running", "", "onlinemarket"),
                                 ("c3", "solo", "running", "", ""), ("c4", "moadix-es-x", "running", "es0123456789", "")])
        why, stopped = es.preflight()
        j = " ".join(why)
        record(G, "a running foreign container or compose project blocks, and each is named; its own does not",
               "onlinemarket-app-1" in j and "solo" in j and "compose projects with running containers: onlinemarket" in j
               and "moadix-es-x" not in j, why)
    finally:
        es.docker, es.confined.docker_path = saved
    src = open(os.path.join(REPO, "tests", "confined-engine", "run.py")).read()
    record(G, "the suite records images too, and fails on any difference",
           '"images"' in src and "DIFFERENCE" in src and "not diff" in src, "")
    record(G, "it never starts, stops or inspects a foreign object: inspect only on its own pinned images and its own "
              "containers", '"start"' not in src and '"stop"' not in src and src.count('"inspect"') == 1, "")
    # a crashing group is one failed check plus its unrun checks reported as failed: the total stays fixed
    # (49 since 0.7.3: the user and smoke groups; 50 since 0.7.5: the secrets control; 57 since 0.7.6: rel076)
    saved_results = list(es.RESULTS)
    del es.RESULTS[:]

    def test_host(_n):
        es.record("host paths", "first check", True)
        raise es.confined.Refused("may not mount a host path or the Docker socket")
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            es.run_group(test_host, (None,))
        got = list(es.RESULTS)
    finally:
        es.RESULTS[:] = saved_results
    record(G, "engine suite: a group that crashes after 1 of its 6 checks reports 6 (1 passed, the crash, 4 not run); "
              "the suite's total is fixed at 70 (0.7.3: user 5, smoke 13; 0.7.5: secrets 5; 0.7.6: rel076 7; 0.7.7: rel077 2; 0.7.8: rel078 4; 0.7.9: rel079 4; 0.8.0: rel080 3)",
           es.TOTAL == 70 and len(got) == 6 and [x[2] for x in got] == [True] + [False] * 5 and "crashed" in got[1][1],
           got)


def test_install_and_locks():
    G = "installer and locks"
    sh = open(os.path.join(REPO, "managed", "install.sh")).read()
    record(G, "the installer copies gate/*.py (check_exec, confined, egress_proxy), gate/exec and every lock directory",
           '"$HERE"/gate/*.py' in sh and '"$HERE"/gate/exec/*' in sh and '"$HERE"/gate/config/locks/*/' in sh, "")
    record(G, "the installer copies gate/config/*.json (critic.schema.json was never installed before 7d)",
           re.search(r'"\$HERE"/gate/config/\*\.json', sh) is not None, "")
    record(G, "the installer creates the 7b tool configuration directories (semgrep redocly k6 vacuum squawk actionlint)",
           "semgrep redocly k6 vacuum squawk actionlint" in sh, "")
    locks = os.path.join(REPO, "gate", "config", "locks")
    same, diff = [], []
    for name in sorted(os.listdir(locks)):
        for kind in ("npm", "python"):
            src = os.path.join(REPO, "tools", kind, name)
            if os.path.isdir(src):
                for f in os.listdir(os.path.join(locks, name)):
                    a, b = os.path.join(locks, name, f), os.path.join(src, f)
                    (same if os.path.exists(b) and open(a, "rb").read() == open(b, "rb").read() else diff).append(
                        "%s/%s" % (name, f))
    record(G, "every gate lock file equals its tools/ copy (%d files)" % len(same), same and not diff, diff)
    need = {g["tool"][1] for g in X.GATES.values() if g.get("tool")}
    record(G, "every gate tool has a lock directory (%s)" % ", ".join(sorted(need)),
           all(os.path.isdir(os.path.join(locks, n)) for n in need), sorted(set(need) - set(os.listdir(locks))))
    record(G, "the npm locks carry integrity hashes; the Python locks carry --hash pins",
           all("integrity" in open(os.path.join(locks, n, "package-lock.json")).read()
               for n in need if os.path.exists(os.path.join(locks, n, "package-lock.json"))) and
           all("--hash=sha256:" in open(os.path.join(locks, n, "requirements.txt")).read()
               for n in need if os.path.exists(os.path.join(locks, n, "requirements.txt"))), "")
    import hlib
    reg = [c for c in hlib.load_yaml(os.path.join(REPO, "gate", "config", "registry.yaml"))["components"]
           if c["module"] == "check_exec"]
    want = {"check-exec-%s-%s" % (g, ph) for g, v in X.GATES.items() for ph in v["phases"]}
    record(G, "the registry carries one check-exec entry per gate and phase (%d)" % len(want),
           {c["id"] for c in reg} == want and all([str(a) for a in c.get("args") or []] == ["--gate", c["id"].split("-", 2)[2].rsplit("-", 1)[0],
                                                                     "--phase", c["id"].rsplit("-", 1)[1]] for c in reg),
           sorted({c["id"] for c in reg} ^ want))
    cfg = confined._yaml(os.path.join(REPO, "gate", "config", "confinement.yaml"))
    record(G, "every image a gate uses is pinned by digest, with its source and a status", all(
        confined.DIGEST_REF.match(cfg["images"][g["image"]]["ref"]) and cfg["images"][g["image"]].get("source") and
        cfg["images"][g["image"]].get("status") in ("blocked", "cleared") for g in X.GATES.values()), "")
    tp = open(os.path.join(REPO, "THIRD-PARTY.md")).read()
    record(G, "THIRD-PARTY.md records each image's digest and source (ruling 1)",
           all(e["ref"].split("@")[1] in tp for e in cfg["images"].values()), "")


def main():
    try:
        test_parsers()
        p = product("execprod")
        fd = fail_set()
        for t, a in ((test_gates, (p, fd)), (test_argv, (p,)), (test_forged, (p,)), (test_applicability_and_inputs, ()),
                     (test_fail_closed, (p,)), (test_axe_urls, ()), (test_zap_rules, (p,)), (test_runner_kill_and_mounts, ()),
                     (test_safeguards, ()),
                     (test_install_and_locks, ())):
            try:
                t(*a)
            except Exception as e:
                import traceback
                record(t.__name__, "group ran to the end", False, "%s: %s\n%s" % (type(e).__name__, e,
                                                                                 traceback.format_exc()[-1500:]))
        viol = E.violations()
        record("guard", "no test read, wrote or started a real product, keychain or ~/.claude", not viol, viol)
    finally:
        E.remove()
    n = len(RESULTS)
    bad = [r for r in RESULTS if not r[2]]
    for g, name, _ok in bad:
        print("FAILED [%s] %s" % (g, name))
    print("\n%d checks, %d passed, %d failed (%d s)" % (n, n - len(bad), len(bad), time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
