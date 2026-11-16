#!/usr/bin/python3
"""0.7.1 suite: the plain defects from the task-tracker run (~/task-tracker/docs/moadix-findings.md).

    /usr/bin/python3 tests/rel071/run.py

Fixtures only: throwaway repos under $TMPDIR, the stub checker, no network.

  hook        each loosened rule (L1-L6) with the command it now lets through, and next to it the
              guarded commands that must stay refused (G-cases), through the real PreToolUse hook
  memory      a write to Claude Code's memory folder is refused with its own reason (MF-6)
  linter      the coverage linter runs in the file form /moadix:coverage gives (MF-15)
  docs        the WAIVE and COLLAPSE lines come from opcmd.USAGE (MF-9, MF-13); the README table is
              generated (MF-4); one definition of size S (MF-2); forge-idea asks in rounds (MF-1)
  ids         the critic's brief names the GC ids its new findings will get, and ingest agrees (MF-14)
  collapse    COLLAPSE 11b under a WEB ruling, at size S and M; refused under APP-FIRST (MF-3)
"""
import base64
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r71").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import contract, opcmd, pathmap, state  # noqa: E402
import contract_fixture  # noqa: E402

RESULTS = []
T0 = time.time()
GIT = "/usr/bin/git"
FIX_BRD = open(os.path.join(REPO, "tests", "fixtures", "product", "sdlc", "00-brd.md")).read()
GATE_BIN = "moadix-" + "checker"  # spelled apart so this file's own text names no gate program


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % str(evidence)[:900])


