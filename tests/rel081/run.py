#!/usr/bin/python3
"""0.8.1 suite: the first product's phase 9 (task-tracker MF-60, MF-62 to MF-65, MF-52, and the 0.8.0 engine run's
anonymous volumes). Written before the fix; on 0.8.0 (c39a878) its fix checks fail.

    /usr/bin/python3 tests/rel081/run.py

  gitleaks   MF-63: an allowlist entry covers a test fixture's value quoted in a non-test file (a findings log), history
             included, only when it names an adopted fixture entry under tests/ whose finding has the same value
             (compared inside the gate), never under src/ or in configuration, always with a reason. Real gitleaks.
  security   MF-65: check-security's own secret scan applies the same adopted allowlist (0.8.0 ignored it, and no
             operator command could waive its findings); a value in src/, a different value, or an allowlist that was
             not adopted are still found
  surface    MF-64: the surface enumerator runs with the gate's pinned Node first on its PATH (0.8.0: execvp() of
             'node' failed); the product names no machine path
  st201      MF-60: the operator's adopted schemathesis.refusal-statuses (ADOPT checks them) make ST201 accept such a
             status for an operation whose contract documents it, and only there; the gate-owned st_config.py drives
             the real pinned Schemathesis in-process (WSGI) here, and the confined run's script uses it
  verifiers  MF-62: a verifier launched at this commit that has not written its evidence is STALE, never MISSING; the
             validator worker re-checks at its end and waits for running launches
  volumes    the engine run: an image's VOLUME (the official postgres image) leaves an anonymous volume unless the
             container is removed with --volumes (rm -v); the engine double now models it
  critic     MF-52: a gap-critic fix over 1,000 characters is cut with a marker, and the findings are read
  engine     the engine suite's rel081 group (real Schemathesis with 413 on the stack, and no volume left) and total

Fixtures only: throwaway repos under $TMPDIR, the engine double, the pinned tools from ~/.cache/moadix-tools.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r81").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import confined, validation  # noqa: E402
import contract_fixture  # noqa: E402  (after gate: it imports the gate itself)

RESULTS = []
SKIPPED = []
T0 = time.time()
OLD = "c39a878"  # 0.8.0
FIX76 = os.path.join(REPO, "tests", "fixtures", "smoke-076")
FIX80 = os.path.join(REPO, "tests", "fixtures", "smoke-080")
FIX81 = os.path.join(REPO, "tests", "fixtures", "smoke-081")
DBL = os.path.join(E.base, "engine-double")
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
TOOLS = os.path.expanduser("~/.cache/moadix-tools")
SD = "." + "sdlc"
WORD = "Granite-" + "Willow-4410"   # the test fixture's password (assembled: this file holds no literal)
OTHER = "Copper-" + "Lantern-5827"  # another value of the same shape, which gitleaks flags too
SPEC = 'const PASSWORD = "%s";\nexport const signUp = () => PASSWORD;\n' % WORD
TT = "tests/ui/core-loop.spec.ts"
REASON = "the throwaway account's password the UI test signs up with"
QREASON = "the findings log quotes the UI test's throwaway password"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def skip(group, name, why):
    SKIPPED.append((group, name))
    print("SKIP  [%s] %s (%s)" % (group, name, why))


def git(p, *args):
    return subprocess.run(["/usr/bin/git", "-C", p] + list(args), capture_output=True, text=True).stdout.strip()


def old_home(files):
    """A copy of the fixture gate with 0.8.0's files (the control)."""
    h = os.path.join(E.base, "home080-" + "-".join(re.sub(r"[^a-z0-9]", "", f.rsplit("/", 1)[-1]) for f in files))
    if not os.path.isdir(h):
        os.makedirs(h)
        for n in os.listdir(E.home):
            if n == "gate":
                shutil.copytree(os.path.join(E.home, n), os.path.join(h, n), symlinks=True)
            else:
                os.symlink(os.path.join(E.home, n), os.path.join(h, n))
        for rel in files:
            p = subprocess.run(["/usr/bin/git", "-C", REPO, "show", "%s:%s" % (OLD, rel)], capture_output=True, text=True)
            target = os.path.join(h, rel)
            if p.returncode != 0:  # new in 0.8.1: 0.8.0 had no such file
                if os.path.exists(target):
                    os.unlink(target)
                continue
            with open(target, "w") as f:
                f.write(p.stdout)
    return h


def install_tool(name):
    import toolrun
    d = "%s-%s" % (name, toolrun.pins()[name]["version"])
    os.makedirs(os.path.join(E.home, "tools"), exist_ok=True)
    if not os.path.exists(os.path.join(E.home, "tools", d)):
        os.symlink(os.path.join(TOOLS, d), os.path.join(E.home, "tools", d))
    return os.path.isdir(os.path.join(TOOLS, d))


