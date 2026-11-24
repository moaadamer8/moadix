#!/usr/bin/python3
"""0.8.2 suite: image vulnerabilities with no fixed version, and exempted acceptance criteria (MF-66). Written before
the fix; on 0.8.1 (867970f) its fix checks fail.

    /usr/bin/python3 tests/rel082/run.py

  trivy  check-trivy on a declared image (`images:`): a High or Critical with a fixed version fails, and listing it as
         accepted residual risk changes nothing; one with no fixed version does not fail by itself: it is listed in
         the evidence (trivy-unfixed.json: CVE, package, image digest, scan date) and must be listed under "Residual
         risk" in the scope's 09-security-report.md with the operator's acceptance, or it fails; every scan checks
         again, so one that gets a fix fails. The filesystem scan is unchanged. A fake pinned trivy writes canned
         JSON: no network, no image, no real scan.
  built  check-trivy builds the images the gate builds from the product's Dockerfiles (the shipped image, each
         compose build, tests/gate/*) through the engine double, saves each, scans it offline after the build and
         before the run's cleanup, and records it by digest (trivy-built.json); a built image with a fixable High
         fails even when its base is declared under images:, one without it passes, the residual-risk rule applies,
         an unbuildable Dockerfile fails, and the build proxy's allowed hosts are unchanged.
  ac    MF-66: the ac-coverage-critic's check (check-verifiers) reads the adopted traceability-exemptions.yaml: an
         exempted acceptance criterion (untested-ac, or every criterion of an untested-story) passes with no test; a
         criterion not exempted, or an entry without a reason, still fails.

Fixtures only: throwaway repos under $TMPDIR, a fake trivy, the engine double, the stub checker.
"""
import base64
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

E = fixtures.Env("r82").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import pathmap, state  # noqa: E402
import contract_fixture  # noqa: E402

RESULTS = []
T0 = time.time()
OLD = "867970f"  # 0.8.1
SD = "." + "sdlc"
IMG = "registry.example/fixture-app:1.0"
DIGEST = "registry.example/fixture-app@sha256:" + "ab" * 32
SCANNED = "2026-11-20T09:15:00.000000Z"
CVE_FIX, CVE_OPEN, CVE_CRIT = "CVE-2099-0001", "CVE-2099-0002", "CVE-2099-0003"
OPERATOR = "the-operator"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def git(p, *args):
    return subprocess.run(["/usr/bin/git", "-C", p] + list(args), capture_output=True, text=True).stdout.strip()


def old_home(files):
    """A copy of the fixture gate with 0.8.1's files (the control)."""
    h = os.path.join(E.base, "home081-" + "-".join(re.sub(r"[^a-z0-9]", "", f.rsplit("/", 1)[-1]) for f in files))
    if not os.path.isdir(h):
        os.makedirs(h)
        for n in os.listdir(E.home):
            if n == "gate":
                shutil.copytree(os.path.join(E.home, n), os.path.join(h, n), symlinks=True)
            else:
                os.symlink(os.path.join(E.home, n), os.path.join(h, n))
        for rel in files:
            p = subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:%s" % (OLD, rel)], capture_output=True,
                               text=True)
            with open(os.path.join(h, rel), "w") as f:
                f.write(p.stdout)
    return h


def in_home(home, code, cwd):
    r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path[:0] = [%r, %r]\n%s" % (
        home, os.path.join(home, "gate", "v1"), code)], capture_output=True, text=True, cwd=cwd, timeout=120,
        env=E.env())
    return r.stdout + r.stderr


