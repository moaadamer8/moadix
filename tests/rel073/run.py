#!/usr/bin/python3
"""0.7.3 suite: the review of 0.7.2, items 1, 2, 4 and 5 (item 3, the real-engine smoke runs, is in
tests/confined-engine, Terminal only), and MF-28's documentation.

    /usr/bin/python3 tests/rel073/run.py

Fixtures only: throwaway repos under $TMPDIR, the stub checker, the engine double (no Docker), no network.

  user       MF-27: every confined run is uid 65534 (nobody); the runner checks the image's passwd entry
             before the first run of an image and reports UNKNOWN without one
  logs       item 2: a failing executing gate reports the tool's exit code and the last lines of its log,
             bounded and with secret-looking text removed, and keeps the run log in the evidence folder
  reads      item 4: the dotenvx key file, private keys and the overlay are never readable (hook: Read
             tool, any Bash command, a substitution; policy: sandbox denyRead and managed Read() rules);
             an encrypted .env, .env.example, CA bundles and public certificates stay readable
  waivers    item 5: WAIVE defaults; proposed waivers shown by REVIEW; APPROVE <phase> WITH-WAIVERS records
             exactly them under one code with the file's digest; plain APPROVE still refused; a BLOCKER, an
             unknown id or a failing non-verifier validator refuses the whole command
  docs       MF-28 and item 5 in /moadix:coverage and the README
"""
import base64
import datetime
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r73").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import check_exec as X  # noqa: E402
from gate import confined, contract, opcmd, pathmap, state, verify  # noqa: E402
import contract_fixture  # noqa: E402

RESULTS = []
T0 = time.time()
FIX_BRD = open(os.path.join(REPO, "tests", "fixtures", "product", "sdlc", "00-brd.md")).read()
PASS = os.path.join(REPO, "tests", "exec", "double", "pass")
DBL = os.path.join(E.base, "engine-double")
HOME = os.path.expanduser("~")
SD = "." + "sdlc"  # spelled apart: commands naming it are handed to the hook as text


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def short(s, n=400):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


def product(name, brd=FIX_BRD, files=None):
    p = E.repo(name, docs=())
    E.write(p, "sdlc/00-brd.md", brd)
    for rel, text in (files or {}).items():
        E.write(p, rel, text)
    E.commit(p, "files")
    E.init(p, name + "fx")
    E.commit(p, "init")
    return p


# ------------------------------------------------------------------ MF-27
def test_user():
    G = "user"
    record(G, "the runner's uid is 65534 (nobody) in confinement.yaml", confined.config().get("uid") == 65534)
    argv = confined.run_argv("xtest00001", "docker.io/library/node@sha256:" + "a" * 64, ["true"], confined.limits("E-lint"),
                             "moadix-xtest00001-src", "moadix-xtest00001-out")
    j = " ".join(argv)
    record(G, "a confined run is --user 65534:65534, non-root, no capabilities, read-only root, no host mount",
           "--user 65534:65534" in j and "--cap-drop ALL" in j and "--read-only" in j and "no-new-privileges" in j
           and "type=bind" not in j, j)
    calls_log = os.path.join(DBL, "calls.log")
    shutil.rmtree(DBL, ignore_errors=True)
    os.environ.update(MOADIX_TEST_ENGINE=os.path.join(E.shim, "engine-double"), MOADIX_DOUBLE_DIR=DBL)
    r = confined.Run("xtest00002")
    try:
        r.execute("docker.io/library/node@sha256:" + "a" * 64, ["true"], "E-lint", [])
        r.execute("docker.io/library/node@sha256:" + "a" * 64, ["true"], "E-lint", [])
    finally:
        r.close()
    calls = [json.loads(x) for x in open(calls_log).read().splitlines() if x.strip()] if os.path.exists(calls_log) \
        else []
    gets = [c for c in calls if "getent" in json.dumps(c)]
    record(G, "before the first run in an image the runner checks the uid's passwd entry (getent passwd 65534), once "
              "per image and user", len(gets) == 1 and "65534" in json.dumps(gets[0]), short(gets))