def check(p, module, *args, home=None, **env):
    home = home or E.home
    e = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", **env)
    e.pop("MOADIX_PHASE_DOC", None)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(home, "gate", "v1", "_launch.py"),
                     os.path.join(home, "gate", "v1", module + ".py")] + list(args), cwd=p, env=e, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def in_home(home, code, cwd, env=None):
    r = subprocess.run([sys.executable, "-I", "-c", "import sys, json; sys.path[:0] = [%r, %r]\n%s" % (
        home, os.path.join(home, "gate", "v1"), code)], capture_output=True, text=True, cwd=cwd, timeout=300,
        env=env or E.env())
    return r.stdout + r.stderr


def plain_product(name, files, msg="fixture"):
    p = E.repo(name, docs=())
    for rel, text in files.items():
        E.write(p, rel, text)
    E.commit(p, msg)
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    return p


def entry(fp, path, reason=REASON, fixture="true", same=None, extra=""):
    s = "    - fingerprint: \"%s\"\n      path: %s\n" % (fp, path)
    if reason is not None:
        s += "      reason: \"%s\"\n" % reason
    if same is not None:
        s += "      same-value-as: \"%s\"\n" % same
    elif fixture is not None:
        s += "      fixture: %s\n" % fixture
    return s + extra


def adopt(p, text):
    shutil.rmtree(os.path.join(p, ".sdlc-proposals"), ignore_errors=True)
    E.write(p, ".sdlc-proposals/config/product-tools.yaml", text)
    return E.prompt(p, "ADOPT %s" % E.fresh())


def allowed(out):
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("ALLOWLISTED ")]


def first_commit(p, rel):
    return git(p, "log", "--format=%H", "--diff-filter=A", "--", rel).splitlines()[-1]


