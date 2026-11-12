#!/usr/bin/python3
"""MOADIX increment-6 suite: feature cycles, onboarding, BMad core, size collapse, and the
increment-5 rulings. Fixtures only (tests/lib/fixtures.py: stub checker, fixture gate copy,
test guard). GitHub and Claude Security are stubbed, as in the increment-5 suite; the pinned
tools come from ~/.cache/moadix-tools (release-please for phase 11's local check).

    /usr/bin/python3 tests/inc6/run.py

Groups:
  feature     a feature cycle from FEATURE through the merge at 11 (real APPROVEs through the
              gate's worker for phases 0-4 and 11; phases 5-10c recorded by the stub checker,
              as the earlier suites do); a contradicting addition refused; a second FEATURE
              while one is active refused; conflicting SEC-IDs refused; path map
  onboarding  INIT on a repo with code -> phase B; a baseline with a dead citation fails and
              with real citations passes (with the fresh-context baseline verifier's evidence);
              APPROVE B; then a feature cycle on the onboarded product through its merge
  bmad        BMad core installed by INIT, byte-identical to upstream, the skills' run folders
              writable in their phase; check-seam's BMAD half catches a tampered script
  collapse    COLLAPSE records a size-profile ruling; refused where the profile does not
  triage      ruling 1: unconfirmed SF findings block until triaged or waived
  session     ruling 5: plugin drift reported at session start
  github      ruling 2: the token comes from the Keychain through the gate's launcher
  installer   ruling 4: root's scratch folder, and the last line
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

TOOLS = os.path.expanduser("~/.cache/moadix-tools")
E = fixtures.Env("v6").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import bmadcore, pathmap, state  # noqa: E402

RESULTS = []
TOK = "ghp_fixture"
os.environ["MOADIX_TEST_GITHUB_TOKEN"] = TOK   # the fixture gate's stand-in for the Keychain item (check-release)


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    ev = " ".join(str(evidence).split())
    print("%s  [%s] %s\n      %s" % ("PASS" if ok else "FAIL", group, name, ev[:600]))


def git(p, *args):
    return subprocess.run([fixtures.GIT, "-C", p] + list(args), capture_output=True, text=True).stdout.strip()


def head(p):
    return git(p, "rev-parse", "HEAD")


def ok_rec(ctx):
    """An operator action the gate recorded (not 'NOT recorded')."""
    return bool(re.search(r" recorded \(ledger seq \d+\)", ctx)) and "NOT recorded" not in ctx


def short(s, n=300):
    return " ".join(str(s).split())[:n]


# ------------------------------------------------------------------ fixture setup
def install_tools():
    """<fixture home>/tools: release-please from the sha256-checked cache, the GitHub MCP stub."""
    tdir = os.path.join(E.home, "tools")
    os.makedirs(tdir, exist_ok=True)
    import toolrun
    for name, t in toolrun.pins().items():
        d = "%s-%s" % (name, t["version"])
        if name == "github-mcp-server":
            os.makedirs(os.path.join(tdir, d), exist_ok=True)
            dst = os.path.join(tdir, d, "github-mcp-server")
            shutil.copy(os.path.join(REPO, "tests", "lib", "github_mcp_stub.py"), dst)
            os.chmod(dst, 0o755)
            with open(os.path.join(tdir, d, ".moadix-tool.json"), "w") as f:
                json.dump({"name": name, "version": str(t["version"]), "kind": "stub"}, f)
        elif os.path.isdir(os.path.join(TOOLS, d)):
            os.symlink(os.path.join(TOOLS, d), os.path.join(tdir, d))
    stub = os.path.join(E.shim, "claude")
    shutil.copy(os.path.join(REPO, "tests", "lib", "claude_stub.py"), stub)
    os.chmod(stub, 0o755)


def line(p, pid, action, payload):
    """A ledger line the operator's code would record (the stub checker signs it)."""
    pl = dict(payload, source_commit=head(p))
    r = E.checker("record", "--product", pid, "--action", action, "--code", E.fresh(),
                  "--payload-b64", base64.b64encode(json.dumps(pl, sort_keys=True).encode()).decode())
    assert r.returncode == 0, r.stdout + r.stderr
    state.append_line(p, r.stdout.strip())
    entries = [json.loads(x["body"]) for x in E.ledger(p)]
    state.write_phase(p, state.replay(pid, entries))


def approve_direct(p, pid, labels, feature=None):
    for lab in labels:
        pl = {"phase": lab, "validation": {"verdict": "pass", "results": [], "digest": "sha256:fixture"}}
        if feature:
            pl["feature"] = feature
        line(p, pid, "APPROVE %s" % lab, pl)


def status(p):
    return E.prompt(p, "STATUS")


def approve(p, label, tries=240):
    """The real path: the agent's turn ends (Stop), the gate's worker runs the phase's validators,
    and the operator's APPROVE reads the result."""
    rv = E.review_until_fresh(p, label, tries=tries)
    return rv, E.prompt(p, "APPROVE %s %s" % (label, E.fresh()))


def pretool(p, tool, ti, agent_type=None):
    payload = {"hook_event_name": "PreToolUse", "session_id": "v6", "cwd": p, "tool_name": tool, "tool_input": ti}
    if agent_type:
        payload.update(agent_id="agent-x", agent_type=agent_type)
    rc, out, err = E.hook("pretool", payload)
    hs = out.get("hookSpecificOutput") or {}
    return hs.get("permissionDecision", "none"), hs.get("permissionDecisionReason", ""), hs.get("updatedInput")


def check(p, module, *args, env=None):
    e = E.env(MOADIX_PRODUCT_ROOT=p, MOADIX_GATE_RUN="yes")
    e.update(env or {})
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "v1", "_launch.py"),
                     os.path.join(E.home, "gate", "v1", module + ".py")] + list(args), cwd=p, env=e, timeout=600)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def fails(out):
    return " | ".join(x.strip() for x in out.splitlines() if re.match(r"^\s+(FAIL|UNKNOWN)", x))[:500] or short(out)


GOOD_WF = ("on: {push: {branches: [main]}}\njobs:\n  release:\n    runs-on: ubuntu-latest\n    steps:\n"
           "      - uses: googleapis/release-please-action@%s\n" % ("a" * 40))
RELEASE_FILES = {"release-please-config.json": json.dumps({"packages": {".": {"release-type": "node"}}}),
                 ".release-please-manifest.json": json.dumps({".": "1.2.0"}),
                 ".github/workflows/release.yml": GOOD_WF}


