#!/usr/bin/python3
"""0.7.9 suite: unique per-step names and labelled build images. Written before the fix; on 0.7.8 (f834a21) its fix
checks fail.

    /usr/bin/python3 tests/rel079/run.py

The product run on 0.7.8: Schemathesis UNKNOWN in every run, "docker network create failed: network with name
moadix-<id>-build already exists". The product builds two services with build.network: registry, and start_live
created the run's build network once per built service under the same name. The 0.7.8 engine run also left two
unlabelled <none> images: the classic builder (registry builds) keeps every step's image and every earlier stage's,
untagged, and `docker build --label` labels only the final one. 0.7.9: every network, volume and container a run
creates gets a name no earlier step used (confined.Run.unique); each build and the install step remove their own
objects when they end (Run.end_step); the Dockerfile the engine builds has the run's labels set right after every
FROM (confined.label_stages). The real-engine case is group rel079 of tests/confined-engine (every live gate on
smoke-076, which now builds two services, app and a two-stage worker).

Fixtures only: throwaway repos under $TMPDIR, the engine double (which now refuses a second network of a name and
the removal of a network a container is on, as the engine does, and records the images a build keeps), no network.

  names     the 0.7.8 control (UNKNOWN, "already exists"); unique names; each build its own step, removed when it ends
  gates     every live gate passes with two registry builds, and nothing of the run is left
  labels    label_stages; the Dockerfile the engine got; every image a classic build keeps carries the run's label
            (the 0.7.8 control: unlabelled ones)
  fixture   smoke-076 builds two services under build.network: registry, one in two stages
  engine    the engine suite's rel079 group, its total, and its image accounting with untagged images
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r79").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined  # noqa: E402

RESULTS = []
T0 = time.time()
OLD = "f834a21"  # 0.7.8
FIX76 = os.path.join(REPO, "tests", "fixtures", "smoke-076")
DBL = os.path.join(E.base, "engine-double")
DOUBLE = os.path.join(E.shim, "engine-double")
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
SD = "." + "sdlc"
LIVE = (("schemathesis", "8"), ("zap", "9"), ("lhci", "10a"), ("axe", "8"))


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


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


def old_home():
    """A copy of the fixture gate with 0.7.8's runner and gate script (the control)."""
    h = os.path.join(E.base, "home078")
    if not os.path.isdir(h):
        shutil.copytree(E.home, h)
        for rel in ("gate/confined.py", "gate/v1/check_exec.py"):
            with open(os.path.join(h, rel), "w") as f:
                f.write(subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:%s" % (OLD, rel)], capture_output=True,
                                       text=True).stdout)
    return h


def run_gate(p, gate, label, home=None):
    shutil.rmtree(DBL, ignore_errors=True)
    home = home or E.home
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(home, "gate", "v1", "_launch.py"),
                     os.path.join(home, "gate", "v1", "check_exec.py"), "--gate", gate, "--phase", label],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS), timeout=300)
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


def builds():
    f = os.path.join(DBL, "builds.log")
    return [json.loads(x) for x in open(f).read().splitlines() if x.strip()] if os.path.exists(f) else []


def left():
    s = dstate()
    return list(s["containers"]) + list(s["networks"]) + list(s["volumes"])


def double(*args, stdin=None, **env):
    return subprocess.run([DOUBLE] + list(args), input=stdin, capture_output=True,
                          env=E.env(MOADIX_DOUBLE_DIR=DBL, **env))