# ------------------------------------------------------------------ gitleaks (MF-63)
def test_gitleaks():
    G = "gitleaks"
    if not install_tool("gitleaks"):
        record(G, "the pinned gitleaks is installed (managed/fetch_tools.py ~/.cache/moadix-tools)", False, TOOLS)
        return
    import gitleaks_allow as GA
    doc = "# Findings\n\n    const PASSWORD = \"%s\";\n\nMore text.\n" % WORD
    p = plain_product("glq", {TT: SPEC, "docs/findings.md": doc, "src/app.js": "export const x = 1;\n"})
    d = first_commit(p, "docs/findings.md")
    E.write(p, "docs/findings.md", "# Findings\n\n    const PASSWORD = \"<the fixture's password>\";\n\nMore text.\n")
    E.commit(p, "stop quoting the password")
    t = first_commit(p, TT)
    ftree, fhist = "%s:generic-api-key:1" % TT, "%s:%s:generic-api-key:1" % (t, TT)
    dhist = "%s:docs/findings.md:generic-api-key:3" % d
    fixtures_ = entry(ftree, TT) + entry(fhist, TT)
    good = {"fingerprint": dhist, "path": "docs/findings.md", "reason": QREASON, "same-value-as": ftree}
    fx = {"fingerprint": ftree, "path": TT, "reason": REASON, "fixture": True}
    old = in_home(old_home(("gate/v1/gitleaks_allow.py",)), "import gitleaks_allow as G\nprint(json.dumps(G.problems("
                  "%s)))" % json.dumps([fx, good]).replace("true", "True"), p)
    record(G, "control: on 0.8.0 no entry can cover a quote of the fixture in docs/ (its history hit stays high for good)",
           "not a file under tests/" in old and "docs/findings.md" in old, old[-400:])
    record(G, "a same-value-as entry for a quote in docs/ (or README.md), naming an adopted fixture entry under tests/, "
              "is accepted", not GA.problems([fx, good]) and not GA.problems([fx, dict(good, path="README.md",
                                                                                         fingerprint="README.md:x:2")]),
           GA.problems([fx, good]))
    lib = {"fingerprint": "lib/fixtures/a.js:generic-api-key:1", "path": "lib/fixtures/a.js", "reason": REASON,
           "fixture": True}
    cases = {
        "a quote in src/": dict(good, path="src/notes.md", fingerprint="src/notes.md:generic-api-key:3"),
        "a quote under src/ deeper": dict(good, path="app/src/a.md", fingerprint="app/src/a.md:generic-api-key:3"),
        "a quote in a config directory": dict(good, path="config/notes.md", fingerprint="config/notes.md:x:3"),
        "a quote in .env": dict(good, path=".env", fingerprint=".env:generic-api-key:3"),
        "a quote in a dot-directory": dict(good, path=".github/a.md", fingerprint=".github/a.md:x:3"),
        "a quote in YAML configuration": dict(good, path="docs/app.yaml", fingerprint="docs/app.yaml:x:3"),
        "a quote in JSON": dict(good, path="docs/app.json", fingerprint="docs/app.json:x:3"),
        "a quote in a Dockerfile": dict(good, path="Dockerfile", fingerprint="Dockerfile:x:3"),
        "a quote in env.example": dict(good, path="env.example", fingerprint="env.example:x:3"),
        "same-value-as naming no entry of the list": dict(good, **{"same-value-as": "tests/other.ts:generic-api-key:9"}),
        "same-value-as naming itself": dict(good, **{"same-value-as": dhist}),
        "same-value-as naming a fixture outside tests/": dict(good, **{"same-value-as": lib["fingerprint"]}),
        "same-value-as naming another quote": dict(good, fingerprint="docs/b.md:x:1", path="docs/b.md",
                                                   **{"same-value-as": dhist}),
        "same-value-as and fixture: true together": dict(good, fixture=True),
        "no reason": {k: v for k, v in good.items() if k != "reason"},
        "a one-word reason": dict(good, reason="quote"),
        "a glob path": dict(good, path="docs/*", fingerprint="docs/*:x:3"),
        "no fingerprint (a whole file)": {k: v for k, v in good.items() if k != "fingerprint"},
    }
    wrong = [k for k, v in cases.items() if not GA.problems([fx, lib, good, v] if "another quote" in k else [fx, lib, v])]
    record(G, "a quote entry is refused under src/, in configuration, without an adopted tests/ fixture of the same "
              "list, without a reason, or for a whole file (%d cases)" % len(cases), not wrong, wrong)
    ctx = adopt(p, "gitleaks:\n  allow:\n" + fixtures_ + entry("src/notes.md:generic-api-key:3", "src/notes.md",
                                                                 QREASON, same=ftree))
    record(G, "ADOPT refuses a quote entry in src/; nothing is adopted", "NOT recorded" in ctx and "src/notes.md" in ctx
           and not os.path.exists(os.path.join(p, SD, "config", "product-tools.yaml")), ctx[-300:])
    rc, out = check(p, "check_scanners", "--tool", "gitleaks")
    record(G, "without the quote entry, the docs/ history hit fails as [high] (the product run's state)",
           rc == 1 and "[high] gitleaks:generic-api-key history docs/findings.md:3" in out, out[-600:])
    ctx = adopt(p, "gitleaks:\n  allow:\n" + fixtures_ + entry(dhist, "docs/findings.md", QREASON, same=ftree))
    rc, out = check(p, "check_scanners", "--tool", "gitleaks")
    al = allowed(out)
    record(G, "MF-63: with the adopted quote entry, check-gitleaks passes: the docs/ history hit has the fixture's value",
           "recorded" in ctx and rc == 0 and "[high]" not in out, (ctx[-200:], out[-800:]))
    record(G, "the quote's ALLOWLISTED line says it is the same value as the named fixture, with the reason; the value "
              "itself is printed nowhere", any(x.startswith("ALLOWLISTED %s " % dhist) and "same value as the adopted "
                                               "test fixture %s" % ftree in x and "findings log quotes" in x for x in al)
           and WORD not in out, al)
    # negative: a quote entry over a different value
    q = plain_product("glo", {TT: SPEC, "docs/other.md": "x\n\n    const PASSWORD = \"%s\";\n" % OTHER})
    oc = first_commit(q, "docs/other.md")
    ofp = "%s:docs/other.md:generic-api-key:3" % oc
    ctx = adopt(q, "gitleaks:\n  allow:\n" + entry(ftree, TT) + entry("%s:%s:generic-api-key:1" % (
        first_commit(q, TT), TT), TT) + entry(ofp, "docs/other.md", "the findings log quotes some other test value",
                                              same=ftree) + entry("docs/other.md:generic-api-key:3", "docs/other.md",
                                                                  "the findings log quotes some other test value",
                                                                  same=ftree))
    rc, out = check(q, "check_scanners", "--tool", "gitleaks")
    record(G, "negative: a quote entry never covers another value (history and tree fail as [high]: not the value of "
              "the fixture finding)", "recorded" in ctx and rc == 1 and
           len(re.findall(r"\[high\] gitleaks:generic-api-key (?:history|tree) docs/other\.md:3 .*not the value of the "
                          r"fixture finding", out)) == 2 and OTHER not in out and WORD not in out, out[-900:])
    # negative: written past ADOPT
    E.write(q, SD + "/config/product-tools.yaml", "gitleaks:\n  allow:\n" + entry(ftree, TT) +
            entry("src/k.md:generic-api-key:1", "src/k.md", QREASON, same=ftree))
    rc, out = check(q, "check_scanners", "--tool", "gitleaks")
    record(G, "negative: a quote entry written past ADOPT (or in src/) is refused at scan time and nothing is applied",
           rc == 1 and "not adopted" in out and "src/k.md" in out and not allowed(out), out[-600:])