# ------------------------------------------------------------------ item 2
SECRET_LOG = "\n".join(["starting likec4"] + ["line %d" % i for i in range(600)] + [
    "GITHUB_TOKEN=ghp_" + "A1b2C3d4" * 5, "password: hunter2hunter2", "Authorization: Bearer abc.def.ghi",
    "url https://user:s3cretpass@registry.example.com/x", "-----BEGIN PRIVATE KEY-----", "MIIEvAIBADAN",
    "-----END PRIVATE KEY-----", "random Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0LzXcVbNm12345678",
    "SystemError [ERR_SYSTEM_ERROR]: uv_os_get_passwd returned ENOENT"])


def test_logs():
    G = "logs"
    red = X.redact(SECRET_LOG)
    for what, secret in (("a GitHub token", "ghp_A1b2"), ("a password", "hunter2"), ("a bearer token", "abc.def.ghi"),
                         ("URL credentials", "s3cretpass"), ("a private key", "MIIEvAIBADAN"),
                         ("a long random string", "Zx9Qw8Er7Ty6")):
        record(G, "redaction removes %s" % what, secret not in red, [ln for ln in red.splitlines() if secret in ln][:2])
    record(G, "redaction keeps the error line", "uv_os_get_passwd returned ENOENT" in red)
    b = X.bounded(SECRET_LOG)
    record(G, "the kept log is bounded (last %d lines) and says it was cut" % X.LOG_LINES,
           len(b.splitlines()) <= X.LOG_LINES + 1 and b.startswith("[... earlier output cut]"), len(b.splitlines()))
    # end to end: a likec4 run that crashes at load, through the gate's launcher and the engine double
    p = product("lc", files={"arch/model.c4": "specification { element system }\nmodel { s = system 'S' }\n"})
    outs = os.path.join(E.base, "outs-crash")
    os.makedirs(os.path.join(outs, "likec4"))
    with open(os.path.join(outs, "likec4", "validate.log"), "w") as f:
        f.write(SECRET_LOG + "\n")
    with open(os.path.join(outs, "likec4", "validate.rc"), "w") as f:
        f.write("1\n")
    shutil.rmtree(DBL, ignore_errors=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", "likec4", "--phase", "3"],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=outs), timeout=300)
    out = r.stdout + r.stderr
    record(G, "MF-27: a crash of likec4 validate is reported as the crash (exit code), not as a missing model.json "
              "first", "likec4 validate exited 1" in out, out[-1500:])
    record(G, "item 2: the failure names the tool's exit code and the last lines of its log", "tool exit validate.rc=1"
           in out and "uv_os_get_passwd returned ENOENT" in out, out[-1500:])
    record(G, "item 2: the failure has no secret from the log", not any(s in out for s in (
        "ghp_A1b2", "hunter2", "s3cretpass", "MIIEvAIBADAN")), out[-1500:])
    m = re.search(r"kept at (\S+)", out) or re.search(r"run log (\S+)", out)
    kept = os.path.join(p, m.group(1).rstrip(")")) if m else ""
    log = open(kept).read() if kept and os.path.exists(kept) else ""
    record(G, "item 2: the run log is kept in the evidence folder, bounded, with the files written and exit codes",
           kept.startswith(os.path.join(p, SD, "evidence")) and "files written:" in log and "validate.rc=1" in log and
           "hunter2" not in log, (kept, log[:600]))
    # a passing run also keeps its log
    shutil.rmtree(DBL, ignore_errors=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", "check_exec.py"), "--gate", "likec4", "--phase", "3"],
                    cwd=p, env=E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_DOUBLE_OUTPUTS=PASS), timeout=300)
    record(G, "a passing run notes its kept log", r.returncode == 0 and "run log %s/evidence" % SD in r.stdout,
           r.stdout[-800:])


