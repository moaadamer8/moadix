#!/usr/bin/python3
"""0.7.5 suite: the two failures of the 0.7.4 engine run, through the engine double, which since 0.7.5
also refuses a command that is not on the run's PATH in its image.

    /usr/bin/python3 tests/rel075/run.py

Fixtures only: throwaway repos under $TMPDIR, the stub checker, the engine double (no Docker), no network.

  secrets   the engine suite's secrets check is a property (tests/lib/env_leak.py), not a string: the 0.7.4 run's
            output passes it (nothing of the host), and outputs with a host variable, the canary, a host file,
            a host value under a runner name or a token fail it; the old exact-string assertion is gone
  path      the runner's PATH replaces the image's; the double refuses a bare command whose directory is not on
            it (the 0.7.4 ZAP invocation fails with 127, as on the real engine); the gate names zap-baseline.py
            by its absolute path, runs from /tmp, and the ZAP run passes end to end
  wait      the live wait writes its note to the gate's own output folder and exits 3 even when the note cannot
            be written (ZAP has no /out: the 0.7.4 loop never exited)
  services  the postgres test service gets the image's own tool directory on its PATH from the gate's
            configuration (0.7.4 left initdb off PATH; the double refuses that), never from the product
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import engine_double  # noqa: E402
import env_leak  # noqa: E402
import fixtures  # noqa: E402

E = fixtures.Env("r75").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined  # noqa: E402

RESULTS = []
T0 = time.time()
SMOKE = os.path.join(REPO, "tests", "fixtures", "smoke")
DBL = os.path.join(E.base, "engine-double")
DOUBLE = os.path.join(E.shim, "engine-double")
SD = "." + "sdlc"
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
ZAP = confined.image("zap")
PG = confined.image("postgres")
RUNNER = {"PATH": confined.RUN_PATH, "HOME": "/tmp", "LANG": "C.UTF-8", "CI": "1", "TZ": "UTC"}  # noqa: S108
NODE_OWN = ["PATH", "NODE_VERSION", "YARN_VERSION"]  # the pinned node image's Config.Env names
CANARY = "moadix-canary-0123456789abcdef"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def product(name, pt=None):
    p = os.path.join(E.base, name)
    shutil.copytree(SMOKE, p, ignore=shutil.ignore_patterns(".claude", "product-tools.yaml"))
    subprocess.run(["/usr/bin/git", "init", "-q", p])
    E.commit(p, "smoke fixture")
    E.init(p, name + "fx")
    E.commit(p, "init")
    if pt is None:
        with open(os.path.join(SMOKE, "product-tools.yaml")) as f:
            pt = f.read()
    E.write(p, SD + "/config/product-tools.yaml", pt)
    return p


def run_gate(p, gate, label):
    shutil.rmtree(DBL, ignore_errors=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", gate, "--phase", label],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS),
                    timeout=300)
    return r.returncode, r.stdout + r.stderr


def calls():
    f = os.path.join(DBL, "calls.log")
    return [json.loads(x) for x in open(f).read().splitlines() if x.strip()] if os.path.exists(f) else []


def double(args):
    return subprocess.run([DOUBLE] + args, capture_output=True, env=E.env(MOADIX_DOUBLE_DIR=DBL))


def section_out(env_lines, files=("/home:", "node"), grep=()):
    m = env_leak.MARK
    return "\n".join(["%senv" % m] + env_lines + ["%spid1" % m] + env_lines + ["", "%sfiles" % m] + list(files) +
                     ["%sgrep" % m] + list(grep) + ["%send" % m]) + "\n"


# The 0.7.4 engine run's output (the operator's report): nothing of the host, HOME=/tmp.
RUN_074 = ["CI=1", "NODE_VERSION=24.22.3", "HOSTNAME=3744e860a850", "YARN_VERSION=1.22.22", "HOME=/tmp",
           "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "PWD=/", "TZ=UTC"]


# ------------------------------------------------------------------ secrets
def test_secrets():
    G = "secrets"
    src = open(os.path.join(REPO, "tests", "confined-engine", "run.py")).read()
    record(G, "the 0.7.4 failing assertion (the literal HOME=/tmp/home) is gone from the engine suite",
           "HOME=/tmp/home" not in src and "env_leak.problems" in src, "")
    found = env_leak.problems(section_out(RUN_074), "ls: cannot open directory '/root': Permission denied", CANARY,
                              RUNNER, NODE_OWN)
    record(G, "the 0.7.4 engine run's output passes the property check (nothing of the host is in it)", not found, found)
    cases = [
        ("a host variable", RUN_074 + ["MOADIX_ENGINE_CANARY=" + CANARY], "MOADIX_ENGINE_CANARY", ()),
        ("a variable that is neither the runner's nor the image's", RUN_074 + ["EDITOR=vim"], "EDITOR", ()),
        ("a host value under a runner name", [x if not x.startswith("HOME=") else "HOME=/Users/someone"
                                              for x in RUN_074], "HOME=/Users/someone", ()),
        ("an SSH agent", RUN_074 + ["SSH_AUTH_SOCK=/private/tmp/launch/Listeners"], "SSH_AUTH_SOCK", ()),
        ("a file holding the canary", RUN_074, "file holding the canary", ("/hostcanary/canary-file",)),
    ]
    for what, env_lines, needle, grep in cases:
        got = env_leak.problems(section_out(env_lines, grep=grep), "", CANARY, RUNNER, NODE_OWN)
        record(G, "hostile: %s fails the check, and is named" % what, any(needle in x for x in got), got)
    got = env_leak.problems("", "", CANARY, RUNNER, NODE_OWN)
    record(G, "a run that printed nothing fails the check (it cannot pass by not running)", got, got)
    record(G, "the engine suite has a control run that is deliberately unconfined and must fail the same check",
           "deliberately unconfined" in src and "cfound" in src and "/hostcanary" in src, "")
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    sys.path.insert(0, os.path.dirname(p))
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    record(G, "the engine suite's total is 77 (0.7.5: 50, secrets 5 with the control; 0.7.6: rel076 7; 0.7.7: rel077 2; 0.7.8: rel078 4; 0.7.9: rel079 4; 0.8.0: rel080 3; 0.8.1: rel081 3; 0.8.2: rel082 4)",
           es.TOTAL == 77 and es.PLAN["test_secrets"][1] == 5, (es.TOTAL, es.PLAN["test_secrets"]))


# ------------------------------------------------------------------ path
OLD_ZAP = ("zap-baseline.py -t http://sut.moadix.test:3000 -c zap-rules.tsv -J zap.json -I -m 1 -z '-dir /tmp/zaphome' "
           "> /zap/wrk/run.log 2>&1; echo $? > /zap/wrk/run.rc")


def test_path():
    G = "path"
    base = ["run", "--rm", "--name", "x-zap", "--network", "none", "--env", "PATH=" + confined.RUN_PATH, ZAP, "bash", "-c"]
    r = double(base + [OLD_ZAP])
    record(G, "the double refuses the 0.7.4 ZAP invocation as the real engine did (127, command not found)",
           r.returncode == 127 and b"zap-baseline.py: command not found" in r.stderr, r.stderr)
    r = double(["run", "--rm", "--name", "x-zap", "--network", "none", ZAP, "bash", "-c", OLD_ZAP])
    record(G, "control: with the image's own PATH (which has /zap) the same bare word resolves",
           r.returncode == 0, r.stderr)
    s = X.live_script("zap", 3000, None, ["/"], 2048)
    r = double(base + [s])
    record(G, "the 0.7.5 ZAP script resolves under the runner's PATH", r.returncode == 0, r.stderr)
    record(G, "it names zap-baseline.py by its absolute path, runs from /tmp (zap.out; /zap is on the read-only root) "
              "and caps the Java heap at half the run's memory",
           "cd /tmp && /zap/zap-baseline.py " in s and "-Xmx1024m" in s and "zap-baseline.py" not in
           s.replace("/zap/zap-baseline.py", ""), s)
    p = product("zap")
    rc, out = run_gate(p, "zap", "9")
    scan = next((c for c in calls() if c[:1] == ["run"] and "--name" in c and c[c.index("--name") + 1].endswith("zap")), [])
    j = " ".join(scan)
    record(G, "zap (phase 9) passes end to end through the gate and the double, the scan under the runner's PATH",
           rc == 0 and "/zap/zap-baseline.py" in j and "--env PATH=%s " % confined.run_path(engine_double.IMAGE_PATH["zaproxy"]) in j + " ", out[-800:] + j[-400:])
    for gate, label in (("schemathesis", "8"), ("lhci", "10a"), ("axe", "6")):
        rc, out = run_gate(p, gate, label)
        record(G, "%s (phase %s) still passes with the stricter double" % (gate, label), rc == 0, out[-800:])
    words = []
    for gate in ("schemathesis", "zap", "lhci", "axe"):
        words += [(gate, w) for w in __import__("engine_double").command_words(X.live_script(gate, 3000, "x.yaml", ["/"]))]
    off = [(g, w) for g, w in words if "/" not in w and any(w in t for t in __import__("engine_double").OFF_PATH.values())]
    record(G, "no live script names, by a bare word, a command that lives off the runner's PATH in any pinned image",
           not off and words, off or words)


# ------------------------------------------------------------------ wait
def test_wait():
    G = "wait"
    s = X.live_script("zap", 3000, None, ["/"], 2048)
    record(G, "the ZAP wait writes its note to /zap/wrk (the run has no /out)", "> /zap/wrk/wait.log" in s and "/out/" not in s, s)
    # the wait's give-up branch, run by bash here with a 1-step limit and a port nothing listens on
    w = X.wait_for(1, "/nonexistent-dir").replace("-gt 90", "-gt 1").replace("sleep 1", "sleep 0")
    w = w.replace("/dev/tcp/%s/1" % confined.SUT_ALIAS, "/dev/tcp/127.0.0.1/1")
    r = subprocess.run(["/bin/bash", "-c", w + "echo reached"], capture_output=True, text=True, timeout=30)
    record(G, "the wait exits 3 when the app never listens, even when its note cannot be written (0.7.4 looped on)",
           r.returncode == 3 and "reached" not in r.stdout, (r.returncode, r.stdout, r.stderr))
    w = X.wait_for(1, E.base).replace("-gt 90", "-gt 1").replace("sleep 1", "sleep 0")
    w = w.replace("/dev/tcp/%s/1" % confined.SUT_ALIAS, "/dev/tcp/127.0.0.1/1")
    r = subprocess.run(["/bin/bash", "-c", w], capture_output=True, text=True, timeout=30)
    note = os.path.join(E.base, "wait.log")
    record(G, "and writes the note where it can", r.returncode == 3 and os.path.exists(note) and
           "never listened" in open(note).read(), r.stderr)


# ------------------------------------------------------------------ services
def test_services():
    G = "services"
    old = ["run", "--name", "x-svc", "--network", "none", "--env", "PATH=" + confined.RUN_PATH, "-d", PG]
    r = double(old)
    # 0.8.0: as the engine, the double starts the detached run; the container stops with 127 and the message
    st = double(["inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", "x-svc"]).stdout
    lg = double(["logs", "--tail", "50", "x-svc"]).stderr
    record(G, "the 0.7.4 postgres service (initdb not on the runner's PATH) stops with 127 in the double, as on the "
              "real engine", r.returncode == 0 and st.split() == [b"exited", b"127"] and b"initdb: command not found" in lg,
           (st, lg))
    svc = (confined.config().get("services") or {}).get("postgres") or {}
    r = double(["run", "--name", "x-svc2"] + old[3:6] + ["PATH=" + svc.get("path", "")] + old[7:])
    st = double(["inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", "x-svc2"]).stdout
    record(G, "with the gate's configured service PATH the service starts", r.returncode == 0 and
           st.split() == [b"running", b"0"] and "/usr/lib/postgresql/17/bin" in svc.get("path", ""), (r.stderr, st))
    pt = open(os.path.join(SMOKE, "product-tools.yaml")).read().replace(
        "tests:\n", "tests:\n  services: [postgres]\n", 1)
    p = product("svc", pt)
    rc, out = run_gate(p, "tests", "8")
    sv = next((c for c in calls() if c[:1] == ["run"] and "-d" in c and PG in c), [])
    tr = next((c for c in calls() if c[:1] == ["run"] and "--name" in c and c[c.index("--name") + 1].endswith("-tests")), [])
    record(G, "the tests gate with services: [postgres] passes end to end; the service runs with the gate's PATH",
           rc == 0 and "--env PATH=%s" % svc.get("path") in " ".join(sv) and "DATABASE_URL=postgres://" in " ".join(tr),
           out[-800:] + " ".join(sv)[-400:])
    shutil.rmtree(DBL, ignore_errors=True)
    saved_engine = confined.engine
    confined.engine = lambda: DOUBLE  # the double, in process (the test guard refuses a real engine)
    os.environ["MOADIX_DOUBLE_DIR"] = DBL
    try:
        r = confined.Run("r75x")
        try:
            r.execute(PG, [], "L", [], path="/usr/bin;rm -rf /")
            why = ""
        except confined.Refused as e:
            why = str(e)
        finally:
            r.close()
    finally:
        confined.engine = saved_engine
        os.environ.pop("MOADIX_DOUBLE_DIR", None)
    ran = [c for c in calls() if c[:1] == ["run"]]
    record(G, "a PATH that is not a list of absolute directories is refused before the engine is called",
           "absolute directories" in why and not ran, (why, ran))
    pt2 = pt.replace("tests:\n", "tests:\n  path: /tmp/evil\n", 1)
    E.write(p, SD + "/config/product-tools.yaml", pt2)
    E.commit(p, "a product tries to set the service PATH")
    rc, out = run_gate(p, "tests", "8")
    sv = next((c for c in calls() if c[:1] == ["run"] and "-d" in c and PG in c), [])
    record(G, "the service PATH comes only from the gate's configuration: a product's own path key changes nothing",
           "/tmp/evil" not in " ".join(calls()[0] if calls() else []) + " ".join(sv) and
           "--env PATH=%s" % svc.get("path") in " ".join(sv), out[-600:] + " ".join(sv)[-300:])


def main():
    try:
        for t in (test_secrets, test_path, test_wait, test_services):
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