def gh_spec(p):
    hd = head(p)
    spec = {"tools": [], "commit": {"sha": hd}, "prs": [{"number": 7}],
            "pr": {"number": 7, "merged": True, "merge_commit_sha": hd,
                   "head": {"ref": "release-please--branches--main"}, "merged_by": {"login": "moad", "type": "User"}},
            "runs": [{"name": "ci", "head_sha": hd, "status": "completed", "conclusion": "success"}],
            "alerts": []}
    with open(os.path.join(E.home, "tools", "github-mcp-server-2.0.3", "spec.json"), "w") as f:
        json.dump(spec, f)


def product_config(p):
    os.makedirs(os.path.join(p, ".sdlc", "config"), exist_ok=True)
    with open(os.path.join(p, ".sdlc", "config", "product-tools.yaml"), "w") as f:
        f.write("release:\n  repo: someone/shop\n")


# ------------------------------------------------------------------ documents
PRODUCT_DOCS = {
    "sdlc/02-prd.md": open(os.path.join(fixtures.FIXDOCS, "sdlc", "02-prd.md")).read(),
    "sdlc/03-hld.md": "# HLD\n\nOne process serves notes.\n",
    "sdlc/04-threat-model.md": ("# Threat model\n\n## Trust Boundaries\n\n| ID | Boundary | Description |\n|---|---|---|\n"
                                "| TB-1 | browser to server | notes arrive from the browser |\n\n"
                                "### SEC-001 - Stored XSS in a note\n\n- **Trust boundary:** TB-1\n- **STRIDE:** Tampering\n"
                                "- **Threat:** a note carries script\n- **Mitigation requirement:** escape on output\n"
                                "- **Owner phase:** 7\n"),
    "sdlc/05-lld.md": "# LLD\n\nUS-001: POST /notes stores a note.\n",
}


def feature_docs(fid, n=2, prd_extra="", sec_id="SEC-002"):
    us = "US-%03d" % n
    pre = "sdlc/features/%s/" % fid
    return {
        pre + "00-brd.md": "# BRD additions: %s\n\n- **Size:** M\n\n## Business Goals\n\n| ID | Goal | Metric | Priority |\n"
                           "|---|---|---|---|\n| BG-%d | Let a visitor remove a note | removals | must |\n" % (fid, n),
        pre + "02-prd.md": "# PRD additions: %s\n\n### %s — Delete a note\n\n- **BRD goal:** BG-%d\n- **Priority:** must\n"
                           "- **AC-1:** When the visitor deletes a note, the system shall remove it from the list.\n%s" % (
                               fid, us, n, prd_extra),
        pre + "03-hld.md": "# HLD changes\n\nA DELETE route next to POST /notes.\n",
        pre + "04-threat-model.md": "# Threat model additions\n\n### %s - Deleting another visitor's note\n\n"
                                    "- **Trust boundary:** TB-1\n- **STRIDE:** Tampering\n- **Threat:** delete by id guess\n"
                                    "- **Mitigation requirement:** check ownership\n- **Owner phase:** 7\n" % sec_id,
        pre + "05-lld.md": "# LLD changes\n\n%s: DELETE /notes/{id}, owner only.\n" % us,
        pre + "05-lld/delete-%s.md" % fid.lower(): "DELETE /notes/{id} returns 204.\n",
        pre + "06-ux.md": "# UX\n\nA delete button on each note.\n",
        pre + "06b-provisioning.md": "# Provisioning\n\nNothing new.\n",
        pre + "07-tasks.md": "# Tasks\n\n### T-%03d — Delete route\n\n- **Story:** %s\n- **Satisfies SEC-IDs:** %s\n" % (
            n, us, sec_id),
        pre + "08-test-report.md": "# Test report\n\n| AC | Test | Result |\n|---|---|---|\n| %s/AC-1 | tests/x.test.js:1 | pass |\n" % us,
        pre + "09-security-report.md": "# Security report\n\n%s: ownership checked.\n" % sec_id,
        pre + "10a-live.md": "# Live\n", pre + "10b-regression.md": "# Regression\n", pre + "10c-load.md": "# Load\n",
        pre + "11-release.md": "# Release\n\nShips the delete feature.\n",
    }


def write_all(p, files):
    for rel, text in files.items():
        E.write(p, rel, text)


# ------------------------------------------------------------------ A. feature cycles
def released_product(name, pid):
    p = E.repo(name, docs=("00-brd.md",))
    write_all(p, PRODUCT_DOCS)
    E.write(p, ".gitignore", "node_modules/\n")
    E.commit(p, "product docs")
    E.init(p, pid)   # greenfield: documents only, no code yet
    write_all(p, RELEASE_FILES)
    E.commit(p, "init")
    product_config(p)
    return p


