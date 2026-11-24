#!/usr/bin/python3
"""0.8.3 suite: OS packages in the builds the gate runs. Written before the fix; on 0.8.2 (70ad949) its fix checks fail.

    /usr/bin/python3 tests/rel083/run.py

  lint   every Dockerfile the gate builds: each apk add and apt-get install names every package at an exact version
         (pkg=version); apk upgrade, apt-get upgrade, dist-upgrade and an unpinned install fail, naming the line; a
         pinned apk add passes. Nothing in the RUN may let a missing version pass (|| after the install, a pipe, a ;
         with no set -e, an if test, apt-get --ignore-missing). Checked through check-trivy's build of the shipped
         image (the engine double), so the refusal is the gate's, before any build; and a build that fails because a
         pinned version is gone says so.
  proxy  builds (build.network: registry) may also reach the Alpine and Debian package servers through the build
         proxy, and the install step's proxy is unchanged. The proxy itself (gate/egress_proxy.py, in process, over
         socket pairs: no network): a host off the list is refused (CONNECT and plain http), a look-alike suffix too;
         plain http goes only to a listed package server on port 80, as one GET/HEAD with Connection: close.
  engine the real-engine suite has a rel083 group (2 checks).
  docs   INSTALL's update section, the report, the README line, the version.

Fixtures only: throwaway repos under $TMPDIR, the engine double, a fake trivy, socket pairs.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r83").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import confined  # noqa: E402  (the fixture gate's copy of this checkout)
from gate import egress_proxy  # noqa: E402

RESULTS = []
T0 = time.time()
OLD = "70ad949"  # 0.8.2
SD = "." + "sdlc"
D = "ab" * 32
BASE = "registry.example/fixture-base@sha256:" + "ef" * 32
F = "FROM %s\n" % BASE
OS_HOSTS = ("dl-cdn.alpinelinux.org", "deb.debian.org", "security.debian.org")


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def git(p, *args):
    return subprocess.run(["/usr/bin/git", "-C", p] + list(args), capture_output=True, text=True).stdout.strip()


def old_confined():
    """0.8.2's gate/confined.py, loaded as a module (the control)."""
    import importlib.util
    path = os.path.join(E.base, "confined082.py")
    with open(path, "w") as f:
        f.write(subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:gate/confined.py" % OLD],
                               capture_output=True, text=True).stdout)
    spec = importlib.util.spec_from_file_location("confined082", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def probs(text, tools=None):
    return confined.dockerfile_problems(text, tools)


# ------------------------------------------------------------------ lint
def test_lint():
    G = "lint"
    old = old_confined()
    df = F + "RUN apk add --no-cache curl\n"
    p = probs(df)
    record(G, "an unpinned apk add fails, naming the line and the package",
           p == ["line 2: apk add --no-cache curl: curl is not pinned to an exact version (write curl=<version>)"], p)
    record(G, "control (0.8.2): the same Dockerfile passed", old.dockerfile_problems(df) == [],
           old.dockerfile_problems(df))
    p = probs(F + "\nRUN apk update \\\n    && apk upgrade --no-cache\n")
    record(G, "apk upgrade fails, naming the line its RUN starts on",
           len(p) == 1 and p[0].startswith("line 3: apk upgrade --no-cache upgrades packages to whatever is newest"), p)
    p = probs(F + "RUN apt-get update && apt-get upgrade -y && apt-get clean\n")
    record(G, "apt-get upgrade fails, naming the line",
           len(p) == 1 and p[0].startswith("line 2: apt-get upgrade -y upgrades packages to whatever is newest"), p)
    p = probs(F + "RUN apt-get -y dist-upgrade\nRUN apt full-upgrade -y\n")
    record(G, "apt-get dist-upgrade and apt full-upgrade fail, each naming its line",
           len(p) == 2 and p[0].startswith("line 2: apt-get -y dist-upgrade upgrades") and
           p[1].startswith("line 3: apt full-upgrade -y upgrades"), p)
    p = probs(F + "RUN apk add --no-cache curl=8.14.1-r2 'libstdc++=14.2.0-r6' \\\n    && rm -rf /var/cache/apk/*\n")
    record(G, "a pinned apk add passes the linter", p == [], p)
    p = probs(F + "RUN apt-get update \\\n  # a comment inside the RUN\n  && DEBIAN_FRONTEND=noninteractive apt-get install "
              "-y --no-install-recommends -o Dpkg::Options::=--force-confnew ca-certificates=20230311+deb12u1 "
              "curl=7.88.1-10+deb12u12 2>/dev/null \\\n  && rm -rf /var/lib/apt/lists/*\n")
    record(G, "a pinned apt-get install passes (options with values, an environment prefix, a redirection, a comment line)",
           p == [], p)
    p = probs(F + "RUN apt-get install -y curl tzdata=2024* bash/bookworm 'jq>=1.6' && apk add 'busybox~1.36'\n")
    record(G, "unpinned, wildcard, release and range installs fail, one line each (apt-get and apk)",
           len(p) == 5 and all(x.startswith("line 2: ") for x in p) and
           [re.search(r": (\S+) is not pinned", x).group(1) for x in p] ==
           ["curl", "tzdata=2024*", "bash/bookworm", "jq>=1.6", "busybox~1.36"], p)
    p = probs(F + "ARG CURL_V=8.14.1-r2\nRUN apk add curl=${CURL_V} jq=$JQ_V\n")
    record(G, "a version from an ARG with a value is read; one from an unset variable fails",
           len(p) == 1 and "jq=$JQ_V has an unresolved variable" in p[0] and p[0].startswith("line 3: "), p)
    p = probs(F + "ARG JQ_V\nRUN apk add jq=$JQ_V\n", {"build": {"args": {"JQ_V": "1.8.0-r0"}}})
    record(G, "an ARG given by the adopted build.args is read", p == [], p)
    p = probs(F + 'RUN ["apk", "add", "curl"]\nRUN <<EOF\nset -e\napk add jq=1.8.0-r0\napk add bash\nEOF\n'
              "RUN --mount=type=cache,target=/var/cache/apk apk add git\n")
    record(G, "exec form, a heredoc and RUN flags are read too",
           len(p) == 3 and p[0].startswith("line 2: apk add curl:") and "bash is not pinned" in p[1] and
           p[1].startswith("line 3: ") and p[2].startswith("line 8: apk add git:"), p)

    # never a fallback: a pinned version that no longer exists must fail the build
    cases = {
        "|| after it": F + "RUN apk add curl=8.14.1-r2 || apk add curl=8.14.1-r1\n",
        "|| true": F + "RUN apk add curl=8.14.1-r2 && echo ok || true\n",
        "a pipe": F + "RUN apt-get install -y curl=7.88.1-10 | tee /tmp/log\n",
        "; with no set -e": F + "RUN apk add curl=8.14.1-r2; echo done\n",
        "an if test": F + "RUN if apk add curl=8.14.1-r2; then echo; fi\n",
        "--ignore-missing": F + "RUN apt-get install -y --ignore-missing curl=7.88.1-10\n",
        "-m in a bundle": F + "RUN apt-get install -ym curl=7.88.1-10\n",
    }
    got = {k: probs(v) for k, v in cases.items()}
    record(G, "nothing may let a missing pinned version pass: || after the install, a pipe, ; with no set -e, an if "
              "test, apt-get --ignore-missing (-m), each named by its line",
           all(len(v) == 1 and v[0].startswith("line 2: ") for v in got.values()), got)
    p = probs(F + "RUN set -eux; apk add curl=8.14.1-r2; rm -rf /var/cache/apk/*\n")
    record(G, "control: ; after the install with set -e before it passes", p == [], p)

    # through the gate: check-trivy builds the shipped image with check_exec.build_image (the engine double)
    tdir = fake_trivy()
    with open(os.path.join(tdir, "canned-image.json"), "w") as f:
        json.dump({"SchemaVersion": 2, "Results": []}, f)
    n0 = len(double_calls())
    p = built_product("lunpinned", {"Dockerfile": F + "RUN apk add --no-cache curl\nUSER 65534\nCMD [\"app\"]\n"})
    rc, out = trivy(p)
    builds = [c for c in double_calls()[n0:] if c and c[0] == "build"]
    record(G, "through the gate: check-trivy refuses to build a Dockerfile with an unpinned apk add (no engine build), "
              "names the line, and fails",
           rc == 1 and "could not be built, so it was not scanned" in out and
           "line 2: apk add --no-cache curl: curl is not pinned" in out and not builds, (rc, builds, out[-700:]))
    n0 = len(double_calls())
    q = built_product("lpinned", {"Dockerfile": F + "RUN apk add --no-cache curl=8.14.1-r2\nUSER 65534\nCMD [\"app\"]\n"})
    rc, out = trivy(q)
    builds = [c for c in double_calls()[n0:] if c and c[0] == "build"]
    record(G, "through the gate: the pinned apk add is built and scanned", rc == 0 and len(builds) == 1, (rc, out[-600:]))
    gone = ("Step 2/4 : RUN apk add --no-cache curl=8.0.0-r0\nfetch https://dl-cdn.alpinelinux.org/alpine/v3.22/main/"
            "aarch64/APKINDEX.tar.gz\nERROR: unable to select packages:\n  curl-8.14.1-r2:\n    breaks: "
            "world[curl=8.0.0-r0]")
    rc, out = trivy(q, MOADIX_DOUBLE_BUILD_LOG=gone)
    record(G, "a build that fails because a pinned version is gone fails loudly: check-trivy fails and says the pinned "
              "version is not on the package server, quoting apk",
           rc == 1 and "a pinned OS package version is not on the package server" in out and
           "breaks: world[curl=8.0.0-r0]" in out, out[-900:])
    record(G, "and the message reads apt's refusal too",
           confined.missing_pins("E: Version '7.0.0-1' for 'curl' was not found") ==
           ["E: Version '7.0.0-1' for 'curl' was not found"], confined.missing_pins("E: Version '7.0.0-1' for 'curl' "
                                                                                     "was not found"))


FAKE_TRIVY = """#!/usr/bin/python3
# Fixture trivy (tests/rel083): no network, no layers; every scan reports nothing.
import json, sys
a = sys.argv[1:]
out = a[a.index("--output") + 1] if "--output" in a else None
if out:
    json.dump({"SchemaVersion": 2, "ArtifactType": "container_image", "Metadata": {"ImageID": "sha256:" + "00" * 32},
               "Results": []}, open(out, "w"))
sys.exit(0)
"""


def fake_trivy():
    import toolrun
    ver = str(toolrun.pins()["trivy"]["version"])
    d = os.path.join(E.home, "tools", "trivy-%s" % ver)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "trivy"), "w") as f:
        f.write(FAKE_TRIVY)
    os.chmod(os.path.join(d, "trivy"), 0o755)
    with open(os.path.join(d, ".moadix-tool.json"), "w") as f:
        json.dump({"version": ver}, f)
    return d