# ------------------------------------------------------------------ names
def test_names():
    G = "names"
    shutil.rmtree(DBL, ignore_errors=True)
    a = double("network", "create", "--label", "moadix.run=r79c", "--internal", "moadix-r79c-build")
    b = double("network", "create", "--label", "moadix.run=r79c", "--internal", "moadix-r79c-build")
    record(G, "control: the double refuses a second network of a name, as the engine does",
           a.returncode == 0 and b.returncode != 0 and b"already exists" in b.stderr, b.stderr)
    p = product("names")
    rc, out = run_gate(p, "schemathesis", "8", home=old_home())
    record(G, "control: on 0.7.8 schemathesis with two registry-built services is UNKNOWN (\"network with name "
              "moadix-<id>-build already exists\"), as in the product run", rc != 0 and "UNKNOWN" in out and
           re.search(r"network with name moadix-x[0-9a-f]{10}-build already exists", out), out[-600:])
    r = confined.Run.__new__(confined.Run)
    r.id, r._used = "r79u", set()
    got = [r.unique("moadix-r79u-build") for _ in range(3)] + [r.unique("moadix-r79u-proxy-build")]
    try:
        r.unique("other-build")
        refused = False
    except confined.Refused:
        refused = True
    record(G, "Run.unique: the first use keeps the name, a later one gets -2, -3; a name not the run's is refused",
           got == ["moadix-r79u-build", "moadix-r79u-build-2", "moadix-r79u-build-3", "moadix-r79u-proxy-build"] and
           refused, got)
    rc, out = run_gate(p, "schemathesis", "8")
    cs = calls()
    nets = [c[-1] for c in cs if c[:2] == ["network", "create"]]
    names = [c[c.index("--name") + 1] for c in cs if c[:1] in (["run"], ["create"]) and "--name" in c]
    vols = [c[-1] for c in cs if c[:2] == ["volume", "create"]]
    record(G, "schemathesis passes with two registry-built services (0.7.8: UNKNOWN)", rc == 0 and "UNKNOWN" not in out,
           out[-800:])
    bnets = [n for n in nets if re.search(r"-build(-\d+)?$", n)]
    record(G, "every network, volume and container of the run has its own name; each build its own network, egress "
              "network, proxy and volume", len(nets) == len(set(nets)) and len(vols) == len(set(vols)) and
           len(names) == len(set(names)) and len(bnets) == 2 and
           len([n for n in names if "-proxy-build" in n]) == 2 and len([v for v in vols if "-build-proxy" in v]) == 2,
           (nets, vols, names))
    bidx = [i for i, c in enumerate(cs) if c[:1] == ["build"]]
    ok = len(bidx) == 2
    for i, n in zip(bidx, bnets):
        rm = [j for j, c in enumerate(cs) if c[:2] == ["network", "rm"] and n in c]
        ok = ok and rm and bidx[0] < rm[0] and (n != bnets[0] or rm[0] < bidx[1])
    rms = [c[-1] for c in cs if c[:2] == ["network", "rm"]]
    inst = [j for j, c in enumerate(cs) if c[:2] == ["network", "rm"] and re.search(r"-x[0-9a-f]{10}-(install|egress)$",
                                                                                     c[-1])]
    # a removal the engine refused would be tried again by close(): each network removed once was accepted at once
    record(G, "each step's objects go when the step ends: the install step's networks before the first build, the "
              "first build's network before the second build (the engine accepts each removal)",
           ok and len(inst) == 2 and bidx and max(inst) < bidx[0] and sorted(rms) == sorted(set(nets)),
           (bidx, inst, bnets, rms))
    record(G, "nothing of the run is left afterwards", not left(), left())


# ------------------------------------------------------------------ gates
def test_gates():
    G = "gates"
    p = product("gates")
    for gate, label in LIVE:
        rc, out = run_gate(p, gate, label)
        n = len([c for c in calls() if c[:1] == ["build"]])
        record(G, "%s (phase %s) with two registry-built services passes, and nothing of its run is left" % (gate, label),
               rc == 0 and "PASS" in out and n == 2 and not left(), (n, left(), out[-600:]))