def test_feature():
    G = "feature"
    p = released_product("feat", "featprod")
    approve_direct(p, "featprod", pathmap.LABELS[:pathmap.LABELS.index("9")])
    ctx = E.prompt(p, "FEATURE F1 %s" % E.fresh())
    record(G, "FEATURE before the product's baseline is approved (not released at 11) is refused",
           "NOT recorded" in ctx and "no approved baseline" in ctx, short(ctx))
    approve_direct(p, "featprod", pathmap.LABELS[pathmap.LABELS.index("9"):pathmap.LABELS.index("11b")])
    n0 = len(E.ledger(p))
    ctx = E.prompt(p, "FEATURE F1 %s" % E.fresh())
    body, pl = E.payload(p, n0 + 1) if len(E.ledger(p)) > n0 else ({}, {})
    record(G, "FEATURE F1 <code> on a released product is recorded; the ledger line carries the feature id",
           ok_rec(ctx) and body.get("action") == "FEATURE F1" and pl.get("feature") == "F1", short(ctx))
    fy = os.path.join(p, ".sdlc", "features", "F1", "phase.yaml")
    st = status(p)
    record(G, ".sdlc/features/F1/phase.yaml is rebuilt from the ledger; STATUS is clean and shows the feature at phase 0",
           os.path.exists(fy) and "feature: F1" in open(fy).read() and "INTEGRITY OK" in st and
           "scope feature F1" in st and "current phase 0" in st, short(st, 240))
    ctx = E.prompt(p, "FEATURE F2 %s" % E.fresh())
    record(G, "a second FEATURE while F1 is active is refused (one feature at a time)",
           "NOT recorded" in ctx and "feature F1 is active" in ctx and len(E.ledger(p)) == n0 + 1, short(ctx))
    # path map
    cases = [("sdlc/02-prd.md", "deny", "frozen"), ("sdlc/features/F1/00-brd.md", "none", ""),
             ("sdlc/features/F1/02-prd.md", "deny", "has not started"), ("sdlc/features/F2/00-brd.md", "deny", "not the active")]
    got = []
    for rel, want, why in cases:
        d, reason, _u = pretool(p, "Write", {"file_path": os.path.join(p, rel), "content": "x"})
        got.append((rel, d, d == want and why in reason, reason[:80]))
    record(G, "path map in a feature: product documents frozen, the feature's phase-0 document writable, later and "
              "other features' documents denied", all(g[2] for g in got), got)
    docs = feature_docs("F1")
    # phases 0..4 through the real worker and APPROVE
    labs = ["0", "1", "2", "3", "4"]
    stage = {"0": ["00-brd.md"], "2": ["02-prd.md"], "3": ["03-hld.md"], "4": ["04-threat-model.md"]}
    outs = []
    for lab in labs:
        for f in stage.get(lab, []):
            E.write(p, "sdlc/features/F1/" + f, docs["sdlc/features/F1/" + f])
        if lab == "2":
            # first a contradicting addition: same trigger as the approved US-001/AC-1, negated response
            E.write(p, "sdlc/features/F1/02-prd.md", docs["sdlc/features/F1/02-prd.md"] +
                    "- **AC-2:** When the visitor submits a note, the system shall not store it and show it in the list.\n")
            E.commit(p, "feature PRD (contradicting)")
            rv, ctx = approve(p, "2")
            record(G, "an addition that contradicts an approved requirement is refused: APPROVE 2 names the "
                      "contradiction", "NOT recorded" in ctx and "CONTRADICTION" in ctx and "US-001/AC-1" in ctx,
                   short(ctx, 400))
            E.write(p, "sdlc/features/F1/02-prd.md", docs["sdlc/features/F1/02-prd.md"] +
                    "- **Supersedes:** US-001/AC-1\n")
            E.commit(p, "feature PRD (declared supersede)")
            rv, ctx = approve(p, "2")
            record(G, "an addition that declares it supersedes an approved requirement is refused",
                   "NOT recorded" in ctx and "supersedes" in ctx, short(ctx, 300))
            E.write(p, "sdlc/features/F1/02-prd.md", docs["sdlc/features/F1/02-prd.md"])
        if lab == "4":
            E.write(p, "sdlc/features/F1/04-threat-model.md", docs["sdlc/features/F1/04-threat-model.md"].replace(
                "SEC-002", "SEC-001"))
            E.commit(p, "feature threat model (conflicting SEC-ID)")
            rv, ctx = approve(p, "4")
            record(G, "a new SEC-ID that conflicts with the product's (SEC-001 redefined) is refused",
                   "NOT recorded" in ctx and "ID conflict" in ctx and "SEC-001" in ctx, short(ctx, 300))
            E.write(p, "sdlc/features/F1/04-threat-model.md", docs["sdlc/features/F1/04-threat-model.md"])
        E.commit(p, "feature phase %s" % lab)
        rv, ctx = approve(p, lab)
        outs.append((lab, ok_rec(ctx), short(ctx, 160)))
    record(G, "feature phases 0-4 approved through the gate's worker (check-feature on each)",
           all(o[1] for o in outs), outs)
    _b, pl = E.payload(p, len(E.ledger(p)))
    record(G, "each feature APPROVE line carries the feature id and the validator digest it relied on",
           pl.get("feature") == "F1" and pl.get("phase") == "4" and str((pl.get("validation") or {}).get("digest", "")).startswith("sha256:"),
           short(pl, 200))
    # phases 5..10c: documents written, approvals recorded by the stub checker (their gate-run tools are the
    # increment-5 suite's subject, and their live runs are the toy run's)
    write_all(p, docs)
    E.commit(p, "feature documents")
    approve_direct(p, "featprod", pathmap.LABELS[pathmap.LABELS.index("5"):pathmap.LABELS.index("11")], feature="F1")
    st = status(p)
    record(G, "after 10c the feature's current phase is 11 and STATUS is clean", "current phase 11" in st and
           "INTEGRITY OK" in st, short(st, 200))
    before_prd = open(os.path.join(p, "sdlc", "02-prd.md")).read()
    gh_spec(p)
    hd0 = head(p)
    rv, ctx = approve(p, "11")
    n = len(E.ledger(p))
    _b, pl = E.payload(p, n)
    merge = pl.get("merge") or {}
    targets = sorted(f["target"] for f in merge.get("files") or [])
    record(G, "APPROVE 11 of the feature (check-feature-11 and check-release pass on the worker) is recorded and "
              "the ledger line records the merge", ok_rec(ctx) and "merged into the product documents" in ctx and
           "sdlc/02-prd.md" in targets and "sdlc/04-threat-model.md" in targets and
           "sdlc/05-lld/delete-f1.md" in targets, short(ctx, 300) + " | " + short(rv, 200))
    prd = open(os.path.join(p, "sdlc", "02-prd.md")).read()
    import hashlib
    shas_ok = all(hashlib.sha256(open(os.path.join(p, f["target"]), "rb").read()).hexdigest() == f["after_sha256"]
                  for f in merge.get("files") or [])
    record(G, "the product documents now hold the additions (US-002 under 'Feature F1'), every file's sha256 is the "
              "one the ledger recorded, and the approved text is unchanged above it",
           "## Feature F1" in prd and "### US-002" in prd and prd.startswith(before_prd.rstrip("\n")) and shas_ok,
           "shas match: %s" % shas_ok)
    log = git(p, "log", "-1", "--format=%an|%s")
    record(G, "the gate committed the merge (author MOADIX gate) on top of the approved commit; the tree is clean",
           log.startswith("MOADIX gate|MOADIX: merge feature F1") and git(p, "rev-parse", "HEAD~1") == hd0 and
           not git(p, "status", "--porcelain", "--", ".", ":(exclude).sdlc"), log)
    approve_direct(p, "featprod", ["11b"], feature="F1")
    st = status(p)
    fy = open(os.path.join(p, ".sdlc", "features", "F1", "phase.yaml")).read()
    record(G, "after 11b the feature is done: STATUS lists it as finished (merged), its phase.yaml says done",
           "finished features: F1 (merged at seq %d)" % n in st and "status: done" in fy and "INTEGRITY OK" in st,
           short(st, 260))
    ctx = E.prompt(p, "FEATURE F2 %s" % E.fresh())
    record(G, "a second feature starts once the first is finished", ok_rec(ctx), short(ctx, 160))
    ctx = E.prompt(p, "FEATURE F1 %s" % E.fresh())
    record(G, "a feature id cannot be reused (and F2 is active anyway)", "NOT recorded" in ctx, short(ctx, 200))
    # F2's addition reusing F1's (now merged) US-002 conflicts with the product
    write_all(p, {k.replace("F1", "F2"): v for k, v in feature_docs("F2").items() if "/00-" in k or "/02-" in k})
    E.commit(p, "F2 docs reusing ids")
    rc, out = check(p, "check_feature", "--phase", "2", env={"MOADIX_FEATURE": "F2"})
    record(G, "after the merge, a later feature that reuses the merged IDs (BG-2, US-002) conflicts with the product",
           rc == 1 and "ID conflict" in out and "US-002" in out, fails(out))