def built_product(name, files, tools="images: []\n"):
    p = E.repo(name, docs=())
    for rel, text in files.items():
        E.write(p, rel, text)
    E.commit(p, "fixture")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    E.write(p, ".sdlc-proposals/config/product-tools.yaml", tools)
    ctx = E.prompt(p, "ADOPT %s" % E.fresh())
    assert "product-tools.yaml" in ctx and "NOT" not in ctx, ctx
    return p


def trivy(p, **env):
    e = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", **env)
    e.pop("MOADIX_PHASE_DOC", None)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_scanners.py"), "--tool", "trivy"], cwd=p, env=e,
                    timeout=300)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def double_calls():
    try:
        return [json.loads(ln) for ln in open(os.path.join(E.base, "engine-double", "calls.log"))]
    except OSError:
        return []


# ------------------------------------------------------------------ proxy
def ask(request, allowed, http_allowed=frozenset(), upstream=None):
    """Send one request to egress_proxy.handle over a socket pair; (reply, what the upstream got, the host:port the
    proxy dialled). `upstream`: the bytes a fake upstream answers with (socket.create_connection is replaced, so
    nothing leaves the process)."""
    dialled, got = [], []
    real = socket.create_connection

    def fake(addr, timeout=None):
        dialled.append("%s:%s" % addr)
        a, b = socket.socketpair()

        def serve():
            buf = b""
            b.settimeout(5)
            try:
                while b"\r\n\r\n" not in buf:
                    c = b.recv(4096)
                    if not c:
                        break
                    buf += c
                got.append(buf)
                b.sendall(upstream or b"")
            finally:
                b.close()
        threading.Thread(target=serve, daemon=True).start()
        return a
    egress_proxy.socket.create_connection = fake
    try:
        c, s = socket.socketpair()
        t = threading.Thread(target=egress_proxy.handle, args=(s, set(allowed), frozenset(http_allowed)), daemon=True)
        t.start()
        c.sendall(request)
        c.settimeout(5)
        reply = b""
        try:
            while True:
                d = c.recv(4096)
                if not d:
                    break
                reply += d
                if request.startswith(b"CONNECT") and b"\r\n\r\n" in reply:
                    break
        except socket.timeout:
            pass
        c.close()
        t.join(5)
    finally:
        egress_proxy.socket.create_connection = real
    return reply.decode("latin-1"), b"".join(got).decode("latin-1"), dialled


