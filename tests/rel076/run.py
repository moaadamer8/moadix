#!/usr/bin/python3
"""0.7.6 suite: the defects that stopped the executing gates in phase 8 of the first full product run
(task-tracker, size S), through the engine double and a Playwright double. Each group was written before its
fix and failed on 0.7.5.

    /usr/bin/python3 tests/rel076/run.py

Fixtures only: throwaway repos under $TMPDIR, the stub checker, the engine double (no Docker), the Playwright
double (no browser), no network. The real-engine cases are group rel076 of tests/confined-engine.

  proxy     MF-54: a live gate with build.network: registry starts the install proxy and the build proxy; they
            had one name, so the engine refused the second and the gate ended UNKNOWN. Each now has its own
            name and is removed when its step ends, and on every other exit path by the run's label
  stryker   MF-53: Stryker's sandbox resolves the product's packages (its temporary folder is inside the work
            folder, whose node_modules link Node finds by walking up); MF-51: the stryker gate gets the same
            gate-started services (tests.services: postgres) and DATABASE_URL as the tests gate
  axe       MF-49: axe-core is evaluated through the browser automation (a DevTools evaluation, which the
            page's Content-Security-Policy does not govern), never as an inline script tag, and the policy is
            not bypassed; MF-50: a product declares a sign-in step for the axe run (axe.signin) and the paths
            visited without the session (axe.public); a designed screen with no URL is declared as checked
            another way (axe.checked_elsewhere) instead of failing
  trace     MF-46: check-traceability writes its generated matrix under the gate's cache, never into a later
            phase's path; a leftover sdlc/08-traceability.md (0.7.5) no longer blocks the clean-tree check or a
            verifier launch
  stale     a gate run's objects carry the gate's owner label and the gate process's pid; the next run removes
            what an earlier gate run left (its process is gone, or a pre-0.7.6 gate run), and nothing else; a
            gate stopped with SIGTERM still removes its run
  engine    the engine suite carries the real-engine smoke cases (group rel076) and its fixed total
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r76").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined, validation, verify  # noqa: E402

RESULTS = []
T0 = time.time()
SMOKE = os.path.join(REPO, "tests", "fixtures", "smoke")
FIX76 = os.path.join(REPO, "tests", "fixtures", "smoke-076")
DBL = os.path.join(E.base, "engine-double")
DOUBLE = os.path.join(E.shim, "engine-double")
SD = "." + "sdlc"
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
PG = confined.image("postgres")
FAKEPW = os.path.join(REPO, "tests", "lib", "fakepw")
RUNNER = os.path.join(REPO, "gate", "exec", "axe-run.js")
NODE = shutil.which("node") or "/opt/homebrew/bin/node"
# 0.7.7: the browser gates open the app under .localhost, mapped to its alias by a resolver rule in the plan
BASE_URL = "http://%s:3000" % confined.BROWSER_ALIAS
OLD_URL = "http://%s:3000" % confined.SUT_ALIAS  # what the 0.7.5 runner was given
RULE = confined.BROWSER_RULE
OLD = "33b8e32"  # 0.7.5


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def product(name, fixture=SMOKE, pt=None):
    p = os.path.join(E.base, name)
    shutil.copytree(fixture, p, ignore=shutil.ignore_patterns(".claude", "product-tools.yaml", "node_modules"))
    subprocess.run(["/usr/bin/git", "init", "-q", p])
    E.commit(p, "fixture")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    if pt is None:
        with open(os.path.join(fixture, "product-tools.yaml")) as f:
            pt = f.read()
    E.write(p, SD + "/config/product-tools.yaml", pt)
    return p


def run_gate(p, gate, label, **extra):
    shutil.rmtree(DBL, ignore_errors=True)
    return run_gate_keep(p, gate, label, **extra)


def run_gate_keep(p, gate, label, **extra):
    """Run the gate without clearing the double's state first (the stale group seeds it)."""
    env = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS, **extra)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", gate, "--phase", label],
                    cwd=p, env=env, timeout=300)
    return r.returncode, r.stdout + r.stderr