# ------------------------------------------------------------------ B. onboarding
APP_JS = "\n".join(["// notes app", "const notes = [];", "function save(n) {", "  if (!n) throw new Error('empty');",
                    "  notes.push(n);", "  return notes;", "}", "function list() { return notes; }",
                    "module.exports = { save, list };", ""])
TEST_JS = "\n".join(["const { save } = require('../src/app.js');", "test('save', () => {", "  save('a');", "});", ""])
SERVER_JS = "\n".join(["const http = require('http');", "const port = process.env.PORT || 4173;",
                       "const db = process.env.DATABASE_URL;", "http.createServer().listen(port);", ""])


def baseline_docs(cite="src/app.js:3-6"):
    return {
        "sdlc/00-brd.md": "# BRD (as-is): notes\n\n- **Target Platform Ruling:** WEB\n- **Size:** M\n\n## Purpose\n\n"
                          "Stores notes (src/app.js:1-9).\n\n## Users\n\nVisitors on port 4173 (src/server.js:2).\n\n"
                          "## Business Goals\n\n| ID | Goal | Evidence |\n|---|---|---|\n| BG-1 | Keep a visitor's notes | %s |\n" % cite,
        "sdlc/02-prd.md": "# PRD (as-is)\n\n### US-001 — Save a note\n\n- **BRD goal:** BG-1\n- **Priority:** must\n"
                          "- **Implemented in:** %s\n"
                          "- **AC-1:** When the visitor submits a note, the system shall store it (code: src/app.js:5).\n"
                          "- **AC-2:** If the note is empty, then the system shall refuse it (code: src/app.js:4).\n" % cite,
        "sdlc/03-architecture.md": "# Architecture\n\n## Components\n\n| Component | Responsibility | Code |\n|---|---|---|\n"
                                   "| store | keeps notes in memory | src/app.js:2-9 |\n| server | HTTP | src/server.js:1-4 |\n",
        "sdlc/04-threat-model.md": "# Threat model (as-is)\n\n## Trust Boundaries\n\n| ID | Boundary | Description |\n"
                                   "|---|---|---|\n| TB-1 | browser to server | src/server.js:4 |\n\n"
                                   "### SEC-001 - Unbounded note size\n\n- **Trust boundary:** TB-1\n- **STRIDE:** Denial of Service\n"
                                   "- **Threat:** a huge note exhausts memory\n- **Current status:** open\n"
                                   "- **Evidence:** src/app.js:5\n- **Mitigation requirement:** cap the size\n",
        "sdlc/B-test-inventory.md": "# Test inventory\n\n## Test command\n\n`npm test`\n\n## Test environment\n\n"
                                    "http://127.0.0.1:4173 with an in-memory store.\n\n## Suites\n\n| Suite | Kind | Code |\n"
                                    "|---|---|---|\n| app | unit | tests/app.test.js:1-4 |\n\n## Coverage\n\n"
                                    "| Acceptance criterion | Test |\n|---|---|\n| US-001/AC-1 | tests/app.test.js:2-4 |\n"
                                    "| US-001/AC-2 | none |\n",
        "sdlc/B-known-gaps.md": "# Known gaps\n\n## Gaps\n\n| ID | Kind | Ref | Description | Evidence |\n|---|---|---|---|---|\n"
                                "| GAP-001 | untested-ac | US-001/AC-2 | the empty-note refusal has no test | src/app.js:4 |\n"
                                "| GAP-002 | open-finding | SEC-001 | no size cap | src/app.js:5 |\n",
        "sdlc/B-accounts.md": "# Accounts\n\n## Accounts and services\n\n| Service | Purpose | Configured at | Secret (name only) |\n"
                              "|---|---|---|---|\n| Postgres | notes later | src/server.js:3 | DATABASE_URL |\n",
    }


def baseline_verifier(p, findings=()):
    d, why, ui = pretool(p, "Agent", {"subagent_type": "moadix:baseline-verifier", "prompt": "check it", "description": "x"})
    if d != "allow" or not ui:
        return d, why, None
    prompt = ui["prompt"]
    bh = re.search(r"^brief_sha256: ([0-9a-f]+)$", prompt, re.M).group(1)
    rcp = re.search(r"^receipt: ([0-9a-f]+)$", prompt, re.M).group(1)
    req = re.findall(r"^- (sdlc/\S+)$", prompt.split("## Required evidence paths")[1].split("##")[0], re.M)
    ev = {"role": "baseline-verifier", "source_commit": head(p), "brief_sha256": bh, "receipt": rcp, "reviewed": req,
          "findings": list(findings)}
    edir = os.path.join(p, ".sdlc", "cache", "verify", "B", "baseline-verifier", "evidence")
    with open(os.path.join(edir, "findings.json"), "w") as f:
        json.dump(ev, f)
    return d, why, prompt