def test_proxy():
    G = "proxy"
    build = confined.proxy_hosts("build")
    cut = build.index("--http")
    record(G, "the build proxy tunnels npm, PyPI and the Alpine and Debian package servers, and forwards plain http only "
              "to the package servers",
           set(build[:cut]) == set(confined.REGISTRIES) | set(OS_HOSTS) and set(build[cut + 1:]) == set(OS_HOSTS), build)
    record(G, "the install step's proxy is unchanged: npm and PyPI only, no plain http",
           confined.proxy_hosts("install") == ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"],
           confined.proxy_hosts("install"))
    src = open(os.path.join(REPO, "gate", "confined.py")).read() + open(os.path.join(REPO, "gate", "v1",
                                                                                     "check_exec.py")).read()
    record(G, "only a build's proxy gets them: OS_PACKAGE_HOSTS is used by proxy_hosts alone, and the gate starts a "
              "\"build\" proxy only in build_image (runtime containers keep --network none or the internal network)",
           src.count("OS_PACKAGE_HOSTS") == 3 and src.count('pvol, "build"))') == 1 and
           src.count('r.proxy(inet, enet, pvol, "install")') == 1, src.count("OS_PACKAGE_HOSTS"))

    # through the gate: a registry build starts its proxy with those arguments (the engine double records the run)
    fake_trivy()
    n0 = len(double_calls())
    p = built_product("pregistry", {"Dockerfile": F + "RUN apk add --no-cache curl=8.14.1-r2\nUSER 65534\nCMD [\"app\"]\n"},
                      "images: []\nbuild:\n  network: registry\n")
    rc, out = trivy(p)
    runs = [c for c in double_calls()[n0:] if c and c[0] == "run" and "/p/egress_proxy.py" in c]
    tail = runs[0][runs[0].index("/p/egress_proxy.py") + 1:] if runs else []
    record(G, "through the gate: a build under build.network: registry starts one proxy with the package servers "
              "(tunnel and plain http), and the build passes",
           rc == 0 and len(runs) == 1 and tail[:1] == ["3128"] and tail[1:] == build, (rc, tail, out[-500:]))

    allowed, http_allowed = build[:cut], build[cut + 1:]
    off = {}
    for host in ("example.com", "dl-cdn.alpinelinux.org.evil.example", "evil-deb.debian.org"):
        off[host] = ask(b"CONNECT %s:443 HTTP/1.1\r\nHost: x\r\n\r\n" % host.encode(), allowed, http_allowed)
    record(G, "a host off the list is refused during a build (CONNECT: example.com, a look-alike suffix and prefix): "
              "403, nothing dialled",
           all(r[0].startswith("HTTP/1.1 403") and not r[2] for r in off.values()), off)
    plain = {
        "off-list host": b"GET http://example.com/x HTTP/1.1\r\nHost: example.com\r\n\r\n",
        "listed host, port 8080": b"GET http://deb.debian.org:8080/debian/ HTTP/1.1\r\nHost: x\r\n\r\n",
        "listed host, POST": b"POST http://deb.debian.org/debian/ HTTP/1.1\r\nHost: x\r\n\r\n",
        "user info": b"GET http://u@deb.debian.org/debian/ HTTP/1.1\r\nHost: x\r\n\r\n",
        "a registry over http": b"GET http://registry.npmjs.org/ HTTP/1.1\r\nHost: x\r\n\r\n",
    }
    got = {k: ask(v, allowed, http_allowed) for k, v in plain.items()}
    record(G, "plain http is refused to every host but a listed package server, to every port but 80, and for every "
              "method but GET and HEAD (403, nothing dialled)",
           all(r[0].startswith("HTTP/1.1 403") and not r[2] for r in got.values()), got)
    r = ask(b"GET http://deb.debian.org/debian/dists/bookworm/InRelease HTTP/1.1\r\nHost: deb.debian.org\r\n"
            b"Proxy-Authorization: Basic eDp5\r\nConnection: keep-alive\r\nUser-Agent: Debian APT-HTTP/1.3\r\n\r\n",
            allowed, http_allowed, upstream=b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    record(G, "a listed package server over plain http gets one origin-form request on port 80 (Host set, Connection: "
              "close, no proxy headers), and its answer comes back",
           r[2] == ["deb.debian.org:80"] and r[1].startswith("GET /debian/dists/bookworm/InRelease HTTP/1.1\r\n"
                                                             "Host: deb.debian.org\r\nConnection: close\r\n") and
           "Proxy-Authorization" not in r[1] and "keep-alive" not in r[1] and "User-Agent: Debian APT" in r[1] and
           r[0].endswith("\r\n\r\nok"), r)
    r = ask(b"CONNECT dl-cdn.alpinelinux.org:443 HTTP/1.1\r\nHost: x\r\n\r\n", allowed, http_allowed)
    record(G, "control: a listed package server is tunnelled (CONNECT :443, 200)",
           r[0].startswith("HTTP/1.1 200") and r[2] == ["dl-cdn.alpinelinux.org:443"], r)
    inst = confined.proxy_hosts("install")
    r1 = ask(b"CONNECT deb.debian.org:443 HTTP/1.1\r\nHost: x\r\n\r\n", inst)
    r2 = ask(b"GET http://deb.debian.org/debian/ HTTP/1.1\r\nHost: x\r\n\r\n", inst)
    record(G, "the install step's proxy still refuses the package servers (403) and plain http (405 Only CONNECT)",
           r1[0].startswith("HTTP/1.1 403") and r2[0].startswith("HTTP/1.1 405") and not r1[2] and not r2[2], (r1, r2))
    a, envb = confined.build_argv("r83", "t", "Dockerfile", confined.limits("build", {}), {})
    record(G, "a build with no build.network still has no network at all",
           a[a.index("--network") + 1] == "none" and envb == {"DOCKER_BUILDKIT": "1"}, a)


# ------------------------------------------------------------------ engine
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite083", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    text = open(p).read()
    record(G, "the engine suite has a rel083 group (2 checks), and its total is 79",
           es.PLAN.get("test_rel083") == ("rel083", 2) and es.TOTAL == 79 and "test_rel083, (node,)" in text,
           (es.PLAN.get("test_rel083"), es.TOTAL))
    body = text.split("def test_rel083", 1)[1].split("\n# ", 1)[0] if "def test_rel083" in text else ""
    record(G, "it builds a tiny Alpine image FROM a pinned digest with one package pinned to the server's current "
              "version, through check_exec.build_image under build.network: registry, and checks the installed version",
           "alpine_version(" in body and "build083(check_exec, df, tools)" in body and '"network": "registry"' in body
           and "apk add --no-cache tini=%s" in body and re.search(r'ALPINE = "alpine:[0-9.]+@sha256:[0-9a-f]{64}"', text)
           and "[ALPINE]" in text, body[:300])
    record(G, "and checks that the build cannot reach a host off the list (refused by the proxy, 403) nor anything "
              "without the proxy, with a listed package server as the control",
           "https://example.com/" in body and "http://example.com/" in body and "-Y off" in body and
           "dl-cdn.alpinelinux.org" in body and '"403" in log2' in body, body[-600:])


# ------------------------------------------------------------------ docs
def test_docs():
    G = "docs"
    inst = open(os.path.join(REPO, "docs", "INSTALL.md")).read()
    sec = inst.split("## Updating from 0.8.2 to 0.8.3", 1)[1].split("\n## ", 1)[0] if \
        "## Updating from 0.8.2 to 0.8.3" in inst else ""
    record(G, "INSTALL has the 0.8.2 to 0.8.3 update section, with the suites, the engine total and the hosts",
           "tests/rel083/run.py" in sec and "79 checks" in sec and all(h in sec for h in OS_HOSTS) and
           "--only rel083" in sec, sec[:300])
    rep = os.path.join(REPO, "docs", "release-0.8.3-report.md")
    record(G, "the report exists", os.path.exists(rep) and "0.8.3" in open(rep).read())
    readme = open(os.path.join(REPO, "README.md")).read()
    record(G, "the README lists the suite", "tests/rel083/run.py" in readme)
    v = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))["version"]
    record(G, "the plugin's version is 0.8.3", v == "0.8.3", v)


def main():
    try:
        for t in (test_lint, test_proxy, test_engine, test_docs):
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
    print("\n%d checks, %d passed, %d failed, 0 skipped (%d s)" % (n, n - len(bad), len(bad), time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