# ------------------------------------------------------------------ security (MF-65)
def test_security():
    G = "security"
    files = {TT: SPEC, "docs/findings.md": "# Findings\n\n    const PASSWORD = \"%s\";\n" % WORD,
             "docs/other.md": "# Other\n\n    const PASSWORD = \"%s\";\n" % OTHER,
             "src/leak.js": "export const PASSWORD = \"%s\";\n" % WORD}
    p = plain_product("sec", files)
    ftree = "%s:generic-api-key:1" % TT
    allow = ("gitleaks:\n  allow:\n" + entry(ftree, TT) +
             entry("docs/findings.md:generic-api-key:3", "docs/findings.md", QREASON, same=ftree) +
             entry("docs/other.md:generic-api-key:3", "docs/other.md", "the findings log quotes another test value",
                   same=ftree))
    ctx = adopt(p, allow)
    rc, out = check(p, "check_security", home=old_home(("gate/v1/check_security.py",)))
    hits = re.findall(r"SECRET DETECTED by the gate's own scan: (\S+?):\d+ ", out)
    record(G, "control: on 0.8.0 the adopted allowlist does not reach check-security: the fixture still fails, and the "
              "message points to a waiver no operator command records", "recorded" in ctx and TT in hits and
           "or waive with a reason and an approver" in out, (ctx[-200:], hits))
    rc, out = check(p, "check_security")
    hits = sorted(set(re.findall(r"SECRET DETECTED by the gate's own scan: (\S+?):\d+ ", out)))
    al = allowed(out)
    record(G, "MF-65: check-security applies the adopted allowlist: the tests/ fixture and its quote in docs/ pass",
           TT not in hits and "docs/findings.md" not in hits, hits)
    record(G, "each hit it covers is listed (ALLOWLISTED, with the entry, the reason and, for a quote, the fixture it "
              "repeats) for REVIEW", any(x.startswith("ALLOWLISTED %s tree %s:1" % (ftree, TT)) for x in al) and
           any("docs/findings.md:3" in x and "same value as the adopted test fixture %s" % ftree in x for x in al) and
           WORD not in " ".join(al), al)
    record(G, "negative: the same value in src/, and a quote entry over another value, are still SECRET DETECTED; the "
              "message names the allowlist, not a waiver", hits == ["docs/other.md", "src/leak.js"] and
           "gitleaks allowlist the operator adopts" in out and "waive with a reason" not in out, (hits, out[-500:]))
    E.write(p, SD + "/config/product-tools.yaml", allow + "\n")
    rc, out = check(p, "check_security")
    hits = sorted(set(re.findall(r"SECRET DETECTED by the gate's own scan: (\S+?):\d+ ", out)))
    record(G, "negative: an allowlist edited past ADOPT is not applied here either, and the gate says why",
           TT in hits and "docs/findings.md" in hits and "not adopted" in out and not allowed(out), (hits, out[-500:]))


# ------------------------------------------------------------------ surface (MF-64)
ENUM = ("import check_surface_coverage as S, sandbox\n%s"
        "print('RESULT ' + json.dumps(S.run_enumerator(%r, '', {'method': 'command', 'command': ['node', "
        "'scripts/routes.mjs']})))")
NO_SANDBOX = "sandbox.wrap = lambda root, argv, prof: (open(prof, 'w').close(), list(argv))[1]\n"


def enum_result(out):
    line = next((x for x in out.splitlines() if x.startswith("RESULT ")), None)
    return json.loads(line[7:]) if line else [None, [], out[-300:]]


def nested_sandbox():
    try:
        return subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"],
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def test_surface():
    G = "surface"
    if not install_tool("node"):
        record(G, "the pinned Node is installed (~/.cache/moadix-tools)", False, TOOLS)
        return
    p = plain_product("surf", {"scripts/routes.mjs": "console.log('GET /notes');\nconsole.log('POST /notes');\n"})
    env = E.env(PATH="/usr/bin:/bin:/usr/sbin:/sbin", MOADIX_PRODUCT_ROOT=p)  # the worker's PATH: no node on it
    old = old_home(("gate/v1/check_surface_coverage.py",))
    r = enum_result(in_home(old, ENUM % (NO_SANDBOX, p), p, env))
    record(G, "control: on 0.8.0 an enumerator declared [node, scripts/routes.mjs] fails: no node on the worker's PATH",
           r[0] == "failed" and ("No such file" in str(r[2]) or "not found" in str(r[2])), r)
    r = enum_result(in_home(E.home, ENUM % (NO_SANDBOX, p), p, env))
    record(G, "MF-64: the same declaration runs with the gate's pinned Node first on PATH and lists the surface",
           r[0] == "declared" and sorted(map(tuple, r[1])) == [("GET", "/notes"), ("POST", "/notes")], r)
    out = in_home(E.home, "import check_surface_coverage as S\nenv, why = S.enumerator_env({'PATH': '/usr/bin:/bin'})\n"
                          "print('PATH ' + env['PATH'])", p, env)
    first = next((x[5:] for x in out.splitlines() if x.startswith("PATH ")), "").split(":")[0]
    record(G, "the PATH entry is the gate's own pinned Node (the tools cache), never a product setting",
           first.endswith("/tools/node-24.22.2") and os.path.realpath(os.path.join(first, "node")) ==
           os.path.realpath(os.path.join(TOOLS, "node-24.22.2", "node")), out[-300:])
    if nested_sandbox():
        r = enum_result(in_home(E.home, ENUM % ("", p), p, env))
        record(G, "under sandbox-exec (the real confinement), the enumerator finds node and lists the surface",
               r[0] == "declared" and len(r[1]) == 2, r)
    else:
        skip(G, "under sandbox-exec (the real confinement), the enumerator finds node and lists the surface",
             "sandbox-exec cannot nest inside this sandbox; run the suite from Terminal")


