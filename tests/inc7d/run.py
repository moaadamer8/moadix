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
    record(G, "the product-code run: --network none, read-only, uid 10001, the E-lint limits, /src read-only, /deps read-only",
           bool(tool) and "--network none" in tj and "--read-only" in tj and "--user 10001:10001" in tj and
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
        shutil.copy(os.path.join(REPO, "gate", "config", "confinement.yaml"), cfg)
        for gate in X.GATES:
            rc, out = run(p, gate)
            record(G, "%s with the repository's configuration (image blocked by the licence ruling): UNKNOWN, nothing run"
                   % gate, rc == 2 and "UNKNOWN" in out and "blocked" in out and not [c for c in calls() if c[0] == "run"],
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
                     (test_fail_closed, (p,)), (test_install_and_locks, ())):
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
