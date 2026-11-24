#!/usr/bin/python3
"""0.7.7 suite: the four failures of the 0.7.6 engine run (rel076: MF-53, MF-51, MF-49 with MF-50), each written
before its fix and failing on 0.7.6 (ee48c77). The causes were measured on the real engine first
(docs/release-0.7.7-report.md); the real-engine cases are groups rel076 and rel077 of tests/confined-engine.

    /usr/bin/python3 tests/rel077/run.py

Fixtures only: throwaway folders and repos under $TMPDIR, the engine double (no Docker), the Playwright double (no
browser), no network.

  link      node_modules in the work copy is a real folder of links to the read-only /deps, so Vite can write its
            bundled configuration beside the packages (0.7.6: one link into /deps, and Vitest under Stryker died
            with ENOENT: mkdir '/tmp/work/node_modules/.vite-temp')
  summary   a failed run's summary names its first error lines and drops stack frames (0.7.6 kept only the last
            12 lines, the stack's tail, and cut the ENOENT line): the 0.7.6 engine run's real log
  browser   the browser gates open the app as http://sut.localhost:<port> with Chromium's resolver rule
            MAP sut.localhost sut.moadix.test, because Chromium keeps a __Host- Secure cookie over http only for a
            .localhost name (on sut.moadix.test it refused it, with or without the 0.7.6 flag); Lighthouse CI the same
  engine    the engine suite's rel077 group and its fixed total
"""
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r77").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined  # noqa: E402

RESULTS = []
T0 = time.time()
OLD = "ee48c77"  # 0.7.6
SMOKE = os.path.join(REPO, "tests", "fixtures", "smoke")
FIX76 = os.path.join(REPO, "tests", "fixtures", "smoke-076")
DBL = os.path.join(E.base, "engine-double")
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
SD = "." + "sdlc"
FAKEPW = os.path.join(REPO, "tests", "lib", "fakepw")
NODE = shutil.which("node") or "/opt/homebrew/bin/node"
ENGINE_LOG = os.path.join(REPO, "tests", "exec", "raw", "stryker-076-vite-enoent.log")


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def old_file(rel):
    return subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:%s" % (OLD, rel)], capture_output=True,
                          text=True).stdout


def old_check_exec():
    """0.7.6's check_exec, imported beside the fixture gate's (it uses the same gate modules)."""
    p = os.path.join(E.home, "gate", "v1", "check_exec_076.py")
    with open(p, "w") as f:
        f.write(old_file("gate/v1/check_exec.py"))
    import importlib
    return importlib.import_module("check_exec_076")


def product(name, fixture=SMOKE):
    p = os.path.join(E.base, name)
    shutil.copytree(fixture, p, ignore=shutil.ignore_patterns(".claude", "product-tools.yaml", "node_modules"))
    subprocess.run(["/usr/bin/git", "init", "-q", p])
    E.commit(p, "fixture")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    with open(os.path.join(fixture, "product-tools.yaml")) as f:
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


# ------------------------------------------------------------------ link
def link_step(script):
    """The node_modules step of a gate script (everything between `cd /tmp/work` and the tool)."""
    m = re.search(r"cd /tmp/work( && .*?) && node ", script)
    return m.group(1)[4:] if m else None