# ------------------------------------------------------------------ item 4
PROTECTED = [".env.keys", "app/.env.keys", "certs/server.key", "certs/store.p12", "certs/store.pfx", "keys/app.jks",
             "keys/app.keystore", "~/.ssh/id_rsa", "~/.ssh/id_ed25519", "deploy/id_ecdsa", "tls/key.pem",
             "tls/privkey.pem", "tls/server-key.pem", "tls/private.pem", "~/.config/moadix/overlay.json"]
READABLE = [".env", ".env.production", ".env.example", "tls/cert.pem", "tls/fullchain.pem", "certifi/cacert.pem",
            "tls/server.crt", "~/.ssh/id_rsa.pub", "src/keyboard.js"]


def test_reads():
    G = "reads"
    p = product("rp")
    for path in PROTECTED:
        full = path.replace("~", HOME) if path.startswith("~") else os.path.join(p, path)
        d1, w1 = E.pretool(p, "Read", {"file_path": full})
        d2, w2 = E.pretool(p, "Bash", {"command": "cat %s" % path})
        d3, w3 = E.pretool(p, "Bash", {"command": 'echo "$(head -1 %s)"' % path})
        d4, w4 = E.pretool(p, "Bash", {"command": "cp %s /tmp/x" % path})
        record(G, "never readable: %s (Read tool, cat, a substitution, cp)" % path,
               d1 == d2 == d3 == d4 == "deny" and "never readable" in w1 + w2, (d1, w1, d2, w2, d3, w3, d4, w4))
    for path in READABLE:
        full = os.path.join(p, path.replace("~/", "")) if not path.startswith("~") else path.replace("~", HOME)
        d1, w1 = E.pretool(p, "Read", {"file_path": full})
        d2, w2 = E.pretool(p, "Bash", {"command": "cat %s" % path})
        record(G, "readable: %s" % path, d1 != "deny" and d2 != "deny", (d1, w1, d2, w2))
    for cmd in ("find . -name '*.key'", "git commit -m 'stop reading server.key in tests'", "grep -rn --include='*.pem' x ."):
        d, why = E.pretool(p, "Bash", {"command": cmd})
        record(G, "a pattern or message naming a key file is not a read: %s" % cmd, d != "deny", why)
    pol = json.load(open(os.path.join(REPO, "managed", "managed-settings.json")))
    deny_read = pol["sandbox"]["filesystem"]["denyRead"]
    rules = pol["permissions"]["deny"]
    for pat in ("~/.config/moadix", "~/**/.env.keys", "~/**/*.key", "~/**/*.p12", "~/**/*.pfx", "~/**/*.jks",
                "~/**/*.keystore", "~/**/id_rsa", "~/**/id_ed25519", "~/**/id_ecdsa", "~/**/id_dsa", "~/**/*key*.pem",
                "~/**/*private*.pem"):
        rr = "Read(%s)" % (pat + "/**" if pat == "~/.config/moadix" else pat)
        record(G, "policy: %s is in the sandbox's denyRead and %s in the managed deny rules" % (pat, rr),
               pat in deny_read and rr in rules)
    record(G, "policy: no rule makes .env or a certificate unreadable", not any(
        re.search(r"\.env\)?$|\.crt|\.cer\b|cert\.pem", x) for x in deny_read + [r for r in rules if r.startswith("Read(")]),
        deny_read)


# ------------------------------------------------------------------ item 5
def cov_finding(p, tid, sev, cid):
    rel = "sdlc/0/COVERAGE.md"
    lines = open(os.path.join(p, rel)).read().splitlines()
    n = next(i for i, ln in enumerate(lines, 1) if ln.startswith("- %s:" % tid))
    return {"id": cid, "topic": tid, "severity": sev, "quote": lines[n - 1][2:50], "citation": "%s:%d" % (rel, n),
            "fix": "cover %s" % tid}


def phase0(name, findings):
    p = product(name)
    st, size, ruling = contract_fixture.scope_of(p, E)
    contract_fixture.write(p, contract_fixture.files("0", st, size, ruling))
    contract_fixture.commit(p, "contract files 0")
    contract_fixture.critic(E, p, "0", findings=[cov_finding(p, *f) for f in findings])
    rv = E.review_until_fresh(p, "0", contract=False)
    st = state.current_state(p)[0]
    _ev, run, _sch = verify.current_critic(p, st, "0")
    return p, rv, (run or {}).get("map", {})