def test_onboarding():
    G = "onboarding"
    p = E.repo("legacy", docs=())
    write_all(p, {"src/app.js": APP_JS, "src/server.js": SERVER_JS, "tests/app.test.js": TEST_JS})
    write_all(p, RELEASE_FILES)
    E.commit(p, "existing code")
    ctx = E.init(p, "legacyprod")
    _b, pl = E.payload(p, 1)
    record(G, "INIT on a repo that already has code starts in onboarding mode at phase B (recorded in the INIT line)",
           "ONBOARDING mode at phase B" in ctx and pl.get("mode") == "onboarding" and pl.get("code_files") == 6,
           short(ctx, 200))
    E.commit(p, "init")
    product_config(p)
    st = status(p)
    record(G, "STATUS: product (onboarding), current phase B, integrity OK",
           "scope product (onboarding)" in st and "current phase B" in st and "INTEGRITY OK" in st, short(st, 200))
    d1, w1, _ = pretool(p, "Write", {"file_path": os.path.join(p, "sdlc", "B-known-gaps.md"), "content": "x"})
    d2, w2, _ = pretool(p, "Write", {"file_path": os.path.join(p, "src", "app.js"), "content": "x"})
    d3, w3, _ = pretool(p, "Write", {"file_path": os.path.join(p, "sdlc", "05-lld.md"), "content": "x"})
    record(G, "phase B may write the baseline documents, not the product's code or later documents",
           d1 != "deny" and d2 == "deny" and d3 == "deny", "%s / %s (%s) / %s" % (d1, d2, w2[:60], d3))
    # templates as they ship fail (placeholders)
    for f in os.listdir(os.path.join(REPO, "templates", "baseline")):
        shutil.copy(os.path.join(REPO, "templates", "baseline", f), os.path.join(p, "sdlc", f))
    E.commit(p, "templates")
    rc, out = check(p, "check_baseline")
    record(G, "the templates as shipped fail check-baseline (placeholders, no real citations)",
           rc == 1 and "placeholders" in out, fails(out))
    for f in os.listdir(os.path.join(REPO, "templates", "baseline")):
        os.unlink(os.path.join(p, "sdlc", f))
    # a dead citation
    write_all(p, baseline_docs(cite="src/app.js:3-60"))
    E.commit(p, "baseline with a dead citation")
    rc, out = check(p, "check_baseline")
    record(G, "a baseline with a dead citation (src/app.js:3-60, the file has 9 lines) fails check-baseline",
           rc == 1 and "DEAD CITATION src/app.js:3-60" in out, fails(out))
    write_all(p, baseline_docs(cite="src/gone.js:3"))
    E.commit(p, "baseline citing a file that does not exist")
    rc, out = check(p, "check_baseline")
    record(G, "a citation of a file that does not exist at HEAD fails", rc == 1 and "src/gone.js does not exist" in out,
           fails(out))
    docs = baseline_docs()
    bad = dict(docs)
    bad["sdlc/B-known-gaps.md"] = bad["sdlc/B-known-gaps.md"].replace(
        "| GAP-002 | open-finding | SEC-001 | no size cap | src/app.js:5 |\n", "")
    bad["sdlc/B-test-inventory.md"] = bad["sdlc/B-test-inventory.md"].replace("http://127.0.0.1:4173",
                                                                              "https://notes.example.com")
    bad["sdlc/B-accounts.md"] = bad["sdlc/B-accounts.md"].replace("DATABASE_URL", "password=hunter2hunter2")
    write_all(p, bad)
    E.commit(p, "baseline with gaps missing, a production URL and a secret")
    rc, out = check(p, "check_baseline")
    record(G, "an open SEC-ID missing from the gaps register, a production test URL and a secret value each fail",
           rc == 1 and "SEC-001 is open" in out and "never against production" in out and "looks like a secret" in out,
           fails(out))
    write_all(p, docs)
    E.commit(p, "baseline with real citations")
    rc, out = check(p, "check_baseline")
    record(G, "the baseline with real citations passes check-baseline", rc == 0 and "every claim cites code" in out,
           fails(out) if rc else short(out, 200))
    # APPROVE B needs the fresh-context baseline verifier's evidence
    rv, ctx = approve(p, "B")
    record(G, "APPROVE B without the baseline verifier's evidence is refused", "NOT recorded" in ctx and
           "baseline-verifier" in ctx, short(ctx, 300))
    d, why, prompt = baseline_verifier(p, findings=[{"id": "F1", "severity": "high", "summary": "AC-1 says the note "
                                                     "is shown; the code only stores it", "citations": ["src/app.js:5"]}])
    record(G, "moadix:baseline-verifier is scheduled in phase B and gets the gate's brief (every baseline document "
              "required)", d == "allow" and prompt and "sdlc/B-known-gaps.md" in prompt and "As IT IS".lower() in
           prompt.lower(), short(why, 160))
    rv, ctx = approve(p, "B")
    record(G, "a high baseline-verifier finding (a claim the code does not support) blocks APPROVE B",
           "NOT recorded" in ctx and "finding at a failing severity" in ctx, short(ctx, 300))
    baseline_verifier(p, findings=[{"id": "F1", "severity": "low", "summary": "wording", "citations": ["src/app.js:1"]}])
    rv, ctx = approve(p, "B")
    st = status(p)
    record(G, "with real citations and clean verifier evidence, APPROVE B is recorded; every change is now a feature",
           ok_rec(ctx) and "APPROVE B recorded" in ctx and "feature cycle" in ctx and "current phase done" in st, short(ctx, 300))
    d4, w4, _ = pretool(p, "Write", {"file_path": os.path.join(p, "sdlc", "02-prd.md"), "content": "x"})
    record(G, "after APPROVE B the baseline is frozen", d4 == "deny" and "frozen" in w4, w4[:160])
    # a feature cycle on the onboarded product
    ctx = E.prompt(p, "FEATURE O1 %s" % E.fresh())
    record(G, "FEATURE on the onboarded product is recorded (its baseline is approved)", ok_rec(ctx), short(ctx, 160))
    docs = feature_docs("O1")
    docs["sdlc/features/O1/04-threat-model.md"] = docs["sdlc/features/O1/04-threat-model.md"]
    E.write(p, "sdlc/features/O1/00-brd.md", docs["sdlc/features/O1/00-brd.md"])
    E.commit(p, "O1 BRD")
    outs = []
    for lab in ("0", "1"):
        rv, ctx = approve(p, lab)
        outs.append((lab, ok_rec(ctx), short(ctx, 120)))
    E.write(p, "sdlc/features/O1/02-prd.md", docs["sdlc/features/O1/02-prd.md"] +
            "- **AC-2:** If the note is empty, then the system shall not refuse it.\n")
    E.commit(p, "O1 PRD contradicting the baseline")
    rv, ctx = approve(p, "2")
    record(G, "on the onboarded product, an addition contradicting the BASELINE's requirement (US-001/AC-2) is refused",
           "NOT recorded" in ctx and "CONTRADICTION" in ctx and "US-001/AC-2" in ctx, short(ctx, 300))
    write_all(p, docs)
    E.commit(p, "O1 documents")
    rv, ctx = approve(p, "2")
    outs.append(("2", ok_rec(ctx), short(ctx, 120)))
    approve_direct(p, "legacyprod", pathmap.LABELS[pathmap.LABELS.index("3"):pathmap.LABELS.index("11")], feature="O1")
    gh_spec(p)
    rv, ctx = approve(p, "11")
    outs.append(("11", ok_rec(ctx) and "merged into the product documents" in ctx, short(ctx, 200)))
    prd = open(os.path.join(p, "sdlc", "02-prd.md")).read()
    record(G, "a feature cycle on the onboarded product runs through its merge at 11: the baseline PRD now holds "
              "US-002 under 'Feature O1'", all(o[1] for o in outs) and "## Feature O1" in prd and "### US-002" in prd,
           outs)
    _b, pl = E.payload(p, len(E.ledger(p)))
    record(G, "the onboarded product's merge is in the ledger like a released product's (feature O1, files, sha256)",
           (pl.get("merge") or {}).get("feature") == "O1" and pl.get("feature") == "O1" and
           all(len(f.get("after_sha256", "")) == 64 for f in (pl.get("merge") or {}).get("files") or []), short(pl, 200))


