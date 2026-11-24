#!/usr/bin/python3
"""0.8.0 suite: the first product's phase 9 (task-tracker MF-56 to MF-59). Written before the fix; on 0.7.9 (ff7cca6)
its fix checks fail.

    /usr/bin/python3 tests/rel080/run.py

  path      MF-57: every container keeps its image's own PATH, the gate's entries appended (0.7.9 replaced it, so the
            official postgres image found no initdb and the database exited 127); a database built FROM the official
            image starts as a live service; the 0.7.9 control fails
  logs      MF-56: when a live gate's wait for the app gives up, the evidence keeps every service container's state
            and last output, bounded and with secrets removed (0.7.9 kept only the wait line)
  trace     MF-58: a ### SEC-nnn heading in the phase 9 security report is a reference, not a second definition, so
            check-security and trace-lint agree (0.7.9: "SEC-001 is defined 2 times")
  gitleaks  MF-59: an operator-reviewed allowlist for test fixtures in product-tools.yaml, adopted with ADOPT: each entry
            names the finding's fingerprint, the path, the reason and fixture: true; it covers history findings; never
            a path outside tests/ or a fixtures directory, never a whole rule; allowlisted findings are shown in REVIEW.
            Negative: a real-looking key in src/ is never allowlisted. Real gitleaks (the pinned one, as tests/tools).
  engine    the engine suite's rel080 group (the official postgres image as a live service), and its total

Fixtures only: throwaway repos under $TMPDIR, the engine double (which now keeps a detached service's exit and output,
answers `logs` and `image inspect`, and gives a built image its base image's PATH), no network.
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

E = fixtures.Env("r80").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined  # noqa: E402

RESULTS = []
T0 = time.time()
OLD = "ff7cca6"  # 0.7.9
FIX76 = os.path.join(REPO, "tests", "fixtures", "smoke-076")
FIX80 = os.path.join(REPO, "tests", "fixtures", "smoke-080")
DBL = os.path.join(E.base, "engine-double")
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
TOOLS = os.path.expanduser("~/.cache/moadix-tools")
SD = "." + "sdlc"
PG_BIN = "/usr/lib/postgresql/17/bin"
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLQ"  # assembled so this file holds no literal key
FIXTURE_WORD = "Granite-" + "Willow-4410"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def git(p, *args):
    return subprocess.run(["/usr/bin/git", "-C", p] + list(args), capture_output=True, text=True).stdout.strip()


def old_home(files=("gate/confined.py", "gate/v1/check_exec.py")):
    """A copy of the fixture gate with 0.7.9's files (the control)."""
    h = os.path.join(E.base, "home079-" + str(abs(hash(files)) % 10000))
    if not os.path.isdir(h):
        # the gate copied; everything else (the checker and its anchors) shared, so products INIT later verify too
        os.makedirs(h)
        for n in os.listdir(E.home):
            if n == "gate":
                shutil.copytree(os.path.join(E.home, n), os.path.join(h, n), symlinks=True)
            else:
                os.symlink(os.path.join(E.home, n), os.path.join(h, n))
        for rel in files:
            with open(os.path.join(h, rel), "w") as f:
                f.write(subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:%s" % (OLD, rel)], capture_output=True,
                                       text=True).stdout)
    return h


def product(name, overlay=True, compose=None):
    """smoke-076 with the smoke-080 overlay (a database built FROM the official postgres image)."""
    p = os.path.join(E.base, name)
    shutil.copytree(FIX76, p, ignore=shutil.ignore_patterns(".claude", "product-tools.yaml", "node_modules"))
    if overlay:
        shutil.copytree(FIX80, p, dirs_exist_ok=True)
    if compose is not None:
        with open(os.path.join(p, "compose.yaml"), "w") as f:
            f.write(compose)
    subprocess.run(["/usr/bin/git", "init", "-q", p])
    E.commit(p, "fixture")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    with open(os.path.join(FIX76, "product-tools.yaml")) as f:
        E.write(p, SD + "/config/product-tools.yaml", f.read())
    return p


def run_gate(p, gate, label, home=None, **env):
    shutil.rmtree(DBL, ignore_errors=True)
    home = home or E.home
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(home, "gate", "v1", "_launch.py"),
                     os.path.join(home, "gate", "v1", "check_exec.py"), "--gate", gate, "--phase", label],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS, **env),
                    timeout=300)
    return r.returncode, r.stdout + r.stderr