def calls():
    f = os.path.join(DBL, "calls.log")
    return [json.loads(x) for x in open(f).read().splitlines() if x.strip()] if os.path.exists(f) else []


def dstate():
    try:
        with open(os.path.join(DBL, "state.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"containers": {}, "volumes": {}, "networks": {}}


def name_of(c):
    return c[c.index("--name") + 1] if "--name" in c else ""


def runs():
    return [c for c in calls() if c[:1] == ["run"]]


# ------------------------------------------------------------------ proxy (MF-54)
def test_proxy():
    G = "proxy"
    os.makedirs(DBL, exist_ok=True)
    first = subprocess.run([DOUBLE, "run", "-d", "--name", "moadix-r76c-proxy", "--label", "moadix.run=r76c",
                            "--network", "none", confined.image("python"), "true"], capture_output=True,
                           env=E.env(MOADIX_DOUBLE_DIR=DBL))
    again = subprocess.run([DOUBLE, "run", "-d", "--name", "moadix-r76c-proxy", "--label", "moadix.run=r76c",
                            "--network", "none", confined.image("python"), "true"], capture_output=True,
                           env=E.env(MOADIX_DOUBLE_DIR=DBL))
    record(G, "control: the double refuses a second container with a name in use, as the engine does (125)",
           first.returncode == 0 and again.returncode == 125 and b"already in use" in again.stderr, again.stderr)
    p = product("proxy", FIX76)
    rc, out = run_gate(p, "schemathesis", "8")
    record(G, "schemathesis (phase 8) with build.network: registry passes end to end (0.7.5: UNKNOWN, the build proxy's "
              "name was the install proxy's)", rc == 0 and "UNKNOWN" not in out, out[-900:])
    proxies = [name_of(c) for c in runs() if "/p/egress_proxy.py" in c]
    # 0.7.9: the fixture builds two services (app and worker), each its own step with its own build proxy
    record(G, "three proxies started (install, and one per built service), each under its own name",
           len(proxies) == 3 and len(set(proxies)) == 3, proxies)
    rms = [c for c in calls() if c[:2] == ["rm", "-f"]]
    own = [[x for x in calls() if x[:2] == ["ps", "-aq"] and "name=^/%s$" % n in x] for n in proxies]
    record(G, "each proxy is removed as soon as its step ends (looked up by its own name and the run's label)",
           len(proxies) == 3 and all(own) and len(rms) >= 3, (proxies, own))
    left = [n for n, v in dstate()["containers"].items()] + list(dstate()["networks"]) + list(dstate()["volumes"])
    record(G, "nothing the run created is left afterwards (containers, networks, volumes)", not left, left)
    # a refused build (an exit path before the scan): the build proxy and everything else still go
    rc, out = run_gate(p, "schemathesis", "8", MOADIX_DOUBLE_BUILD_FAIL="1")
    left = [n for n, v in dstate()["containers"].items()] + list(dstate()["networks"]) + list(dstate()["volumes"])
    bproxy = [name_of(c) for c in runs() if "/p/egress_proxy.py" in c]
    record(G, "a failed build fails the gate and still removes both proxies and the rest of the run",
           rc == 1 and len(bproxy) == 2 and not left, (rc, bproxy, left, out[-400:]))


# ------------------------------------------------------------------ stryker (MF-53, MF-51)
def resolves_from_sandbox(temp_dir_name):
    """Node's resolution, as in the gate's run: the product's packages are in /deps/product/node_modules, the work
    folder /tmp/work links node_modules to them, and Stryker copies the project (without node_modules: the
    0.7.5 engine run shows it made no link) into <tempDirName>/sandbox-x, where Vitest's bundled configuration
    imports vitest. Simulated under a fake root; True when the import resolves."""
    root = os.path.join(E.base, "noderes-%d" % len(os.listdir(E.base)))
    deps = os.path.join(root, "deps", "product", "node_modules", "vitest")
    os.makedirs(deps)
    with open(os.path.join(deps, "package.json"), "w") as f:
        json.dump({"name": "vitest", "version": "0.0.0", "type": "module", "exports": {".": "./index.js"}}, f)
    with open(os.path.join(deps, "index.js"), "w") as f:
        f.write("export const ok = 1;\n")
    work = os.path.join(root, "tmp", "work")
    os.makedirs(work)
    os.symlink(os.path.join(root, "deps", "product", "node_modules"), os.path.join(work, "node_modules"))
    tmp = temp_dir_name if temp_dir_name.startswith("/") else os.path.join("/tmp/work", temp_dir_name)  # noqa: S108
    box = os.path.join(root, tmp.lstrip("/"), "sandbox-x", "tests")
    os.makedirs(box)
    cfg = os.path.join(box, "vitest.config.mjs.timestamp-1-x.mjs")
    with open(cfg, "w") as f:
        f.write("import { ok } from 'vitest';\nconsole.log('resolved', ok);\n")
    r = subprocess.run([NODE, cfg], capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and "resolved 1" in r.stdout, r.stderr


def test_stryker():
    G = "stryker"
    old = subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:gate/v1/check_exec.py" % OLD], capture_output=True,
                         text=True).stdout
    old_dir = re.search(r"--tempDirName (\S+)", old).group(1)
    ok, err = resolves_from_sandbox(old_dir)
    record(G, "control: from 0.7.5's temporary folder (%s) Node cannot find vitest (the task-tracker error)" % old_dir,
           not ok and "Cannot find package 'vitest'" in err, err[-300:])
    s = X.tool_script("stryker", None, {})
    m = re.search(r"--tempDirName (\S+)", s)
    ok, err = (resolves_from_sandbox(m.group(1)) if m else (False, "no --tempDirName in %s" % s))
    record(G, "MF-53: from the gate's temporary folder Stryker's sandbox resolves the product's packages "
              "(through the work folder's node_modules link)", ok, (m and m.group(1), err[-300:]))
    pt = open(os.path.join(FIX76, "product-tools.yaml")).read()
    p = product("stryker", FIX76, pt)
    rc, out = run_gate(p, "stryker", "8")
    sv = next((c for c in runs() if "-d" in c and PG in c), [])
    st = next((c for c in runs() if name_of(c).endswith("-stryker")), [])
    net = st[st.index("--network") + 1] if "--network" in st else ""
    record(G, "MF-51: with tests.services: [postgres] the stryker gate starts the gate's PostgreSQL service and passes",
           rc == 0 and sv and "--network-alias" in sv and "postgres.moadix.test" in sv, out[-600:] + " ".join(sv)[-300:])
    record(G, "and Stryker runs on the service network with DATABASE_URL, as the tests gate does",
           st and net.endswith("-svc") and "DATABASE_URL=postgres://moadix@postgres.moadix.test:5432/test" in st,
           " ".join(st)[-600:])
    p2 = product("strykernosvc", FIX76, pt.replace("  services: [postgres]\n", ""))
    rc, out = run_gate(p2, "stryker", "8")
    st = next((c for c in runs() if name_of(c).endswith("-stryker")), [])
    record(G, "without services the stryker run has no network and no service (unchanged)",
           rc == 0 and st and st[st.index("--network") + 1] == "none" and not [c for c in runs() if PG in c], out[-400:])


# ------------------------------------------------------------------ axe (MF-49, MF-50)
SITE = {"/": {"title": "Home", "csp": True}, "/signin": {"title": "Sign in", "csp": True, "form": True},
        "/tasks": {"title": "Tasks", "csp": True, "session": True}}
STEPS = [{"goto": "/signin"}, {"fill": "#email", "value": "axe@example.test"},
         {"fill": "#password", "value": "not-a-secret-fixture"}, {"click": "button[type=submit]"}, {"wait_url": "/tasks"}]


def axe_run(runner_src, plan, site=None, base=None):
    d = os.path.join(E.base, "axe-%d" % len(os.listdir(E.base)))
    os.makedirs(d)
    runner = os.path.join(d, "axe-run.js")
    with open(runner, "w") as f:
        f.write(runner_src)
    with open(os.path.join(d, "plan.json"), "w") as f:
        json.dump(plan, f)
    log = os.path.join(d, "pw.log")
    r = subprocess.run([NODE, runner, base or BASE_URL, os.path.join(d, "axe.json"), "--paths-file", os.path.join(d, "plan.json")],
                       capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, MOADIX_TOOL_MODULES=FAKEPW, FAKEPW_SITE=json.dumps(site or SITE), FAKEPW_LOG=log))
    out = json.load(open(os.path.join(d, "axe.json"))) if os.path.exists(os.path.join(d, "axe.json")) else {}
    events = [json.loads(x) for x in open(log).read().splitlines()] if os.path.exists(log) else []
    return r, out, events


def test_axe():
    G = "axe"
    old = subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:gate/exec/axe-run.js" % OLD], capture_output=True,
                         text=True).stdout
    new = open(RUNNER).read()
    _r, out, _ev = axe_run(old, ["/", "/signin"], base=OLD_URL)
    f, _n, _d = X.parse_axe(json.dumps(out))
    record(G, "control: the 0.7.5 runner cannot check a page with a strict CSP (the inline script tag is refused)",
           len(f) == 2 and all("could not be checked" in x and "Content Security Policy" in x for x in f), f)
    r, out, ev = axe_run(new, {"paths": ["/", "/signin"], "host_rules": RULE})
    f, _n, _d = X.parse_axe(json.dumps(out))
    record(G, "MF-49: the runner checks every page of a strict-CSP app (axe evaluated by the browser automation)",
           r.returncode == 0 and not f and len(out.get("results") or []) == 2 and
           sum(1 for e in ev if e["what"] == "axe.run") == 2, (r.stderr[-300:], f, out))
    record(G, "it never adds a script tag and never bypasses the page's policy (the page's inline canary did not run)",
           not [e for e in ev if e["what"] == "addScriptTag"] and
           not [e for e in ev if e["what"] == "newContext" and (e.get("opts") or {}).get("bypassCSP")] and
           all(x.get("title") not in ("CSP-BYPASSED", None) for x in out.get("results") or []), (ev, out))
    record(G, "the runner names no addScriptTag and no bypassCSP", "addScriptTag" not in new and "bypassCSP" not in
           new.replace("never bypassCSP", ""), "")
    plan = {"paths": ["/", "/signin", "/tasks"], "public": ["/", "/signin"], "signin": {"steps": STEPS}, "host_rules": RULE}
    r, out, ev = axe_run(new, plan)
    f, n, data = X.parse_axe(json.dumps(out))
    tasks = next((x for x in out.get("results") or [] if x.get("path") == "/tasks"), {})
    record(G, "MF-50: with axe.signin the runner signs in once and visits /tasks with the session, landing on /tasks",
           r.returncode == 0 and not f and (out.get("signin") or {}).get("ok") and tasks.get("session") is True and
           (tasks.get("final") or "").endswith("/tasks") and tasks.get("title") == "Tasks", (r.stderr[-300:], f, out))
    launch = next((e for e in ev if e["what"] == "launch"), {})
    record(G, "Chromium opens the app under .localhost through the plan's resolver rule (0.7.7: so the __Host- Secure "
              "session cookie is kept over http)", "--host-resolver-rules=%s" % RULE in (launch.get("args") or []), launch)
    pub = [x for x in out.get("results") or [] if x.get("path") in ("/", "/signin")]
    record(G, "axe.public paths are visited without the session", len(pub) == 2 and all(x.get("session") is False
                                                                                         for x in pub), pub)
    record(G, "the evidence holds no cookie value", "__Host-session" not in json.dumps(out) or
           '"value"' not in json.dumps(out), out.get("signin"))
    bad = dict(plan, signin={"steps": STEPS[:1] + [{"fill": "#email", "value": "someone@example.test"}] + STEPS[2:]})
    r, out, _ev = axe_run(new, bad)
    f, _n, _d = X.parse_axe(json.dumps(out))
    record(G, "a sign-in that does not reach its wait_url fails the gate, naming the sign-in; the session pages are not "
              "checked as the sign-in page", any("sign-in" in x for x in f) and any("/tasks" in x for x in f), f)
    landed = {"tool": "axe-core", "signin": {"ok": True, "page": "/signin", "cookies": 1}, "results": [
        {"url": BASE_URL + "/tasks", "path": "/tasks", "session": True, "final": BASE_URL + "/signin", "title": "Sign in",
         "error": None, "violations": []}]}
    f, _n, _d = X.parse_axe(json.dumps(landed))
    record(G, "a session page that lands on the sign-in page fails (the session did not hold)",
           any("landed on" in x and "/signin" in x for x in f), f)
    # the plan the gate hands the runner (validated before the engine is called)
    pt = {"axe": {"public": ["/signin"], "signin": {"steps": STEPS}}}
    doc = X.axe_plan(pt, ["/", "/tasks"])
    record(G, "the gate's plan file carries the paths, the public paths and the sign-in steps",
           doc == {"paths": ["/", "/tasks"], "public": ["/signin"], "signin": {"steps": STEPS}}, doc)
    hostile = [
        ("a goto that leaves the app", [{"goto": "http://evil.example/"}], "app-relative"),
        ("an unknown action", [{"goto": "/signin"}, {"eval": "alert(1)"}], "not one of"),
        ("a value that looks like a secret", [{"goto": "/signin"}, {"fill": "#t", "value": "ghp_" + "A1b2C3d4E5" * 3}],
         "secret"),
        ("a selector with a line break", [{"goto": "/signin"}, {"click": "a\nb"}], "selector"),
        ("a first step that is not a goto", [{"click": "button"}], "goto"),
        ("too many steps", [{"goto": "/signin"}] * 21, "at most 20"),
    ]
    for what, steps, needle in hostile:
        try:
            X.axe_plan({"axe": {"signin": {"steps": steps}}}, ["/"])
            why = ""
        except confined.Refused as e:
            why = str(e)
        record(G, "hostile: %s is refused before the engine is called" % what, needle in why, why)
    # rows without a URL declared as checked another way
    q = product("axeurl", FIX76)
    st = X.state.current_state(q)[0]
    pt = X.toolrun.product_tools(q)
    notes = []
    paths, probs = X.axe_urls(q, st, pt, "8", notes)
    record(G, "MF-50: a designed screen with no URL declared in axe.checked_elsewhere is not a failure, and is named",
           not probs and paths == ["/", "/signin", "/tasks"] and any("Edit task" in x and "checked elsewhere" in x
                                                                     for x in notes), (paths, probs, notes))
    pt2 = json.loads(json.dumps(pt))
    pt2["axe"]["checked_elsewhere"] = []
    _p, probs = X.axe_urls(q, st, pt2, "8")
    record(G, "an undeclared row with no URL still fails and names the row",
           any("Edit task" in x and "no URL" in x for x in probs), probs)
    pt2["axe"]["checked_elsewhere"] = [{"screen": "Edit task", "state": "default", "how": "by hand"},
                                       {"screen": "Nowhere", "state": "default", "how": "a declaration that matches no row"}]
    _p, probs = X.axe_urls(q, st, pt2, "8")
    record(G, "a declaration needs a reason of four words or more, and one that matches no URL-less designed row fails",
           any("Edit task" in x and "four words" in x for x in probs) and any("Nowhere" in x and "matches no" in x
                                                                              for x in probs), probs)
    rc, out = run_gate(q, "axe", "8")
    gx = [c for c in calls() if c[:1] == ["cp"] and "-" in c]
    record(G, "axe (phase 8) on the CSP and sign-in fixture passes end to end through the gate and the double",
           rc == 0 and "checked elsewhere" in out and gx, out[-900:])


