#!/usr/bin/python3
"""MOADIX increment-5 suite: the gate-run tools. Fixtures only (tests/lib/fixtures.py:
stub checker, fixture gate copy, test guard); the REAL pinned tools from
~/.cache/moadix-tools (managed/fetch_tools.py fetches them, sha256-checked).

    /usr/bin/python3 managed/fetch_tools.py ~/.cache/moadix-tools   # once
    /usr/bin/python3 tests/tools/run.py

For each tool, a clean case that passes and a planted problem it must catch,
run through the gate's own validator entry point (gate/v1/_launch.py, as the
worker runs them). Network: only the scanners' own databases (api.osv.dev,
api.deps.dev, mirror.gcr.io/ghcr.io for Trivy's DB), all on the policy's
allowlist. GitHub and Claude Security are stubbed (no account, no tokens).

Cases that need a server listening on loopback (Arazzo execution, the live
probe against a running app) run only where binding is allowed; elsewhere they
are reported as SKIPPED, never as passed.
"""
import base64
import json
import os
import re
import shutil
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

TOOLS = os.path.expanduser("~/.cache/moadix-tools")
E = fixtures.Env("v5").build()
# toolrun, hlib and the validators from the FIXTURE gate copy: its tools/ is <fixture home>/tools
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import pathmap, state  # noqa: E402
import hlib  # noqa: E402
import mcpclient  # noqa: E402

RESULTS = []
SKIPPED = []
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLQ"          # assembled so this file holds no literal key
PLAIN_VALUE = "s3cr3t-plaintext-value-" + "do-not-leak"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok), evidence))
    ev = " ".join(str(evidence).split())
    print("%s  [%s] %s\n      %s" % ("PASS" if ok else "FAIL", group, name, ev[:500]))


def skip(group, name, why):
    SKIPPED.append((group, name, why))
    print("SKIP  [%s] %s\n      %s" % (group, name, why))


def git(p, *args):
    return subprocess.run([fixtures.GIT, "-C", p] + list(args), capture_output=True, text=True).stdout.strip()


def head(p):
    return git(p, "rev-parse", "HEAD")


# ------------------------------------------------------------------ fixture setup
def install_tools():
    """<fixture home>/tools: the real pinned tools (symlinks into the sha256-checked cache),
    except github-mcp-server, which is the MCP stub (the real one needs an account)."""
    tdir = os.path.join(E.home, "tools")
    os.makedirs(tdir)
    import toolrun
    for name, t in toolrun.pins().items():
        d = "%s-%s" % (name, t["version"])
        if name == "github-mcp-server":
            os.makedirs(os.path.join(tdir, d))
            dst = os.path.join(tdir, d, "github-mcp-server")
            shutil.copy(os.path.join(REPO, "tests", "lib", "github_mcp_stub.py"), dst)
            os.chmod(dst, 0o755)
            with open(os.path.join(tdir, d, ".moadix-tool.json"), "w") as f:
                json.dump({"name": name, "version": str(t["version"]), "kind": "stub"}, f)
        else:
            os.symlink(os.path.join(TOOLS, d), os.path.join(tdir, d))
    stub = os.path.join(E.shim, "claude")
    shutil.copy(os.path.join(REPO, "tests", "lib", "claude_stub.py"), stub)
    os.chmod(stub, 0o755)
    return tdir