# ------------------------------------------------------------------ labels
def test_labels():
    G = "labels"
    run = "x0123456789"
    lab = "LABEL moadix.owner=gate moadix.run=%s" % run
    src = ("# syntax=docker/dockerfile:1\nARG V=1\nFROM a@sha256:%s AS one\nRUN true\n# comment\n"
           "from --platform=linux/arm64 \\\n  b@sha256:%s\nCOPY --from=one / /\n") % ("1" * 64, "2" * 64)
    got = confined.label_stages(src, run)
    record(G, "label_stages: the run's labels right after every FROM (a continued FROM after its last line); nothing "
              "else changes", got.split("\n") == ["# syntax=docker/dockerfile:1", "ARG V=1", "FROM a@sha256:%s AS one" % (
                  "1" * 64), lab, "RUN true", "# comment", "from --platform=linux/arm64 \\", "  b@sha256:%s" % ("2" * 64),
                  lab, "COPY --from=one / /", ""], got)
    esc = confined.label_stages("# escape=`\nFROM a@sha256:%s `\n  AS s\nRUN x\n" % ("1" * 64), run)
    try:
        confined.label_stages("RUN true\n", run)
        nofrom = False
    except confined.Refused:
        nofrom = True
    record(G, "label_stages keeps the escape directive (a backtick continuation) and refuses a file with no FROM",
           esc.split("\n")[3] == lab and esc.split("\n")[2] == "  AS s" and nofrom, esc)
    p = product("labels")
    rc, out = run_gate(p, "schemathesis", "8")
    rid = next((c[c.index("--label") + 1].split("=", 1)[1] for c in calls() if c[:1] == ["build"]), "")
    bl = builds()
    record(G, "the engine built each service's Dockerfile with the run's labels after every FROM (app 1 stage, worker 2)",
           rc == 0 and len(bl) == 2 and [b["dockerfile"].count("LABEL moadix.owner=gate moadix.run=%s" % rid) for b in bl]
           == [1, 2] and all(b["classic"] for b in bl), [(b["dockerfile"][-300:], b["classic"]) for b in bl])
    imgs = dstate().get("images") or []
    record(G, "every image the classic builds kept (%d: each step's, the worker's first stage, untagged) carries "
              "moadix.run=<run>" % len(imgs), len(imgs) >= 8 and len([i for i in imgs if not i["tag"]]) >= 6 and
           all(i["labels"].get("moadix.run") == rid for i in imgs), imgs)
    bargs = next((c for c in calls() if c[:1] == ["build"]), [])
    record(G, "a classic build removes its step containers even when it fails (--rm --force-rm), so its network can go",
           "--force-rm" in bargs and "--rm" in bargs, bargs)
    # control: the worker's own Dockerfile as 0.7.8 sent it, through the double's classic builder
    shutil.rmtree(DBL, ignore_errors=True)
    double("network", "create", "--label", "moadix.run=r79c", "--internal", "moadix-r79c-b")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        data = open(os.path.join(FIX76, "Dockerfile.worker"), "rb").read()
        m = tarfile.TarInfo("Dockerfile.worker")
        m.size = len(data)
        tf.addfile(m, io.BytesIO(data))
    c = double("build", "-", "-f", "Dockerfile.worker", "-t", "w:1", "--label", "moadix.run=r79c", "--network",
               "moadix-r79c-b", stdin=buf.getvalue(), DOCKER_BUILDKIT="0")
    every = double("image", "ls", "-a", "-q").stdout.split()
    lab_ = double("image", "ls", "-a", "-q", "--filter", "label=moadix.run=r79c").stdout.split()
    record(G, "control: 0.7.8's build (--label only) leaves unlabelled untagged images in the classic builder",
           c.returncode == 0 and len(every) > len(lab_) >= 1, (c.stderr, len(every), len(lab_)))
    try:
        X._context_tar(os.path.join(E.base, "none.tar"), ".", E.base, dockerfile="Dockerfile", replace=b"x")
        outside = False
    except (confined.Refused, OSError, tarfile.TarError) as e:
        outside = isinstance(e, confined.Refused) or "none.tar" in str(e)
    exp = os.path.join(E.base, "ctx.tar")
    with tarfile.open(exp, "w") as tf:
        for n in ("Dockerfile", "sub/x"):
            m = tarfile.TarInfo(n)
            m.size = 1
            tf.addfile(m, io.BytesIO(b"a"))
    try:
        X._context_tar(exp, "sub", E.base, dockerfile="../Dockerfile", replace=b"x")
        outside = False
    except confined.Refused as e:
        outside = outside and "not inside the build context" in str(e)
    record(G, "a Dockerfile outside its build context is refused (the labelled file must be the one built)", outside,
           outside)


# ------------------------------------------------------------------ fixture
def test_fixture():
    G = "fixture"
    import hlib
    doc = hlib.load_yaml(os.path.join(FIX76, "compose.yaml"))
    pt = hlib.load_yaml(os.path.join(FIX76, "product-tools.yaml"))
    built = sorted(n for n, s in (doc.get("services") or {}).items() if "build" in s)
    wk = open(os.path.join(FIX76, "Dockerfile.worker")).read()
    record(G, "smoke-076 builds two services (app, worker) under build.network: registry; the worker in two pinned stages",
           built == ["app", "worker"] and (pt.get("build") or {}).get("network") == "registry" and
           len(confined.FROM.findall(wk)) == 2 and not confined.dockerfile_problems(wk, pt), (built, pt.get("build")))


# ------------------------------------------------------------------ engine
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite079", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    text = open(p).read()
    record(G, "the engine suite has a rel079 group (every live gate with two registry builds), and its total is 73 (0.8.0: rel080 3; 0.8.1: rel081 3)",
           es.PLAN.get("test_rel079") == ("rel079", 4) and es.TOTAL == 73 and "test_rel079, (node,)" in text and
           [g for g, _l in es.LIVE_GATES] == ["schemathesis", "zap", "lhci", "axe"], (es.PLAN.get("test_rel079"), es.TOTAL))
    body = text.split("def built_images", 1)[1].split("\ndef ", 1)[0]
    rel = text.split("def test_rel079", 1)[1].split("\n# ", 1)[0]
    record(G, "it counts untagged images: built_images lists with -a, and rel079 requires every image a run added to "
              "carry the run's label", '"image", "ls", "-a"' in body and "unlabelled" in rel and "all_images()" in rel,
           body[:300])


def main():
    try:
        for t in (test_names, test_gates, test_labels, test_fixture, test_engine):
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
