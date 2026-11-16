#!/usr/bin/python3
"""0.7.4 suite: the four live gates of the 0.7.3 engine run, through the engine double, which since 0.7.4
refuses what the real engine and the pinned images refuse.

    /usr/bin/python3 tests/rel074/run.py

Fixtures only: throwaway repos under $TMPDIR, the stub checker, the engine double (no Docker), no network.

  context   the build context streamed to `docker build -` starts with a plain ustar header (no PAX or GNU
            long-name header first), built only from the export; the 0.7.3 context is refused, as the engine did
  double    the double refuses each combination the real engine or the images refuse: an ambiguous stdin
            Dockerfile, a build or run network that does not exist, a network alias on `none`, /dev/tcp under dash
  live      schemathesis, zap, lhci and axe run end to end through the gate and the double: the app is built,
            the scanner runs under bash with HOME=/tmp, ZAP gets a writable home (-dir)
  registry  build.network registry: an internal build network joined to the allowlisting proxy, which exists
  buildlog  a failing build keeps the engine's output in the evidence folder, bounded and redacted, and the
            failure line shows its last lines (the 0.7.3 line said "log:" and nothing)
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

E = fixtures.Env("r74").build()
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
NODE = (confined.config().get("images") or {}).get("node", {}).get("ref", "")
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def git(p, *args):
    return subprocess.run(["/usr/bin/git", "-C", p] + list(args), capture_output=True, text=True)


def product(name, pt_extra=""):
    """The smoke fixture as a MOADIX product (its Dockerfile names the pinned node digest)."""
    p = os.path.join(E.base, name)
    shutil.copytree(SMOKE, p, ignore=shutil.ignore_patterns(".claude", "product-tools.yaml"))
    E.commit(p, "x") if os.path.isdir(os.path.join(p, ".git")) else None
    subprocess.run(["/usr/bin/git", "init", "-q", p])
    E.commit(p, "smoke fixture")
    E.init(p, name + "fx")
    E.commit(p, "init")
    with open(os.path.join(SMOKE, "product-tools.yaml")) as f:
        E.write(p, SD + "/config/product-tools.yaml", f.read() + pt_extra)
    return p


def run_gate(p, gate, label, **extra):
    shutil.rmtree(DBL, ignore_errors=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", gate, "--phase", label],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS, **extra),
                    timeout=300)
    return r.returncode, r.stdout + r.stderr


def calls():
    f = os.path.join(DBL, "calls.log")
    return [json.loads(x) for x in open(f).read().splitlines() if x.strip()] if os.path.exists(f) else []


def double(args, stdin=b"", env=None):
    return subprocess.run([DOUBLE] + args, input=stdin, capture_output=True,
                          env=E.env(MOADIX_DOUBLE_DIR=DBL, **(env or {})))


def old_context(export, out):
    """The 0.7.3 _context_tar: members copied as read, PAX headers and all."""
    with tarfile.open(export) as src, tarfile.open(out, "w") as dst:
        for m in src.getmembers():
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
    return out


# ------------------------------------------------------------------ context
def test_context():
    G = "context"
    p = product("ctx")
    exp = os.path.join(E.base, "export.tar")
    git(p, "archive", "--format=tar", "-o", exp, "HEAD")
    with open(exp, "rb") as f:
        record(G, "control: git archive's export starts with a PAX global header (git's commit id)",
               f.read(512)[156:157] == b"g")
    tmp = os.path.join(E.base, "ctx-new")
    os.makedirs(tmp)
    new = X._context_tar(exp, ".", tmp)
    with open(new, "rb") as f:
        head = f.read(512)
    record(G, "the 0.7.4 context starts with a plain ustar header (no PAX, no GNU long name)",
           confined.stdin_context_problem(new) is None and head[156:157] in (b"0", b"5"), head[156:157])
    with tarfile.open(new) as t:
        names = t.getnames()
        record(G, "the context holds exactly the export's files (no link, nothing from outside the export)",
               "Dockerfile" in names and "src/server.js" in names and not any(m.issym() or m.islnk() or
                                                                               m.name.startswith("/") or ".." in m.name
                                                                               for m in t.getmembers()), names[:8])
        record(G, "no member carries PAX headers (git's comment no longer rides on every file)",
               all(not m.pax_headers for m in t.getmembers()))
    old = old_context(exp, os.path.join(E.base, "ctx-old.tar"))
    record(G, "the 0.7.3 context is refused by the gate's own check, naming the header",
           "'x' header" in (confined.stdin_context_problem(old) or ""), confined.stdin_context_problem(old))
    long_dir = os.path.join(E.base, "ctx-long")
    os.makedirs(long_dir)
    q = product("longname")
    deep = "src/" + "d" * 60 + "/" + "e" * 60 + "/file.js"
    E.write(q, deep, "module.exports = 1;\n")
    E.commit(q, "long name")
    exp2 = os.path.join(E.base, "export2.tar")
    git(q, "archive", "--format=tar", "-o", exp2, "HEAD")
    c2 = X._context_tar(exp2, ".", long_dir)
    with tarfile.open(c2) as t:
        record(G, "a path over 100 characters is kept (GNU long name), and a short name still comes first",
               deep in t.getnames() and confined.stdin_context_problem(c2) is None, t.getnames()[:3])


# ------------------------------------------------------------------ double
def test_double():
    G = "double"
    shutil.rmtree(DBL, ignore_errors=True)
    p = product("dbl")
    exp = os.path.join(E.base, "export-d.tar")
    git(p, "archive", "--format=tar", "-o", exp, "HEAD")
    with open(old_context(exp, os.path.join(E.base, "ctx-d-old.tar")), "rb") as f:
        old = f.read()
    os.makedirs(os.path.join(E.base, "ctx-d"), exist_ok=True)
    with open(X._context_tar(exp, ".", os.path.join(E.base, "ctx-d")), "rb") as f:
        new = f.read()
    base = ["build", "-", "-f", "Dockerfile", "-t", "t", "--label", "moadix.run=xd", "--pull=false", "--memory",
            "4096m", "--network", "none"]
    r = double(base, old, {"DOCKER_BUILDKIT": "1"})
    record(G, "the double refuses the 0.7.3 context exactly as the engine did",
           r.returncode != 0 and b"ambiguous Dockerfile source" in r.stderr, r.stderr)
    r = double(base, new, {"DOCKER_BUILDKIT": "1"})
    record(G, "the double accepts the 0.7.4 context", r.returncode == 0, r.stderr)
    r = double(base[:-1] + ["moadix-x-nothere"], new, {"DOCKER_BUILDKIT": "0"})
    record(G, "a classic build on a network that was never created is refused (the 0.7.3 registry build)",
           r.returncode != 0 and b"not found" in r.stderr, r.stderr)
    r = double(base[:-1] + ["moadix-x-nothere"], new, {"DOCKER_BUILDKIT": "1"})
    record(G, "BuildKit refuses a named network", r.returncode != 0 and b"not supported by buildkit" in r.stderr,
           r.stderr)
    r = double(["run", "--name", "a", "--network", "moadix-x-gone", "img", "true"])
    record(G, "a run on a network that does not exist is refused", r.returncode == 125, r.stderr)
    r = double(["run", "--name", "a", "--network", "none", "--network-alias", "sut.moadix.test", "img", "true"])
    record(G, "a network alias on `none` is refused", r.returncode == 125 and b"user defined" in r.stderr, r.stderr)
    r = double(["run", "--name", "a", "--network", "none", "img", "sh", "-c", X.wait_for(3000) + "true"])
    record(G, "the 0.7.3 wait (/dev/tcp under sh, which is dash in the pinned images) fails, as it did",
           r.returncode == 3 and b"/dev/tcp" in r.stderr, r.stderr)
    r = double(["run", "--name", "a", "--network", "none", "img", "bash", "-c", X.wait_for(3000) + "true"])
    record(G, "the same wait under bash runs", r.returncode == 0, r.stderr)


# ------------------------------------------------------------------ live
LIVE = [("schemathesis", "8"), ("zap", "9"), ("lhci", "10a"), ("axe", "6")]


def test_live():
    G = "live"
    p = product("live")
    for gate, label in LIVE:
        rc, out = run_gate(p, gate, label)
        cs = calls()
        builds = [c for c in cs if c[:1] == ["build"]]
        scan = next((c for c in cs if c[:1] == ["run"] and any("/dev/tcp/" in str(x) for x in c)), None)
        j = " ".join(scan or [])
        record(G, "%s (phase %s): the app is built from the export (stdin context, -f, no network) and the gate "
                  "passes" % (gate, label),
               rc == 0 and builds and builds[0][1] == "-" and "--network none" in " ".join(builds[0]), out[-1200:])
        record(G, "%s: the scanner runs under bash with HOME=/tmp" % gate,
               scan is not None and " bash -c " in " %s " % j and "--env HOME=/tmp " in j + " ", j[-600:])
    rc, out = run_gate(p, "zap", "9")
    scan = next((c for c in calls() if c[:1] == ["run"] and "--name" in c and c[c.index("--name") + 1].endswith("zap")),
                [])
    record(G, "zap gets a writable ZAP home (-z '-dir /tmp/zaphome'), since Java reads /home/zap from passwd",
           "-dir /tmp/zaphome" in " ".join(scan), " ".join(scan)[-400:])


# ------------------------------------------------------------------ registry
def test_registry():
    G = "registry"
    p = product("reg", pt_extra="build:\n  network: registry\n")
    rc, out = run_gate(p, "zap", "9")
    cs = calls()
    b = next((c for c in cs if c[:1] == ["build"]), [])
    net = b[b.index("--network") + 1] if "--network" in b else ""
    created = [c[-1] for c in cs if c[:2] == ["network", "create"]]
    record(G, "a registry build runs on the run's own build network, which exists", rc == 0 and net in created and
           net.endswith("-build"), (net, created, out[-600:]))
    internal = [c for c in cs if c[:2] == ["network", "create"] and c[-1] == net and "--internal" in c]
    record(G, "that network is internal; its only way out is the allowlisting proxy, joined to it",
           internal and any(c[:3] == ["network", "connect", "--alias"] and net in c for c in cs), created)
    record(G, "the build reaches the registries through the proxy (HTTP(S)_PROXY build args), never with a secret",
           "HTTPS_PROXY=http://moadix-proxy:3128" in b and not any(re.search(r"(?i)token|secret|password", x)
                                                                   for x in b), b)
    try:
        confined.build_argv("r", "t", "Dockerfile", confined.limits("build"), {"build": {"network": "registry"}})
        why = ""
    except confined.Refused as e:
        why = str(e)
    record(G, "a registry build without the run's build network is refused", "build network" in why, why)
    try:
        confined.build_argv("r", "t", "Dockerfile", confined.limits("build"),
                            {"build": {"args": {"HTTPS_PROXY": "http://evil:1"}}})
        why = ""
    except confined.Refused as e:
        why = str(e)
    record(G, "a product cannot set the proxy itself", "set by the gate" in why, why)


# ------------------------------------------------------------------ buildlog
def test_buildlog():
    G = "buildlog"
    p = product("blog")
    rc, out = run_gate(p, "axe", "6", MOADIX_DOUBLE_BUILD_FAIL="1")
    record(G, "a failed build is a failure that names the engine's exit and its last lines",
           rc == 1 and "building app failed (engine exit 1)" in out and "did not complete successfully" in out,
           out[-1200:])
    record(G, "the build's output has no secret (a token in the engine's output is redacted)",
           "Q1w2E3r4T5y6" not in out, out[-800:])
    m = re.search(r"build log is kept at (\S+)", out)
    kept = os.path.join(p, m.group(1)) if m else ""
    log = open(kept).read() if kept and os.path.exists(kept) else ""
    record(G, "the build log is kept in the evidence folder, with the engine's stdout and stderr",
           kept.startswith(os.path.join(p, SD, "evidence")) and "container stderr" in log and "npm ci" in log and
           "Q1w2E3r4T5y6" not in log, (kept, log[:500]))


def main():
    try:
        for t in (test_context, test_double, test_live, test_registry, test_buildlog):
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