def product(name, files, pid=None, config=None, msg="product"):
    p = E.repo(name)
    for rel, text in files.items():
        E.write(p, rel, text)
    E.commit(p, msg)
    if pid:
        E.init(p, pid)
        E.commit(p, "init")
    if config is not None:
        cfg_dir = os.path.join(p, ".sdlc", "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "product-tools.yaml"), "w") as f:
            f.write(config)
    return p


def bare_product(name, files, config=None):
    """A product with only .sdlc/product.yaml (the validators need nothing else)."""
    p = E.repo(name)
    E.write(p, ".sdlc/product.yaml", "platform: web\n")
    E.write(p, ".gitignore", ".sdlc/\n")
    for rel, text in files.items():
        E.write(p, rel, text)
    if config is not None:
        E.write(p, ".sdlc/config/product-tools.yaml", config)
    E.commit(p, "product")
    return p


def check(p, module, *args, env=None):
    """Run a validator exactly as gate/validate.py does (fixture gate copy, _launch.py)."""
    e = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes")
    e.pop("MOADIX_PHASE_DOC", None)
    e.update(env or {})
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", module + ".py")] + list(args), cwd=p, env=e, timeout=2400)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def fails_line(out):
    return " | ".join(ln.strip() for ln in out.splitlines() if re.match(r"^\s+(FAIL|UNKNOWN)", ln))[:400] or \
        " ".join(out.split())[-300:]


def index_lines(p):
    f = os.path.join(p, ".sdlc", "evidence", "index.jsonl")
    return [json.loads(x) for x in open(f).read().splitlines()] if os.path.exists(f) else []


def can_bind():
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ A. pins
def test_pins():
    import toolrun
    pins = toolrun.pins()
    for name, t in sorted(pins.items()):
        if name == "github-mcp-server":
            continue
        try:
            p, _t = toolrun.tool(name)
            ok = os.path.exists(p)
            st = json.load(open(os.path.join(TOOLS, "%s-%s" % (name, t["version"]), ".moadix-tool.json")))
            record("pins", "%s %s is installed and its stamp matches the pin" % (name, t["version"]),
                   ok and st["version"] == str(t["version"]), "%s (%s)" % (p, st.get("sha256") or st.get("lock_sha256")))
        except toolrun.ToolUnavailable as e:
            record("pins", "%s %s is installed" % (name, t["version"]), False, str(e))
    sys.path.insert(0, os.path.join(REPO, "managed"))
    import fetch_tools
    t = dict(pins["gitleaks"])
    t["assets"] = {"darwin-arm64": dict(t["assets"]["darwin-arm64"], sha256="0" * 64)}
    work = os.path.join(E.base, "tmp", "fetch")
    os.makedirs(work)
    try:
        fetch_tools.fetch_asset(t, "darwin-arm64", work, work)
        record("pins", "a download whose sha256 differs from the pin is refused", False, "accepted")
    except RuntimeError as e:
        record("pins", "a download whose sha256 differs from the pin is refused", "does not match the pin" in str(e),
               str(e)[:200])


# ------------------------------------------------------------------ B. Redocly (phase 5)
OPENAPI = """openapi: 3.1.0
info: {title: Notes, version: 1.0.0, description: Notes API, license: {name: MIT, url: https://opensource.org/licenses/MIT}}
servers: [{url: http://127.0.0.1:8080}]
security: []
tags: [{name: notes, description: Notes}]
paths:
  /notes:
    get:
      operationId: listNotes
      summary: List notes
      description: List notes
      tags: [notes]
      responses:
        "200": {description: ok, content: {application/json: {schema: {type: array, items: {type: string}}}}}
        "400": {description: bad request}
"""
ARAZZO = """arazzo: 1.0.1
info: {title: Notes flow, version: 1.0.0}
sourceDescriptions:
  - name: notes
    url: ./notes.openapi.yaml
    type: openapi
workflows:
  - workflowId: listNotes
    steps:
      - stepId: list
        operationId: listNotes
        successCriteria: [{condition: $statusCode == 200}]
"""


def test_redocly():
    p = bare_product("contracts-clean", {"sdlc/05-lld/notes.openapi.yaml": OPENAPI,
                                         "sdlc/05-lld/notes.arazzo.yaml": ARAZZO})
    rc, out = check(p, "check_contracts")
    record("redocly", "clean: a valid OpenAPI 3.1 contract and an Arazzo workflow pass", rc == 0,
           fails_line(out) if rc else "rc=0; %s" % " ".join(l.strip() for l in out.splitlines() if "openapi" in l or "arazzo" in l)[:200])
    ix = [x for x in index_lines(p) if x["tool"] == "redocly"]
    record("redocly", "the lint report is in the evidence index with the source commit",
           bool(ix) and ix[-1]["source_commit"] == head(p) and os.path.exists(os.path.join(p, ix[-1]["path"])),
           json.dumps(ix[-1] if ix else {})[:200])
    bad = OPENAPI.replace("      operationId: listNotes\n",
                          "      operationId: listNotes\n      parameters: [{name: id, in: path, required: true, schema: {type: string}}]\n")
    p = bare_product("contracts-planted", {"sdlc/05-lld/notes.openapi.yaml": bad})
    rc, out = check(p, "check_contracts")
    record("redocly", "planted lint error (a path parameter the path does not have) fails", rc == 1 and
           "path-parameters-defined" in out, fails_line(out))
    p = bare_product("contracts-bypass", {
        "sdlc/05-lld/notes.openapi.yaml": bad,
        "redocly.yaml": "rules:\n  path-parameters-defined: off\n",
        "sdlc/05-lld/redocly.yaml": "rules:\n  path-parameters-defined: off\n",
        "sdlc/05-lld/.redocly.lint-ignore.yaml": "notes.openapi.yaml:\n  path-parameters-defined:\n    - '#/paths/~1notes/get/parameters/0/name'\n"})
    rc, out = check(p, "check_contracts")
    record("redocly", "the product's redocly.yaml and lint-ignore file cannot hide the error (gate config only)",
           rc == 1 and "path-parameters-defined" in out, fails_line(out))
    p = bare_product("contracts-none", {"sdlc/05-lld/README.md": "no contract\n"})
    rc, out = check(p, "check_contracts")
    record("redocly", "no OpenAPI/Arazzo description at all fails", rc == 1 and "no OpenAPI or Arazzo" in out,
           fails_line(out))


# ------------------------------------------------------------------ C. dotenvx (phase 6b)
def dotenvx_encrypt(p, rel, text):
    E.write(p, rel, text)
    import toolrun
    argv, _t = toolrun.argv_for("dotenvx", ["encrypt", "-f", rel])
    h = os.path.join(E.base, "tmp", "dxhome")
    os.makedirs(h, exist_ok=True)
    r = fixtures.sh(argv, cwd=p, env={"PATH": "/usr/bin:/bin", "HOME": h})
    return r.returncode


def test_dotenvx():
    p = E.repo("env-clean")
    E.write(p, ".sdlc/product.yaml", "platform: web\n")
    E.write(p, ".gitignore", ".sdlc/\n.env.keys\n")
    E.write(p, ".env.example", "DATABASE_URL=\nAPI_TOKEN=\n")
    rc0 = dotenvx_encrypt(p, ".env.production", "DATABASE_URL=postgres://u:%s@127.0.0.1/db\nAPI_TOKEN=%s\n" % (
        PLAIN_VALUE, PLAIN_VALUE))
    E.commit(p, "env")
    rc, out = check(p, "check_env")
    record("dotenvx", "clean: real `dotenvx encrypt` output with every required key passes", rc0 == 0 and rc == 0,
           fails_line(out) if rc else out.splitlines()[1].strip())
    ix = [x for x in index_lines(p) if x["tool"] == "dotenvx-check"]
    ev = open(os.path.join(p, ix[-1]["path"])).read() if ix else ""
    record("dotenvx", "values are never read into the output or the evidence (key names only)",
           bool(ix) and PLAIN_VALUE not in ev and PLAIN_VALUE not in out and "encrypted:" not in ev,
           "evidence %s: %s" % (ix[-1]["path"] if ix else "-", ev.replace("\n", " ")[:160]))
    p2 = E.repo("env-plain")
    E.write(p2, ".sdlc/product.yaml", "platform: web\n")
    E.write(p2, ".gitignore", ".sdlc/\n.env.keys\n")
    E.write(p2, ".env.example", "DATABASE_URL=\nAPI_TOKEN=\nSMTP_PASSWORD=\n")
    dotenvx_encrypt(p2, ".env.production", "DATABASE_URL=postgres://x@127.0.0.1/db\nAPI_TOKEN=abc\n")
    with open(os.path.join(p2, ".env.production"), "a") as f:
        f.write("SMTP_PASSWORD=%s\n" % PLAIN_VALUE)        # planted: appended after encryption, in clear
    E.commit(p2, "env")
    rc, out = check(p2, "check_env")
    record("dotenvx", "planted unencrypted value fails, naming the key and not the value",
           rc == 1 and "SMTP_PASSWORD is not encrypted" in out and PLAIN_VALUE not in out, fails_line(out))
    E.write(p2, ".env.example", "DATABASE_URL=\nAPI_TOKEN=\nSTRIPE_KEY=\n")
    dotenvx_encrypt(p2, ".env.production", "DATABASE_URL=postgres://x@127.0.0.1/db\nAPI_TOKEN=abc\n")
    E.commit(p2, "missing key")
    rc, out = check(p2, "check_env")
    record("dotenvx", "a required key (.env.example) missing from the encrypted file fails",
           rc == 1 and "required key STRIPE_KEY is missing" in out, fails_line(out))
    E.write(p2, ".gitignore", ".sdlc/\n")
    E.commit(p2, "commit the keys")
    rc, out = check(p2, "check_env")
    record("dotenvx", "a committed .env.keys (the private keys) fails", rc == 1 and ".env.keys is committed" in out,
           fails_line(out))


# ------------------------------------------------------------------ D. gitleaks
def test_gitleaks():
    p = bare_product("gl-clean", {"src/app.js": "export const greet = (n) => 'hello ' + n;\n"})
    rc, out = check(p, "check_scanners", "--tool", "gitleaks")
    record("gitleaks", "clean: history and tree with no secret pass", rc == 0, fails_line(out) if rc else "rc=0")
    p = bare_product("gl-history", {"src/app.js": "const k = '%s';\n" % FAKE_AWS})
    E.write(p, "src/app.js", "const k = process.env.AWS_KEY;\n")
    E.commit(p, "remove the key")
    rc, out = check(p, "check_scanners", "--tool", "gitleaks")
    record("gitleaks", "planted fake secret, removed from the tree but still in HISTORY, fails",
           rc == 1 and "aws-access-token" in out and "history" in out, fails_line(out))
    ix = [x for x in index_lines(p) if x["tool"] == "gitleaks"]
    leaked = any(FAKE_AWS in open(os.path.join(p, x["path"])).read() for x in ix)
    record("gitleaks", "the SARIF evidence (history and tree) is indexed with the commit and the secret is redacted",
           len(ix) == 2 and not leaked and all(x["source_commit"] == head(p) for x in ix),
           "; ".join("%s %s" % (x["path"], x["sha256"][:12]) for x in ix))
    p = bare_product("gl-bypass", {"src/app.js": "const k = '%s'; // gitleaks:allow\n" % FAKE_AWS,
                                   ".gitleaksignore": "src/app.js:aws-access-token:1\n",
                                   ".gitleaks.toml": "[allowlist]\npaths = ['''src/''']\n"})
    rc, out = check(p, "check_scanners", "--tool", "gitleaks")
    record("gitleaks", "gitleaks:allow, .gitleaksignore and the product's .gitleaks.toml cannot hide it",
           rc == 1 and "aws-access-token" in out, fails_line(out))


# ------------------------------------------------------------------ E. OSV-Scanner
def lockfile(pkg, ver, integrity):
    return json.dumps({"name": "fx", "version": "1.0.0", "lockfileVersion": 3, "requires": True,
                       "packages": {"": {"name": "fx", "version": "1.0.0", "dependencies": {pkg: ver}},
                                    "node_modules/" + pkg: {"version": ver, "resolved":
                                                            "https://registry.npmjs.org/%s/-/%s-%s.tgz" % (pkg, pkg, ver),
                                                            "integrity": integrity}}}, indent=1)


def test_osv():
    p = bare_product("osv-clean", {"package-lock.json": lockfile(
        "is-number", "7.0.0", "sha512-41Cifkg6e8TylSpdtTpeLVMqvSBEVzTttHvERD741+pnZ8ANv0004MRL43QKPDlK9cGvNp6NZWZUBlbGXYxxng==")})
    rc, out = check(p, "check_scanners", "--tool", "osv-scanner")
    record("osv", "clean: a lockfile with no known vulnerability passes", rc == 0, fails_line(out) if rc else "rc=0")
    vuln = lockfile("lodash", "4.17.15",
                    "sha512-8xOcRHvCjnocdS5cpwJQXQq86VNe8U2+v32Q/0B8EgRNPP4iXxUQjMmQ2Ck2QPkr+Q6zVUlOKm2twfELrfLvDQ==")
    p = bare_product("osv-planted", {"package-lock.json": vuln})
    rc, out = check(p, "check_scanners", "--tool", "osv-scanner")
    record("osv", "planted vulnerable lockfile entry (lodash 4.17.15) fails on a high finding",
           rc == 1 and "lodash@4.17.15" in out and "[high]" in out, fails_line(out))
    p = bare_product("osv-bypass", {"package-lock.json": vuln, "osv-scanner.toml":
                                    "\n".join("[[IgnoredVulns]]\nid = \"%s\"\nreason = \"x\"\n" % g for g in (
                                        "GHSA-p6mc-m468-83gw", "GHSA-35jh-r3h4-6jhm", "GHSA-r5fr-rjxr-66jc",
                                        "GHSA-29mw-wpgm-hmr9", "GHSA-xxjr-mmjv-4gpg", "GHSA-jf85-cpcp-j695"))})
    rc, out = check(p, "check_scanners", "--tool", "osv-scanner")
    record("osv", "the product's osv-scanner.toml cannot ignore the advisories", rc == 1 and "lodash@4.17.15" in out,
           fails_line(out))


# ------------------------------------------------------------------ F. Trivy
def test_trivy():
    clean_lock = lockfile("is-number", "7.0.0",
                          "sha512-41Cifkg6e8TylSpdtTpeLVMqvSBEVzTttHvERD741+pnZ8ANv0004MRL43QKPDlK9cGvNp6NZWZUBlbGXYxxng==")
    df_ok = "FROM alpine:3.19\nRUN adduser -D app\nUSER app\nHEALTHCHECK CMD true\nCMD [\"true\"]\n"
    p = bare_product("trivy-clean", {"Dockerfile": df_ok, "package-lock.json": clean_lock})
    rc, out = check(p, "check_scanners", "--tool", "trivy")
    record("trivy", "clean: a non-root Dockerfile and a clean lockfile pass (DB downloaded, scan offline)", rc == 0,
           fails_line(out) if rc else "rc=0")
    df_root = "FROM alpine:3.19\nUSER root\nCMD [\"true\"]\n"
    p = bare_product("trivy-planted", {"Dockerfile": df_root, "package-lock.json": clean_lock})
    rc, out = check(p, "check_scanners", "--tool", "trivy")
    record("trivy", "planted misconfiguration (image runs as root, DS-0002 HIGH) fails", rc == 1 and "DS-0002" in out,
           fails_line(out))
    p = bare_product("trivy-bypass", {"Dockerfile": df_root, "package-lock.json": clean_lock,
                                      ".trivyignore": "DS-0002\nAVD-DS-0002\n",
                                      "trivy.yaml": "misconfiguration:\n  scanners: []\n"})
    rc, out = check(p, "check_scanners", "--tool", "trivy")
    record("trivy", "the product's .trivyignore and trivy.yaml cannot hide it", rc == 1 and "DS-0002" in out,
           fails_line(out))


# ------------------------------------------------------------------ G. Semgrep
CLEAN_JS = "export function add(a, b) { return a + b; }\n"
BAD_JS = "const cp = require('child_process');\nexport function ls(dir) { cp.exec(`ls ${dir}`); }\n"


def test_semgrep():
    p = bare_product("sg-clean", {"src/a.js": CLEAN_JS})
    rc, out = check(p, "check_scanners", "--tool", "semgrep")
    record("semgrep", "clean: code with no rule match passes (local rules, metrics off, no account)", rc == 0,
           fails_line(out) if rc else "rc=0")
    p = bare_product("sg-planted", {"src/a.js": BAD_JS})
    rc, out = check(p, "check_scanners", "--tool", "semgrep")
    record("semgrep", "planted shell injection (exec of a template string) fails",
           rc == 1 and "moadix.js.child-process-shell-interpolation" in out, fails_line(out))
    p = bare_product("sg-bypass", {"src/a.js": BAD_JS.replace("cp.exec(`ls ${dir}`); }", "cp.exec(`ls ${dir}`); // nosemgrep\n}"),
                                   ".semgrepignore": "src/\n"})
    rc, out = check(p, "check_scanners", "--tool", "semgrep")
    record("semgrep", "nosemgrep comments and .semgrepignore cannot hide it", rc == 1 and "child-process" in out,
           fails_line(out))
    rule = ("rules:\n  - id: no-console-secret\n    languages: [javascript]\n    severity: ERROR\n"
            "    message: secrets must not be logged\n    pattern: console.log($X.secret)\n")
    p = bare_product("sg-product-rule", {"src/a.js": "export function f(u) { console.log(u.secret); }\n",
                                         "security/semgrep/own.yml": rule})
    rc, out = check(p, "check_scanners", "--tool", "semgrep")
    record("semgrep", "the product's own rules (security/semgrep/*.yml) add findings", rc == 1 and "no-console-secret" in out,
           fails_line(out))


# ------------------------------------------------------------------ H. k6 (phase 10c)
K6 = """import { Trend, Counter } from 'k6/metrics';
const checkout = new Trend('checkout_ms');
export const options = { iterations: 5, thresholds: { checkout_ms: ['p(95)<%d'], iterations: ['count>=5'] } };
export default function () { checkout.add(%d); }
"""
INVARIANT_OK = "import sys\nprint('orders.total == sum(order_lines.amount): 0 violations')\nsys.exit(0)\n"
INVARIANT_BAD = "import sys\nprint('stock < 0 for 3 rows')\nsys.exit(1)\n"
LOAD_CFG = """load:
  base_url: %s
  scripts:
    - load/checkout.js
  invariant_check:
    - python3
    - load/invariants.py
"""


def test_k6():
    good = {"load/checkout.js": K6 % (100, 10), "load/invariants.py": INVARIANT_OK}
    p = bare_product("k6-clean", good, LOAD_CFG % "http://127.0.0.1:8080")
    rc, out = check(p, "check_load")
    record("k6", "clean: thresholds hold and the product's invariant check passes", rc == 0,
           fails_line(out) if rc else " ".join(l.strip() for l in out.splitlines() if "k6 exit" in l or "invariant" in l)[:200])
    ix = [x for x in index_lines(p) if x["tool"] == "k6"]
    junit = open(os.path.join(p, [x for x in ix if "-junit-" in x["path"]][0]["path"])).read() if ix else ""
    record("k6", "handleSummary wrote JSON and JUnit (one test case per threshold), indexed with the commit",
           len(ix) == 2 and junit.count("<testcase") == 2 and 'failures="0"' in junit and
           all(x["source_commit"] == head(p) and x["exit_code"] == 0 for x in ix),
           "; ".join("%s exit=%s" % (x["path"], x["exit_code"]) for x in ix))
    p = bare_product("k6-broken", {"load/checkout.js": K6 % (100, 500), "load/invariants.py": INVARIANT_OK},
                     LOAD_CFG % "http://127.0.0.1:8080")
    rc, out = check(p, "check_load")
    ix = [x for x in index_lines(p) if x["tool"] == "k6"]
    junit = open(os.path.join(p, [x for x in ix if "-junit-" in x["path"]][0]["path"])).read() if ix else ""
    record("k6", "planted broken threshold: k6 really exits 99 and the check fails",
           rc == 1 and ix and ix[0]["exit_code"] == 99 and "threshold crossed: checkout_ms p(95)<100" in out,
           "k6 exit=%s; %s" % (ix[0]["exit_code"] if ix else "?", fails_line(out)))
    record("k6", "the broken threshold is a failed JUnit test case", '<failure message="threshold crossed: p(95)&lt;100"/>'
           in junit and 'failures="1"' in junit, junit.replace("\n", " ")[:220])
    p = bare_product("k6-nothresh", {"load/checkout.js": "export const options = { iterations: 1 };\nexport default function () {}\n",
                                     "load/invariants.py": INVARIANT_OK}, LOAD_CFG % "http://127.0.0.1:8080")
    rc, out = check(p, "check_load")
    record("k6", "a load script with no thresholds fails (it cannot fail, so it is not a test)",
           rc == 1 and "declares no thresholds" in out, fails_line(out))
    p = bare_product("k6-invariant", {"load/checkout.js": K6 % (100, 10), "load/invariants.py": INVARIANT_BAD},
                     LOAD_CFG % "http://127.0.0.1:8080")
    rc, out = check(p, "check_load")
    record("k6", "planted SQL-invariant violation: the product's own check is required and fails the phase",
           rc == 1 and "invariant check failed (exit 1)" in out and "stock < 0" in out, fails_line(out))
    p = bare_product("k6-noinvariant", {"load/checkout.js": K6 % (100, 10)},
                     "load:\n  base_url: http://127.0.0.1:8080\n  scripts:\n    - load/checkout.js\n")
    rc, out = check(p, "check_load")
    record("k6", "no invariant check declared fails (it is a required second check)",
           rc == 1 and "no load.invariant_check" in out, fails_line(out))
    p = bare_product("k6-prod", good, LOAD_CFG % "https://shop.example.com")
    rc, out = check(p, "check_load")
    record("k6", "a non-loopback base_url is refused before k6 runs (never a production URL)",
           rc == 1 and "not a loopback" in out and not [x for x in index_lines(p) if x["tool"] == "k6"], fails_line(out))
    escape = """import http from 'k6/http';
import { Counter } from 'k6/metrics';
const refused = new Counter('refused_by_blacklist');
export const options = { iterations: 1, thresholds: { refused_by_blacklist: ['count<1'] } };
export default function () {
  const r = http.get('http://93.184.215.14/');
  if (String(r.error).indexOf('blacklisted') >= 0) refused.add(1);
}
"""
    p = bare_product("k6-escape", {"load/checkout.js": escape, "load/invariants.py": INVARIANT_OK},
                     LOAD_CFG % "http://127.0.0.1:8080")
    rc, out = check(p, "check_load")
    record("k6", "a script that calls a public IP is refused by k6's --blacklist-ip (the counter of refusals crossed)",
           rc == 1 and "refused_by_blacklist count<1" in out, fails_line(out))


# ------------------------------------------------------------------ phase helpers (stub checker)
def approve_until(p, pid, target):
    for label in pathmap.LABELS[:pathmap.LABELS.index(target)]:
        pl = {"phase": label, "source_commit": head(p),
              "validation": {"verdict": "pass", "results": [], "digest": "sha256:fixture"}}
        r = E.checker("record", "--product", pid, "--action", "APPROVE %s" % label, "--code", E.fresh(),
                      "--payload-b64", base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
        assert r.returncode == 0, r.stdout + r.stderr
        state.append_line(p, r.stdout.strip())
    entries = [json.loads(l["body"]) for l in E.ledger(p)]
    state.write_phase(p, state.replay(pid, entries))


def gated(name, pid, phase, files):
    p = E.repo(name, docs=("00-brd.md",))
    E.write(p, ".gitignore", "node_modules/\n")
    for rel, text in files.items():
        E.write(p, rel, text)
    E.commit(p, "docs")
    E.init(p, pid)
    E.commit(p, "init")
    approve_until(p, pid, phase)
    return p


def pretool(p, tool, ti, agent_type=None):
    payload = {"hook_event_name": "PreToolUse", "session_id": "v5", "cwd": p, "tool_name": tool, "tool_input": ti}
    if agent_type:
        payload.update(agent_id="agent-x", agent_type=agent_type)
    rc, out, err = E.hook("pretool", payload)
    hs = out.get("hookSpecificOutput") or {}
    return hs.get("permissionDecision", "none"), hs.get("permissionDecisionReason", ""), hs.get("updatedInput")


# ------------------------------------------------------------------ I. Claude Security (phase 9)
REPORT9 = "# Security report\n\n| ID | Severity | Description | Status |\n|---|---|---|---|\n%s\n"


def scan_spec(spec):
    with open(os.path.join(E.shim, "claude-scan.json"), "w") as f:
        json.dump(spec, f)


def wait_scan(p, budget=60):
    """The scan result for the CURRENT HEAD once the worker has finished (an older result
    for a previous commit does not count)."""
    res = os.path.join(p, ".sdlc", "cache", "verify", "9", "claude-security", "result.json")
    lock = os.path.join(os.path.dirname(res), "scan.lock")
    hd = head(p)
    t0 = time.time()
    while time.time() - t0 < budget:
        if os.path.exists(res) and not os.path.exists(lock):
            try:
                r = json.load(open(res))
            except ValueError:
                r = {}
            if r.get("head") == hd:
                return r
        time.sleep(0.25)
    return None


def request_review(p):
    return pretool(p, "Skill", {"skill": "moadix:request-review"})


def test_claude_security():
    calls = os.path.join(E.shim, "claude-calls.log")
    p = gated("cs", "cs-prod", "9", {"src/a.js": BAD_JS, "sdlc/09-security-report.md": REPORT9 % ""})
    scan_spec({"findings": [], "stamp": "head"})
    rc, out, err = E.stop(p)
    time.sleep(1.0)
    record("claude-security", "the Stop hook never starts a scan (a scan costs tokens; only request-review does)",
           not os.path.exists(calls) and not os.path.exists(os.path.join(p, ".sdlc", "cache", "verify", "9",
                                                                           "claude-security", "scan.lock")),
           "claude calls: %d" % (len(open(calls).read().splitlines()) if os.path.exists(calls) else 0))
    d, why, _u = request_review(p)
    res = wait_scan(p)
    log = [json.loads(l) for l in open(calls).read().splitlines()] if os.path.exists(calls) else []
    argv = log[-1]["argv"] if log else []
    record("claude-security", "request-review in phase 9 schedules ONE headless scan: --agent claude-security:claude-security, "
           "auto mode, token cost accepted in the prompt",
           res is not None and res.get("head") == head(p) and len(log) == 1 and "--agent" in argv and
           argv[argv.index("--agent") + 1] == "claude-security:claude-security" and "auto" in argv and
           "I understand it will use a lot of tokens" in " ".join(argv),
           "argv=%s" % " ".join(argv)[:240])
    record("claude-security", "the scan runs in a clone at HEAD outside the product, with no .sdlc/ in it",
           bool(log) and log[-1]["sdlc_in_clone"] is False and not log[-1]["cwd"].startswith(p + os.sep) and
           "/scans/" in log[-1]["cwd"], "cwd=%s" % (log[-1]["cwd"] if log else "-"))
    rc, out = check(p, "check_claude_security")
    record("claude-security", "clean: a scan of HEAD with no findings passes", rc == 0, fails_line(out) if rc else "rc=0")
    request_review(p)
    time.sleep(1.0)
    record("claude-security", "one scan per commit: request-review again at the same HEAD starts nothing",
           len(open(calls).read().splitlines()) == 1, "claude calls: %d" % len(open(calls).read().splitlines()))
    # planted: a high finding and an unconfirmed LOW one
    E.write(p, "src/b.js", BAD_JS)
    E.commit(p, "more code")
    scan_spec({"findings": [
        {"id": "v3:aaa", "severity": "HIGH", "confidence": "HIGH", "panel": {"true": 3, "voters": 3},
         "path": "src/a.js", "line": 2, "title": "OS command injection in ls()"},
        {"id": "v3:bbb", "severity": "LOW", "confidence": "LOW", "path": "src/b.js", "line": 1,
         "title": "maybe an issue"},
        {"id": "v3:ccc", "severity": "MEDIUM", "confidence": "HIGH", "panel": {"true": 2, "voters": 3},
         "path": "src/b.js", "line": 2, "title": "medium thing"}], "stamp": "head"})
    request_review(p)
    res = wait_scan(p)
    fs = {f["plugin_id"]: f for f in (res or {}).get("findings") or []}
    record("claude-security", "SARIF ingested as findings with stable SF-n ids from the gate's register",
           [fs[k]["id"] for k in ("v3:aaa", "v3:bbb", "v3:ccc") if k in fs] == ["SF-1", "SF-2", "SF-3"],
           json.dumps({k: (v["id"], v["severity"]) for k, v in fs.items()}))
    record("claude-security", "a finding it could not confirm (rated LOW, no panel) lands as `unknown`, never low",
           fs.get("v3:bbb", {}).get("severity") == "unknown" and fs.get("v3:bbb", {}).get("confirmed") is False,
           json.dumps(fs.get("v3:bbb")))
    ix = [x for x in index_lines(p) if x["tool"] == "claude-security"]
    record("claude-security", "the SARIF is in the evidence index, stamped with the commit",
           bool(ix) and ix[-1]["source_commit"] == head(p) and ix[-1]["stamp"].startswith("CLAUDE-SECURITY-REVISION-" + head(p)[:12]),
           json.dumps(ix[-1] if ix else {})[:220])
    rc, out = check(p, "check_claude_security")
    record("claude-security", "planted high finding fails (findings only: the gate decides), unconfirmed one too",
           rc == 1 and "[high] SF-1" in out and "[unknown] SF-2" in out and "UNCONFIRMED" in out, fails_line(out))
    record("claude-security", "every SF-n must appear in sdlc/09-security-report.md", "SF-3 (medium) is in the gate's register but not" in out,
           fails_line(out))
    E.write(p, "sdlc/09-security-report.md", REPORT9 % "| SF-1 | low | injection | open |\n| SF-2 | unknown | ? | open |\n| SF-3 | medium | m | open |")
    E.commit(p, "report")
    scan_spec({"findings": [], "stamp": "other"})
    request_review(p)
    res = wait_scan(p)
    rc, out = check(p, "check_claude_security")
    record("claude-security", "a revision stamp for another commit is refused (not evidence for this one)",
           rc == 1 and "expected exactly CLAUDE-SECURITY-REVISION-%s.json" % head(p)[:12] in out, fails_line(out))
    E.write(p, "README.md", "x\n")
    E.commit(p, "x")
    scan_spec({"findings": [], "stamp": "dirty"})
    request_review(p)
    wait_scan(p)
    rc, out = check(p, "check_claude_security")
    record("claude-security", "a -dirty revision stamp is refused", rc == 1 and "-dirty" in out, fails_line(out))
    d, why, _u = pretool(p, "Write", {"file_path": os.path.join(E.base, "scans", "x", "y", "repo", "CLAUDE-SECURITY-x",
                                                                 "CLAUDE-SECURITY-RESULTS.sarif"), "content": "{}"})
    record("claude-security", "the builder cannot write into a scan clone (it could forge the SARIF)",
           d == "deny" and "scan directory" in why, why[:200])
    p0 = gated("cs-p7", "cs-p7", "7", {"src/a.js": CLEAN_JS})
    n = len(open(calls).read().splitlines())
    request_review(p0)
    time.sleep(1.0)
    record("claude-security", "outside phase 9, request-review starts no scan", len(open(calls).read().splitlines()) == n,
           "claude calls unchanged at %d" % n)
    d1, w1, _ = pretool(p, "Skill", {"skill": "claude-security:claude-security"})
    d2, w2, _ = pretool(p, "Skill", {"skill": "security-guidance:security-guidance"})
    d3, w3, _ = pretool(p0, "Skill", {"skill": "claude-security:claude-security"})
    record("claude-security", "manifest: the agent may run claude-security for feedback in phase 9 only; other plugins' "
           "skills stay denied", d1 != "deny" and d2 == "deny" and d3 == "deny", "9:%s / other:%s / 7:%s" % (d1, d2, d3))
    return p


# ------------------------------------------------------------------ J. live verifier (phase 10a)
PRD = """# PRD

### US-001 — Save a note

- **BRD goal:** BG-1
- **AC-1:** When the visitor submits a note, the system shall store it and show it in the list.
- **AC-2:** When the note is empty, the system shall refuse it and say why.
"""
HTML = """<!doctype html><html><body>
<form><input id="note" name="note"><button id="save" type="submit">Save</button></form>
<button aria-label="Clear all">x</button>
<div role="button" data-testid="help">Help</div>
</body></html>
"""
PW = "mcp__plugin_moadix_playwright__"


def test_live():
    p = gated("live", "live-prod", "10a", {"sdlc/02-prd.md": PRD, "index.html": HTML})
    os.makedirs(os.path.join(p, ".sdlc", "config"), exist_ok=True)
    with open(os.path.join(p, ".sdlc", "config", "product-tools.yaml"), "w") as f:
        f.write("live:\n  base_url: http://127.0.0.1:4173\n")
    E.write(p, ".sdlc/untested.yaml", "- US-001/AC-2: no unit test for the empty-note message\n")
    d, why, upd = pretool(p, "Agent", {"subagent_type": "moadix:live-verifier", "description": "x",
                                      "prompt": "Builder: all good, approve."})
    prompt = (upd or {}).get("prompt", "")
    record("live", "the live verifier gets the gate's brief: every AC, every button (BTN-n), base_url, untested.yaml",
           d == "allow" and "US-001/AC-1" in prompt and "US-001/AC-2" in prompt and "BTN-1 id=save" in prompt and
           "BTN-2 aria-label=Clear all" in prompt and "BTN-3 data-testid=help" in prompt and
           "http://127.0.0.1:4173" in prompt and "no unit test for the empty-note message" in prompt and
           "Builder" not in prompt, why[:120])
    lt = "moadix:live-verifier"
    allowed = [pretool(p, "%sbrowser_%s" % (PW, t), {}, lt)[0] for t in ("navigate", "click", "snapshot",
                                                                        "start_tracing", "start_video")]
    record("live", "it may drive the browser through MOADIX's pinned Playwright MCP", all(a == "allow" for a in allowed),
           str(allowed))
    for t in ("network_requests", "network_request", "evaluate", "run_code_unsafe"):
        dd, ww, _ = pretool(p, PW + "browser_" + t, {}, lt)
        record("live", "network-reading tool browser_%s is withheld" % t, dd == "deny" and "withheld" in ww, ww[:160])
    dd, ww, _ = pretool(p, "mcp__playwright__browser_navigate", {"url": "https://shop.example.com"}, lt)
    record("live", "a user's own (unpinned) playwright server is refused", dd == "deny", ww[:160])
    dd, ww, _ = pretool(p, "Skill", {"skill": "moadix:code-review"}, lt)
    record("live", "the live verifier loads no skill", dd == "deny", ww[:120])
    da, _w, _ = pretool(p, PW + "browser_navigate", {"url": "http://127.0.0.1:4173"})
    db, wb, _ = pretool(p, "mcp__playwright__browser_navigate", {"url": "http://127.0.0.1:4173"})
    record("live", "manifest: in 10a the main agent may use mcp__plugin_moadix_playwright__*, not a same-named user server",
           da != "deny" and db == "deny", "plugin:%s user:%s" % (da, db))
    # evidence
    rec = re.search(r"^receipt: ([0-9a-f]+)$", prompt, re.M).group(1)
    bh = re.search(r"^brief_sha256: ([0-9a-f]{64})$", prompt, re.M).group(1)
    edir = os.path.join(p, ".sdlc", "cache", "verify", "10a", "live-verifier", "evidence")

    def evidence(ev, artifacts=True):
        if artifacts:
            os.makedirs(os.path.join(edir, "playwright"), exist_ok=True)
            for n in ("video-1.webm", "trace-1.zip", "save.png"):
                with open(os.path.join(edir, "playwright", n), "wb") as f:
                    f.write(b"fixture artifact")
        with open(os.path.join(edir, "findings.json"), "w") as f:
            json.dump(ev, f)
        return check(p, "check_verifiers", "--phase", "10a")

    base = {"role": "live-verifier", "source_commit": head(p), "brief_sha256": bh, "receipt": rec, "reviewed": [],
            "findings": [],
            "coverage": [{"ac": "US-001/AC-1", "observed": "saved", "artifacts": ["playwright/video-1.webm"]},
                         {"ac": "US-001/AC-2", "observed": "refused", "artifacts": ["playwright/save.png"]}],
            "buttons": [{"id": "BTN-%d" % i, "exercised": True, "observed": "ok",
                         "artifacts": ["playwright/trace-1.zip"]} for i in (1, 2, 3)]}
    rc, out = evidence(base)
    record("live", "clean: every AC and every button backed by trace/video artifacts passes", rc == 0,
           " ".join(out.split())[:300])
    bad = json.loads(json.dumps(base))
    bad["buttons"][1]["exercised"] = False
    rc, out = evidence(bad)
    record("live", "planted: a button not exercised fails", rc != 0 and "BTN-2 was not exercised" in out,
           " ".join(out.split())[:300])
    bad = json.loads(json.dumps(base))
    bad["coverage"][1]["artifacts"] = []
    rc, out = evidence(bad)
    record("live", "planted: an AC with no artifact (not verified live) fails", rc != 0 and "US-001/AC-2 has no artifact" in out,
           " ".join(out.split())[:300])
    os.unlink(os.path.join(edir, "playwright", "video-1.webm"))
    rc, out = evidence(base, artifacts=False)
    record("live", "planted: no video recorded fails (and a cited artifact that does not exist fails)",
           rc != 0 and "no video" in out and "does not exist" in out, " ".join(out.split())[:300])
    # live probe and Arazzo: never a production URL
    surf = ("contract: sdlc/05-lld/notes.openapi.yaml\nenumerate:\n  method: command\n"
            "  command: [\"python3\", \"scripts/routes.py\"]\n")
    p2 = bare_product("live-probe", {"sdlc/05-lld/notes.openapi.yaml": OPENAPI, "sdlc/05-lld/notes.arazzo.yaml": ARAZZO,
                                     "scripts/routes.py": "print('GET /notes')\n"},
                      "live:\n  base_url: https://shop.example.com\n")
    E.write(p2, ".sdlc/config/product-surface.yaml", surf)
    rc, out = check(p2, "check_surface_coverage", "--live")
    record("live", "v1's live probe (re-enabled for 10a) refuses a non-loopback base_url: never a production URL",
           rc == 1 and "not a loopback" in out, fails_line(out))
    rc, out = check(p2, "check_live_contracts")
    record("live", "Arazzo contract tests refuse a non-loopback base_url", rc == 1 and "never a production URL" in out,
           fails_line(out))
    E.write(p2, ".sdlc/config/product-tools.yaml", "live:\n  base_url: http://127.0.0.1:9\n")
    rc, out = check(p2, "check_live_contracts")
    record("live", "Arazzo with the local app not running is UNKNOWN (2), never a pass", rc == 2 and "does not answer" in out,
           fails_line(out))
    if can_bind():
        live_server_cases(p2)
    else:
        skip("live", "Arazzo workflow passes against a running local app; a failing step fails",
             "this sandbox does not allow binding a loopback port (EPERM); run the suite from Terminal")
        skip("live", "the live probe confirms enumerated routes on a running local app",
             "this sandbox does not allow binding a loopback port (EPERM)")


def live_server_cases(p):
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        status = 200

        def do_GET(self):
            self.send_response(H.status if self.path.startswith("/notes") else 200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    E.write(p, ".sdlc/config/product-tools.yaml", "live:\n  base_url: %s\n" % url)
    rc, out = check(p, "check_live_contracts")
    record("live", "Arazzo workflow passes against the running local app", rc == 0, fails_line(out) if rc else url)
    H.status = 500
    rc, out = check(p, "check_live_contracts")
    record("live", "a failing Arazzo step fails the phase", rc == 1, fails_line(out))
    H.status = 200
    rc, out = check(p, "check_surface_coverage", "--live")
    record("live", "the live probe confirms the enumerated route on the running local app", rc == 0, fails_line(out))
    srv.shutdown()


def test_playwright_mcp():
    import toolrun
    argv, _t = toolrun.argv_for("playwright-mcp", ["--isolated", "--headless", "--caps", "devtools"])
    h = os.path.join(E.base, "tmp", "pwhome")
    os.makedirs(h, exist_ok=True)
    c = mcpclient.Client(argv, {"PATH": "/usr/bin:/bin", "HOME": h}, cwd=h, timeout=90)
    try:
        c.start()
        names = sorted(t["name"] for t in c.tools())
    finally:
        c.close()
    sys.path.insert(0, os.path.join(E.home))
    from gate import verify
    withheld = sorted(n for n in names if verify.WITHHELD.search(n))
    record("playwright-mcp", "the pinned Playwright MCP 0.0.83 lists %d tools; exactly the network/script tools match "
           "the withheld pattern" % len(names),
           withheld == ["browser_evaluate", "browser_network_request", "browser_network_requests",
                        "browser_run_code_unsafe"] and "browser_start_tracing" in names and "browser_start_video" in names,
           "withheld: %s" % withheld)
    fm = open(os.path.join(REPO, "agents", "live-verifier.md")).read().split("---")[1]
    listed = re.findall(r"mcp__plugin_moadix_playwright__(\w+)", fm)
    record("playwright-mcp", "the live-verifier agent lists only real, non-withheld tools of the pinned server",
           listed and all(n in names and not verify.WITHHELD.search(n) for n in listed),
           "%d tools listed" % len(listed))
    pj = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))
    pw = pj["mcpServers"]["playwright"]["args"]
    record("playwright-mcp", "plugin.json pins the server (tools/playwright-mcp-0.0.83), storage-state, loopback origins, "
           "and saves to the live verifier's evidence folder",
           "playwright-mcp-0.0.83" in pw[0] and "--storage-state" in pw and "--isolated" in pw and
           pw[pw.index("--output-dir") + 1] == ".sdlc/cache/verify/10a/live-verifier/evidence/playwright" and
           all("127.0.0.1" in o or "localhost" in o or "[::1]" in o for o in pw[pw.index("--allowed-origins") + 1].split(";")),
           " ".join(pw[1:])[:240])


# ------------------------------------------------------------------ K. release (phase 11)
GOOD_WF = ("on: {push: {branches: [main]}}\njobs:\n  release:\n    runs-on: ubuntu-latest\n    steps:\n"
           "      - uses: googleapis/release-please-action@%s\n" % ("a" * 40))


def gh_spec(p, **kw):
    hd = head(p)
    spec = {"tools": [], "commit": {"sha": hd},
            "prs": [{"number": 7}],
            "pr": {"number": 7, "merged": True, "merge_commit_sha": hd, "head": {"ref": "release-please--branches--main"},
                   "merged_by": {"login": "moad", "type": "User"}},
            "runs": [{"name": "ci", "head_sha": hd, "status": "completed", "conclusion": "success"},
                     {"name": "old", "head_sha": "f" * 40, "status": "completed", "conclusion": "failure"}],
            "alerts": [{"number": 3, "rule": {"id": "js/xss", "security_severity_level": "medium"}}]}
    spec.update(kw)
    d = os.path.join(E.home, "tools", "github-mcp-server-2.0.3")
    with open(os.path.join(d, "spec.json"), "w") as f:
        json.dump(spec, f)


def release_product(name, wf=GOOD_WF):
    return bare_product(name, {"release-please-config.json": json.dumps({"packages": {".": {"release-type": "node"}}}),
                               ".release-please-manifest.json": json.dumps({".": "1.2.0"}),
                               ".github/workflows/release.yml": wf},
                        "release:\n  repo: someone/shop\n")


def test_release():
    tok = {"MOADIX_TEST_GITHUB_TOKEN": "ghp_fixture"}
    p = release_product("rel-clean")
    gh_spec(p)
    rc, out = check(p, "check_release", env=tok)
    calls = [json.loads(l) for l in open(os.path.join(E.home, "tools", "github-mcp-server-2.0.3", "calls.log")).read().splitlines()]
    record("release", "clean: release-please PR merged by a human, CI green for HEAD, no high alert -> pass",
           rc == 0, fails_line(out) if rc else " ".join(l.strip() for l in out.splitlines() if "release PR" in l))
    record("release", "the gate started the GitHub MCP server with --read-only (it is the MCP client)",
           calls and calls[-1]["argv"][:2] == ["stdio", "--read-only"] and calls[-1]["token"], json.dumps(calls[-1])[:160])
    gh_spec(p, pr={"number": 7, "merged": True, "merge_commit_sha": head(p), "head": {"ref": "release-please--branches--main"},
                   "merged_by": {"login": "release-bot[bot]", "type": "Bot"}})
    rc, out = check(p, "check_release", env=tok)
    record("release", "planted: the release PR merged by a bot fails (a human merges it)", rc == 1 and "not by a human" in out,
           fails_line(out))
    gh_spec(p, runs=[{"name": "ci", "head_sha": head(p), "status": "completed", "conclusion": "failure"}])
    rc, out = check(p, "check_release", env=tok)
    record("release", "planted: a failed CI run for HEAD fails", rc == 1 and "concluded failure" in out, fails_line(out))
    gh_spec(p, alerts=[{"number": 9, "rule": {"id": "js/sql-injection", "security_severity_level": "high"}}])
    rc, out = check(p, "check_release", env=tok)
    record("release", "planted: an open high code-scanning alert fails", rc == 1 and "js/sql-injection" in out, fails_line(out))
    gh_spec(p, prs=[], pr=None)
    rc, out = check(p, "check_release", env=tok)
    record("release", "planted: HEAD not the merge of a release PR fails", rc == 1 and "not the merge commit" in out,
           fails_line(out))
    gh_spec(p, tools=["merge_pull_request", "push_files"])
    rc, out = check(p, "check_release", env=tok)
    record("release", "a GitHub MCP server offering write tools is refused: the gate reads nothing from it",
           rc == 1 and "not in --read-only mode" in out, fails_line(out))
    gh_spec(p)
    rc, out = check(p, "check_release")
    record("release", "no read-only token is UNKNOWN (2), never a pass", rc == 2 and "no read-only GitHub token" in out,
           fails_line(out))
    p2 = release_product("rel-tag", GOOD_WF.replace("a" * 40, "v4"))
    gh_spec(p2)
    rc, out = check(p2, "check_release", env=tok)
    record("release", "planted: release-please-action pinned by tag (movable) fails", rc == 1 and "pin it to a full commit SHA" in out,
           fails_line(out))
    real = os.path.join(TOOLS, "github-mcp-server-2.0.3", "github-mcp-server")
    h = os.path.join(E.base, "tmp", "ghhome")
    os.makedirs(h, exist_ok=True)
    import check_release
    lists = {}
    for mode, args in (("ro", check_release.READ_ONLY_ARGS),
                       ("rw", [a for a in check_release.READ_ONLY_ARGS if a != "--read-only"])):
        c = mcpclient.Client([real] + args, {"PATH": "/usr/bin:/bin", "HOME": h, "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_x"},
                             cwd=h, timeout=60)
        try:
            c.start()
            lists[mode] = sorted(t["name"] for t in c.tools())
        finally:
            c.close()
    ro_writes = [n for n in lists["ro"] if check_release.WRITE_TOOL.search(n)]
    rw_writes = [n for n in lists["rw"] if check_release.WRITE_TOOL.search(n)]
    record("release", "the REAL pinned github-mcp-server 2.0.3 with --read-only lists no write tool (%d tools)" % len(lists["ro"]),
           not ro_writes and "list_code_scanning_alerts" in lists["ro"] and "actions_list" in lists["ro"], str(ro_writes))
    record("release", "negative control: without --read-only it lists write tools, and the gate's check catches them",
           "merge_pull_request" in rw_writes and "push_files" in rw_writes, "%d write tools: %s" % (len(rw_writes), rw_writes[:5]))


# ------------------------------------------------------------------ L. waivers for verifier findings
def test_waivers(p9):
    p = gated("waive", "waive-prod", "7", {"src/a.js": CLEAN_JS})
    edir = os.path.join(p, ".sdlc", "cache", "verify", "7", "code-reviewer", "evidence")
    os.makedirs(edir)
    with open(os.path.join(edir, "findings.json"), "w") as f:
        json.dump({"role": "code-reviewer", "findings": [
            {"id": "S1", "severity": "medium", "summary": "naming", "citations": ["src/a.js:1"]},
            {"id": "P1", "severity": "high", "summary": "AC missing", "citations": ["src/a.js:1"]}]}, f)
    exp = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 30 * 86400))

    def waive(prod, wid):
        return E.prompt(prod, "WAIVE %s owner=moad scope=src/a.js expiry=%s reason=accepted for now %s" % (
            wid, exp, E.fresh()))

    out = waive(p, "code-reviewer.S1")
    stt = E.prompt(p, "STATUS")
    record("waivers", "WAIVE accepts a verifier finding id (code-reviewer.S1, medium) with owner, scope and expiry",
           "code-reviewer.S1 (owner moad, scope src/a.js, expires %s)" % exp in stt, out[:200])
    out = waive(p, "code-reviewer.P1")
    stt = E.prompt(p, "STATUS")
    record("waivers", "WAIVE of a high verifier finding is refused", "CANNOT be waived" in out and
           "code-reviewer.P1 (" not in stt, out[:200])
    out = waive(p, "code-reviewer.Z9")
    record("waivers", "WAIVE of a verifier finding that is not in the evidence is refused", "has no finding Z9" in out,
           out[:200])
    out = waive(p9, "SF-2")
    record("waivers", "WAIVE of an unconfirmed Claude Security finding (unknown severity) is refused",
           "CANNOT be waived" in out and "unknown" in out, out[:200])
    out = waive(p9, "SF-3")
    stt = E.prompt(p9, "STATUS")
    record("waivers", "WAIVE of a medium Claude Security finding (SF-3) is recorded", "SF-3 (owner moad" in stt,
           out[:200])