# ------------------------------------------------------------------ st201 (MF-60)
ST_PY = os.path.join(TOOLS, "schemathesis-4.32.7", "venv", "bin", "python")
ST_SPEC = {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {
    "/notes": {"post": {"requestBody": {"required": True, "content": {"application/x-www-form-urlencoded": {"schema": {
        "type": "object", "required": ["title"],
        "properties": {"title": {"type": "string", "maxLength": 32, "pattern": "^[a-z]*$"}}}}}},
        "responses": {"303": {"description": "saved"}, "400": {"description": "invalid"},
                      "413": {"description": "too large"}}}},
    "/memos": {"post": {"requestBody": {"required": True, "content": {"application/x-www-form-urlencoded": {"schema": {
        "type": "object", "required": ["title"],
        "properties": {"title": {"type": "string", "maxLength": 32, "pattern": "^[a-z]*$"}}}}}},
        "responses": {"303": {"description": "saved"}, "400": {"description": "invalid"}}}}}}
# The app as smoke-076's /notes: a body over 38 bytes is 413, an invalid form 400, a valid one 303. In-process (WSGI), the
# transport drops form keys with control characters, so a negative "additional property" case can arrive valid: the
# harness contract has no additionalProperties: false, generation is ASCII and Hypothesis keeps no example database.
ST_TEST = r'''
import os, re, urllib.parse
import schemathesis
from schemathesis.config import SchemathesisConfig
from schemathesis.specs.openapi.checks import negative_data_rejection
spec = __SPEC__
def app(environ, start):
    n = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(n).decode("latin-1") if n else ""
    if n > 38:
        start("413 Content Too Large", [("content-type", "text/html")]); return [b"too large"]
    f = urllib.parse.parse_qs(body, keep_blank_values=True)
    ok = list(f) == ["title"] and len(f["title"]) == 1 and re.fullmatch(r"[a-z]{0,32}", f["title"][0])
    start("303 See Other" if ok else "400 Bad Request", [("location", "/")]); return [b""]
toml = '[generation]\nmode = "negative"\ncodec = "ascii"\ndatabase = "none"\n[phases.examples]\nenabled = false\n'
if os.environ.get("ST_TOML"):
    toml += open(os.environ["ST_TOML"]).read()
schema = schemathesis.openapi.from_dict(spec, config=SchemathesisConfig.from_str(toml))
schema.app = app
@schema.parametrize()
def test_api(case):
    case.call_and_validate(checks=[negative_data_rejection], app=app)
'''