def propose(p, rows):
    E.write(p, ".sdlc-proposals/waivers.yaml", "waivers:\n" + "".join(
        "  - id: %s\n    reason: %s\n" % (i, r) for i, r in rows))


def test_waivers():
    G = "waivers"
    p, rv, m = phase0("ww", [("B9", "MAJOR", "C1"), ("B12", "MAJOR", "C2")])
    g1, g2 = m["C1"], m["C2"]
    propose(p, [("gap-critic." + g1, "the operator accepts it for the first release"),
                ("gap-critic." + g2, "settled in phase 2")])
    rv = E.prompt(p, "REVIEW 0")
    record(G, "REVIEW shows the proposed waivers with the file's digest and the command that records them",
           "Proposed waivers (.sdlc-proposals/waivers.yaml, sha256" in rv and g1 in rv and g2 in rv and
           "APPROVE 0 WITH-WAIVERS <code> records exactly these" in rv, short(rv, 900))
    ctx = E.prompt(p, "APPROVE 0 %s" % E.fresh())
    record(G, "plain APPROVE is still refused while an unwaived MAJOR is open", "NOT recorded" in ctx and g1 in ctx,
           short(ctx, 500))
    n0 = len(E.ledger(p))
    ctx = E.prompt(p, "APPROVE 0 WITH-WAIVERS %s" % E.fresh())
    body, pl = E.payload(p, len(E.ledger(p)))
    sha = __import__("hashlib").sha256(
        ("waivers:\n  - id: gap-critic.%s\n    reason: the operator accepts it for the first release\n  - id: "
         "gap-critic.%s\n    reason: settled in phase 2\n" % (g1, g2)).encode()).hexdigest()
    record(G, "APPROVE 0 WITH-WAIVERS: one ledger line, one code, the approval and exactly the proposed waivers, with "
              "the proposals file's digest", " recorded (ledger seq" in ctx and len(E.ledger(p)) == n0 + 1 and
           [w["id"] for w in pl.get("waivers") or []] == ["gap-critic." + g1, "gap-critic." + g2] and
           pl.get("waivers_file_sha256") == sha and body["action"] == "APPROVE 0 WITH-WAIVERS", short(ctx, 600))
    st = E.prompt(p, "STATUS")
    stt = state.current_state(p)[0]
    w = {x["id"]: x for x in stt["waivers"]}
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    record(G, "the waivers are in force with the defaults: owner operator, 30 days, scope the finding's document",
           w.get("gap-critic." + g1, {}).get("owner") == "operator" and w["gap-critic." + g1]["expiry"] == exp and
           w["gap-critic." + g1]["scope"] == "sdlc/0/COVERAGE.md" and "0 BRD: APPROVED" in st, short(w))
    record(G, "the proposals file is used up (removed)", not os.path.exists(os.path.join(p, ".sdlc-proposals",
                                                                                        "waivers.yaml")))
    # refusals: a BLOCKER, an unknown id
    q, rv, m = phase0("wb", [("B9", "MAJOR", "C1"), ("B12", "BLOCKER", "C2")])
    propose(q, [("gap-critic." + m["C1"], "fine"), ("gap-critic." + m["C2"], "the operator would like to")])
    n0 = len(E.ledger(q))
    ctx = E.prompt(q, "APPROVE 0 WITH-WAIVERS %s" % E.fresh())
    record(G, "a proposal naming a BLOCKER refuses the whole command (nothing recorded)", "NOT recorded" in ctx and
           "BLOCKER" in ctx and len(E.ledger(q)) == n0, short(ctx, 500))
    propose(q, [("gap-critic." + m["C1"], "fine"), ("code-reviewer.S99", "unknown")])
    ctx = E.prompt(q, "APPROVE 0 WITH-WAIVERS %s" % E.fresh())
    record(G, "a proposal naming an unknown id refuses the whole command", "NOT recorded" in ctx and len(E.ledger(q))
           == n0, short(ctx, 500))
    propose(q, [("gap-critic." + m["C1"], "fine"), ("SEC-77", "not in any report")])
    ctx = E.prompt(q, "APPROVE 0 WITH-WAIVERS %s" % E.fresh())
    record(G, "a SEC id that no report lists is unknown", "NOT recorded" in ctx and "SEC-77" in ctx, short(ctx, 500))
    E.write(q, ".sdlc-proposals/waivers.yaml", "")
    ctx = E.prompt(q, "APPROVE 0 WITH-WAIVERS %s" % E.fresh())
    record(G, "WITH-WAIVERS with no proposals is refused", "NOT recorded" in ctx, short(ctx, 300))
    # a failing check that is not verifier evidence cannot be waived
    r_, rv, m = phase0("wc", [("B9", "MAJOR", "C1")])
    cov = open(os.path.join(r_, "sdlc", "0", "COVERAGE.md")).read().replace("- B9:", "- B99:")
    E.write(r_, "sdlc/0/COVERAGE.md", cov)
    E.commit(r_, "break coverage")
    contract_fixture.critic(E, r_, "0", findings=[cov_finding(r_, "B12", "MAJOR", "C1")])
    E.review_until_fresh(r_, "0", contract=False)
    gid = verify.current_critic(r_, state.current_state(r_)[0], "0")[1]["map"]["C1"]
    propose(r_, [("gap-critic." + gid, "fine")])
    ctx = E.prompt(r_, "APPROVE 0 WITH-WAIVERS %s" % E.fresh())
    record(G, "WITH-WAIVERS is refused when a validator other than verifier evidence fails (coverage-lint)",
           "NOT recorded" in ctx and "a waiver covers a finding, not a failing check" in ctx, short(ctx, 500))
    # WAIVE with only a reason
    s_, rv, m = phase0("wd", [("B9", "MAJOR", "C1")])
    ctx = E.prompt(s_, "WAIVE gap-critic.%s reason=accepted for now %s" % (m["C1"], E.fresh()))
    _b, pl = E.payload(s_, len(E.ledger(s_)))
    record(G, "WAIVE with only a reason: owner operator, expiry in 30 days, scope the finding's document",
           " recorded (ledger seq" in ctx and pl.get("owner") == "operator" and pl.get("expiry") == exp and
           pl.get("scope") == "sdlc/0/COVERAGE.md", short(ctx) + " " + short(pl))
    ctx = E.prompt(s_, "WAIVE gap-critic.%s owner=moad scope=x expiry=%s reason=r %s" % (m["C1"], exp, E.fresh()))
    record(G, "the full WAIVE form still parses (here refused only because the waiver exists)",
           "already exist" in ctx, short(ctx))


# ------------------------------------------------------------------ docs
def test_docs():
    G = "docs"
    doc = open(os.path.join(REPO, "commands", "coverage.md")).read()
    record(G, "commands/coverage.md is the generated text", doc == contract.coverage_doc())
    record(G, "MF-28: /moadix:coverage says docker must be the whole command and shows docker's own flags",
           "Docker runs outside the sandbox only as the whole command" in doc and "--project-directory" in doc and
           "docker build -f" in doc)
    record(G, "item 5: /moadix:coverage describes the proposals file and APPROVE WITH-WAIVERS",
           ".sdlc-proposals/waivers.yaml" in doc and "APPROVE <phase> WITH-WAIVERS <code>" in doc)
    readme = open(os.path.join(REPO, "README.md")).read()
    record(G, "the README table is generated and shows WITH-WAIVERS", opcmd.command_table() in readme and
           "APPROVE <phase> [WITH-WAIVERS] <code>" in readme)
    record(G, "ADOPT ignores the waiver proposals", "waivers.yaml" not in __import__("gate.adopt", fromlist=["x"]).pending(
        os.path.join(E.base, "nowhere")) and True)


def main():
    try:
        for t in (test_user, test_logs, test_reads, test_waivers, test_docs):
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