# ------------------------------------------------------------------ trace (MF-46)
def traceability(p):
    return fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                        os.path.join(E.home, "gate", "v1", "check_traceability.py")],
                       cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes"), timeout=120)


def test_trace():
    G = "trace"
    p = product("trace", FIX76)
    r = traceability(p)
    head, changed = validation.tree_state(p)
    record(G, "MF-46: check-traceability (no test results yet, as after REOPEN 7) leaves the working tree clean",
           not changed and not verify.dirty(p) and not os.path.exists(os.path.join(p, "sdlc", "08-traceability.md")),
           (changed, r.stdout[-400:], r.stderr[-300:]))
    cache = os.path.join(p, SD, "cache", "08-traceability.md")
    record(G, "it writes the generated matrix under the gate's cache", os.path.exists(cache) and
           "Do not hand-edit" in open(cache).read(), r.stdout[-400:])
    # 0.7.5 wrote it into sdlc/: a leftover copy (untracked, the gate's own header) must not block anything
    legacy = os.path.join(p, "sdlc", "08-traceability.md")
    if os.path.exists(cache):
        shutil.copy(cache, legacy)
    record(G, "a leftover sdlc/08-traceability.md (written by 0.7.5) does not block the clean-tree check or a verifier",
           not validation.tree_state(p)[1] and not verify.dirty(p), (validation.tree_state(p), verify.dirty(p)))
    E.write(p, "sdlc/notes.md", "an uncommitted change\n")
    record(G, "control: any other uncommitted file still blocks", verify.dirty(p) == ["sdlc/notes.md"], verify.dirty(p))
    os.unlink(os.path.join(p, "sdlc", "notes.md"))
    E.write(p, "sdlc/08-traceability.md", "# hand-written\n")
    record(G, "control: a file at that path that is not the gate's generated matrix still blocks",
           verify.dirty(p) == ["sdlc/08-traceability.md"], verify.dirty(p))
    os.unlink(os.path.join(p, "sdlc", "08-traceability.md"))