def st_pytest(work, toml=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": work, "TMPDIR": work, "LANG": "C.UTF-8"}
    if toml:
        env["ST_TOML"] = toml
    r = subprocess.run([ST_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "test_st.py"],
                       cwd=work, env=env, capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    return sorted(set(re.findall(r"FAILED test_st\.py::test_api\[POST (/\w+)\]", out))), out


def product(name, tools=None):
    """smoke-076 with the smoke-080 (official postgres database) and smoke-081 (POST /notes in the contract) overlays."""
    p = os.path.join(E.base, name)
    shutil.copytree(FIX76, p, ignore=shutil.ignore_patterns(".claude", "product-tools.yaml", "node_modules"))
    shutil.copytree(FIX80, p, dirs_exist_ok=True)
    shutil.copytree(FIX81, p, dirs_exist_ok=True)
    subprocess.run(["/usr/bin/git", "init", "-q", p])
    E.commit(p, "fixture")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    with open(os.path.join(FIX76, "product-tools.yaml")) as f:
        E.write(p, SD + "/config/product-tools.yaml", f.read() + (tools or ""))
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


def st_run():
    """(the `docker run` of Schemathesis itself, its script): the run whose script starts schemathesis.cli (the install
    step's run carries the same name suffix)."""
    for c in reversed(calls()):
        if c[:1] == ["run"] and "-c" in c and "schemathesis.cli" in c[c.index("-c") + 1]:
            return c, c[c.index("-c") + 1]
    return [], ""


def test_st201():
    G = "st201"
    import st_refusal
    if not os.path.exists(ST_PY):
        record(G, "the pinned Schemathesis is installed (~/.cache/moadix-tools/schemathesis-4.32.7)", False, ST_PY)
        return
    work = os.path.join(E.base, "tmp", "st201")
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "test_st.py"), "w") as f:
        f.write(ST_TEST.replace("__SPEC__", repr(ST_SPEC)))
    with open(os.path.join(work, "api.json"), "w") as f:
        json.dump(ST_SPEC, f)
    failed, out = st_pytest(work)
    record(G, "control: the pinned Schemathesis, with its own statuses, counts the app's 413 as an accepted schema-"
              "violating request (ST201) on both operations, as in the product run",
           failed == ["/memos", "/notes"] and "Schema-violating request accepted" in out, out[-600:])
    toml = os.path.join(work, "st.toml")
    r = subprocess.run([ST_PY, os.path.join(E.home, "gate", "exec", "st_config.py"), os.path.join(work, "api.json"), toml,
                        "[413]"], capture_output=True, text=True, cwd=work, timeout=120)
    text = open(toml).read() if os.path.exists(toml) else ""
    record(G, "the gate's st_config.py selects each operation whose contract documents 413 by its exact name (never "
              "include-path with include-method, which match any operation having either)",
           r.returncode == 0 and 'include-name = "POST /notes"' in text and "/memos" not in text and
           "include-path" not in text and '"413"' in text and "ST201 also accepts 413 for POST /notes" in r.stdout,
           (r.returncode, r.stdout, r.stderr[-300:], text))
    failed, out = st_pytest(work, toml)
    record(G, "MF-60: with that configuration the real Schemathesis accepts 413 for POST /notes (its contract lists "
              "it); POST /memos, whose contract does not, still fails ST201", failed == ["/memos"], out[-600:])
    bad = {"200": [200], "a 3xx": [303], "a 5xx": [503], "a default refusal": [400], "a word": ["big"],
           "a repeat": [413, 413], "five": [413, 414, 431, 451, 418], "an empty list": [], "a boolean": [True]}
    wrong = [k for k, v in bad.items() if not st_refusal.from_tools({"schemathesis": {"refusal-statuses": v}})[1]]
    okv = st_refusal.from_tools({"schemathesis": {"refusal-statuses": [413, "414"]}})
    unk = st_refusal.from_tools({"schemathesis": {"checks": {"negative_data_rejection": {}}}})[1]
    record(G, "refusal-statuses takes only 4xx statuses Schemathesis does not already count, at most 4; no other key "
              "(%d refused shapes)" % len(bad), not wrong and okv == ([413, 414], []) and unk, (wrong, okv, unk))
    q = plain_product("stadopt", {"README.md": "x\n"})
    ctx = adopt(q, "schemathesis:\n  refusal-statuses: [200]\n")
    record(G, "ADOPT refuses a refusal status that is not a client error", "NOT recorded" in ctx and "4xx" in ctx,
           ctx[-300:])
    ctx = adopt(q, "schemathesis:\n  refusal-statuses: [413]\n")
    record(G, "ADOPT records schemathesis.refusal-statuses: [413]", "recorded" in ctx and "NOT recorded" not in ctx,
           ctx[-300:])
    p = product("st", "schemathesis:\n  refusal-statuses: [413]\n")
    rc, out = run_gate(p, "schemathesis", "8", home=old_home(("gate/v1/check_exec.py", "gate/v1/st_refusal.py")))
    sc, script = st_run()
    record(G, "control: on 0.8.0 the setting changes nothing: Schemathesis runs with no configuration of the gate's",
           sc and "--config-file" not in script and "st_config" not in script, (rc, script[-300:], out[-300:]))
    rc, out = run_gate(p, "schemathesis", "8")
    sc, script = st_run()
    gx = [x for x in sc if "dst=/gx" in x]
    record(G, "the confined run writes the configuration with the gate's st_config.py (mounted read-only at /gx) from "
              "the contract and passes it to Schemathesis; a failure to write it fails the run (exit 97)",
           rc == 0 and "/gx/st_config.py /src/sdlc/05-lld/api.yaml /tmp/st.toml '[413]'" in script and
           "schemathesis.cli --config-file /tmp/st.toml run" in script and "echo 97 > /out/run.rc" in script and
           gx and gx[0].endswith(",readonly") and "ST201 also accepts 413" in out, (rc, script[-400:], gx, out[-400:]))
    p2 = product("stbad", "schemathesis:\n  refusal-statuses: [200]\n")
    rc, out = run_gate(p2, "schemathesis", "8")
    record(G, "a refusal status that is not a 4xx fails the gate before Schemathesis runs",
           rc == 1 and "not a 4xx status" in out and not st_run()[0] and not calls(), out[-400:])
    p3 = product("stnone")
    rc, out = run_gate(p3, "schemathesis", "8")
    sc, script = st_run()
    record(G, "without the setting, the run is as before (no configuration, no /gx)",
           rc == 0 and "--config-file" not in script and not [x for x in sc if "dst=/gx" in x], script[-300:])