def calls():
    f = os.path.join(DBL, "calls.log")
    return [json.loads(x) for x in open(f).read().splitlines() if x.strip()] if os.path.exists(f) else []


def run_call(suffix):
    """The `docker run` the gate made for the container whose name ends with suffix."""
    return next((c for c in calls() if c[:1] == ["run"] and "--name" in c and
                 re.search(suffix + "$", c[c.index("--name") + 1])), [])


def env_of(c, k):
    return next((x.split("=", 1)[1] for x in [c[i + 1] for i, a in enumerate(c) if a == "--env"] if
                 x.startswith(k + "=")), None)


def kept_log(p, out):
    """The run log the gate kept, as its output names it ("the run's log is kept at <path>")."""
    m = re.findall(r"(?:log is kept at|run log) (\S+?)\)?(?:;|\s|$)", out)
    f = os.path.join(p, m[-1]) if m else ""
    return open(f).read() if f and os.path.isfile(f) else ""


# ------------------------------------------------------------------ path (MF-57)
def test_path():
    G = "path"
    p = product("path")
    rc, out = run_gate(p, "schemathesis", "8", home=old_home())
    db = run_call("-svc-db")
    record(G, "control: on 0.7.9 the database built FROM the official postgres image gets the gate's PATH only, finds "
              "no initdb, and schemathesis FAILs (the app never listened), as in the product run",
           rc == 1 and env_of(db, "PATH") == "/usr/local/bin:/usr/bin:/bin" and "never listened" in out, out[-600:])
    merged = confined.run_path("/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:%s" % PG_BIN)
    record(G, "run_path keeps the image's own PATH in its order and appends the gate's entries it lacks",
           merged == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:%s" % PG_BIN and
           confined.run_path("/zap/:/opt/x") == "/zap/:/opt/x:/usr/local/bin:/usr/bin:/bin", merged)
    bad = [confined.run_path(x) for x in (None, "", ".:/usr/bin", "/a b:/bin", "/usr/bin::/bin", "bin:/x", "$HOME/bin")]
    record(G, "an image PATH that is missing or not a list of absolute directories is never used (the gate's PATH "
              "alone)", all(b == confined.RUN_PATH for b in bad), bad)
    record(G, "a gate service's own directories (confinement.yaml path) come first, then the image's, then the gate's",
           confined.run_path("/usr/bin:/bin", first="/opt/pg/bin") == "/opt/pg/bin:/usr/bin:/bin:/usr/local/bin", "")
    rc, out = run_gate(p, "schemathesis", "8")
    db, app, st = run_call("-svc-db"), run_call("-svc-app"), run_call("-schemathesis")
    path = (env_of(db, "PATH") or "").split(":")
    record(G, "the database's container keeps its image's PATH (with %s) and gets the gate's entries" % PG_BIN,
           PG_BIN in path and "/usr/local/bin" in path and "/bin" in path and path.index("/usr/local/sbin") == 0, path)
    record(G, "schemathesis passes with the database as a live service (0.7.9: FAIL)", rc == 0 and "PASS" in out,
           out[-800:])
    zp = product("pathzap")
    rc, out = run_gate(zp, "zap", "9")
    z = run_call("-zap")
    record(G, "a tool image keeps its own PATH too (ZAP's /zap/), the gate's entries appended",
           rc == 0 and "/zap/" in (env_of(z, "PATH") or "").split(":") and
           (env_of(z, "PATH") or "").endswith("/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"), (env_of(z, "PATH"), out[-400:]))
    insp = [c for c in calls() if c[:2] == ["image", "inspect"]]
    record(G, "the image's PATH is read from the image (image inspect), never from the product's files or the host",
           insp and all("{{json .Config.Env}}" in c for c in insp) and app and st, insp[:2])


# ------------------------------------------------------------------ logs (MF-56)
SECRET = "pw-" + "Q1w2E3r4T5y6U7i8"


def svc_env(**over):
    d = {"app": {"exit": 1, "stderr": "\n".join(["noise line %d" % i for i in range(3000)] +
                                                 ["DATABASE_URL is not set",
                                                  "connecting to postgres://app:%s@db:5432/x" % SECRET,
                                                  "password=%s" % SECRET])}}
    d.update(over)
    return json.dumps(d)