# ------------------------------------------------------------------ trivy
FAKE_TRIVY = """#!/usr/bin/python3
# Fixture trivy (tests/rel082): no network, no layers. `image --download-db-only` succeeds; `fs` reports nothing;
# `image ... --output <file> <image>` copies canned-image.json; `image ... --input <tar>` reads the engine double's
# saved record and reports, from canned-built.json, each vulnerability whose marker its Dockerfile contains, and
# records the image ID it was handed in its own report (FixtureScan): confined, it may write only --output.
import json, os, sys, tarfile
d = os.path.dirname(os.path.realpath(__file__))
a = sys.argv[1:]
def opt(f):
    return a[a.index(f) + 1] if f in a and a.index(f) + 1 < len(a) else None
out = opt("--output")
if a[0] == "fs":
    open(out, "w").write('{"Results": []}')
elif a[0] == "image" and out and opt("--input"):
    with tarfile.open(opt("--input")) as tf:
        rec = json.load(tf.extractfile("moadix-double-image.json"))
    rules = json.load(open(os.path.join(d, "canned-built.json")))
    vulns = [v for marker, v in rules if marker in rec["dockerfile"]]
    json.dump({"SchemaVersion": 2, "CreatedAt": "2026-11-22T10:00:00Z", "ArtifactName": opt("--input"),
               "ArtifactType": "container_image", "Metadata": {"ImageID": rec["id"], "RepoDigests": []},
               "Results": [{"Target": "built (debian 12.9)", "Vulnerabilities": vulns}],
               # what this double was handed, in its own report: under sandbox-exec it may write only --output
               "FixtureScan": {"input": rec["id"], "network": os.environ.get("HTTPS_PROXY", "")}}, open(out, "w"))
elif a[0] == "image" and out:
    open(out, "w").write(open(os.path.join(d, "canned-image.json")).read())
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
    if not os.path.exists(os.path.join(d, "canned-built.json")):
        with open(os.path.join(d, "canned-built.json"), "w") as f:
            f.write("[]")
    return d


def canned(tdir, vulns, digest=None):
    doc = {"SchemaVersion": 2, "CreatedAt": SCANNED, "ArtifactName": IMG, "ArtifactType": "container_image",
           "Metadata": {"ImageID": "sha256:" + "cd" * 32, "RepoDigests": [digest or DIGEST]},
           "Results": [{"Target": "%s (debian 12.9)" % IMG, "Class": "os-pkgs", "Type": "debian",
                        "Vulnerabilities": vulns}]}
    with open(os.path.join(tdir, "canned-image.json"), "w") as f:
        json.dump(doc, f)


def vuln(cve, pkg, sev, fixed=None):
    v = {"VulnerabilityID": cve, "PkgName": pkg, "InstalledVersion": "1.2.3-1", "Severity": sev}
    if fixed:
        v["FixedVersion"] = fixed
    return v


def report(*lines):
    return "# Security report\n\n## Scope\n\nThe fixture image.\n\n## Residual risk\n\n" + \
        "".join("%s\n" % ln for ln in lines) + "\n## Sign-off\n\nNone yet.\n"


def accepted(cve, pkg, who=OPERATOR, date="2026-11-21"):
    return "- %s in %s (%s): no fixed version upstream; not reachable from the app. Accepted by %s %s." % (
        cve, pkg, DIGEST, who, date)


def scan_product(name, report_text=None):
    return built_product(name, {} if report_text is None else {"sdlc/09-security-report.md": report_text},
                         "images:\n  - %s\n" % IMG)  # unquoted: 0.8.2 reads it as a string


def built_product(name, files, tools):
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


def set_report(p, text):
    E.write(p, "sdlc/09-security-report.md", text)
    E.commit(p, "report")


def check(p, module, *args, home=None):
    home = home or E.home
    e = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes")
    e.pop("MOADIX_PHASE_DOC", None)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(home, "gate", "v1", "_launch.py"),
                     os.path.join(home, "gate", "v1", module + ".py")] + list(args), cwd=p, env=e, timeout=300)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def trivy(p, home=None):
    return check(p, "check_scanners", "--tool", "trivy", home=home)


def unfixed_evidence(p):
    d = os.path.join(p, SD, "evidence", "9")
    hd = git(p, "rev-parse", "HEAD")[:12]
    f = os.path.join(d, "trivy-unfixed-%s.json" % hd)
    if not os.path.exists(f):
        return None, None
    idx = [json.loads(ln) for ln in open(os.path.join(p, SD, "evidence", "index.jsonl"))]
    line = next((i for i in idx if i["path"].endswith("trivy-unfixed-%s.json" % hd)), None)
    return json.load(open(f)), line


def test_trivy():
    G = "trivy"
    tdir = fake_trivy()
    old = old_home(["gate/v1/check_scanners.py"])
    old_yaml = old_home(["gate/v1/hlib.py"])

    # 1. a fixable High fails, and the report cannot accept it away
    canned(tdir, [vuln(CVE_FIX, "libfixable", "HIGH", fixed="1.2.4-1")])
    p = scan_product("tfix", report(accepted(CVE_FIX, "libfixable")))
    rc, out = trivy(p)
    record(G, "a High with a fixed version fails (FAIL [high], fixed in ...)",
           rc == 1 and re.search(r"FAIL  \[high\] %s .*libfixable@1\.2\.3-1.*\(fixed in 1\.2\.4-1\)" % CVE_FIX, out),
           out[-800:])
    record(G, "listing a fixable High as accepted residual risk does not let it through", rc == 1 and
           "RESIDUAL" not in out, out[-600:])
    canned(tdir, [vuln(CVE_FIX, "libfixable", "CRITICAL", fixed="1.2.4-1")])
    rc, out = trivy(p)
    record(G, "a Critical with a fixed version fails too", rc == 1 and "FAIL  [critical] %s" % CVE_FIX in out,
           out[-600:])
    import waivers
    record(G, "high and critical stay unwaivable (waivers.py unchanged)",
           set(waivers.RULES.get("unwaivable_severities") or []) >= {"high", "critical"}
           if hasattr(waivers, "RULES") else "\"unwaivable_severities\": [\"high\", \"critical\"]" in
           open(os.path.join(E.home, "gate", "v1", "waivers.py")).read(), "")

    # 2. an unfixed High fails until an APPROVE 9 accepts it; text the agent writes never does
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH")])
    q = scan_product("tmiss")
    rc, out = trivy(q)
    record(G, "an unfixed High with no APPROVE 9 fails, saying the operator accepts it only with APPROVE 9",
           rc == 1 and "FAIL  [high] %s" % CVE_OPEN in out and "not in the set the operator accepted with an APPROVE 9 "
           "(none yet): REVIEW 9 lists it, and APPROVE 9 records the set" in out, out[-800:])
    un = [json.loads(ln.strip()[len("UNFIXED "):]) for ln in out.splitlines() if ln.strip().startswith("UNFIXED {")]
    record(G, "it prints its UNFIXED line (CVE, package, image digest; not accepted) and UNFIXED-ONLY, its only failure",
           len(un) == 1 and un[0]["cve"] == CVE_OPEN and un[0]["package"] == "libopen" and un[0]["digest"] == DIGEST
           and un[0]["accepted_seq"] is None and out.rstrip().endswith("UNFIXED-ONLY"), out[-600:])
    for what, text in (("an agent-written `Accepted by` line under Residual risk", report(accepted(CVE_OPEN, "libopen"))),
                       ("the same line with any operator name and date", report(accepted(CVE_OPEN, "libopen",
                                                                                     who="the-security-lead")))):
        set_report(q, text)
        rc, out = trivy(q)
        record(G, "CORPUS: %s, with no APPROVE 9, does not pass" % what,
               rc == 1 and "FAIL  [high] %s" % CVE_OPEN in out and "RESIDUAL" not in out, out[-600:])
    record(G, "the report line is noted as documentation only, never acceptance",
           "documented in sdlc/09-security-report.md:9 (documentation only, not acceptance)" in out, out[-600:])
    ev, line = unfixed_evidence(q)
    u = (ev or {}).get("unfixed") or [{}]
    record(G, "the evidence lists it: CVE, package, image, image digest, scan date (trivy-unfixed.json, indexed)",
           ev is not None and len(u) == 1 and u[0].get("cve") == CVE_OPEN and u[0].get("package") == "libopen" and
           u[0].get("image") == IMG and u[0].get("digest") == DIGEST and u[0].get("scan_date") == SCANNED and
           line and line.get("tool") == "trivy" and line.get("source_commit") == git(q, "rev-parse", "HEAD"),
           (ev, line))
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH"), vuln(CVE_FIX, "libfixable", "HIGH", fixed="1.2.4-1")])
    rc, out = trivy(q)
    record(G, "with a fixable High beside it, no UNFIXED-ONLY (an APPROVE cannot accept a fixable finding)",
           rc == 1 and "UNFIXED-ONLY" not in out and "UNFIXED {" in out, out[-600:])
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH", fixed="1.2.4-1")])
    rc, out = trivy(q)
    record(G, "once it has a fixed version it is an ordinary failing finding and leaves the unfixed list",
           rc == 1 and re.search(r"FAIL  \[high\] %s .*\(fixed in 1\.2\.4-1\)" % CVE_OPEN, out) and
           "UNFIXED" not in out and (unfixed_evidence(q)[0] or {}).get("unfixed") == [], out[-800:])
    canned(tdir, [vuln("CVE-2099-0009", "libmed", "MEDIUM")])
    rc, out = trivy(q)
    record(G, "an unfixed Medium is reported as before (find, not residual risk)",
           rc == 0 and "find  [medium] CVE-2099-0009" in out and "UNFIXED" not in out, out[-600:])

    # 3. scope and helpers
    canned(tdir, [])
    rc, out = trivy(q)
    record(G, "no image findings -> passes, with an empty trivy-unfixed.json", rc == 0 and
           "0 high/critical image vulnerability(ies) with no fixed version" in out, out[-600:])
    import check_scanners as cs
    fs = cs.trivy_findings({"Results": [{"Target": "package-lock.json", "Vulnerabilities": [
        vuln(CVE_OPEN, "libopen", "HIGH")]}]}, "fs")
    record(G, "the filesystem scan still reports an unfixed High as a failing finding (images only)",
           fs and fs[0][0] == "high", fs)
    sec = cs.residual_section(report(accepted(CVE_OPEN, "libopen")) + "\n## Residual risks (later)\n\nmore\n")
    record(G, "the residual-risk section ends at the next heading of its level",
           any(CVE_OPEN in ln for _n, ln in sec) and not any("None yet" in ln for _n, ln in sec), sec)
    import hlib
    y = hlib.parse_yaml("images:\n  - postgres:17\n  - %s\n  - http://h/x\nl:\n  - id: 0\n    n: 1\n  - k: a:b\n" % DIGEST)
    record(G, "YAML: an unquoted list item with a colon (- postgres:17, - repo@sha256:...) stays a string; a key "
              "with `: ` still starts a map", y == {"images": ["postgres:17", DIGEST, "http://h/x"],
                                                    "l": [{"id": 0, "n": 1}, {"k": "a:b"}]}, y)
    old_y = in_home(old_yaml, "import hlib; print(hlib.parse_yaml('images:\\n  - postgres:17\\n'))", q)
    record(G, "control (0.8.1): the same item was read as a map", "{'postgres': 17}" in old_y or
           "{'postgres': '17'}" in old_y, old_y)

    # 4. the control: 0.8.1 has no unfixed set
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH")])
    rc, out = trivy(q, home=old)
    record(G, "control (0.8.1): an unfixed High fails as an ordinary finding, with no UNFIXED set for APPROVE",
           rc == 1 and "FAIL  [high] %s" % CVE_OPEN in out and "UNFIXED" not in out, out[-600:])


# ------------------------------------------------------------------ built (images the gate builds)
BASE = "registry.example/fixture-base@sha256:" + "ef" * 32
CVE_BUILT, CVE_BUILT_OPEN = "CVE-2099-0101", "CVE-2099-0102"
DF_VULN = "FROM %s\nRUN install-libvuln\nUSER 65534\nCMD [\"app\"]\n" % BASE
DF_CLEAN = "FROM %s\nRUN true\nUSER 65534\nCMD [\"app\"]\n" % BASE
COMPOSE = ("services:\n  app:\n    build:\n      context: .\n      dockerfile: Dockerfile\n"
           "  worker:\n    build:\n      context: worker\n")


def built_rules(tdir, rules):
    with open(os.path.join(tdir, "canned-built.json"), "w") as f:
        json.dump(rules, f)


def double_calls():
    try:
        return [json.loads(ln) for ln in open(os.path.join(E.base, "engine-double", "calls.log"))]
    except OSError:
        return []


def built_evidence(p):
    f = os.path.join(p, SD, "evidence", "9", "trivy-built-%s.json" % git(p, "rev-parse", "HEAD")[:12])
    return json.load(open(f)) if os.path.exists(f) else None


def test_built():
    G = "built"
    tdir = fake_trivy()
    canned(tdir, [])  # the declared base is clean
    built_rules(tdir, [["install-libvuln", vuln(CVE_BUILT, "libvuln", "HIGH", fixed="2.0.1-1")]])
    tools = "images:\n  - %s\n" % BASE

    # 1. a built image with a fixable High fails even when its base is declared
    n0 = len(double_calls())
    p = built_product("bvuln", {"Dockerfile": DF_VULN}, tools)
    rc, out = trivy(p)
    record(G, "a built image with a fixable High fails even when its base is declared (and the base scan is clean)",
           rc == 1 and re.search(r"FAIL  \[high\] %s image built shipped image \(Dockerfile\) libvuln@1\.2\.3-1 .*"
                                 r"\(fixed in 2\.0\.1-1\)" % CVE_BUILT, out) and "1 declared image(s): %s" % BASE in out,
           out[-900:])
    calls = double_calls()[n0:]
    builds = [c for c in calls if c and c[0] == "build"]
    saves = [i for i, c in enumerate(calls) if c and c[0] == "save"]
    record(G, "the gate built it from the product's Dockerfile, confined as the live gates build it (no network, "
              "the run's labels)", len(builds) == 1 and "--network" in builds[0] and
           builds[0][builds[0].index("--network") + 1] == "none" and any(x.startswith("moadix.run=x") for x in builds[0]),
           builds)
    cleanup = [i for i, c in enumerate(calls) if c[:2] == ["ps", "-aq"] and any("label=moadix.run=x" in x for x in c)]
    record(G, "scanned after the build and before the run's cleanup (save, then close)",
           saves and cleanup and saves[0] > calls.index(builds[0]) and saves[0] < cleanup[-1], (saves, cleanup))
    ev = built_evidence(p)
    imgs = (ev or {}).get("built") or [{}]
    ids = [x["id"] for x in json.load(open(os.path.join(E.base, "engine-double", "state.json")))["images"]
           if x.get("tag")]
    record(G, "the evidence records the built image by its digest (trivy-built.json: image, Dockerfile, digest, "
              "scan date, report)", ev is not None and len(imgs) == 1 and imgs[0].get("digest") in ids and
           imgs[0]["digest"].startswith("sha256:") and imgs[0].get("dockerfile") == "Dockerfile" and
           imgs[0].get("scan_date") and imgs[0].get("report") == "trivy-built-1.json" and
           ("trivy scanned 1 image(s) the gate built: shipped image (Dockerfile) %s" % imgs[0].get("digest")) in out,
           (ev, out[-400:]))
    rf = os.path.join(p, SD, "evidence", "9", "trivy-built-1-%s.json" % git(p, "rev-parse", "HEAD")[:12])
    scans = [json.load(open(rf)).get("FixtureScan") or {}] if os.path.exists(rf) else []
    record(G, "trivy scanned the saved image offline (its --input, the same image ID)",
           scans and scans[-1].get("input") == imgs[0].get("digest") and not scans[-1].get("network"), scans[-1:])

    # 2. a built image without that High passes
    q = built_product("bclean", {"Dockerfile": DF_CLEAN}, tools)
    rc, out = trivy(q)
    record(G, "a built image without that High passes", rc == 0 and "the gate built: shipped image (Dockerfile) sha256:"
           in out and CVE_BUILT not in out, out[-700:])

    # 3. the phase 9 rule applies to built images: an unfixed High is in the unfixed set, by the built image's digest
    built_rules(tdir, [["install-libvuln", vuln(CVE_BUILT_OPEN, "libvuln", "HIGH")]])
    r = built_product("bopen", {"Dockerfile": DF_VULN}, tools)
    set_report(r, report("- %s in libvuln (the built app image): no fix upstream. Accepted by %s 2026-11-22." % (
        CVE_BUILT_OPEN, OPERATOR)))
    rc, out = trivy(r)
    un = [json.loads(ln.strip()[len("UNFIXED "):]) for ln in out.splitlines() if ln.strip().startswith("UNFIXED {")]
    record(G, "an unfixed High in a built image fails without an APPROVE 9, even with an `Accepted by` line; its "
              "UNFIXED line names the built image's digest", rc == 1 and "FAIL  [high] %s" % CVE_BUILT_OPEN in out and
           len(un) == 1 and un[0]["digest"].startswith("sha256:") and un[0]["image"] == "built shipped image (Dockerfile)"
           and out.rstrip().endswith("UNFIXED-ONLY"), (out[-700:], un))

    # 4. which Dockerfiles: the shipped image, compose builds (no repeat), tests/gate/*; not others
    built_rules(tdir, [])
    s = built_product("bset", {"Dockerfile": DF_CLEAN, "worker/Dockerfile": DF_CLEAN, "compose.yaml": COMPOSE,
                               "tests/gate/Dockerfile.e2e": DF_CLEAN, "docs/example/Dockerfile": DF_CLEAN},
                      tools + "live:\n  compose: compose.yaml\n")
    rc, out = trivy(s)
    ev = built_evidence(s) or {}
    got = sorted((b["context"], b["dockerfile"]) for b in ev.get("built") or [])
    record(G, "the shipped image, each compose build and each tests/gate/ Dockerfile are built and scanned, once each",
           rc == 0 and got == [(".", "Dockerfile"), (".", "tests/gate/Dockerfile.e2e"), ("worker", "Dockerfile")],
           (got, out[-500:]))
    record(G, "a Dockerfile elsewhere (docs/) is not built (trivy fs still reads it)",
           "docs/example" not in json.dumps(ev), ev)

    # 5. a Dockerfile the gate cannot build is a failure, never a silent pass
    t = built_product("bunpinned", {"Dockerfile": "FROM alpine:3.19\nCMD [\"app\"]\n"}, tools)
    rc, out = trivy(t)
    record(G, "an unpinned FROM cannot be built: check-trivy fails and says the image was not scanned",
           rc == 1 and "shipped image (Dockerfile) could not be built, so it was not scanned" in out and
           "not pinned by @sha256" in out, out[-600:])

    # 6. control and the proxy
    old = old_home(["gate/v1/check_scanners.py"])
    built_rules(tdir, [["install-libvuln", vuln(CVE_BUILT, "libvuln", "HIGH", fixed="2.0.1-1")]])
    rc, out = trivy(p, home=old)
    record(G, "control (0.8.1): the built image's fixable High is not seen; only the declared base is scanned",
           rc == 0 and CVE_BUILT not in out, out[-500:])
    # 0.8.3 widened the build proxy (the OS package servers); 0.8.2 itself left it as in 0.8.1
    diff = subprocess.run(["/usr/bin/git", "-C", REPO, "diff", OLD, "70ad949", "--", "gate/egress_proxy.py",
                           "gate/config/confinement.yaml"], capture_output=True, text=True).stdout
    record(G, "0.8.2 left the build proxy's allowed hosts unchanged (egress_proxy.py and confinement.yaml as in 0.8.1)",
           diff == "", diff[:400])


# ------------------------------------------------------------------ approve (acceptance is APPROVE 9)
KEEP9 = ("check-trivy", "check-sec-verification-9")
SEC4 = "sec_id,th_id,asvs_id,verification\nSEC-001,TH-001,V8.2.1,an authorization test per role\n"
SEC9 = "sec_id,method,evidence,result\nSEC-001,test,README.md,verified\n"


def narrow_phase9():
    """The fixture gate's phase 9 runs only check-trivy and check-sec-verification-9, so a REVIEW/APPROVE of phase 9
    turns on them alone (the other phase-9 validators need real scanners and documents)."""
    p = os.path.join(E.home, "gate", "config", "registry.yaml")
    text = open(p).read()
    head, body = text.split("components:\n", 1)
    blocks = re.split(r"(?m)^(?=  - id: )", body)
    keep = [b for b in blocks if not ("\n    kind: validator\n" in b and re.search(r"(?m)^    phase: 9$", b) and
                                      re.match(r"  - id: (\S+)", b).group(1) not in KEEP9)]
    with open(p, "w") as f:
        f.write(head + "components:\n" + "".join(keep))


def last_payload(p):
    from gate import state as gstate
    body = json.loads(E.ledger(p)[-1]["body"])
    return body, gstate.decode_payload(body)


def test_approve():
    G = "approve"
    from gate import validation
    tdir = fake_trivy()
    narrow_phase9()
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH")])
    p = built_product("apr", {"sdlc/4/SEC-CONTROLS.csv": SEC4, "sdlc/9/SEC-VERIFICATION.csv": SEC9,
                              "sdlc/09-security-report.md": report(accepted(CVE_OPEN, "libopen"))},
                      "images:\n  - %s\n" % IMG)
    approves_until(p, "aprfx", "9")
    ctx = E.review_until_fresh(p, "9", contract=False)
    record(G, "REVIEW 9 lists every unfixed High/Critical: CVE, package, image digest, not yet accepted, with the set's "
              "sha256", "Unfixed High/Critical image vulnerabilities (no fixed version; residual risk) (1, set sha256" in ctx
           and "%s [high] libopen@1.2.3-1 in %s (%s) NOT YET ACCEPTED" % (CVE_OPEN, IMG, DIGEST) in ctx and
           "APPROVE 9 records this set" in ctx and "FAIL" in ctx, ctx[-1200:])
    rc, out = trivy(p)
    record(G, "CORPUS: the agent-written `Accepted by` line in the committed report, with no APPROVE 9, does not pass",
           rc == 1 and "FAIL  [high] %s" % CVE_OPEN in out, out[-500:])

    # another validator failing: APPROVE refuses
    E.write(p, "sdlc/9/SEC-VERIFICATION.csv", "sec_id,method,evidence,result\nSEC-001,test,README.md,failed\n")
    E.commit(p, "a failed control")
    E.review_until_fresh(p, "9", contract=False)
    ctx = E.prompt(p, "APPROVE 9 %s" % E.fresh())
    record(G, "APPROVE 9 is refused while another validator fails too (only the unfixed set can be accepted)",
           "APPROVE NOT recorded" in ctx and "check-sec-verification-9" in ctx, ctx[-600:])
    E.write(p, "sdlc/9/SEC-VERIFICATION.csv", SEC9)
    E.commit(p, "control verified")
    E.review_until_fresh(p, "9", contract=False)
    n0 = len(E.ledger(p))
    ctx = E.prompt(p, "APPROVE 9 %s" % E.fresh())
    record(G, "APPROVE 9 is recorded when check-trivy's only failures are unfixed findings, and says what it accepts",
           len(E.ledger(p)) == n0 + 1 and "It accepts 1 unfixed High/Critical image finding(s) as residual risk" in ctx
           and "%s libopen (%s)" % (CVE_OPEN, DIGEST) in ctx, ctx[-800:])
    body, pl = last_payload(p)
    ua = pl.get("unfixed_accepted") or {}
    want = [{"cve": CVE_OPEN, "package": "libopen", "digest": DIGEST}]
    record(G, "its ledger line records the unfixed set (CVE, package, image digest) and the set's sha256",
           body.get("action") == "APPROVE 9" and ua.get("sha256") == validation.unfixed_digest(want) and
           [{k: f[k] for k in ("cve", "package", "digest")} for f in ua.get("findings") or []] == want and
           (pl.get("validation") or {}).get("passed_with_unfixed_accepted") is True, (body.get("action"), ua))
    seq = body.get("seq")

    # the next scans: only the recorded set passes
    rc, out = trivy(p)
    record(G, "the next check-trivy passes the accepted finding, naming the APPROVE's ledger seq",
           rc == 0 and "RESIDUAL [high] %s" % CVE_OPEN in out and "accepted by APPROVE 9 (ledger seq %s)" % seq in out,
           out[-600:])
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH"), vuln(CVE_CRIT, "libcrit", "CRITICAL")])
    rc, out = trivy(p)
    record(G, "a new unfixed finding fails until the next APPROVE 9 (the accepted one still passes)",
           rc == 1 and "FAIL  [critical] %s" % CVE_CRIT in out and "the last APPROVE 9 (ledger seq %s)" % seq in out and
           "RESIDUAL [high] %s" % CVE_OPEN in out and "FAIL  [high] %s" % CVE_OPEN not in out, out[-800:])
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH")], digest=IMG.split(":")[0] + "@sha256:" + "12" * 32)
    rc, out = trivy(p)
    record(G, "the same CVE in another image digest is a new finding: it fails (acceptance is bound to the digest)",
           rc == 1 and "FAIL  [high] %s" % CVE_OPEN in out, out[-600:])
    canned(tdir, [vuln(CVE_OPEN, "libopen", "HIGH", fixed="1.2.4-1")])
    rc, out = trivy(p)
    record(G, "once a fix exists, the accepted finding fails (an APPROVE never accepts a fixable one)",
           rc == 1 and re.search(r"FAIL  \[high\] %s .*\(fixed in 1\.2\.4-1\)" % CVE_OPEN, out) and
           "RESIDUAL" not in out, out[-600:])
    approve_built(tdir)


def unfixed_lines(out):
    return [json.loads(ln.strip()[len("UNFIXED "):]) for ln in out.splitlines() if ln.strip().startswith("UNFIXED {")]


def approve_built(tdir):
    """A built image's ID changes on every gate run (the run's label is in its config), so an APPROVE 9 binds a built
    image's unfixed finding to CVE, package, installed version and Dockerfile path, never to the ID."""
    G = "approve"
    from gate import validation
    canned(tdir, [])  # the declared base is clean
    built_rules(tdir, [["install-libvuln", vuln(CVE_BUILT_OPEN, "libvuln", "HIGH")]])
    p = built_product("bapr", {"sdlc/4/SEC-CONTROLS.csv": SEC4, "sdlc/9/SEC-VERIFICATION.csv": SEC9},
                      "images:\n  - %s\n" % BASE)
    E.write(p, "Dockerfile", DF_VULN)  # after INIT: a product with code at INIT is onboarded (scope B, no phase 9)
    E.commit(p, "the shipped image")
    approves_until(p, "baprfx", "9")
    E.review_until_fresh(p, "9", contract=False)
    n0 = len(E.ledger(p))
    ctx = E.prompt(p, "APPROVE 9 %s" % E.fresh())
    body, pl = last_payload(p)
    acc = (pl.get("unfixed_accepted") or {}).get("findings") or []
    first = acc[0].get("digest") if acc else None
    record(G, "APPROVE 9 on a built image's unfixed High records its Dockerfile path and installed version (the "
              "acceptance key), with this build's image ID for tracing",
           len(E.ledger(p)) == n0 + 1 and len(acc) == 1 and acc[0].get("dockerfile") == "Dockerfile" and
           acc[0].get("installed") == "1.2.3-1" and str(first).startswith("sha256:") and
           validation.unfixed_key(acc[0]) == ("built", CVE_BUILT_OPEN, "libvuln", "1.2.3-1", "Dockerfile"),
           (ctx[-500:], acc))
    seq = body.get("seq")
    rc, out = trivy(p)  # a second gate run: a new build of the same Dockerfile
    un = unfixed_lines(out)
    record(G, "the same Dockerfile built by the next gate run gets a new image ID, and the finding accepted in the "
              "first run still passes", rc == 0 and len(un) == 1 and un[0]["digest"] != first and
           un[0]["accepted_seq"] == seq and "RESIDUAL [high] %s" % CVE_BUILT_OPEN in out and
           "accepted by APPROVE 9 (ledger seq %s)" % seq in out, (first, un, out[-600:]))
    newer = dict(vuln(CVE_BUILT_OPEN, "libvuln", "HIGH"), InstalledVersion="1.2.5-1")
    built_rules(tdir, [["install-libvuln", newer]])
    rc, out = trivy(p)
    record(G, "a new installed version of the package is a new finding: it fails until the next APPROVE 9",
           rc == 1 and "FAIL  [high] %s" % CVE_BUILT_OPEN in out and "libvuln@1.2.5-1" in out, out[-600:])
    built_rules(tdir, [["install-libvuln", vuln(CVE_BUILT_OPEN, "libvuln", "HIGH")]])
    E.write(p, "tests/gate/Dockerfile.e2e", DF_VULN)
    E.commit(p, "an e2e image with the same package")
    rc, out = trivy(p)
    by = {u.get("dockerfile"): u for u in unfixed_lines(out)}
    record(G, "the same CVE in an image built from another Dockerfile is a new finding (the root one still passes)",
           rc == 1 and (by.get("Dockerfile") or {}).get("accepted_seq") == seq and
           (by.get("tests/gate/Dockerfile.e2e") or {}).get("accepted_seq") is None, (by, out[-600:]))