def simulate(step, with_packages=True):
    """Run a gate's node_modules step under a fake root: /deps/product/node_modules read-only (as mounted in the
    run), the work copy writable. Returns (rc, can Vite write node_modules/.vite-temp, resolves vitest, root)."""
    root = os.path.join(E.base, "link-%d" % len(os.listdir(E.base)))
    nm = os.path.join(root, "deps", "product", "node_modules")
    os.makedirs(os.path.join(root, "tmp", "work"))
    os.makedirs(nm)
    if with_packages:
        os.makedirs(os.path.join(nm, "vitest"))
        with open(os.path.join(nm, "vitest", "package.json"), "w") as f:
            json.dump({"name": "vitest", "version": "0.0.0", "type": "module", "exports": {".": "./index.js"}}, f)
        with open(os.path.join(nm, "vitest", "index.js"), "w") as f:
            f.write("export const ok = 1;\n")
        os.makedirs(os.path.join(nm, ".bin"))
    for d, dirs, _files in os.walk(nm):
        os.chmod(d, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)
    os.chmod(nm, stat.S_IRUSR | stat.S_IXUSR)
    step = step.replace("/deps/", os.path.join(root, "deps") + "/")
    r = subprocess.run(["/bin/sh", "-c", "cd %s && %s && echo chain-continues" % (shlex.quote(os.path.join(root, "tmp", "work")),
                                                                              step)],
                       capture_output=True, text=True, timeout=60)
    work_nm = os.path.join(root, "tmp", "work", "node_modules")
    vite = subprocess.run(["/bin/mkdir", os.path.join(work_nm, ".vite-temp")], capture_output=True, text=True)
    probe = os.path.join(root, "tmp", "work", "probe.mjs")
    with open(probe, "w") as f:
        f.write("import { ok } from 'vitest';\nconsole.log('resolved', ok);\n")
    res = subprocess.run([NODE, probe], capture_output=True, text=True, timeout=60) if with_packages else None
    return r, vite.returncode == 0, bool(res and "resolved 1" in res.stdout), root


def unlock(root):
    for d, dirs, _files in os.walk(root):
        os.chmod(d, stat.S_IRWXU)


def test_link():
    G = "link"
    old = link_step(old_check_exec().tool_script("stryker", None, {}))
    r, vite, res, root = simulate(old)
    unlock(root)
    record(G, "control: with 0.7.6's single link into the read-only /deps, Vite cannot create node_modules/.vite-temp "
              "(the engine run's ENOENT)", old and not vite and res, (old, r.stderr[-300:]))
    for gate in ("stryker", "tests", "eslint", "tsc", "knip"):
        s = X.tool_script(gate, None, {"tests": {"command": ["node", "x.js"]}})
        record(G, "%s: the work copy's node_modules is built by the same step" % gate, X.LINK_PRODUCT in s, s[:200])
    new = link_step(X.tool_script("stryker", None, {}))
    r, vite, res, root = simulate(new)
    deps_untouched = sorted(os.listdir(os.path.join(root, "deps", "product", "node_modules"))) == [".bin", "vitest"]
    links = sorted(os.listdir(os.path.join(root, "tmp", "work", "node_modules")))
    unlock(root)
    record(G, "0.7.7: node_modules is a real folder of links; Vite's temporary folder can be created there, the packages "
              "resolve through the links, and /deps is unchanged", r.returncode == 0 and "chain-continues" in r.stdout and
           vite and res and deps_untouched and {".bin", "vitest"} <= set(links), (r.stdout, r.stderr[-300:], links))
    r, _vite, _res, root = simulate(new, with_packages=False)
    unlock(root)
    record(G, "with no packages at all the step still lets the gate's command run (no dangling link, no stop)",
           r.returncode == 0 and "chain-continues" in r.stdout and
           set(os.listdir(os.path.join(root, "tmp", "work", "node_modules"))) <= {".vite-temp"}, (r.stdout, r.stderr))


# ------------------------------------------------------------------ summary
def summary_of(mod, text):
    d = os.path.join(E.base, "out-%d" % len(os.listdir(E.base)))
    os.makedirs(d)
    with open(os.path.join(d, "run.log"), "w") as f:
        f.write(text)
    with open(os.path.join(d, "run.rc"), "w") as f:
        f.write("1\n")
    return mod.run_logs(d, 0, "", "")[1]


def test_summary():
    G = "summary"
    log = open(ENGINE_LOG).read()
    old = summary_of(old_check_exec(), log)
    record(G, "control: 0.7.6's summary of the engine run's real Stryker log does not say what failed (only the stack's "
              "tail)", "ENOENT" not in old and "at " in old, old[-400:])
    new = summary_of(X, log)
    first = new.split("last lines:")[0]
    record(G, "0.7.7: the summary names the first error lines: ENOENT, mkdir .../node_modules/.vite-temp",
           "first errors:" in first and "ENOENT" in first and ".vite-temp" in first, new[:600])
    record(G, "it drops stack frames from both parts", not re.search(r"\|\s*at\s|:\s*at\s", new), new[:800])
    calm = summary_of(X, "INFO starting\nINFO 3 files\nINFO done\n")
    record(G, "control: a log with no error line gets no first-errors part", "first errors" not in calm and "done" in calm,
           calm)
    record(G, "the summary stays bounded (3 first errors of at most 300 characters, the line at most 3000)",
           len(summary_of(X, ("Error: " + "x" * 900 + "\n") * 50)) <= 3000, "")