# ------------------------------------------------------------------ M. end to end through the worker
def test_worker():
    p = gated("e2e5", "e2e5-prod", "5", {"sdlc/05-lld/notes.openapi.yaml": OPENAPI.replace(
        "      operationId: listNotes\n", "      operationId: listNotes\n      parameters: [{name: id, in: path, required: true, schema: {type: string}}]\n")})
    ctx = E.review_until_fresh(p, "5", tries=240)
    record("worker", "end to end: the Stop hook runs check-contracts in the gate's worker; REVIEW shows it failing",
           "check-contracts: FAIL" in ctx, ctx[:300])


def main():
    install_tools()
    t0 = time.time()
    test_pins()
    test_redocly()
    test_dotenvx()
    test_gitleaks()
    test_osv()
    test_trivy()
    test_semgrep()
    test_k6()
    p9 = test_claude_security()
    test_live()
    test_playwright_mcp()
    test_release()
    test_waivers(p9)
    test_worker()
    viol = E.violations()
    record("guard", "no test touched a real product, a real container engine or the user's files", not viol,
           json.dumps(viol[:3]))
    n = len(RESULTS)
    ok = sum(1 for r in RESULTS if r[2])
    print("\n%d checks, %d passed, %d failed, %d skipped (%.0f s)" % (n, ok, n - ok, len(SKIPPED), time.time() - t0))
    for g, name, why in SKIPPED:
        print("  skipped [%s] %s: %s" % (g, name, why))
    E.remove()
    sys.exit(0 if ok == n else 1)


if __name__ == "__main__":
    main()