def test_logs():
    G = "logs"
    p = product("logs")
    rc, out = run_gate(p, "schemathesis", "8", home=old_home(), MOADIX_DOUBLE_SVC=svc_env())
    log = kept_log(p, out)
    record(G, "control: on 0.7.9 the app's exit and output are not in the evidence when the wait gives up",
           rc == 1 and "never listened" in out and "DATABASE_URL is not set" not in log, (rc, out[-600:], log[-400:]))
    rc, out = run_gate(p, "schemathesis", "8", MOADIX_DOUBLE_SVC=svc_env())
    log = kept_log(p, out)
    sec = log.split("--- service app", 1)[1].split("\n--- ", 1)[0] if "--- service app" in log else ""
    record(G, "the evidence names every service container's state (app exited 1; db running) and keeps the app's "
              "last output", rc == 1 and re.search(r"--- service app \(exited, exit code 1", log) and
           re.search(r"--- service db \(running", log) and "DATABASE_URL is not set" in sec, log[-1500:])
    record(G, "the service's output is bounded (the last %d lines at most) and secrets are removed" % X.LOG_LINES,
           sec and len(sec.splitlines()) <= X.LOG_LINES + 3 and SECRET not in log and "noise line 0\n" not in sec and
           "[redacted]" in sec, (len(sec.splitlines()), sec[-400:]))
    record(G, "the gate's failure line names the stopped service and its first error", rc == 1 and
           re.search(r"services: app exited 1 \(DATABASE_URL is not set", out) and SECRET not in out, out[-900:])
    rc, out = run_gate(p, "schemathesis", "8")
    log = kept_log(p, out)
    record(G, "when the app listens, no service output is added (only a failed wait keeps it)",
           rc == 0 and "--- service" not in log and not [c for c in calls() if c[:1] == ["logs"]], log[-400:])
    lp = product("logslhci")
    rc, out = run_gate(lp, "lhci", "10a", MOADIX_DOUBLE_SVC=svc_env())
    log = kept_log(lp, out)
    record(G, "every live gate keeps it (lhci: the same app error in its evidence)",
           rc == 1 and "DATABASE_URL is not set" in log and SECRET not in log, log[-600:])


# ------------------------------------------------------------------ trace (MF-58)
TM = """# Threat model

## TB-001 Browser to API

### TH-001 Session theft across TB-001

### SEC-001 Signed session cookies mitigate TH-001
- Control: signed cookies.

### SEC-002 Rate limits mitigate TH-001
- Control: rate limits.
"""
REPORT = """# Security report

### SEC-001
- **Verdict:** EVIDENCED
- **Evidence:** src/app.js:1
- **Method:** read the code

### SEC-002 Rate limits
- **Verdict:** EVIDENCED
- **Evidence:** src/app.js:1
- **Method:** read the code
"""


def trace_product(name, report, extra=None):
    p = E.repo(name, docs=())
    E.write(p, "sdlc/04-threat-model.md", TM)
    E.write(p, "sdlc/09-security-report.md", report)
    E.write(p, "src/app.js", "export const x = 1;\n")
    for rel, text in (extra or {}).items():
        E.write(p, rel, text)
    E.commit(p, "docs")
    return p


def in_home(home, code, p):
    r = subprocess.run([sys.executable, "-I", "-c", "import sys, json; sys.path[:0] = [%r, %r]\n%s" % (
        home, os.path.join(home, "gate", "v1"), code)], capture_output=True, text=True, cwd=p, timeout=120)
    return r.stdout + r.stderr


LINT = ("from gate import contract\nf, _n, d = contract.trace_lint(%r, {'phases': [], 'product_phases': []})\n"
        "print(json.dumps(f))")