# ------------------------------------------------------------------ browser
SITE = {"/": {"title": "Home", "csp": True}, "/signin": {"title": "Sign in", "csp": True, "form": True},
        "/tasks": {"title": "Tasks", "csp": True, "session": True}}
STEPS = [{"goto": "/signin"}, {"fill": "#email", "value": "axe@example.test"},
         {"fill": "#password", "value": "not-a-secret-fixture"}, {"click": "button[type=submit]"}, {"wait_url": "/tasks"}]


def axe_run(src, base, plan):
    d = os.path.join(E.base, "axe-%d" % len(os.listdir(E.base)))
    os.makedirs(d)
    with open(os.path.join(d, "axe-run.js"), "w") as f:
        f.write(src)
    with open(os.path.join(d, "plan.json"), "w") as f:
        json.dump(plan, f)
    log = os.path.join(d, "pw.log")
    r = subprocess.run([NODE, os.path.join(d, "axe-run.js"), base, os.path.join(d, "axe.json"), "--paths-file",
                        os.path.join(d, "plan.json")], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, MOADIX_TOOL_MODULES=FAKEPW, FAKEPW_SITE=json.dumps(SITE), FAKEPW_LOG=log))
    out = json.load(open(os.path.join(d, "axe.json"))) if os.path.exists(os.path.join(d, "axe.json")) else {}
    ev = [json.loads(x) for x in open(log).read().splitlines()] if os.path.exists(log) else []
    return r, out, ev


def test_browser():
    G = "browser"
    plan = {"paths": ["/", "/signin", "/tasks"], "public": ["/", "/signin"], "signin": {"steps": STEPS}}
    old_base = "http://%s:3000" % confined.SUT_ALIAS
    r, out, ev = axe_run(old_file("gate/exec/axe-run.js"), old_base, plan)
    f, _n, _d = X.parse_axe(json.dumps(out))
    record(G, "control: the 0.7.6 runner on http://sut.moadix.test (its flag set): the __Host- cookie is refused, the "
              "sign-in times out at /signin and /tasks is never checked (the engine run)",
           any("sign-in" in x for x in f) and any(e.get("what") == "set-cookie" and not e.get("kept") for e in ev) and
           "/signin" in json.dumps(out.get("signin")), (f, out.get("signin")))
    script = X.live_script("axe", 3000, None, ["/"])
    base = X.browser_url(3000)
    record(G, "the gate opens the app as http://sut.localhost:<port> and waits for it at that name (0.7.8: one origin)",
           base == "http://sut.localhost:3000" and " %s " % base in script and "/dev/tcp/%s/3000" % confined.APP_HOST in script,
           script)
    record(G, "the resolver rule maps exactly that name to the app's alias",
           confined.BROWSER_RULE == "MAP sut.localhost sut.moadix.test", confined.BROWSER_RULE)
    new = open(os.path.join(REPO, "gate", "exec", "axe-run.js")).read()
    r, out, ev = axe_run(new, base, dict(plan, host_rules=confined.BROWSER_RULE))
    f, _n, _d = X.parse_axe(json.dumps(out))
    tasks = next((x for x in out.get("results") or [] if x.get("path") == "/tasks"), {})
    launch = next((e for e in ev if e["what"] == "launch"), {})
    record(G, "0.7.7: with the gate's plan the runner signs in (cookie kept) and checks /tasks with the session",
           r.returncode == 0 and not f and (out.get("signin") or {}).get("ok") and tasks.get("title") == "Tasks" and
           "--host-resolver-rules=" + confined.BROWSER_RULE in launch.get("args", []), (r.stderr[-300:], f, out))
    record(G, "the ineffective --unsafely-treat-insecure-origin-as-secure flag is gone",
           "unsafely-treat-insecure-origin-as-secure" not in " ".join(launch.get("args", [])) and
           "--unsafely" not in new.replace("--unsafely-treat-insecure-origin-as-secure did not", ""), launch)
    r, out, _ev = axe_run(new, base, plan)
    record(G, "control: under .localhost without the rule the app cannot be reached (Chromium sends *.localhost to "
              "loopback)", any("ERR_CONNECTION_REFUSED" in str(x.get("error")) for x in out.get("results") or []) or
           "ERR_CONNECTION_REFUSED" in json.dumps(out), out)
    for bad in ("MAP * evil.example", "MAP sut.moadix.test evil.example", "MAP sut.localhost a,MAP x y"):
        r, out, _ev = axe_run(new, base, dict(plan, host_rules=bad))
        record(G, "hostile: a plan rule %r is refused by the runner" % bad, r.returncode == 2 and not out and
               "host rule" in r.stderr, r.stderr[-200:])
    # Lighthouse CI
    cfg = X.lhci_config(3000)
    flags = cfg["ci"]["collect"]["settings"]["chromeFlags"]
    record(G, "lhci: the config audits http://sut.localhost:3000/ and its chromeFlags carry the rule as one quoted flag",
           cfg["ci"]["collect"]["url"] == ["http://sut.localhost:3000/"] and
           "--host-resolver-rules=MAP sut.localhost sut.moadix.test" in shlex.split(flags), flags)
    s = X.live_script("lhci", 3000, None, ["/"])
    old_s = old_check_exec().live_script("lhci", 3000, None, ["/"])
    record(G, "lhci reads the gate's config file (0.7.6 named http://sut.moadix.test in --url, where a Secure cookie is "
              "refused)", "--config=/gx/lighthouserc.json" in s and "--url=" not in s and
           "--url=http://sut.moadix.test:3000/" in old_s, s)
    p = product("lhci")
    rc, out = run_gate(p, "lhci", "10a")
    lr = [c for c in calls() if c[:1] == ["run"] and "--name" in c and c[c.index("--name") + 1].endswith("-lhci")]
    record(G, "lhci (phase 10a) passes end to end through the gate and the double, with the gate's files at /gx",
           rc == 0 and lr and any("dst=/gx,readonly" in x for x in lr[-1]), out[-600:])
    p = product("axe77", FIX76)
    rc, out = run_gate(p, "axe", "8")
    ar = [c for c in calls() if c[:1] == ["run"] and "--name" in c and c[c.index("--name") + 1].endswith("-axe")]
    record(G, "axe (phase 8) on the CSP and sign-in fixture passes through the gate, opening http://sut.localhost:3000",
           rc == 0 and ar and "http://sut.localhost:3000" in " ".join(ar[-1]), out[-600:])