# ------------------------------------------------------------------ ac (MF-66)
PRD = """# PRD

### US-001 — Save a note

- **BRD goal:** BG-1
- **AC-1:** When the visitor submits a note, the system shall store it and show it in the list.
- **AC-2:** When the device is offline, the system shall queue the note and send it later.
- **AC-3:** When the note is empty, the system shall refuse it and say why.

### US-002 — Print a note

- **BRD goal:** BG-1
- **AC-1:** When the visitor prints a note, the system shall send it to the system print dialog.
"""
SRC = "export function save(notes: string[], n: string): string[] {\n  if (!n) throw new Error('empty');\n" \
      "  return [...notes, n];\n}\n"
TEST = "import { save } from '../src/notes';\n// US-001 AC-1\ntest('stores', () => {\n" \
       "  expect(save([], 'a')).toEqual(['a']);\n});\n// US-001 AC-3\ntest('refuses empty', () => {\n" \
       "  expect(() => save([], '')).toThrow();\n});\n"
OFFLINE = "the fixture cannot take the device offline; verified live in phase 10a"
PRINT = "the system print dialog cannot be driven from a unit test; verified live in phase 10a"


def head(p):
    return git(p, "rev-parse", "HEAD")


def approves_until(p, pid, target):
    for label in pathmap.LABELS[:pathmap.LABELS.index(target)]:
        pl = {"phase": label, "source_commit": head(p),
              "validation": {"verdict": "pass", "results": [], "digest": "sha256:fixture"}}
        r = E.checker("record", "--product", pid, "--action", "APPROVE %s" % label, "--code", E.fresh(),
                      "--payload-b64", base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
        assert r.returncode == 0, r.stdout + r.stderr
        state.append_line(p, r.stdout.strip())
    entries = [json.loads(ln["body"]) for ln in E.ledger(p)]
    state.write_phase(p, state.replay(pid, entries))


def ac_product(name, exemptions=None):
    p = E.repo(name, docs=("00-brd.md",))
    E.write(p, "sdlc/02-prd.md", PRD)
    E.write(p, ".gitignore", "node_modules/\n")
    E.commit(p, "docs")
    E.init(p, name)
    E.commit(p, "init")
    if exemptions is not None:
        E.write(p, ".sdlc-proposals/config/traceability-exemptions.yaml", exemptions)
        ctx = E.prompt(p, "ADOPT %s" % E.fresh())
        assert "traceability-exemptions.yaml" in ctx and "NOT" not in ctx, ctx
    approves_until(p, name, "8")
    E.write(p, "src/notes.ts", SRC)
    E.write(p, "tests/notes.test.ts", TEST)
    E.commit(p, "implement US-001")
    return p


def launch(p):
    payload = {"hook_event_name": "PreToolUse", "session_id": "r82", "cwd": p, "tool_name": "Agent",
               "tool_input": {"subagent_type": "moadix:ac-coverage-critic", "description": "check",
                              "prompt": "check coverage"}}
    _rc, out, _err = E.hook("pretool", payload)
    return ((out.get("hookSpecificOutput") or {}).get("updatedInput") or {}).get("prompt", "")


def evidence(p, prompt, coverage):
    ev = {"role": "ac-coverage-critic", "source_commit": head(p),
          "brief_sha256": re.search(r"^brief_sha256: ([0-9a-f]{64})$", prompt, re.M).group(1),
          "receipt": re.search(r"^receipt: ([0-9a-f]+)$", prompt, re.M).group(1),
          "reviewed": ["tests/notes.test.ts"], "findings": [], "coverage": coverage}
    ds = re.search(r'docset_sha256: "([0-9a-f]{64})"', prompt)
    if ds:
        ev["docset_sha256"] = ds.group(1)
    path = os.path.join(p, SD, "cache", "verify", "8", "ac-coverage-critic", "evidence", "findings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(ev, f, indent=1)


def check_verifiers(p, home=None):
    home = home or E.home
    ef = os.path.join(p, SD, "cache", "verify", "8", "gap-critic", "evidence", "CRITIC.json")
    try:
        cur = json.load(open(ef)).get("source_commit") == head(p)
    except (OSError, ValueError):
        cur = False
    if not cur:
        contract_fixture.critic(E, p, "8")
    r = subprocess.run([fixtures.PY, "-I", os.path.join(home, "gate", "v1", "_launch.py"),
                        os.path.join(home, "gate", "v1", "check_verifiers.py"), "--phase", "8"],
                       cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p), capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout + r.stderr).strip()


T1 = ["tests/notes.test.ts:3-5"]
T3 = ["tests/notes.test.ts:7-9"]


def test_ac():
    G = "ac"
    ex = ("exemptions:\n"
          "  - kind: untested-ac\n    ac: US-001/AC-2\n    reason: \"%s\"\n"
          "  - kind: untested-story\n    story: US-002\n    reason: \"%s\"\n" % (OFFLINE, PRINT))
    p = ac_product("racex", ex)
    prompt = launch(p)
    record(G, "the critic is launched in phase 8 with the gate's brief", "role: ac-coverage-critic" in prompt,
           prompt[:200])
    full = [{"ac": "US-001/AC-1", "tests": T1}, {"ac": "US-001/AC-2", "tests": []},
            {"ac": "US-001/AC-3", "tests": T3}, {"ac": "US-002/AC-1", "tests": []}]
    evidence(p, prompt, full)
    rc, out = check_verifiers(p)
    record(G, "MF-66: an exempted AC (untested-ac) with no test passes check-verifiers",
           rc == 0 and "US-001/AC-2 has no test" not in out, out[-900:])
    record(G, "the exempt ACs are printed with their reasons",
           "untested and exempt in traceability-exemptions.yaml: US-001/AC-2 (%s)" % OFFLINE in out and
           "untested and exempt in traceability-exemptions.yaml: US-002/AC-1 (%s)" % PRINT in out, out[-900:])
    record(G, "an untested-story exemption covers every AC of that story", "US-002/AC-1 has no test" not in out and
           rc == 0, out[-600:])
    evidence(p, prompt, [e for e in full if e["ac"] not in ("US-001/AC-2", "US-002/AC-1")])
    rc, out = check_verifiers(p)
    record(G, "an exempted AC may be left unmapped", rc == 0 and "is not mapped" not in out, out[-600:])
    evidence(p, prompt, [{"ac": "US-001/AC-1", "tests": T1}, {"ac": "US-001/AC-2", "tests": []},
                         {"ac": "US-001/AC-3", "tests": []}, {"ac": "US-002/AC-1", "tests": []}])
    rc, out = check_verifiers(p)
    record(G, "a non-exempted untested AC still fails", rc == 1 and "US-001/AC-3 has no test (untested acceptance "
           "criterion)" in out and "US-001/AC-2 has no test" not in out, out[-900:])
    evidence(p, prompt, [e for e in full if e["ac"] != "US-001/AC-3"])
    rc, out = check_verifiers(p)
    record(G, "a non-exempted AC left unmapped still fails", rc == 1 and "US-001/AC-3 is not mapped" in out, out[-600:])
    evidence(p, prompt, [{"ac": "US-001/AC-1", "tests": T1}, {"ac": "US-001/AC-2", "tests": ["tests/notes.test.ts:99"]},
                         {"ac": "US-001/AC-3", "tests": T3}, {"ac": "US-002/AC-1", "tests": []}])
    rc, out = check_verifiers(p)
    record(G, "a test an exempted AC does cite is still checked (a dead citation fails)",
           rc == 1 and "coverage US-001/AC-2" in out, out[-600:])

    # the control: 0.8.1 fails the exempted AC
    evidence(p, prompt, full)
    old = old_home(["gate/verify.py", "gate/v1/check_verifiers.py"])
    rc, out = check_verifiers(p, home=old)
    record(G, "control (0.8.1): the exempted AC fails check-verifiers", rc == 1 and "US-001/AC-2 has no test" in out,
           out[-600:])

    # an entry without a reason exempts nothing; no file exempts nothing
    q = ac_product("racnr", "exemptions:\n  - kind: untested-ac\n    ac: US-001/AC-2\n"
                            "  - kind: untested-story\n    story: US-002\n    reason: \"\"\n")
    pq = launch(q)
    evidence(q, pq, full)
    rc, out = check_verifiers(q)
    record(G, "an exemption with no reason exempts nothing", rc == 1 and "US-001/AC-2 has no test" in out and
           "US-002/AC-1 has no test" in out, out[-600:])
    r = ac_product("racno")
    pr = launch(r)
    evidence(r, pr, full)
    rc, out = check_verifiers(r)
    record(G, "without traceability-exemptions.yaml the untested ACs fail as before",
           rc == 1 and "US-001/AC-2 has no test" in out, out[-600:])


# ------------------------------------------------------------------ engine
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite082", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    text = open(p).read()
    record(G, "the engine suite has a rel082 group (4 checks), and its total is 79 (0.8.3: rel083 2)",
           es.PLAN.get("test_rel082") == ("rel082", 4) and es.TOTAL == 79 and "test_rel082, (node,)" in text,
           (es.PLAN.get("test_rel082"), es.TOTAL))
    body = text.split("def test_rel082", 1)[1].split("\n# ", 1)[0] if "def test_rel082" in text else ""
    record(G, "it builds a tiny image FROM a pinned image with the gate's own code, scans it with the real pinned trivy "
              "(trivy_prepare, scan_built with the suite's run id) and checks trivy-built.json's image ID",
           "cs.trivy_prepare(out)" in body and "cs.scan_built(" in body and "run_id=run_id" in body and
           "SMOKE_RUNS.append(run_id)" in body and '"trivy-built.json"' in body and "ImageID" in body and
           'confined.image("python")' in body, body[:300])


def main():
    try:
        for t in (test_trivy, test_built, test_approve, test_ac, test_engine):
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
