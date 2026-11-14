#!/usr/bin/python3
"""Increment-7b suite: the rulings on increment 7 and the read-only tool gates.

    /usr/bin/python3 tests/inc7b/run.py

Real pinned tools (vacuum, oasdiff, squawk, zizmor, actionlint, Node 24) from the sha256-checked
cache ~/.cache/moadix-tools (managed/fetch_tools.py), run by the fixture gate exactly as the
worker runs them. Fixtures only. Every gate has a clean control and planted defects.
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

TOOLS = os.path.expanduser("~/.cache/moadix-tools")
E = fixtures.Env("v7b").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import contract, pathmap, state  # noqa: E402
import contract_fixture  # noqa: E402

RESULTS = []
T0 = time.time()
FIX = os.path.join(REPO, "tests", "fixtures", "product", "sdlc")


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % str(evidence)[:900])


def short(s, n=400):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


def install_tools():
    tdir = os.path.join(E.home, "tools")
    os.makedirs(tdir, exist_ok=True)
    import toolrun
    for name, t in toolrun.pins().items():
        d = "%s-%s" % (name, t["version"])
        if os.path.isdir(os.path.join(TOOLS, d)):
            os.symlink(os.path.join(TOOLS, d), os.path.join(tdir, d))


def product(name, files=None, config=None):
    p = E.repo(name, docs=("00-brd.md",))
    for rel, text in (files or {}).items():
        E.write(p, rel, text)
    E.commit(p, "product")
    E.init(p, name + "fx")
    if config is not None:
        E.write(p, ".sdlc/config/product-tools.yaml", config)
    return p


def change(p, files, msg="change", remove=()):
    for rel in remove:
        os.unlink(os.path.join(p, rel))
    for rel, text in files.items():
        E.write(p, rel, text)
    E.commit(p, msg)


def check(p, module, *args, feature=None):
    e = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes", MOADIX_FEATURE=feature or "")
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", module + ".py")] + list(args), cwd=p, env=e, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def line(p, pid, action, payload):
    hd = fixtures.sh([fixtures.GIT, "-C", p, "rev-parse", "HEAD"]).stdout.strip()
    pl = dict(payload, source_commit=hd)
    r = E.checker("record", "--product", pid, "--action", action, "--code", E.fresh(),
                  "--payload-b64", base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
    assert r.returncode == 0, r.stdout + r.stderr
    state.append_line(p, r.stdout.strip())
    state.write_phase(p, state.replay(pid, [json.loads(x["body"]) for x in E.ledger(p)]))


def approve_direct(p, pid, labels):
    for lab in labels:
        line(p, pid, "APPROVE %s" % lab, {"phase": lab, "validation": {"verdict": "pass", "results": [],
                                                                       "digest": "sha256:fixture"}})


# ------------------------------------------------------------------ phase 5: vacuum, oasdiff, squawk
SPEC = open(os.path.join(HERE, "clean-openapi.yaml")).read()
CLEAN_SQL = ("SET lock_timeout = '1s';\nSET statement_timeout = '5s';\n"
             "CREATE TABLE IF NOT EXISTS notes (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, body text);\n")
DIRTY_SQL = "CREATE TABLE notes (id serial PRIMARY KEY, body text);\nCREATE INDEX notes_body ON notes (body);\n"
PG = "migrations:\n  dialect: postgres\n  paths: [\"db/migrations/*.sql\"]\n"
ADR = ("# ADR-001: Rename /notes to /memos\n\n- Status: accepted\n\n## Context\n\nThe API moves from /notes to /memos, "
       "a breaking change.\n\n## Alternatives\n\n- keep /notes\n- move to /memos\n\n## Criteria\n\nClarity for clients.\n\n"
       "## Decision\n\nMove; /notes is deprecated for 90 days with a Sunset header (deprecation plan).\n\n"
       "## Consequences\n\nClients migrate.\n\n## Sources\n\n- https://www.rfc-editor.org/rfc/rfc8594 (retrieved 2026-11-01)\n")


def test_api():
    G = "api-tools"
    p = product("api", {"sdlc/05-lld/api.yaml": SPEC, "db/migrations/001.sql": CLEAN_SQL}, PG)
    rc, out = check(p, "check_api_tools")
    record(G, "control: an OWASP-clean spec, no release yet, squawk-clean Postgres migration -> passes (real vacuum, "
              "squawk)", rc == 0 and "no release yet" in out and "squawk: 1 migration file(s), 0 violation(s)" in out,
           short(out, 700))
    record(G, "the gate records the evidence with the three tool versions", "evidence .sdlc/evidence/5/api-tools-" in out and
           "vacuum 0.36.1" in out and "oasdiff 1.35.0" in out and "squawk 2.71.0" in out, short(out, 300))
    change(p, {"sdlc/05-lld/api.yaml": SPEC.replace('        "429": {$ref: "#/components/responses/TooMany"}\n', "")})
    rc, out = check(p, "check_api_tools")
    record(G, "planted: the 429 response removed -> vacuum's OWASP rule fails the phase", rc == 1 and
           "owasp-define-error-responses-429" in out, short(out))
    change(p, {"sdlc/05-lld/api.yaml": SPEC, "db/migrations/001.sql": DIRTY_SQL})
    rc, out = check(p, "check_api_tools")
    record(G, "planted: a migration with serial ids and a blocking index -> squawk fails the phase", rc == 1 and
           "require-concurrent-index-creation" in out and "prefer-identity" in out, short(out))
    change(p, {".squawk.toml": "excluded_rules = [\"require-concurrent-index-creation\", \"prefer-identity\", "
                               "\"prefer-robust-stmts\", \"prefer-bigint-over-int\", \"require-timeout-settings\"]\n"})
    rc, out = check(p, "check_api_tools")
    record(G, "the product's own .squawk.toml (switching the rules off) is never read", rc == 1 and
           "require-concurrent-index-creation" in out and ".squawk.toml" in out, short(out))
    q = product("api-sqlite", {"sdlc/05-lld/api.yaml": SPEC, "db/001.sql": DIRTY_SQL},
                "migrations:\n  dialect: sqlite\n  paths: [\"db/*.sql\"]\n")
    rc, out = check(q, "check_api_tools")
    record(G, "dialect sqlite: squawk is N/A, reported, not run", rc == 0 and "squawk: N/A, migrations are sqlite" in out,
           short(out))
    r = product("api-undeclared", {"sdlc/05-lld/api.yaml": SPEC, "db/001.sql": CLEAN_SQL})
    rc, out = check(r, "check_api_tools")
    record(G, "planted: SQL committed but no migrations.dialect declared -> fails", rc == 1 and
           "declares no migrations.dialect" in out, short(out))
    # oasdiff: a released product, then a breaking change
    s = product("api-rel", {"sdlc/05-lld/api.yaml": SPEC})
    approve_direct(s, "api-relfx", pathmap.LABELS[:pathmap.LABELS.index("11") + 1])
    change(s, {"sdlc/05-lld/api.yaml": SPEC.replace("  /notes:\n", "  /memos:\n")})
    rc, out = check(s, "check_api_tools")
    record(G, "planted: a path removed since the released spec (oasdiff ERR) with no ADR -> fails (real oasdiff)",
           rc == 1 and "oasdiff ERR" in out and "api-path-removed" in out and "/notes" in out, short(out))
    change(s, {"sdlc/5/adr/ADR-001-memos.md": ADR})
    rc, out = check(s, "check_api_tools")
    record(G, "... an accepted ADR naming /notes with a deprecation plan approves the breaking change -> passes",
           rc == 0 and "approved by sdlc/5/adr/ADR-001-memos.md" in out, short(out))
    change(s, {"sdlc/5/adr/ADR-001-memos.md": ADR.replace("Status: accepted", "Status: proposed")})
    rc, out = check(s, "check_api_tools")
    record(G, "... a merely proposed ADR does not", rc == 1 and "oasdiff ERR" in out, short(out))
    u = product("api-none", {})
    rc, out = check(u, "check_api_tools")
    record(G, "planted: no OpenAPI description -> fails", rc == 1 and "no OpenAPI description" in out, short(out))


# ------------------------------------------------------------------ phase 6: tokens, contrast, states
TOKENS = {"color": {"$type": "color", "text": {"$value": "#1a1a1a"}, "bg": {"$value": "#ffffff"},
                    "muted": {"$value": "#9e9e9e"}, "link": {"$value": "{color.text}"}},
          "space": {"$type": "dimension", "s": {"$value": "8px"}, "m": {"$value": {"value": 1, "unit": "rem"}}}}
CONTRAST = "foreground,background,usage\ncolor.text,color.bg,body\n{color.link},color.bg,ui\n"
SCREENS = ("screen,state,status,reference\nNote list,default,designed,design/list.md\nNote list,loading,designed,"
           "design/list.md\nNote list,empty,designed,design/list.md\nNote list,error,n/a,the list never fails on its "
           "own: errors show on the editor\n")
COMPONENTS = "component,state,status,reference\nSave button,enabled,designed,design/list.md\nSave button,disabled,designed,design/list.md\n"
PRD2 = ("# PRD\n\n## Screens\n\n| Screen | Purpose |\n|---|---|\n| Note list | shows notes |\n")
COV2 = "# Coverage\n\n- P5: [screens](../02-prd.md#screens)\n"


def ux_files(**over):
    f = {"design/tokens.json": json.dumps(TOKENS), "design/contrast.csv": CONTRAST, "design/screen-states.csv": SCREENS,
         "design/component-states.csv": COMPONENTS, "design/list.md": "# List\n\nLayouts.\n",
         "sdlc/02-prd.md": PRD2, "sdlc/2/COVERAGE.md": COV2}
    f.update(over)
    return f


def test_ux():
    G = "ux-files"
    p = product("ux", ux_files())
    rc, out = check(p, "check_ux_files")
    record(G, "control: DTCG tokens, body text 17.4:1, every system state, every PRD screen -> passes", rc == 0 and
           "17." in out and "PRD screens (P5): 1" in out, short(out, 600))
    cases = [
        ("a token with an unknown $type", {"design/tokens.json": json.dumps(dict(TOKENS, x={"$type": "colour", "a": {"$value": "#000"}}))},
         "has no valid $type"),
        ("a malformed colour", {"design/tokens.json": json.dumps({"c": {"$type": "color", "a": {"$value": "red"}}})},
         "is not #rgb"),
        ("an alias to nothing", {"design/tokens.json": json.dumps({"c": {"$type": "color", "a": {"$value": "{c.b}"}}})},
         "resolves to no token"),
        ("an alias cycle", {"design/tokens.json": json.dumps({"c": {"$type": "color", "a": {"$value": "{c.b}"},
                                                                     "b": {"$value": "{c.a}"}}})}, "alias cycle"),
        ("tokens.json missing", {"design/tokens.json": None}, "tokens.json is missing"),
        ("body text at 2.7:1 (#9e9e9e on white)", {"design/contrast.csv": "foreground,background,usage\ncolor.muted,color.bg,body\n"},
         "below 4.5:1 for body"),
        ("no body-text pair", {"design/contrast.csv": "foreground,background,usage\ncolor.text,color.bg,ui\n"}, "no body-text pair"),
        ("a screen without its loading state", {"design/screen-states.csv": SCREENS.replace(
            "Note list,loading,designed,design/list.md\n", "")}, "has no loading state"),
        ("an n/a state without a reason", {"design/screen-states.csv": SCREENS.replace(
            "the list never fails on its own: errors show on the editor", "n/a")}, "n/a without a reason"),
        ("a designed state whose reference is not committed", {"design/screen-states.csv": SCREENS.replace(
            "default,designed,design/list.md", "default,designed,design/missing.md")}, "is not a file at HEAD"),
        ("a PRD screen missing from the inventory", {"sdlc/02-prd.md": PRD2 + "| Editor | edits a note |\n"},
         "does not cover PRD screen 'Editor'"),
    ]
    for label, over, why in cases:
        files = ux_files(**{k: v for k, v in over.items() if v is not None})
        q = product("ux-%d" % (cases.index((label, over, why))), {k: v for k, v in files.items()
                                                                  if not (k in over and over[k] is None)})
        rc, out = check(q, "check_ux_files")
        record(G, "planted: %s -> fails" % label, rc == 1 and why in out, short(out))


# ------------------------------------------------------------------ phase 11: zizmor, actionlint
WF = ("name: ci\non:\n  push:\n    branches: [main]\npermissions: {}\njobs:\n  test:\n    name: test\n"
      "    runs-on: ubuntu-latest\n    permissions:\n      contents: read\n    steps:\n"
      "      - uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955  # v4.3.0\n"
      "        with:\n          persist-credentials: false\n      - run: npm test\n")


def test_workflows():
    G = "workflows"
    p = product("wf", {".github/workflows/ci.yml": WF})
    rc, out = check(p, "check_workflows")
    record(G, "control: a pinned, least-privilege workflow -> passes (real zizmor and actionlint)", rc == 0 and
           "zizmor: 0 finding(s)" in out and "actionlint: 0 error(s)" in out, short(out, 500))
    change(p, {".github/workflows/ci.yml": WF.replace("actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955  # v4.3.0",
                                                     "actions/checkout@v4")})
    rc, out = check(p, "check_workflows")
    record(G, "planted: an action pinned by tag, not SHA -> zizmor fails the phase", rc == 1 and "zizmor [" in out and
           "unpinned" in out, short(out))
    change(p, {".github/workflows/ci.yml": WF.replace("      - run: npm test\n",
                                                     "      - run: echo \"${{ github.event.head_commit.message }}\"\n")})
    rc, out = check(p, "check_workflows")
    record(G, "planted: an attacker-controlled expression in a run step -> zizmor (template injection) fails",
           rc == 1 and "template-injection" in out, short(out))
    change(p, {".github/workflows/ci.yml": WF.replace("runs-on: ubuntu-latest", "runs-on: ubuntu-latest\n    timeout-minutes: soon")})
    rc, out = check(p, "check_workflows")
    record(G, "planted: an invalid workflow key value -> actionlint fails", rc == 1 and "actionlint .github/workflows/ci.yml" in out,
           short(out))
    change(p, {".github/workflows/ci.yml": WF.replace("actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955  # v4.3.0",
                                                     "actions/checkout@v4"),
               ".github/zizmor.yml": "rules:\n  unpinned-uses:\n    disable: true\n"})
    rc, out = check(p, "check_workflows")
    record(G, "the product's own zizmor.yml (disabling the rule) is never read", rc == 1 and "unpinned" in out and
           "zizmor.yml" in out, short(out))
    q = product("wf-none", {})
    rc, out = check(q, "check_workflows")
    record(G, "planted: no workflow at all -> fails", rc == 1 and "no workflow is committed" in out, short(out))


# ------------------------------------------------------------------ phases 4 and 9: SEC CSVs
TM = ("# Threat model\n\n### TH-1 Note tampering\n\nAgainst US-001.\n\n### TH-2 Flooding\n\nAgainst US-001.\n\n"
      "### SEC-001 - Stored XSS in a note\n\n- **Trust boundary:** TB-1\n- **Threat:** TH-1\n")
CONTROLS = ("sec_id,th_id,asvs_id,verification\nSEC-001,TH-1,V1.2.1,unit test of the output encoder\n"
            "accepted-risk,TH-2,,operator acceptance recorded in sdlc/04-threat-model.md Residual risk\n")
VERIF = "sec_id,method,evidence,result\nSEC-001,unit test,tests/xss.test.js,verified\n"


def test_sec():
    G = "sec-csv"
    p = product("sec", {"sdlc/04-threat-model.md": TM, "sdlc/4/SEC-CONTROLS.csv": CONTROLS,
                        "sdlc/9/SEC-VERIFICATION.csv": VERIF, "tests/xss.test.js": "test('x', () => {});\n"})
    rc4, out4 = check(p, "check_sec_csv", "--phase", "4")
    rc9, out9 = check(p, "check_sec_csv", "--phase", "9")
    record(G, "control: every SEC-ID and threat mapped (one accepted risk), every control verified -> both pass",
           rc4 == 0 and rc9 == 0, short(out4 + " | " + out9, 600))
    for label, over, phase, why in (
            ("a SEC-ID with no control row", {"sdlc/04-threat-model.md": TM + "\n### SEC-002 - Flood\n\n- **Threat:** TH-2\n"},
             "4", "SEC-002 has no control row"),
            ("a threat with neither control nor accepted risk", {"sdlc/4/SEC-CONTROLS.csv": CONTROLS.splitlines()[0] + "\n" +
                                                                 CONTROLS.splitlines()[1] + "\n"}, "4",
             "threat TH-2 has neither"),
            ("an ASVS ID outside V1-V17", {"sdlc/4/SEC-CONTROLS.csv": CONTROLS.replace("V1.2.1", "V18.1.1")}, "4",
             "not an ASVS 5.0.0 requirement ID"),
            ("a threat the model does not define", {"sdlc/4/SEC-CONTROLS.csv": CONTROLS.replace("TH-1,", "TH-9,")}, "4",
             "TH-9 is not a threat"),
            ("the wrong header", {"sdlc/4/SEC-CONTROLS.csv": CONTROLS.replace("asvs_id", "asvs")}, "4", "lacks column"),
            ("a control left unverified", {"sdlc/9/SEC-VERIFICATION.csv": "sec_id,method,evidence,result\n"}, "9",
             "SEC-001 (a phase-4 control) has no verification row"),
            ("a failed verification", {"sdlc/9/SEC-VERIFICATION.csv": VERIF.replace("verified", "failed")}, "9",
             "SEC-001 failed verification"),
            ("evidence that is not committed", {"sdlc/9/SEC-VERIFICATION.csv": VERIF.replace("tests/xss.test.js",
                                                                                             "tests/gone.test.js")}, "9",
             "is not a file at HEAD"),
            ("an unknown result", {"sdlc/9/SEC-VERIFICATION.csv": VERIF.replace("verified", "probably")}, "9",
             "is not one of verified")):
        change(p, over, label)
        rc, out = check(p, "check_sec_csv", "--phase", phase)
        record(G, "planted (phase %s): %s -> fails" % (phase, label), rc == 1 and why in out, short(out))
        change(p, {"sdlc/04-threat-model.md": TM, "sdlc/4/SEC-CONTROLS.csv": CONTROLS, "sdlc/9/SEC-VERIFICATION.csv": VERIF},
               "restore")


# ------------------------------------------------------------------ phase 10a: LV-INVENTORY.csv
LVI = ("lv_id,target,state,result,artifact\nLV-1,Note list,default,pass,evidence/live/list.webm\n"
       "LV-2,Note list,loading,pass,evidence/live/list.webm\nLV-3,Note list,empty,pass,evidence/live/empty.png\n"
       "LV-4,Save button,enabled,pass,evidence/live/save.webm\nLV-5,Save button,disabled,pass,evidence/live/save.webm\n")


def test_lv():
    G = "lv-inventory"
    p = product("lv", dict(ux_files(), **{"sdlc/10a/LV-INVENTORY.csv": LVI}))
    rc, out = check(p, "check_lv_inventory")
    record(G, "control: every designed screen and component state exercised with an artifact -> passes",
           rc == 0 and "covering 5 of 5" in out, short(out))
    for label, text, why in (
            ("a designed state left out", LVI.replace("LV-5,Save button,disabled,pass,evidence/live/save.webm\n", ""),
             "does not cover save button / disabled"),
            ("a failed state", LVI.replace("LV-3,Note list,empty,pass", "LV-3,Note list,empty,fail"), "failed live verification"),
            ("a pass with no artifact", LVI.replace(",evidence/live/empty.png", ","), "without an artifact"),
            ("a reused LV-ID", LVI.replace("LV-5,", "LV-4,"), "is used twice")):
        change(p, {"sdlc/10a/LV-INVENTORY.csv": text}, label)
        rc, out = check(p, "check_lv_inventory")
        record(G, "planted: %s -> fails" % label, rc == 1 and why in out, short(out))


# ------------------------------------------------------------------ rulings
def test_rulings():
    G = "rulings"
    import hlib
    import toolrun
    reg = {c["id"]: c for c in hlib.load_yaml(os.path.join(REPO, "gate", "config", "registry.yaml"))["components"]}
    want = {"check-sec-controls-4": "4", "check-api-tools-5": "5", "check-ux-files-6": "6", "check-sec-verification-9": "9",
            "check-lv-inventory-10a": "10a", "check-workflows-11": "11", "check-contract-12": "12", "check-verifiers-12": "12"}
    record(G, "the read-only gates and phase 12's checks are registered in their phases, product and feature scope",
           all(str(reg.get(k, {}).get("phase")) == v and reg[k].get("scope") == "both" for k, v in want.items()), "")
    node = toolrun.node()
    record(G, "ruling 5: gate-run npm tools run on the pinned Node 24.22.2 from the tools folder, never the system Node",
           node.startswith(os.path.join(E.home, "tools", "node-24.22.2")) and "homebrew" not in node, node)
    rc, out = check(product("redoc", {"sdlc/05-lld/api.yaml": SPEC}), "check_contracts")
    record(G, "... and Redocly (an npm tool) lints through it", rc == 0, short(out))
    pj = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))
    record(G, "the pinned Playwright MCP server starts with the pinned Node too; plugin.json is 0.5.2 or later",
           "tools/node-24.22.2/node" in pj["mcpServers"]["playwright"]["command"] and pj["version"] >= "0.5.2", pj["version"])
    amd = open(os.path.join(REPO, "docs", "AMENDMENT-3.md")).read()
    record(G, "ruling 1 is in Amendment 3: TH- threats, STR- store release, T- tasks, SR- shared resources; TASK- dropped",
           "TH-/SEC-" in amd and "STR-" in amd and "T- (task)" in amd and "TASK-," not in next(ln for ln in amd.splitlines() if ln.startswith("| Trace IDs")) and "code-simplifier was removed" in amd, "")
    record(G, "ruling 4: code-simplifier is no longer in the tool table", "| Anthropic code-simplifier |" not in amd, "")
    # ruling 2: phase 12 gated on a product cycle; FEATURE waits for it
    p = product("retro")
    approve_direct(p, "retrofx", pathmap.LABELS[:pathmap.LABELS.index("11b") + 1])
    ctx = E.prompt(p, "FEATURE F1 %s" % E.fresh())
    st = E.prompt(p, "STATUS")
    record(G, "ruling 2: after 11b the product is at phase 12; FEATURE is refused and STATUS shows the retro pending",
           "NOT recorded" in ctx and "phase 12 (Retro)" in ctx and "current phase 12" in st and "PENDING" in st, short(ctx))
    d, why = E.pretool(p, "Write", {"file_path": os.path.join(p, "sdlc", "12-retro.md"), "content": "x"})
    d11, why11 = E.pretool(p, "Write", {"file_path": os.path.join(p, "sdlc", "11-release.md"), "content": "x"})
    record(G, "phase 12 owns sdlc/12-*: writable now; phase 11's documents are frozen", d == "none" and d11 == "deny",
           short(why or why11))
    E.write(p, "sdlc/12-retro.md", "# Retro\n\nWhat went well.\n")
    E.commit(p, "retro")
    rv = E.review_until_fresh(p, "12")
    ctx = E.prompt(p, "APPROVE 12 %s" % E.fresh())
    record(G, "APPROVE 12 runs phase 12's contract and gap critic like any phase, and records", "recorded" in ctx and
           "check-contract-12: PASS" in rv and "check-verifiers-12: PASS" in rv, short(rv + " | " + ctx, 600))
    ctx = E.prompt(p, "FEATURE F1 %s" % E.fresh())
    record(G, "... after which FEATURE F1 is recorded", "recorded" in ctx and "NOT" not in ctx, short(ctx))


# ------------------------------------------------------------------ B: PROCEED-PAST over a critic BLOCKER
def test_proceed_past():
    G = "proceed-past"
    p = product("pp")
    contract_fixture.ready(E, p, "0")
    E.review_until_fresh(p, "0", contract=False)
    E.prompt(p, "APPROVE 0 %s" % E.fresh())
    E.write(p, "sdlc/01-research.md", open(os.path.join(FIX, "01-research.md")).read())
    E.commit(p, "research")
    st, size, ruling = contract_fixture.scope_of(p, E)
    contract_fixture.write(p, contract_fixture.files("1", st, size, ruling))
    contract_fixture.commit(p, "contract 1")
    contract_fixture.seed_links(p, {"current_phase": "1", "feature": None})
    rel = "sdlc/1/COVERAGE.md"
    lines = open(os.path.join(p, rel)).read().splitlines()
    n = next(i for i, ln in enumerate(lines, 1) if ln.startswith("- R4:"))
    blocker = {"id": "C1", "topic": "R4", "severity": "BLOCKER", "quote": lines[n - 1][2:50],
               "citation": "%s:%d" % (rel, n), "fix": "cite the legal sources"}
    contract_fixture.critic(E, p, "1", findings=[blocker])
    E.review_until_fresh(p, "1", contract=False)
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    w = E.prompt(p, "WAIVE gap-critic.R4 owner=moad scope=phase-1 expiry=%s reason=let it through %s" % (exp, E.fresh()))
    record(G, "WAIVE never passes a BLOCKER", "NOT recorded" in w and "cannot be waived" in w, short(w))
    n0 = len(E.ledger(p))
    ctx = E.prompt(p, "PROCEED-PAST 1 the operator accepts the legal gap for the toy %s" % E.fresh())
    body, pl = E.payload(p, n0 + 1) if len(E.ledger(p)) > n0 else ({}, {})
    pf = pl.get("passed_findings") or []
    record(G, "PROCEED-PAST (operator, with code) passes the BLOCKER: recorded, and the reply names the finding",
           "recorded" in ctx and "BLOCKER C1 (R4)" in ctx, short(ctx))
    record(G, "the ledger line records the finding it passed: topic, severity, quote, citation, evidence sha256, commit",
           len(pf) == 1 and pf[0]["topic"] == "R4" and pf[0]["severity"] == "BLOCKER" and pf[0]["citation"] == blocker["citation"]
           and re.match(r"^[0-9a-f]{64}$", pf[0]["evidence_sha256"]) and "check-verifiers-1" in (pl.get("failing") or []),
           short(pl))


def main():
    try:
        install_tools()
        for t in (test_api, test_ux, test_workflows, test_sec, test_lv, test_rulings, test_proceed_past):
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