# ------------------------------------------------------------------ C. BMad core, check-seam, collapse
def py311():
    for d in sorted(os.listdir(os.path.join(TOOLS, "python"))) if os.path.isdir(os.path.join(TOOLS, "python")) else []:
        exe = os.path.join(TOOLS, "python", d, "bin", "python3")
        if os.access(exe, os.X_OK):
            return exe
    return None


def test_bmad():
    G = "bmad"
    p = E.repo("bm", docs=("00-brd.md",))
    E.init(p, "bmprod")
    E.commit(p, "init")
    up = bmadcore.upstream()
    import hashlib
    same = all(hashlib.sha256(open(os.path.join(p, "_bmad", rel), "rb").read()).hexdigest() == up[rel]
               for rel in up)
    record(G, "INIT installs BMad core's four scripts into _bmad/scripts/, byte-identical to BMAD-METHOD 6.12.4",
           len(up) == 4 and same, sorted(up))
    record(G, "_bmad/ is gitignored except custom/: the install never dirties the product's tree",
           not git(p, "status", "--porcelain", "--untracked-files=all", "--", ".", ":(exclude).sdlc"),
           git(p, "status", "--porcelain"))
    d1, _w1, _ = pretool(p, "Write", {"file_path": os.path.join(p, "_bmad", "scripts", "memlog.py"), "content": "x"})
    d2, _w2, _ = pretool(p, "Write", {"file_path": os.path.join(p, "_bmad", "custom", "bmad-prd.toml"), "content": "x"})
    record(G, "the agent cannot write BMad core (_bmad/scripts) and _bmad/custom/ is not BMad-protected",
           d1 == "deny" and "BMAD installer-owned" in _w1 and "BMAD installer-owned" not in _w2, "%s / %s" % (d1, d2))
    py = py311()
    if py:
        # as `uv run` runs it: the script's own directory on sys.path (it imports config_utils)
        r = fixtures.sh([py, os.path.join(p, "_bmad", "scripts", "resolve_config.py"), "--project-root", p], cwd=p,
                        env={"PATH": "/usr/bin:/bin", "HOME": E.base})
        cfg = json.loads(r.stdout) if r.returncode == 0 else {}
        record(G, "BMad core's resolve_config.py runs in the product and resolves the output folders to sdlc/",
               (cfg.get("core") or {}).get("output_folder") == "{project-root}/sdlc" and
               (cfg.get("modules") or {}).get("bmm", {}).get("implementation_artifacts") == "{project-root}/sdlc/12-retro",
               short(r.stdout or r.stderr, 200))
        ws = os.path.join(p, "sdlc", "00-forge", "an-idea")
        r = fixtures.sh([py, "-I", os.path.join(p, "_bmad", "scripts", "memlog.py"), "init", "--workspace", ws,
                         "--field", "idea=x"], cwd=p)
        record(G, "BMad core's memlog.py writes its log into the phase-0 run folder (sdlc/00-forge/)",
               r.returncode == 0 and os.path.exists(os.path.join(ws, ".memlog.md")), short(r.stdout + r.stderr, 200))
    else:
        record(G, "a Python 3.11+ is available to run BMad core's scripts (managed/fetch_tools.py installs one)", False,
               "no python under %s/python" % TOOLS)
    rows = []
    for skill, lab, key in (("bmad-forge-idea", "0", "forge_output_path"), ("bmad-deep-recon", "1", "research_output_path"),
                            ("bmad-prd", "2", "prd_output_path"), ("bmad-architecture", "3", "spine_output_path")):
        txt = open(os.path.join(REPO, "skills", skill, "customize.toml")).read()
        m = re.search(r'^%s = "([^"]+)"' % key, txt, re.M)
        out = m.group(1).replace("{project-root}/", "") if m else ""
        dec = pathmap.classify(os.path.join(p, out, "run", "x.md"), p, pathmap.LABELS.index(lab))
        dec2 = pathmap.classify(os.path.join(p, out, "run", "x.md"), p, pathmap.LABELS.index(lab) + 1)
        rows.append((skill, out, dec.allow, not dec2.allow))
    adapter = open(os.path.join(REPO, "gate", "config", "bmad-adapter.yaml")).read()
    record(G, "each BMAD skill's output folder is an sdlc/ path writable in its own phase (frozen after), and the "
              "adapter says the same", all(r[2] and r[3] and ("{project-root}/" + r[1]) in adapter for r in rows), rows)
    rc, out = check(p, "check_seam")
    record(G, "check-seam's BMAD half passes on a product INIT set up", rc == 0 and "SEAM INTACT" in out and
           "byte-identical" in out and "artifact root" in out, fails(out))
    with open(os.path.join(p, "_bmad", "scripts", "memlog.py"), "a") as f:
        f.write("# tampered\n")
    rc, out = check(p, "check_seam")
    record(G, "a tampered _bmad/scripts/memlog.py fails check-seam", rc == 1 and "memlog.py differs" in out, fails(out))
    o = session_hook(p)
    rc2, out2 = check(p, "check_seam")
    record(G, "the next session start re-installs it (and says so), and check-seam passes again",
           "re)installed" in json.dumps(o) and rc2 == 0, short(o, 200))


def session_hook(p, home=None):
    """The SessionStart hook with a fixture HOME (never the user's ~/.claude)."""
    home = home or os.path.join(E.base, "emptyhome")
    os.makedirs(home, exist_ok=True)
    r = fixtures.sh([fixtures.PY, "-I", os.path.join(E.home, "gate", "hook.py"), "session"],
                    input=json.dumps({"hook_event_name": "SessionStart", "cwd": p}), env=E.env(HOME=home))
    return json.loads(r.stdout) if r.stdout.strip() else {}