def head(p):
    return subprocess.run([GIT, "-C", p, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def product(name, brd=FIX_BRD):
    p = E.repo(name, docs=())
    E.write(p, "sdlc/00-brd.md", brd)
    E.commit(p, "brd")
    E.init(p, name + "fx")
    E.commit(p, "init")
    return p


def line(p, pid, action, payload):
    """A ledger line the operator's code would record (the stub checker signs it)."""
    pl = dict(payload, source_commit=head(p))
    r = E.checker("record", "--product", pid, "--action", action, "--code", E.fresh(),
                  "--payload-b64", base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
    assert r.returncode == 0, r.stdout + r.stderr
    state.append_line(p, r.stdout.strip())
    entries = [json.loads(x["body"]) for x in E.ledger(p)]
    state.write_phase(p, state.replay(pid, entries))


# ------------------------------------------------------------------ hook (MF-5, MF-8, MF-16)
def test_hook():
    G = "hook"
    p = product("hooky")
    scratch = os.path.join(E.base, "scratch")
    E.write(p, "docs/notes.md", "notes\n")
    # Each loosened rule: (rule, finding, command that used to be refused and now passes).
    loosened = [
        ("L1 a $( or backtick inside single quotes is literal text, not a substitution", "MF-5",
         "grep -c '`WAIVE`' .sdlc/phase.yaml"),
        ("L2 a substitution whose body only reads ($(git show ...), $(cat ...)) is not opaque", "MF-16d",
         'echo "$(git show HEAD:.sdlc/phase.yaml | head -3)"'),  # 0.7.2: a literal revision only
        ("L3 a quoted-tag heredoc body is data: the gate's names in it do not refuse the command", "MF-8",
         "cat >> docs/notes.md <<'EOF'\nran contract.py coverage; the %s is root-owned\nEOF\ngit status" % GATE_BIN),
        ("L4 the gate's names in the arguments of a command that only reads are data", "MF-8",
         "grep -n %s docs/notes.md" % GATE_BIN),
        ("L5 a literal assignment that opens the command is resolved in write targets", "MF-16b",
         'S=%s; mkdir -p "$S"' % scratch),
        ("L6 sed -i: BSD's suffix argument and the script are not files", "MF-16c",
         "sed -i '' 's/notes/Notes/' docs/notes.md"),
    ]
    for rule, mf, cmd in loosened:
        d, why = E.pretool(p, "Bash", {"command": cmd})
        record(G, "%s (%s): allowed" % (rule, mf), d != "deny", "%s -> %s %s" % (cmd, d, why))
    # Guarded commands: each loosened rule's planted bypass, plus the rules this release tightened.
    guarded = [
        ("L1", 'echo "$(rm -rf .sdlc)"'),
        ("L1", 'echo "`rm -rf .sdlc`"'),
        ("L2", 'echo "$(cat docs/notes.md | sh)" .sdlc'),
        ("L2", 'echo "$(git -c core.pager=sh log)" .sdlc'),
        ("L2", 'echo "$(awk \'BEGIN{system(\\"x\\")}\')" .sdlc'),
        ("L2", 'echo "$(git log --output=.sdlc/x)"'),
        ("L2", 'echo "$(cat docs/notes.md > .sdlc/x)"'),
        ("L2", "echo >(cat) .sdlc"),
        ("L3", "cat > docs/n.md <<EOF\n$(%s record)\nEOF" % GATE_BIN),
        ("L3", "python3 - <<'EOF'\nprint('%s')\nEOF" % GATE_BIN),
        ("L3", "cat <<'EOF' | sh\nrm -rf .sdlc\nEOF"),
        ("L4", "grep x docs/notes.md; %s record" % GATE_BIN),
        ("L4", "./cat %s" % GATE_BIN),
        ("L4", "grep -l x docs/notes.md | xargs %s" % GATE_BIN),
        ("L5", 'S=.sdlc; rm -rf "$S"'),
        ("L5", 'test -d x && S=/tmp/a; rm -rf "$S"'),
        ("L5", 'S=/tmp/a | rm -rf "$S"'),
        ("L5", 'S=/tmp/a; read S; rm -rf "$S"'),
        ("L5", "S=/tmp/a; touch '$S'"),
        ("L5", 'HOME=/tmp; rm -rf "$HOME/.sdlc"'),
        ("L5", 'S=/tmp/a; S=.sdlc; rm -rf "$S"'),
        ("L5", 'S=$(pwd); rm -rf "$S/.sdlc"'),
        ("L5", 'mkdir -p "$S"'),
        ("L6", "sed -i '' 's/a/b/' .sdlc/phase.yaml"),
        ("L6", "sed -i.bak -e 's/a/b/' .sdlc/phase.yaml"),
        ("L6", "gsed -i 's/a/b/' .sdlc/phase.yaml"),
        ("L6", "sed -ni 's/a/b/p' .sdlc/phase.yaml"),
        ("L6", "sed -i '' -f docs/notes.md .sdlc/phase.yaml"),
        ("kept", "python3 -c \"print(open('.sdlc/phase.yaml').read())\""),
        ("new", "X=rm; $X -rf .sdlc"),
    ]
    for rule, cmd in guarded:
        d, why = E.pretool(p, "Bash", {"command": cmd})
        record(G, "guarded (%s) stays refused: %s" % (rule, " ".join(cmd.split())[:90]), d == "deny",
               "%s -> %s %s" % (cmd, d, why))
    # the write a resolved variable names is checked like a literal one
    d, why = E.pretool(p, "Bash", {"command": 'S=sdlc/09-x.md; touch "$S"'})
    record(G, "L5: a resolved target is checked against the phase's path map like a literal one",
           d == "deny" and "09-x.md" in why, why)


def test_memory():
    G = "memory"
    p = product("memo")
    target = os.path.join(os.path.expanduser("~"), ".claude", "projects", "-x-memo", "memory", "note.md")
    d, why = E.pretool(p, "Write", {"file_path": target, "content": "x"})
    record(G, "a write to Claude Code's memory folder is refused, and the reason names standing instructions",
           d == "deny" and "auto-memory" in why and "standing" in why, why)
    d, why = E.pretool(p, "Write", {"file_path": os.path.join(os.path.expanduser("~"), ".claude", "settings.json"),
                                    "content": "x"})
    record(G, "the rest of ~/.claude stays refused as before", d == "deny" and "user-level Claude Code" in why, why)


# ------------------------------------------------------------------ linter (MF-15)
def test_linter():
    G = "linter"
    p = product("lint")
    for lint in ("coverage", "discovery", "adr", "trace", "cite"):
        r = subprocess.run([fixtures.PY, "-I", os.path.join(E.home, "gate", "contract.py"), lint, p, "0"],
                           capture_output=True, text=True, env=E.env(), cwd=p)
        out = r.stdout + r.stderr
        record(G, "`python3 -I <plugin>/gate/contract.py %s . 0` runs (no ImportError)" % lint,
               "ImportError" not in out and "Traceback" not in out and r.returncode in (0, 1), out[-600:])


# ------------------------------------------------------------------ docs (MF-1, MF-2, MF-4, MF-9, MF-13)
def test_docs():
    G = "docs"
    doc = open(os.path.join(REPO, "commands", "coverage.md")).read()
    record(G, "commands/coverage.md is the generated text", doc == contract.coverage_doc(), "regenerate it")
    m = re.search(r"The operator's waiver line is exactly `([^`]+)`", doc)
    record(G, "the WAIVE form in /moadix:coverage is opcmd.USAGE's, scope= included",
           m and m.group(1) == opcmd.USAGE["WAIVE"] and "scope=" in m.group(1), m and m.group(1))
    filled = "WAIVE gap-critic.GC-1-3 owner=moad scope=phase-1 expiry=2026-12-31 reason=accepted for now 123456"
    rx = dict(opcmd.COMMANDS)["WAIVE"]
    record(G, "a WAIVE line filled in from that form parses", bool(rx.match(filled)), filled)
    record(G, "the COLLAPSE form in /moadix:coverage is opcmd.USAGE's", "`%s`" % opcmd.USAGE["COLLAPSE"] in doc)
    readme = open(os.path.join(REPO, "README.md")).read()
    record(G, "the README's command table is command_table() (every USAGE verb but REVIEW/STATUS and "
              "those, generated)", opcmd.command_table() in readme and all(
                  "`%s`" % opcmd.USAGE[v] in readme for v in opcmd.USAGE), "regenerate the README table")
    record(G, "the README no longer claims 3 increments", "3 done so far" not in readme)
    prof = open(os.path.join(REPO, "gate", "config", "profiles.yaml")).read()
    sdef = contract.size_definition("S")
    record(G, "size S has one definition (coverage-topics.yaml); profiles.yaml points at it",
           sdef and "single surface" not in prof and "sizes.S.profile" in prof and sdef in doc, sdef)
    forge = open(os.path.join(REPO, "skills", "forge-idea", "SKILL.md")).read()
    record(G, "forge-idea asks in rounds, like /moadix:coverage", "one question at a time" not in forge.lower()
           and "rounds" in forge)


# ------------------------------------------------------------------ ids (MF-14)
def launch(p):
    rc, out, err = E.hook("pretool", {"hook_event_name": "PreToolUse", "session_id": "r71", "cwd": p,
                                      "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "moadix:gap-critic", "prompt": "x",
                                                     "description": "x"}})
    return ((out.get("hookSpecificOutput") or {}).get("updatedInput") or {}).get("prompt", "")


def test_ids():
    G = "ids"
    from gate import verify
    p = product("ids")
    st, size, ruling = contract_fixture.scope_of(p, E)
    contract_fixture.write(p, contract_fixture.files("0", st, size, ruling))
    contract_fixture.commit(p, "contract files 0")
    brief = launch(p)
    record(G, "run 1's brief says the first new finding becomes GC-0-1", "the first becomes GC-0-1" in brief,
           brief[-800:])
    lines = open(os.path.join(p, "sdlc", "0", "COVERAGE.md")).read().splitlines()
    fs = []
    for k, tid in enumerate(("B1", "B2"), 1):
        n = next(i for i, ln in enumerate(lines, 1) if ln.startswith("- %s:" % tid))
        fs.append({"id": "C%d" % k, "topic": tid, "severity": "MINOR", "quote": lines[n - 1][2:50],
                   "citation": "sdlc/0/COVERAGE.md:%d" % n, "fix": "say more"})
    contract_fixture.critic(E, p, "0", findings=fs)
    st, _probs = state.current_state(p)
    _ev, run, _sch = verify.current_critic(p, st, "0")
    record(G, "ingest gives the ids the brief announced (C1 = GC-0-1, C2 = GC-0-2)",
           (run or {}).get("map") == {"C1": "GC-0-1", "C2": "GC-0-2"}, run)
    E.write(p, "docs/extra.md", "x\n")
    E.commit(p, "unrelated")
    brief2 = launch(p)
    record(G, "run 2's brief continues at GC-0-3", "the first becomes GC-0-3" in brief2, brief2[-800:])


# ------------------------------------------------------------------ collapse (MF-3)
def to_11b(p, pid):
    for _pid, lab, _name, _globs in pathmap.scope_phases("greenfield", None):
        if lab == "11b":
            break
        line(p, pid, "APPROVE %s" % lab, {"phase": lab, "validation": {"verdict": "pass", "results": [],
                                                                        "digest": "sha256:fixture"}})


def test_collapse():
    G = "collapse"
    p = product("webs")
    to_11b(p, "websfx")
    ctx = E.prompt(p, "COLLAPSE 11b %s" % E.fresh())
    _b, pl = E.payload(p, len(E.ledger(p)))
    st = E.prompt(p, "STATUS")
    record(G, "WEB, size S: COLLAPSE 11b is recorded with the ruling's reason and check-store-readiness not run",
           " recorded (ledger seq" in ctx and "NOT recorded" not in ctx and pl.get("ruling") == "WEB" and
           pl.get("checks_not_run") == ["check-store-readiness"] and "WEB platform ruling" in ctx, ctx[:400])
    record(G, "phase 11b is COLLAPSED in STATUS", re.search(r"11b[^\n]*COLLAPSED", st) is not None, st[:600])
    ctx = E.prompt(p, "COLLAPSE 12 %s" % E.fresh())
    record(G, "COLLAPSE 12 stays refused: no profile lists 12, but none declares it not applicable",
           "NOT recorded" in ctx, ctx[:300])
    q = product("webm", FIX_BRD.replace("**Size:** S", "**Size:** M"))
    to_11b(q, "webmfx")
    ctx = E.prompt(q, "COLLAPSE 11b %s" % E.fresh())
    record(G, "WEB, size M: COLLAPSE 11b is recorded too (the ruling, not the size, retires 11b)",
           " recorded (ledger seq" in ctx and "NOT recorded" not in ctx, ctx[:300])
    a = product("appf", FIX_BRD.replace("**Target Platform Ruling:** WEB", "**Target Platform Ruling:** APP-FIRST"))
    to_11b(a, "appffx")
    ctx = E.prompt(a, "COLLAPSE 11b %s" % E.fresh())
    record(G, "APP-FIRST: COLLAPSE 11b is refused (11b is an active phase there)", "NOT recorded" in ctx, ctx[:300])


def main():
    try:
        for t in (test_hook, test_memory, test_linter, test_docs, test_ids, test_collapse):
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