# ------------------------------------------------------------------ the engine suite
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite077", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    record(G, "the engine suite has a rel077 group of 2 real-engine cases, and its fixed total is 79 (0.7.8: rel078 4; 0.7.9: rel079 4; 0.8.0: rel080 3; 0.8.1: rel081 3; 0.8.2: rel082 4; 0.8.3: rel083 2)",
           es.PLAN.get("test_rel077") == ("rel077", 2) and es.TOTAL == 79, (es.PLAN.get("test_rel077"), es.TOTAL))
    src = open(p).read()
    record(G, "rel077 checks lhci's audited address and the failure summary's first errors on the real engine",
           "BROWSER_ALIAS" in src and '"first errors:" in summary' in src and "DATABASE_URL is not set" in src, "")


def main():
    try:
        for t in (test_link, test_summary, test_browser, test_engine):
            try:
                t()
            except Exception as e:  # a crashing group is a failure, never a skip
                import traceback
                record(t.__name__, "group ran to the end", False, "%s: %s\n%s" % (type(e).__name__, e,
                                                                                 traceback.format_exc()[-1500:]))
        viol = E.violations()
        record("guard", "no test read, wrote or started a real product, keychain or ~/.claude", not viol, viol)
    finally:
        for d, dirs, _f in os.walk(E.base):
            for x in dirs:
                try:
                    os.chmod(os.path.join(d, x), stat.S_IRWXU)
                except OSError:
                    pass
        E.remove()
    n = len(RESULTS)
    bad = [r for r in RESULTS if not r[2]]
    for g, name, _ok in bad:
        print("FAILED [%s] %s" % (g, name))
    print("\n%d checks, %d passed, %d failed (%d s)" % (n, n - len(bad), len(bad), time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