def test_collapse():
    G = "collapse"
    p = E.repo("small", docs=("00-brd.md",))   # the fixture BRD declares Size: S
    E.init(p, "smallprod")
    E.commit(p, "init")
    approve_direct(p, "smallprod", ["0"])
    ctx = E.prompt(p, "COLLAPSE 1 %s" % E.fresh())
    _b, pl = E.payload(p, len(E.ledger(p)))
    st = status(p)
    record(G, "COLLAPSE 1 on a size-S product is a recorded ruling: reason and checks not run in the ledger; phase 1 "
              "COLLAPSED, the current phase is 2", ok_rec(ctx) and pl.get("size") == "S" and
           pl.get("checks_not_run") == ["check-handoff-1"] and "1 Research: COLLAPSED" in st and "current phase 2" in st,
           short(ctx, 200))
    ctx = E.prompt(p, "COLLAPSE 2 %s" % E.fresh())
    record(G, "COLLAPSE of a phase the size profile does not collapse is refused", "NOT recorded" in ctx and
           "does not collapse phase 2" in ctx, short(ctx, 200))
    p2 = E.repo("medium", docs=())
    E.write(p2, "sdlc/00-brd.md", open(os.path.join(fixtures.FIXDOCS, "sdlc", "00-brd.md")).read().replace(
        "**Size:** S", "**Size:** M"))
    E.commit(p2, "brd M")
    E.init(p2, "mediumprod")
    E.commit(p2, "init")
    approve_direct(p2, "mediumprod", ["0"])
    ctx = E.prompt(p2, "COLLAPSE 1 %s" % E.fresh())
    record(G, "a size-M product cannot collapse anything (M and L may not)", "NOT recorded" in ctx and
           "nothing at this size" in ctx, short(ctx, 200))


# ------------------------------------------------------------------ rulings 1, 2, 4, 5
BAD_JS = "const cp = require('child_process');\nfunction ls(d) { return cp.execSync('ls ' + d); }\nmodule.exports = { ls };\n"
REPORT9 = "# Security report\n\n| ID | Severity | Description | Status |\n|---|---|---|---|\n%s\n"


def wait_scan(p, budget=60):
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


def triager(p, entries):
    d, why, ui = pretool(p, "Agent", {"subagent_type": "moadix:sf-triager", "prompt": "triage", "description": "x"})
    if d != "allow" or not ui:
        return d, why, None
    prompt = ui["prompt"]
    ev = {"role": "sf-triager", "source_commit": head(p),
          "brief_sha256": re.search(r"^brief_sha256: ([0-9a-f]+)$", prompt, re.M).group(1),
          "receipt": re.search(r"^receipt: ([0-9a-f]+)$", prompt, re.M).group(1),
          "reviewed": re.findall(r"^- (src/\S+)$", prompt.split("## Required evidence paths")[1].split("##")[0], re.M),
          "findings": [], "triage": entries}
    with open(os.path.join(p, ".sdlc", "cache", "verify", "9", "sf-triager", "evidence", "findings.json"), "w") as f:
        json.dump(ev, f)
    return d, why, prompt


def test_triage():
    G = "triage"
    p = E.repo("tri", docs=("00-brd.md",))
    E.init(p, "triprod")
    write_all(p, {"src/a.js": BAD_JS, "src/b.js": BAD_JS})
    E.commit(p, "init, then code")
    approve_direct(p, "triprod", pathmap.LABELS[:pathmap.LABELS.index("9")])
    E.write(p, "sdlc/09-security-report.md", REPORT9 % "| SF-1 | high | maybe | open |\n| SF-2 | medium | maybe | open |\n"
            "| SF-3 | high | real | open |")
    E.commit(p, "report")
    with open(os.path.join(E.shim, "claude-scan.json"), "w") as f:
        json.dump({"stamp": "head", "findings": [
            {"id": "v3:u1", "severity": "HIGH", "confidence": "LOW", "path": "src/a.js", "line": 2, "title": "maybe injection"},
            {"id": "v3:u2", "severity": "MEDIUM", "confidence": "LOW", "path": "src/b.js", "line": 2, "title": "maybe"},
            {"id": "v3:c3", "severity": "HIGH", "confidence": "HIGH", "panel": {"true": 3, "voters": 3},
             "path": "src/b.js", "line": 2, "title": "real injection"}]}, f)
    pretool(p, "Skill", {"skill": "moadix:request-review"})
    res = wait_scan(p)
    fs = {f["plugin_id"]: f for f in (res or {}).get("findings") or []}
    record(G, "an unconfirmed finding keeps the plugin's severity and is marked unconfirmed (no longer rewritten)",
           fs.get("v3:u1", {}).get("severity") == "high" and fs.get("v3:u1", {}).get("confirmed") is False, short(fs))
    rc, out = check(p, "check_claude_security")
    record(G, "unconfirmed findings block until triaged or waived", rc == 1 and "SF-1" in out and "unconfirmed, so it "
           "blocks until moadix:sf-triager" in out, fails(out))
    exp = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 30 * 86400))
    w = E.prompt(p, "WAIVE SF-1 owner=moad scope=src/a.js expiry=%s reason=not reachable from any route %s" % (exp, E.fresh()))
    record(G, "WAIVE of an unconfirmed finding (plugin HIGH) with a reason is recorded: unconfirmed is not unwaivable",
           ok_rec(w), short(w, 200))
    w = E.prompt(p, "WAIVE SF-3 owner=moad scope=src/b.js expiry=%s reason=later %s" % (exp, E.fresh()))
    record(G, "WAIVE of a CONFIRMED high finding is still refused", "CANNOT be waived" in w and "confirmed high" in w,
           short(w, 200))
    d, why, prompt = triager(p, [{"id": "SF-2", "assessment": "rejected", "citations": ["src/b.js:99"],
                                  "reasoning": "x"}])
    record(G, "moadix:sf-triager is scheduled in phase 9 while unconfirmed findings exist; its brief lists them",
           d == "allow" and prompt and "SF-2" in prompt and "SF-1" in prompt and "SF-3" not in prompt.split(
               "could not confirm")[1].split("## knowledge")[0], short(why, 160))
    rc, out = check(p, "check_claude_security")
    record(G, "a triage whose citation does not resolve (src/b.js:99) counts for nothing: SF-2 still blocks",
           rc == 1 and "SF-2" in out and "unconfirmed, so it blocks" in out, fails(out))
    triager(p, [{"id": "SF-1", "assessment": "confirmed", "severity": "high", "citations": ["src/a.js:2"], "reasoning": "y"},
                {"id": "SF-2", "assessment": "rejected", "citations": ["src/b.js:2"], "reasoning": "input is constant"}])
    rc, out = check(p, "check_claude_security")
    record(G, "triaged: SF-2 rejected with path:line evidence stops blocking; SF-1 confirmed high blocks as high (the "
              "earlier waiver of an unconfirmed finding does not cover a confirmed high)",
           "SF-2 rejected by moadix:sf-triager (src/b.js:2)" in out and "[high] SF-1" in out and "[high] SF-3" in out,
           fails(out))
    w = E.prompt(p, "WAIVE SF-2 owner=moad scope=src/b.js expiry=%s reason=rejected anyway %s" % (exp, E.fresh()))
    record(G, "a triager-rejected finding may be waived (it blocks nothing; the waiver is only a record)",
           ok_rec(w), short(w, 160))