def test_trace():
    G = "trace"
    p = trace_product("trace", REPORT)
    out = in_home(old_home(("gate/contract.py",)), LINT % p, p)
    record(G, "control: on 0.7.9 trace-lint fails \"SEC-001 is defined 2 times\" on the report check-security requires",
           "SEC-001 is defined 2 times" in out and "09-security-report.md" in out, out[-400:])
    out = in_home(E.home, LINT % p, p)
    fails = json.loads(out.strip().splitlines()[-1]) if out.strip().startswith("[") else [out]
    record(G, "trace-lint passes: a SEC heading in the phase 9 report is a reference, not a definition", fails == [],
           fails)
    import check_security as CS
    secs = CS.sec_ids_from_threat_model(os.path.join(p, "sdlc", "04-threat-model.md"))
    blocks = CS.blocks(open(os.path.join(p, "sdlc", "09-security-report.md")).read(), "SEC")
    record(G, "check-security still finds every SEC-ID's block in the same report", secs == ["SEC-001", "SEC-002"]
           and sorted(blocks) == secs, (secs, sorted(blocks)))
    p = trace_product("trace-dangling", REPORT + "\n### SEC-099\n- **Verdict:** EVIDENCED\n")
    out = in_home(E.home, LINT % p, p)
    record(G, "a SEC heading in the report that the threat model does not define is a dangling reference",
           "references SEC-099, which no document defines" in out, out[-400:])
    p = trace_product("trace-other", REPORT, {"sdlc/05-lld.md": "# LLD\n\n### SEC-001 Again\n- cites TH-001\n"})
    out = in_home(E.home, LINT % p, p)
    record(G, "a SEC heading in any other document is still a second definition",
           "SEC-001 is defined 2 times" in out and "05-lld.md" in out and "09-security-report" not in out, out[-400:])
    p = trace_product("trace-feature", "x\n", {"sdlc/features/f1/09-security-report.md": REPORT})
    code = ("from gate import contract\nf, _n, d = contract.trace_lint(%r, {'phases': [], 'product_phases': [], "
            "'feature': 'f1'})\nprint(json.dumps(f))" % p)
    out = in_home(E.home, code, p)
    record(G, "the same holds for a feature cycle's security report", out.strip().endswith("[]"), out[-400:])


# ------------------------------------------------------------------ gitleaks (MF-59)
def install_gitleaks():
    import toolrun
    t = toolrun.pins()["gitleaks"]
    d = "gitleaks-%s" % t["version"]
    os.makedirs(os.path.join(E.home, "tools"), exist_ok=True)
    if not os.path.exists(os.path.join(E.home, "tools", d)):
        os.symlink(os.path.join(TOOLS, d), os.path.join(E.home, "tools", d))
    return os.path.isdir(os.path.join(TOOLS, d))


def check(p, module, *args, home=None):
    home = home or E.home
    e = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes")
    e.pop("MOADIX_PHASE_DOC", None)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(home, "gate", "v1", "_launch.py"),
                     os.path.join(home, "gate", "v1", module + ".py")] + list(args), cwd=p, env=e, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


SPEC = 'const PASSWORD = "%s";\nexport const signUp = () => PASSWORD;\n' % FIXTURE_WORD


def gl_product(name, files):
    p = E.repo(name, docs=())
    for rel, text in files.items():
        E.write(p, rel, text)
    E.commit(p, "fixture with a test password")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    return p


def first_commit(p, rel):
    return git(p, "log", "--format=%H", "--diff-filter=A", "--", rel).splitlines()[-1]


def entry(fp, path, reason="the throwaway account's password the UI test signs up with", fixture="true"):
    s = "    - fingerprint: \"%s\"\n      path: %s\n" % (fp, path)
    if reason is not None:
        s += "      reason: \"%s\"\n" % reason
    if fixture is not None:
        s += "      fixture: %s\n" % fixture
    return s


def adopt(p, entries):
    E.write(p, ".sdlc-proposals/config/product-tools.yaml", "gitleaks:\n  allow:\n" + "".join(entries))
    return E.prompt(p, "ADOPT %s" % E.fresh())


def allowed_lines(out):
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("ALLOWLISTED ")]


