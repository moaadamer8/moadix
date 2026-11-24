#!/usr/bin/python3
"""0.7.8 suite: one app origin for every live gate. Written before the fix; on 0.7.7 (a228485) its fix checks fail.

    /usr/bin/python3 tests/rel078/run.py

0.7.7 opened the app as http://sut.localhost:<port> in axe and Lighthouse CI but sent Schemathesis and ZAP to
http://sut.moadix.test:<port>, so a product that accepts only its own origin failed one gate whatever it configured.
0.7.8: confined.app_origin(port) is the one gate-owned value; every live gate uses it for its URL, Host and Origin,
and /moadix:coverage tells the product to set APP_ORIGIN to exactly that value. The real-engine case is group rel078
of tests/confined-engine (every live gate passes against tests/fixtures/smoke-076's strict app).

Fixtures only: throwaway repos under $TMPDIR, the engine double, the fixture app run in process (no port), no network.

  origin    the value, and every live gate's URL, Host and Origin from it (0.7.7 control)
  service   the app's service gets the origin's host as its network alias (and Chromium's mapping alias)
  fixture   the fixture app accepts only that origin (421 for another Host, 403 for another Origin); its stack sets
            APP_ORIGIN to exactly the gate's value
  gates     every live gate passes on the fixture through the gate and the double
  doc       /moadix:coverage documents the origin, generated from the same value
  engine    the engine suite's rel078 group and its total
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r78").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined, contract  # noqa: E402

RESULTS = []
T0 = time.time()
OLD = "a228485"  # 0.7.7
FIX76 = os.path.join(REPO, "tests", "fixtures", "smoke-076")
DBL = os.path.join(E.base, "engine-double")
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
SD = "." + "sdlc"
NODE = shutil.which("node") or "/opt/homebrew/bin/node"
LIVE = (("schemathesis", "8"), ("zap", "9"), ("lhci", "10a"), ("axe", "8"))
ORIGIN = "http://sut.localhost:3000"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def old_check_exec():
    p = os.path.join(E.home, "gate", "v1", "check_exec_077.py")
    with open(p, "w") as f:
        f.write(subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:gate/v1/check_exec.py" % OLD],
                               capture_output=True, text=True).stdout)
    import importlib
    return importlib.import_module("check_exec_077")


def product(name):
    p = os.path.join(E.base, name)
    shutil.copytree(FIX76, p, ignore=shutil.ignore_patterns(".claude", "product-tools.yaml", "node_modules"))
    subprocess.run(["/usr/bin/git", "init", "-q", p])
    E.commit(p, "fixture")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    with open(os.path.join(FIX76, "product-tools.yaml")) as f:
        E.write(p, SD + "/config/product-tools.yaml", f.read())
    return p


def run_gate(p, gate, label):
    shutil.rmtree(DBL, ignore_errors=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", gate, "--phase", label],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS), timeout=300)
    return r.returncode, r.stdout + r.stderr


def calls():
    f = os.path.join(DBL, "calls.log")
    return [json.loads(x) for x in open(f).read().splitlines() if x.strip()] if os.path.exists(f) else []


def urls_in(gate, mod):
    s = mod.live_script(gate, 3000, "sdlc/05-lld/api.yaml", ["/"], 2048)
    if gate == "lhci":
        s += " " + json.dumps(mod.lhci_config(3000))
    return s, sorted(set(re.findall(r"https?://[A-Za-z0-9.-]+:\d+", s)))


# ------------------------------------------------------------------ origin
def test_origin():
    G = "origin"
    old = old_check_exec()
    olds = {g: urls_in(g, old)[1] for g, _l in LIVE}
    record(G, "control: on 0.7.7 the live gates used two origins (Schemathesis and ZAP sut.moadix.test, axe and lhci "
              "sut.localhost)", olds["schemathesis"] == ["http://sut.moadix.test:3000"] and
           olds["zap"] == ["http://sut.moadix.test:3000"] and olds["axe"] == [ORIGIN], olds)
    record(G, "the app origin is one gate-owned value: confined.app_origin(3000) == %s" % ORIGIN,
           confined.app_origin(3000) == ORIGIN and X.browser_url(3000) == ORIGIN, confined.app_origin(3000))
    for gate, _label in LIVE:
        s, urls = urls_in(gate, X)
        record(G, "%s reaches the app only at %s (URL and Host), and waits for it at that host" % (gate, ORIGIN),
               urls == [ORIGIN] and "/dev/tcp/sut.localhost/3000" in s and
               confined.SUT_ALIAS not in s.replace(confined.BROWSER_RULE, ""), (urls, s[-300:]))
    s = X.live_script("schemathesis", 3000, "x.yaml", ["/"])
    record(G, "Schemathesis sends Origin: %s with every request" % ORIGIN, "-H 'Origin: %s'" % ORIGIN in s, s[-300:])
    z = X.live_script("zap", 3000, None, ["/"])
    record(G, "ZAP's replacer adds Origin: %s to every request" % ORIGIN,
           "replacer.full_list(0).matchtype=REQ_HEADER" in z and "replacer.full_list(0).matchstr=Origin" in z and
           "replacer.full_list(0).replacement=%s" % ORIGIN in z and "replacer.full_list(0).enabled=true" in z, z[-500:])
    record(G, "axe and lhci keep Chromium's mapping of that host to the app's second alias (Chromium never asks DNS "
              "for *.localhost)", confined.BROWSER_RULE == "MAP sut.localhost %s" % confined.SUT_ALIAS, confined.BROWSER_RULE)


# ------------------------------------------------------------------ service
def test_service():
    G = "service"
    p = product("svc")
    rc, out = run_gate(p, "schemathesis", "8")
    app = next((c for c in calls() if c[:1] == ["run"] and "--name" in c and c[c.index("--name") + 1].endswith("-svc-app")),
               [])
    aliases = [app[i + 1] for i, x in enumerate(app) if x == "--network-alias"]
    record(G, "the app's service answers at the origin's host on the run's network (and Chromium's mapping alias)",
           rc == 0 and aliases == [confined.APP_HOST, confined.SUT_ALIAS], (aliases, out[-400:]))


# ------------------------------------------------------------------ fixture
SERVE = r"""
import http from "node:http";
import { EventEmitter } from "node:events";
let handler;
http.createServer = (h) => { handler = h; return { listen() {} }; };
process.env.APP_ORIGIN = process.argv[3] || "";
await import(process.argv[2]);
function call(headers) {
  return new Promise((resolve) => {
    const req = new EventEmitter(); req.method = "GET"; req.url = "/health"; req.headers = headers; req.destroy = () => {};
    handler(req, { writeHead(s) { this.s = s; }, end() { resolve(this.s); } });
  });
}
const out = {
  own: await call({ host: "sut.localhost:3000" }),
  ownWithOrigin: await call({ host: "sut.localhost:3000", origin: "http://sut.localhost:3000" }),
  oldHost: await call({ host: "sut.moadix.test:3000" }),
  otherPort: await call({ host: "sut.localhost:4000" }),
  foreignOrigin: await call({ host: "sut.localhost:3000", origin: "http://sut.moadix.test:3000" }),
};
console.log(JSON.stringify(out));
"""


def test_fixture():
    G = "fixture"
    harness = os.path.join(E.base, "serve.mjs")
    with open(harness, "w") as f:
        f.write(SERVE)
    srv = os.path.join(E.base, "server.mjs")
    shutil.copy(os.path.join(FIX76, "src", "server.js"), srv)
    r = subprocess.run([NODE, harness, srv, ORIGIN], capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    record(G, "the fixture app accepts only its origin: 421 for Host sut.moadix.test or another port, 403 for another "
              "Origin", got == {"own": 200, "ownWithOrigin": 200, "oldHost": 421, "otherPort": 421, "foreignOrigin": 403},
           (got, r.stderr[-300:]))
    import hlib
    doc = hlib.load_yaml(os.path.join(FIX76, "compose.yaml"))
    record(G, "its gate test stack sets APP_ORIGIN to exactly the gate's value",
           ((doc.get("services") or {}).get("app") or {}).get("environment", {}).get("APP_ORIGIN") ==
           confined.app_origin(3000), doc)


# ------------------------------------------------------------------ gates
def test_gates():
    G = "gates"
    p = product("gates")
    for gate, label in LIVE:
        rc, out = run_gate(p, gate, label)
        record(G, "%s (phase %s) passes on the strict fixture through the gate and the double" % (gate, label),
               rc == 0 and "PASS" in out, out[-600:])


# ------------------------------------------------------------------ doc
def test_doc():
    G = "doc"
    doc = open(os.path.join(REPO, "commands", "coverage.md")).read()
    record(G, "/moadix:coverage is the generated text", doc == contract.coverage_doc(), "regenerate it")
    m = re.search(r"\*\*Live gates: the app's origin\.\*\*([^\n]+)", doc)
    para = m.group(1) if m else ""
    record(G, "it documents the one origin every live gate uses, and APP_ORIGIN set to exactly that value",
           "http://sut.localhost:<port>" in para and "`APP_ORIGIN: %s`" % ORIGIN in para and "Schemathesis" in para and
           "ZAP" in para and "Host" in para and "Origin header" in para, para)


# ------------------------------------------------------------------ engine
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite078", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    record(G, "the engine suite has a rel078 group (every live gate against the strict app), and its total is 79 (0.7.9: rel079 4; 0.8.0: rel080 3; 0.8.1: rel081 3; 0.8.2: rel082 4; 0.8.3: rel083 2)",
           es.PLAN.get("test_rel078") == ("rel078", 4) and es.TOTAL == 79 and
           [g for g, _l in es.LIVE_GATES] == ["schemathesis", "zap", "lhci", "axe"], (es.PLAN.get("test_rel078"), es.TOTAL))


def main():
    try:
        for t in (test_origin, test_service, test_fixture, test_gates, test_doc, test_engine):
            try:
                t()
            except Exception as e:  # a crashing group is a failure, never a skip
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