# ------------------------------------------------------------------ verifiers (MF-62)
FIX_BRD = open(os.path.join(REPO, "tests", "fixtures", "product", "sdlc", "00-brd.md")).read()
NOTES = ("\n## Notes A\n\nThe fixture keeps a weekly summary of open items for its owner.\n"
         "\n## Notes B\n\nThe fixture sends no messages to anyone outside the team.\n")


def brd_product(name):
    p = E.repo(name, docs=())
    E.write(p, "sdlc/00-brd.md", FIX_BRD + NOTES)
    E.commit(p, "brd")
    E.init(p, re.sub(r"[^a-z0-9]", "", name) + "fx")
    E.commit(p, "init")
    contract_fixture.ready(E, p, "0", with_critic=False)
    return p


def critic_file(p):
    return os.path.join(p, SD, "cache", "verify", "0", "gap-critic", "evidence", "CRITIC.json")


def worker_result(p, label, timeout=120):
    """Start the validator worker (the agent's turn ends) and return its stored result once it has finished."""
    cf = validation.cache_file(p, label)
    if os.path.exists(cf):
        os.unlink(cf)
    E.stop(p)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(cf) and validation.running(p, label) is None:
            return json.load(open(cf))
        time.sleep(0.5)
    return {}


def vrow(data):
    return next((r for r in (data or {}).get("results") or [] if r.get("validator", "").startswith("check-verifiers")),
                {})


def test_verifiers():
    G = "verifiers"
    p = brd_product("ver")
    contract_fixture.critic(E, p, "0")
    ef = critic_file(p)
    os.replace(ef, ef + ".hold")  # launched; the critic has not written yet
    rc, out = check(p, "check_verifiers", "--phase", "0", home=old_home(("gate/verify.py", "gate/v1/check_verifiers.py")))
    record(G, "control: on 0.8.0 a critic launched at this commit that has not written yet is reported MISSING",
           rc == 1 and "MISSING moadix:gap-critic: no evidence at" in out, out[-400:])
    rc, out = check(p, "check_verifiers", "--phase", "0")
    record(G, "MF-62: it is STALE (launched, evidence not written yet; read again when it is), never MISSING, exit 3",
           rc == 3 and "STALE moadix:gap-critic: launched at " in out and "MISSING" not in out, (rc, out[-400:]))

    def write_later():
        time.sleep(4)
        os.replace(ef + ".hold", ef)
    th = threading.Thread(target=write_later)
    th.start()
    os.environ["MOADIX_TEST_VERIFIER_WAIT"] = "60"
    data = worker_result(p, "0")
    th.join()
    row = vrow(data)
    record(G, "the validator worker waits for the running critic and reads its evidence when it is written: "
              "check-verifiers passes in the stored result", row.get("result") == "pass" and
           "OK moadix:gap-critic" in row.get("output", "") and "MISSING" not in row.get("output", ""),
           (row, data.get("verdict")))
    st = __import__("gate.state", fromlist=["x"]).current_state(p)[0]
    status, _d, detail = validation.read(p, "0", st)
    record(G, "that result is fresh for REVIEW (it is keyed to the evidence it read)", status == "fresh", (status, detail))
    os.replace(ef, ef + ".hold")
    contract_fixture.critic(E, p, "0")
    os.replace(ef, ef + ".hold")
    os.environ["MOADIX_TEST_VERIFIER_WAIT"] = "2"
    data = worker_result(p, "0")
    row = vrow(data)
    summ = " ".join(validation.summary(data))
    record(G, "a critic that never writes within the wait leaves the result STALE, never MISSING (REVIEW shows STALE)",
           row.get("result") == "stale" and "STALE moadix:gap-critic" in row.get("output", "") and
           "MISSING" not in row.get("output", "") and "STALE" in summ and data.get("verdict") != "pass", (row, summ))
    os.environ.pop("MOADIX_TEST_VERIFIER_WAIT", None)
    vsrc = open(os.path.join(E.home, "gate", "validate.py")).read()
    record(G, "the installed wait is bounded (VERIFIER_WAIT) and only a test fixture's gate copy may shorten it",
           re.search(r"^VERIFIER_WAIT = \d+", vsrc, re.M) and "_testguard.py" in vsrc.split("def verifier_wait")[1][:400],
           "")