# ------------------------------------------------------------------ stale gate runs
def dead_pid():
    p = subprocess.Popen(["/usr/bin/true"])
    p.wait()
    return p.pid


def seed(objs):
    """Objects an earlier run left, in the double's state: (kind, name, labels)."""
    shutil.rmtree(DBL, ignore_errors=True)
    os.makedirs(DBL)
    s = {"containers": {}, "volumes": {}, "networks": {}, "labels": {}}
    for kind, name, labels in objs:
        run = "moadix.run=%s" % labels["moadix.run"] if "moadix.run" in labels else None
        if kind == "c":
            s["containers"][name] = {"label": run, "labels": labels, "mounts": {}}
        elif kind == "v":
            s["volumes"][name] = run
            s["labels"]["v:" + name] = labels
        else:
            s["networks"][name] = run
            s["labels"]["n:" + name] = labels
    with open(os.path.join(DBL, "state.json"), "w") as f:
        json.dump(s, f)


def test_stale():
    G = "stale"
    p = product("stale", SMOKE)
    dead, live = dead_pid(), os.getpid()
    gate = {"moadix.owner": "gate", "moadix.started": str(int(time.time()) - 60)}
    seed([("c", "moadix-xdead000001-svc-postgres", dict(gate, **{"moadix.run": "xdead000001", "moadix.pid": str(dead)})),
          ("n", "moadix-xdead000001-svc", dict(gate, **{"moadix.run": "xdead000001", "moadix.pid": str(dead)})),
          ("v", "moadix-xdead000001-out", dict(gate, **{"moadix.run": "xdead000001", "moadix.pid": str(dead)})),
          ("c", "moadix-x0123456789-svc-app", {"moadix.run": "x0123456789"}),
          ("c", "moadix-xlive000001-tests", dict(gate, **{"moadix.run": "xlive000001", "moadix.pid": str(live)})),
          ("c", "moadix-es0123456789-x", {"moadix.run": "es0123456789"}),
          ("c", "someone-else", {"com.docker.compose.project": "other"})])
    rc, out = run_gate_keep(p, "tsc", "7")
    s = dstate()
    have = set(s["containers"]) | set(s["networks"]) | set(s["volumes"])
    record(G, "the next gate run removes what a gate run whose process is gone left (container, network, volume)",
           rc == 0 and not have & {"moadix-xdead000001-svc-postgres", "moadix-xdead000001-svc", "moadix-xdead000001-out"},
           (out[-500:], sorted(have)))
    record(G, "and a container a pre-0.7.6 gate run left (the gate's x<10 hex> run label, no pid)",
           "moadix-x0123456789-svc-app" not in have, sorted(have))
    record(G, "it keeps a gate run whose process is alive, the engine suite's objects and every unlabelled object",
           {"moadix-xlive000001-tests", "moadix-es0123456789-x", "someone-else"} <= have, sorted(have))
    record(G, "and says what it removed", "earlier gate run" in out and "xdead000001" in out, out[-600:])
    created = [c for c in calls() if c[:2] in (["volume", "create"], ["network", "create"]) or
               (c[:1] in (["run"], ["create"]) and "getent" not in c)]
    unlabelled = [c[:4] for c in created if not ("moadix.owner=gate" in c and any(x.startswith("moadix.pid=") for x in c))]
    record(G, "every object a gate run creates carries the gate's owner label and its pid", created and not unlabelled,
           unlabelled)
    # a gate stopped with SIGTERM (the hook's timeout, the operator) still removes its run
    shutil.rmtree(DBL, ignore_errors=True)
    env = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS, MOADIX_DOUBLE_SLEEP="30")
    proc = subprocess.Popen([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                             os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", "tsc", "--phase", "7"],
                            cwd=p, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(200):
        if any(name_of(c).endswith("-tsc") for c in runs()):
            break
        time.sleep(0.1)
    time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    try:
        out = proc.communicate(timeout=60)[0].decode(errors="replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        out = "(did not stop)"
    s = dstate()
    left = [n for n in list(s["containers"]) + list(s["networks"]) + list(s["volumes"])]
    record(G, "a gate stopped with SIGTERM removes everything its run created, and does not pass",
           proc.returncode not in (0, None) and not left, (proc.returncode, left, out[-400:]))


# ------------------------------------------------------------------ the engine suite
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite076", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    plan = es.PLAN.get("test_rel076")
    record(G, "the engine suite has a rel076 group of 7 real-engine cases on the smoke-076 fixture",
           plan == ("rel076", 7) and "smoke-076" in open(p).read(), plan)
    record(G, "its fixed total is 73 (0.7.5: 50, plus the 7; 0.7.7: rel077 2; 0.7.8: rel078 4; 0.7.9: rel079 4; 0.8.0: rel080 3; 0.8.1: rel081 3)", es.TOTAL == 73, es.TOTAL)
    src = open(p).read()
    for needle, what in (("schemathesis", "MF-54"), ("NoCoverage", "MF-51"), ("ERR_MODULE_NOT_FOUND", "MF-53"),
                         ("CSP-BYPASSED", "MF-49"), ("checked elsewhere", "MF-50"), ("08-traceability", "MF-46"),
                         ("moadix.pid", "stale")):
        record(G, "the real-engine group runs the %s case end to end" % what, needle in src, needle)
    fx = open(os.path.join(FIX76, "src", "server.js")).read()
    record(G, "the fixture app sends a strict policy (script-src 'self') and signs in with a __Host- Secure cookie",
           "script-src 'self'" in fx and "__Host-session" in fx and "Secure" in fx, "")


def main():
    try:
        for t in (test_proxy, test_stryker, test_axe, test_trace, test_stale, test_engine):
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