def test_session():
    G = "session"
    p = E.repo("sess", docs=("00-brd.md",))
    E.init(p, "sessprod")
    home = os.path.join(E.base, "fakehome")
    os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
    pol = os.path.join(E.base, "managed-settings.json")
    with open(pol, "w") as f:
        json.dump({"enabledPlugins": {"moadix@moadix": True, "claude-security@claude-plugins-official": True,
                                      "frontend-design@claude-plugins-official": False}}, f)

    def run():
        return session_hook(p, home)

    with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
        json.dump({"enabledPlugins": {"moadix@moadix": True}}, f)
    out = run()
    record(G, "only moadix and claude-security enabled: the session start says nothing about plugins",
           "PLUGIN DRIFT" not in json.dumps(out), short(out))
    with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
        json.dump({"enabledPlugins": {"superpowers@superpowers-marketplace": True,
                                      "frontend-design@claude-plugins-official": True}}, f)
    out = run()
    msg = out.get("systemMessage", "")
    ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
    record(G, "another plugin enabled in user settings: reported to the operator (systemMessage) and the agent "
              "(context); one the policy force-disables is not", "superpowers@superpowers-marketplace" in msg and
           "PLUGIN DRIFT" in ctx and "frontend-design" not in msg, short(msg, 200))
    E.write(p, ".claude/settings.local.json", json.dumps({"enabledPlugins": {"local-thing@x": True}}))
    with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
        json.dump({}, f)
    out = run()
    record(G, "a plugin enabled in the project's local settings is reported too", "local-thing@x" in out.get(
        "systemMessage", ""), short(out, 200))
    pol_txt = open(os.path.join(REPO, "managed", "managed-settings.json")).read()
    record(G, "the managed policy runs the SessionStart hook (no onFailure block: it never stops a session)",
           '"SessionStart"' in pol_txt and "hook.py' session" in pol_txt, "")


def test_github():
    G = "github"
    pj = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))
    gh = pj["mcpServers"]["github"]
    record(G, "plugin.json starts the github MCP server through the gate's launcher, with no token in its env",
           gh["command"] == "/usr/bin/python3" and gh["args"][-1].endswith("/gate/ghmcp.py") and "env" not in gh and
           "MOADIX_GITHUB_TOKEN" not in json.dumps(pj), short(gh))
    inst = open(os.path.join(REPO, "docs", "INSTALL.md")).read()
    record(G, "INSTALL.md no longer tells the operator to export the token; it is stored at phase 11 only",
           "export MOADIX_GITHUB_TOKEN" not in inst and "at phase 11 (not before)" in inst and "**Never** `export`" in inst,
           "")
    launcher = os.path.join(E.home, "gate", "ghmcp.py")
    r = fixtures.sh([fixtures.PY, "-I", launcher], env=E.env(MOADIX_TEST_GITHUB_TOKEN=""), input="")
    record(G, "without a token the launcher starts nothing and says why (needed only at phase 11)",
           r.returncode == 1 and "needed only once a product reaches phase 11" in r.stderr, short(r.stderr, 200))
    calls = os.path.join(E.home, "tools", "github-mcp-server-2.0.3", "calls.log")
    n = len(open(calls).read().splitlines()) if os.path.exists(calls) else 0
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    r = fixtures.sh([fixtures.PY, "-I", launcher], env=E.env(MOADIX_TEST_GITHUB_TOKEN=TOK), input=req, timeout=30)
    log = [json.loads(x) for x in open(calls).read().splitlines()][n:] if os.path.exists(calls) else []
    record(G, "with the Keychain token, the launcher runs the pinned server --read-only with the token in that "
              "process only", log and log[-1]["argv"][:2] == ["stdio", "--read-only"] and log[-1]["token"] is True,
           short(log[-1:] or r.stderr, 200))


def test_installer():
    G = "installer"
    s = open(os.path.join(REPO, "managed", "install.sh")).read()
    fetch = s[s.index("3b/6"):s.index("tools: $(ls")]
    record(G, "the root-run tool fetch writes only into root's own scratch folder (TMPDIR and npm cache), created by "
              "root", 'rootwork="$(as_root /usr/bin/mktemp -d' in fetch and 'TMPDIR="$rootwork"' in fetch and
           'npm_config_cache="$rootwork/npm-cache"' in fetch and "$work/npm-cache" not in s, "")
    record(G, "root removes it (right after the fetch, and in the cleanup trap without prompting); the user's own "
              "scratch folder never holds a root file", 'as_root /bin/rm -rf "$rootwork"' in fetch and
           '-n /bin/rm -rf "$rootwork"' in s, "")
    tail = s[s.rindex("trap - EXIT"):]
    body = tail[tail.index("<<EOF"):tail.rindex("EOF")].strip().splitlines()
    record(G, "a successful run cleans up first, silently, and its last line is 'MOADIX is updated.' / 'MOADIX is "
              "installed.'", "cleanup" in tail.split("cat <<EOF")[0] and body[-1].strip() ==
           "MOADIX is $([[ $UPDATE == 1 ]] && echo updated || echo installed).", body[-1])
    dry = open(os.path.join(REPO, "tests", "install", "dryrun.py")).read()
    record(G, "the Terminal dry run checks the last line and an empty stderr on update",
           "last == [\"MOADIX is updated.\"]" in dry and "Permission denied" in dry, "")


def main():
    install_tools()
    t0 = time.time()
    test_feature()
    test_onboarding()
    test_bmad()
    test_collapse()
    test_triage()
    test_session()
    test_github()
    test_installer()
    viol = E.violations()
    record("guard", "no test touched a real product, a real keychain or the user's files", not viol, json.dumps(viol[:3]))
    n = len(RESULTS)
    ok = sum(1 for r in RESULTS if r[2])
    groups = {}
    for g, _n, r in RESULTS:
        a, b = groups.get(g, (0, 0))
        groups[g] = (a + (1 if r else 0), b + 1)
    print("\n" + "  ".join("%s %d/%d" % (g, a, b) for g, (a, b) in groups.items()))
    print("%d checks, %d passed, %d failed (%.0f s)" % (n, ok, n - ok, time.time() - t0))
    E.remove()
    sys.exit(0 if ok == n else 1)


if __name__ == "__main__":
    main()