# ------------------------------------------------------------------ volumes (the engine run)
def anon_volumes():
    try:
        s = json.load(open(os.path.join(DBL, "state.json")))
    except (OSError, ValueError):
        return ["(no state)"]
    return [v for v in s.get("volumes") or {} if re.match(r"^[0-9a-f]{64}$", v)]


def test_volumes():
    G = "volumes"
    p = product("vol")
    rc, out = run_gate(p, "schemathesis", "8", home=old_home(("gate/confined.py",)))
    left = anon_volumes()
    record(G, "control: on 0.8.0 the database's anonymous volume (the official postgres image's VOLUME) is left after "
              "the run", rc == 0 and len(left) == 1, (rc, left, out[-300:]))
    rc, out = run_gate(p, "schemathesis", "8")
    rms = [c for c in calls() if c[:1] == ["rm"]]
    record(G, "the gate removes every container of a run with --volumes, so its anonymous volumes go with it; none is "
              "left",
           rc == 0 and not anon_volumes() and rms and all("--volumes" in c for c in rms), (rc, anon_volumes(), rms[:3]))
    named = [c for c in calls() if c[:2] == ["volume", "rm"]]
    record(G, "the run's named volumes are still removed by their label, as before", named, "")


# ------------------------------------------------------------------ critic (MF-52)
def test_critic():
    G = "critic"
    p = brd_product("crit")
    lines = open(os.path.join(p, "sdlc", "00-brd.md")).read().splitlines()
    n = next(i for i, ln in enumerate(lines, 1) if ln.startswith("The fixture sends"))
    long_fix = "Say who may receive messages and why. " * 40  # about 1,500 characters
    f = {"id": "C1", "topic": "B9", "severity": "BLOCKER", "quote": lines[n - 1][:60],
         "citation": "sdlc/00-brd.md:%d" % n, "fix": long_fix}
    contract_fixture.critic(E, p, "0", findings=[f])
    rc, out = check(p, "check_verifiers", "--phase", "0", home=old_home(("gate/contract.py",)))
    record(G, "control: on 0.8.0 a fix over 1,000 characters makes the whole evidence fail the schema; the BLOCKER is "
              "not read", rc == 1 and "fix is longer than 1000 characters" in out and "BLOCKER C1" not in out,
           out[-500:])
    rc, out = check(p, "check_verifiers", "--phase", "0")
    record(G, "MF-52: the fix is cut with a marker and the finding is read: the BLOCKER blocks, no schema error",
           rc == 1 and "BLOCKER C1" in out and "longer than" not in out, out[-500:])
    record(G, "the cut is noted for the operator (MINOR), with the fix's length and the limit",
           re.search(r"MINOR moadix:gap-critic: finding C1: its fix was \d{4} characters; the gate kept the first \d+ "
                     r"and marked the cut \(the limit is 1000\)", out), out[-600:])
    from gate import contract
    ev = {"findings": [dict(f)]}
    contract.truncate_fixes(ev)
    fx = ev["findings"][0]["fix"]
    record(G, "the kept text is at most 1,000 characters and ends with the gate's marker",
           len(fx) <= 1000 and fx.endswith("over the 1000-character limit]") and "cut by the gate" in fx, len(fx))
    brief = open(os.path.join(p, SD, "cache", "verify", "0", "gap-critic", "brief.md")).read()
    record(G, "the gap critic's brief states the limit", "at most 1,000" in brief and "cuts a longer one" in brief, "")


# ------------------------------------------------------------------ engine
def test_engine():
    G = "engine"
    p = os.path.join(REPO, "tests", "confined-engine", "run.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("es_suite081", p)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    text = open(p).read()
    record(G, "the engine suite has a rel081 group (3 checks), and its total is 79 (0.8.2: rel082 4; 0.8.3: rel083 2)",
           es.PLAN.get("test_rel081") == ("rel081", 3) and es.TOTAL == 79 and "test_rel081, (node,)" in text,
           (es.PLAN.get("test_rel081"), es.TOTAL))
    body = text.split("def test_rel081", 1)[1].split("\n# ", 1)[0] if "def test_rel081" in text else ""
    record(G, "it runs the real Schemathesis on smoke-081 with and without refusal-statuses: [413], checks the real "
              "engine keeps no anonymous volume, and shows `rm` without --volumes leaves one",
           "smoke081_product" in body and "refusal-statuses: [413]" in body and "ST201" in body and
           "volume_names()" in body and '"rm", "-f", control' in body and
           '"rm", "-f", "--volumes", fixed' in body, body[:300])


def main():
    try:
        for t in (test_gitleaks, test_security, test_surface, test_st201, test_verifiers, test_volumes, test_critic,
                  test_engine):
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
    print("\n%d checks, %d passed, %d failed, %d skipped (%d s)" % (n, n - len(bad), len(bad), len(SKIPPED),
                                                                   time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