def test_gitleaks():
    G = "gitleaks"
    if not install_gitleaks():
        record(G, "the pinned gitleaks is installed (managed/fetch_tools.py ~/.cache/moadix-tools)", False, TOOLS)
        return
    import gitleaks_allow as GA
    rel = "tests/ui/core-loop.spec.ts"
    p = gl_product("glfix", {rel: SPEC, "src/app.js": "export const x = 1;\n"})
    rc, out = check(p, "check_scanners", "--tool", "gitleaks", home=old_home(("gate/v1/check_scanners.py",)))
    record(G, "control: on 0.7.9 the test fixture password fails as [high] in the history and the tree, and nothing "
              "can allowlist it", rc == 1 and len(re.findall(r"\[high\] gitleaks:generic-api-key (history|tree) "
                                                             r"tests/ui/core-loop\.spec\.ts:1", out)) == 2, out[-600:])
    c = first_commit(p, rel)
    hist, tree = "%s:%s:generic-api-key:1" % (c, rel), "%s:generic-api-key:1" % rel
    record(G, "the gate reports each gitleaks finding with its fingerprint (gitleaks' own form: commit:path:rule:line "
              "for history, path:rule:line for the tree)", GA.fingerprint("git", c, rel, "generic-api-key", 1) == hist
           and GA.fingerprint("dir", "", rel, "generic-api-key", 1) == tree, "")
    cases = {
        "a path in src/": {"fingerprint": "src/app.js:generic-api-key:1", "path": "src/app.js",
                           "reason": "a fixture string the tests use", "fixture": True},
        "src/fixtures/ (under src/)": {"fingerprint": "src/fixtures/k.js:generic-api-key:1", "path": "src/fixtures/k.js",
                                       "reason": "a fixture string the tests use", "fixture": True},
        "a path outside tests/ and fixtures": {"fingerprint": "lib/k.js:generic-api-key:1", "path": "lib/k.js",
                                               "reason": "a fixture string the tests use", "fixture": True},
        "a whole rule (no fingerprint)": {"rule": "generic-api-key", "path": rel, "reason": "all of them are tests",
                                          "fixture": True},
        "a wildcard fingerprint": {"fingerprint": "*:generic-api-key:*", "path": rel, "reason": "all of them are tests",
                                   "fixture": True},
        "a fingerprint for another path": {"fingerprint": "src/app.js:generic-api-key:1", "path": rel,
                                           "reason": "a fixture string the tests use", "fixture": True},
        "a glob path": {"fingerprint": "tests/*:generic-api-key:1", "path": "tests/*",
                        "reason": "a fixture string the tests use", "fixture": True},
        "a path with ..": {"fingerprint": "tests/../src/a.js:generic-api-key:1", "path": "tests/../src/a.js",
                           "reason": "a fixture string the tests use", "fixture": True},
        "no fixture: true": {"fingerprint": tree, "path": rel, "reason": "a fixture string the tests use"},
        "fixture: false": {"fingerprint": tree, "path": rel, "reason": "a fixture string the tests use", "fixture": False},
        "no reason": {"fingerprint": tree, "path": rel, "fixture": True},
        "a one-word reason": {"fingerprint": tree, "path": rel, "reason": "test", "fixture": True},
        "an unknown key": {"fingerprint": tree, "path": rel, "reason": "a fixture string the tests use", "fixture": True,
                           "paths": ["src/"]},
    }
    wrong = [k for k, v in cases.items() if not GA.problems([v])]
    good = {"fingerprint": hist, "path": rel, "reason": "a fixture string the tests use", "fixture": True}
    record(G, "an entry is refused unless it names one finding's fingerprint, its path under tests/ or a fixtures "
              "directory (never src/), a reason and fixture: true (%d cases)" % len(cases),
           not wrong and not GA.problems([good]) and not GA.problems([dict(good, path="test/fixtures/a.json",
                                                                               fingerprint="test/fixtures/a.json:x:2")]),
           wrong)
    ctx = adopt(p, [entry("src/app.js:generic-api-key:1", "src/app.js")])
    record(G, "ADOPT refuses an allowlist entry for a path in src/; nothing is adopted",
           "NOT recorded" in ctx and "src/app.js" in ctx and
           not os.path.exists(os.path.join(p, SD, "config", "product-tools.yaml")), ctx[-300:])
    shutil.rmtree(os.path.join(p, ".sdlc-proposals"), ignore_errors=True)
    ctx = adopt(p, [entry(hist, rel), entry(tree, rel)])
    record(G, "ADOPT records a valid allowlist (one history and one tree entry)", "recorded" in ctx and
           os.path.exists(os.path.join(p, SD, "config", "product-tools.yaml")), ctx[-300:])
    rc, out = check(p, "check_scanners", "--tool", "gitleaks")
    al = allowed_lines(out)
    record(G, "check-gitleaks passes: the adopted entries allowlist the fixture's history and tree findings",
           rc == 0 and "[high]" not in out, out[-800:])
    record(G, "each allowlisted finding is listed (fingerprint, path, reason) for REVIEW",
           len(al) == 2 and any(hist in x for x in al) and any(x.startswith("ALLOWLISTED %s " % tree) for x in al) and
           all("throwaway account" in x for x in al), al)
    from gate import validation
    data = {"verdict": "pass", "results": [{"validator": "check-gitleaks", "result": "pass", "first_line": "x",
                                            "output": out}]}
    data["allowlisted"] = validation.allowlisted(data["results"])
    summ = " ".join(validation.summary(data))
    record(G, "REVIEW's summary shows the allowlisted findings (validate.py collects them from the validator's output)",
           "Allowlisted test-fixture findings" in summ and hist in summ and tree in summ, summ[-500:])
    vsrc = open(os.path.join(E.home, "gate", "validate.py")).read()
    record(G, "validate.py stores them with the result, and ALLOWLISTED lines are never the validator's first line",
           'allowed += validation.allowlisted(' in vsrc and '"allowlisted": allowed' in vsrc and '"ALLOWLISTED "' in vsrc, "")
    # an edited fixture is a new finding: the old fingerprint no longer matches it
    E.write(p, rel, "\n" + SPEC)
    E.commit(p, "move the password down a line")
    rc, out = check(p, "check_scanners", "--tool", "gitleaks")
    record(G, "a fingerprint allowlists exactly one finding: the same password on another line (tree and new "
              "history) fails again", rc == 1 and re.search(r"\[high\] gitleaks:generic-api-key tree "
                                                            r"tests/ui/core-loop\.spec\.ts:2", out) and
           len(allowed_lines(out)) == 1, out[-800:])
    # negative: a real-looking key in src/
    k = gl_product("glsrc", {rel: SPEC, "src/aws.js": "const k = '%s';\n" % FAKE_AWS})
    ck = first_commit(k, "src/aws.js")
    ctx = adopt(k, [entry("%s:src/aws.js:aws-access-token:1" % ck, "src/aws.js"),
                    entry("src/aws.js:aws-access-token:1", "src/aws.js")])
    record(G, "negative: ADOPT refuses to allowlist a real-looking key in src/ (history or tree)",
           "NOT recorded" in ctx and "src/aws.js" in ctx, ctx[-300:])
    shutil.rmtree(os.path.join(k, ".sdlc-proposals"), ignore_errors=True)
    E.write(k, SD + "/config/product-tools.yaml", "gitleaks:\n  allow:\n" + entry("src/aws.js:aws-access-token:1",
                                                                                     "src/aws.js") +
            entry("tests/aws.js:aws-access-token:1", "tests/aws.js"))
    rc, out = check(k, "check_scanners", "--tool", "gitleaks")
    record(G, "negative: written past ADOPT, the entry is still refused at scan time and the key fails as [high]",
           rc == 1 and re.search(r"\[high\] gitleaks:aws-access-token (history|tree) src/aws\.js:1", out) and
           not [x for x in allowed_lines(out) if "aws" in x], out[-800:])
    record(G, "negative: an allowlist that was not adopted (product-tools.yaml not as ADOPT recorded it) is not "
              "applied, and the gate says so", rc == 1 and "not adopted" in out, out[-800:])
    ctx = adopt(k, [entry("tests/aws.js:aws-access-token:1", "tests/aws.js")])
    rc, out = check(k, "check_scanners", "--tool", "gitleaks")
    record(G, "negative: an adopted tests/ entry never covers the key in src/ (same rule and line, another path)",
           "recorded" in ctx and rc == 1 and re.search(r"\[high\] gitleaks:aws-access-token tree src/aws\.js:1", out) and
           re.search(r"\[high\] gitleaks:aws-access-token history src/aws\.js:1", out) and not allowed_lines(out),
           out[-800:])


# ------------------------------------------------------------------ engine
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite080", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    text = open(p).read()
    record(G, "the engine suite has a rel080 group (the official postgres image as a live service), and its total is 77 (0.8.1: rel081 3; 0.8.2: rel082 4)",
           es.PLAN.get("test_rel080") == ("rel080", 3) and es.TOTAL == 77 and "test_rel080, (node,)" in text,
           (es.PLAN.get("test_rel080"), es.TOTAL))
    body = text.split("def test_rel080", 1)[1].split("\n# ", 1)[0] if "def test_rel080" in text else ""
    db = open(os.path.join(FIX80, "db.Dockerfile")).read()
    record(G, "it runs schemathesis on smoke-080, keeps a stopped app's output, and shows the official image exits 127 "
              "under the gate's old PATH", "smoke080_product" in body and "DATABASE_URL is not set" in body and
           "initdb: command not found" in body and confined.image("postgres") in db, body[:300])


def main():
    try:
        for t in (test_path, test_logs, test_trace, test_gitleaks, test_engine):
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
