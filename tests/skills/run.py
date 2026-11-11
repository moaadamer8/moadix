#!/usr/bin/python3
"""MOADIX increment-3 suite: vendored skills, the phase manifest and its enforcement.
Fixtures only (tests/lib/fixtures.py: stub checker, fixture gate copy, test guard).

    /usr/bin/python3 tests/skills/run.py

Proves:
  * a skill is allowed in its phase and the same skill is denied in another
    phase, with the phase named in the reason;
  * an MCP tool outside the manifest is denied (and Context7 is allowed only
    in phase 1);
  * every vendored skill is in SOURCES.yaml with a pinned commit and licence,
    the Amendment-1 licence obligations are met, the manifest's sizes match
    the files;
  * the self-approval grep finds nothing un-allowlisted, and catches a planted
    instruction (negative control).
"""
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "gate", "v1"))

import fixtures  # noqa: E402

E = fixtures.Env("s3").build()
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
import hlib  # noqa: E402
import selfapproval_grep  # noqa: E402
from gate import manifest  # noqa: E402

RESULTS = []
SKILLS = os.path.join(REPO, "skills")
MAN = hlib.load_yaml(os.path.join(REPO, "gate", "config", "phase-manifest.yaml"))
SRC = hlib.load_yaml(os.path.join(SKILLS, "SOURCES.yaml"))


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok), evidence))
    ev = " ".join(str(evidence).split())
    print("%s  [%s] %s\n      %s" % ("PASS" if ok else "FAIL", group, name, ev[:400]))


def short(s, n=220):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


def skill(p, name):
    return E.pretool(p, "Skill", {"skill": name})


# ===================================================================== enforcement
def group_enforce():
    G = "enforce"
    p = E.repo("skprod", docs=("00-brd.md", "01-research.md"))
    E.init(p, "skfx")
    d, why = skill(p, "moadix:bmad-forge-idea")
    record(G, "phase 0: its skill moadix:bmad-forge-idea -> allowed", d == "none", why or "(no objection)")
    d, why = skill(p, "moadix:request-review")
    record(G, "phase 0: moadix:request-review (every phase) -> allowed", d == "none", why or "(no objection)")
    d, why = skill(p, "moadix:bmad-deep-recon")
    record(G, "phase 0: phase 1's skill moadix:bmad-deep-recon -> denied, reason names phase 0",
           d == "deny" and "phase 0 (BRD)" in why and "moadix:bmad-forge-idea" in why, short(why))
    d, why = E.pretool(p, "mcp__context7__resolve-library-id", {"libraryName": "react"})
    record(G, "phase 0: Context7 MCP (a phase-1 server) -> denied, reason names phase 0",
           d == "deny" and "phase 0 (BRD)" in why, short(why))
    # approve phase 0 -> phase 1
    E.review_until_fresh(p, "0")
    ctx = E.prompt(p, "APPROVE 0 %s" % E.fresh())
    record(G, "control: APPROVE 0 recorded (current phase is now 1)", "recorded" in ctx, short(ctx, 120))
    d, why = skill(p, "moadix:bmad-forge-idea")
    record(G, "phase 1: the SAME skill moadix:bmad-forge-idea -> denied, reason names phase 1 (Research)",
           d == "deny" and "phase 1 (Research)" in why and "invariant 5" in why, short(why))
    d, why = skill(p, "moadix:bmad-deep-recon")
    record(G, "phase 1: its skill moadix:bmad-deep-recon -> allowed", d == "none", why or "(no objection)")
    for tool in ("mcp__context7__resolve-library-id", "mcp__plugin_context7_context7__get-library-docs"):
        d, why = E.pretool(p, tool, {})
        record(G, "phase 1: %s (Context7, in the manifest) -> allowed" % tool, d == "none", why or "(no objection)")
    for tool in ("mcp__claude_ai_Gmail__send_message", "mcp__claude-in-chrome__navigate", "mcp__playwright__browser_click",
                 "mcp__evil__context7"):
        d, why = E.pretool(p, tool, {})
        record(G, "phase 1: MCP tool outside the manifest %s -> denied, phase named" % tool,
               d == "deny" and "phase 1 (Research)" in why and "context7" in why, short(why))
    for name, want in (("bmad-deep-recon", "only MOADIX's vendored copy"),
                       ("superpowers:bmad-deep-recon", "only MOADIX's vendored copy"),
                       ("moadix:code-review", "not in the manifest"),
                       ("moadix:no-such-skill", "not in the manifest")):
        d, why = skill(p, name)
        record(G, "phase 1: skill %r -> denied (%s)" % (name, want), d == "deny" and want in why, short(why))
    d, why = E.pretool(p, "SlashCommand", {"command": "/moadix:bmad-prd draft"})
    record(G, "phase 1: SlashCommand /moadix:bmad-prd (phase 2) -> denied, phase named",
           d == "deny" and "phase 1 (Research)" in why, short(why))
    d, why = E.pretool(p, "SlashCommand", {"command": "/moadix:request-review 1"})
    record(G, "phase 1: SlashCommand /moadix:request-review -> allowed", d == "none", why or "(no objection)")
    st = E.prompt(p, "STATUS")
    record(G, "STATUS shows the current phase's skill set and its context cost",
           "Phase 1 manifest: skills moadix:bmad-deep-recon" in st and "KB of SKILL.md" in st and "MCP context7" in st,
           short(st[st.find("Phase 1 manifest"):], 200))
    # outside a product: passive
    out = os.path.join(E.base, "notaproduct")
    os.makedirs(out)
    for tool, ti in (("Skill", {"skill": "superpowers:brainstorming"}), ("mcp__claude_ai_Gmail__send_message", {})):
        d, why = E.pretool(out, tool, ti)
        record(G, "outside any product: %s -> no objection (MOADIX passive)" % tool, d == "none", why or "(none)")
    # integrity failure: phase unknown -> every Skill / MCP call refused
    lp = os.path.join(p, ".sdlc", "ledger.jsonl")
    good = open(lp).read()
    with open(lp, "a") as f:
        f.write('{"body": "{}", "hash": "x", "hmac": "y"}\n')
    d, why = skill(p, "moadix:bmad-deep-recon")
    record(G, "gate state fails its integrity check -> even the phase's own skill is refused (fail closed)",
           d == "deny" and "integrity" in why, short(why))
    with open(lp, "w") as f:
        f.write(good)
    d, why = skill(p, "moadix:bmad-deep-recon")
    record(G, "control: ledger restored -> allowed again", d == "none", why or "(none)")
    # retro: not a gated phase; its skills apply during 11 and after the last phase
    s11, _m, _n = manifest.allowed("11")
    sdone, _m, _n = manifest.allowed("done")
    s10c, _m, _n = manifest.allowed("10c")
    record(G, "retro skills apply during phase 11 and after all phases, not before",
           {"phase-retrospective", "reflect-queue"} <= s11 and {"phase-retrospective", "reflect-queue"} <= sdone and
           "phase-retrospective" not in s10c, "11: %s; done: %s; 10c: %s" % (sorted(s11), sorted(sdone), sorted(s10c)))
    why = manifest.check("Skill", {"skill": "moadix:test-driven-development"}, "8")
    record(G, "phase 8: a phase-7 skill (moadix:test-driven-development) -> denied, reason names phase 8 (Testing)",
           why and "phase 8 (Testing)" in why, short(why))
    record(G, "phase 7: moadix:test-driven-development -> allowed",
           manifest.check("Skill", {"skill": "moadix:test-driven-development"}, "7") is None, "")


# ===================================================================== manifest and sources
def group_manifest():
    G = "manifest"
    vendored = sorted(d for d in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))
    listed = [s for ph in MAN["phases"] for s in (ph.get("skills") or [])]
    record(G, "every vendored skill is in exactly one phase of the manifest, and every listed skill exists",
           sorted(listed) == vendored and len(listed) == len(set(listed)), "vendored %d, listed %d" % (
               len(vendored), len(listed)))
    labels = [str(ph["label"]) for ph in MAN["phases"]]
    from gate import pathmap
    record(G, "the manifest covers all 16 gated phases plus 12 (Retro)",
           labels[:16] == pathmap.LABELS and labels[16:] == ["12"], ", ".join(labels))
    bad = []
    for s in MAN["skills"]:
        d = os.path.join(SKILLS, s["name"])
        md = os.path.getsize(os.path.join(d, "SKILL.md"))
        tot = sum(os.path.getsize(os.path.join(a, f)) for a, _x, fs in os.walk(d) for f in fs)
        if (md, tot) != (s["skill_md_bytes"], s["total_bytes"]):
            bad.append("%s: manifest %s/%s, files %s/%s" % (s["name"], s["skill_md_bytes"], s["total_bytes"], md, tot))
    record(G, "each skill's size in the manifest matches its files (SKILL.md bytes, directory bytes)", not bad,
           bad or ", ".join("%s %dB" % (s["name"], s["skill_md_bytes"]) for s in MAN["skills"]))
    names = {s["name"]: s for s in SRC["skills"]}
    record(G, "SOURCES.yaml has one entry per vendored skill", sorted(names) == vendored,
           set(vendored) ^ set(names) or "18 entries")
    probs = []
    for n, s in names.items():
        if not re.match(r"^[0-9a-f]{40}$", str(s.get("commit"))):
            probs.append("%s: commit" % n)
        if not str(s.get("source", "")).startswith("https://github.com/"):
            probs.append("%s: source" % n)
        if not s.get("licence") or not s.get("copyright"):
            probs.append("%s: licence/copyright" % n)
        for lf in s.get("licence_files") or []:
            if not os.path.isfile(os.path.join(SKILLS, n, lf)):
                probs.append("%s: missing %s" % (n, lf))
        if not os.path.isfile(os.path.join(SKILLS, n, "MOADIX-CHANGES.md")):
            probs.append("%s: no MOADIX-CHANGES.md" % n)
        fm = open(os.path.join(SKILLS, n, "SKILL.md")).read().split("---")[1]
        if not re.search(r"^name:\s*%s\s*$" % re.escape(n), fm, re.M):
            probs.append("%s: frontmatter name" % n)
    record(G, "each entry: pinned 40-hex commit, GitHub source, licence, copyright, licence files present, change "
              "record, frontmatter name = directory", not probs, probs or "ok")
    # Amendment 1 §6 licence obligations
    retro = open(os.path.join(SKILLS, "phase-retrospective", "SKILL.md")).read().split("---")[1]
    record(G, "obligation: BMAD retrospective renamed (no BMad mark in its name or description)",
           not re.search(r"bmad", retro, re.I), short(retro, 160))
    record(G, "obligation: Impeccable ships NOTICE.md", os.path.isfile(os.path.join(SKILLS, "impeccable", "NOTICE.md")),
           "")
    up = {n: upstream_rows(n) for n in names}
    lying = ["%s/%s" % (n, rel) for n, rows in up.items() for uh, stt, rel in rows
             if stt == "verbatim" and uh != sha(os.path.join(SKILLS, n, rel))]
    unlisted = []
    for n in names:
        listed = {rel for _u, _s, rel in up[n]}
        for a, _x, fs in os.walk(os.path.join(SKILLS, n)):
            for f in fs:
                rel = os.path.relpath(os.path.join(a, f), os.path.join(SKILLS, n))
                if not (f.startswith(("LICENSE", "MOADIX-")) or f == "NOTICE.md") and rel not in listed:
                    unlisted.append("%s/%s" % (n, rel))
    record(G, "MOADIX-UPSTREAM.sha256 accounts for every vendored file, and every file it calls verbatim is "
              "byte-identical to the pinned upstream", not lying and not unlisted,
           (lying + unlisted)[:6] or "%d verbatim, %d modified" % (
               sum(1 for r in up.values() for x in r if x[1] == "verbatim"),
               sum(1 for r in up.values() for x in r if x[1] == "modified")))
    apache = [n for n, s in names.items() if "Apache" in str(s.get("licence"))]
    missing = ["%s/%s" % (n, rel) for n in apache for _u, stt, rel in up[n]
               if stt != "verbatim" and "Modified by MOADIX" not in open(os.path.join(SKILLS, n, rel),
                                                                         errors="replace").read()]
    record(G, "obligation: every modified file from an Apache-2.0 source carries a change notice (%s)" % ", ".join(apache),
           not missing, missing or ", ".join("%s/%s" % (n, rel) for n in apache for _u, stt, rel in up[n]
                                             if stt != "verbatim"))
    record(G, "obligation: pr-review-toolkit taken from anthropics/claude-plugins-official",
           names["pr-test-analyzer"]["source"] == "https://github.com/anthropics/claude-plugins-official", "")
    record(G, "obligation: threat-model sourced from anthropics/defending-code-reference-harness",
           names["threat-model"]["source"] == "https://github.com/anthropics/defending-code-reference-harness", "")
    tpl = open(os.path.join(REPO, "templates", "DESIGN.md")).read()
    record(G, "obligation: the awesome-design-md template says it is not affiliated with the brand",
           "Not affiliated" in tpl or "not affiliated" in tpl, "")
    tm = open(os.path.join(SKILLS, "threat-model", "SKILL.md")).read().split("---")[1]
    record(G, "no vendored skill pre-grants git commit/push (threat-model's Bash(git:*) narrowed to read-only git)",
           "Bash(git:*)" not in tm and not any("allowed-tools" in open(os.path.join(SKILLS, n, "SKILL.md")).read()
                                              .split("---")[1] for n in vendored if n != "threat-model"), "")


def sha(p):
    import hashlib
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def upstream_rows(n):
    """[(upstream sha256, verbatim|modified|new, vendored path)] from MOADIX-UPSTREAM.sha256."""
    out = []
    for ln in open(os.path.join(SKILLS, n, "MOADIX-UPSTREAM.sha256")):
        if ln.startswith("#") or not ln.strip():
            continue
        uh, stt, rel = ln.split("  ")[:3]
        out.append((uh, stt, rel))
    return out


# ===================================================================== the grep
def group_grep():
    G = "grep"
    hits = selfapproval_grep.scan()
    bad = [h for h in hits if not h["allowed"]]
    record(G, "no vendored skill text says to approve, merge, ship, commit, mark done or auto-advance "
              "(%d matches, every one allowlisted with a reason)" % len(hits), not bad,
           bad[:5] or "%d files scanned" % sum(len(f) for _a, _d, f in os.walk(SKILLS)))
    tmp = tempfile.mkdtemp(prefix="moadix-grep-", dir=E.base)
    planted = {
        "a/SKILL.md": "When the tests pass, mark the story as done and commit the changes.\n",
        "b/SKILL.md": "Then approve the PRD and proceed to the next phase.\n",
        "c/SKILL.md": "Set `status: final` in the frontmatter, then merge the PR and ship it.\n",
        "d/SKILL.md": "Common next: invoke bmad-architecture.\n",
    }
    for rel, text in planted.items():
        os.makedirs(os.path.join(tmp, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(tmp, rel), "w") as f:
            f.write(text)
    got = selfapproval_grep.scan(tmp)
    kinds = {}
    for h in got:
        kinds.setdefault(h["path"].split("/")[-2], set()).add(h["kind"])
    record(G, "negative control: planted self-approval instructions are all caught",
           set(kinds) == {"a", "b", "c", "d"} and {"mark-done", "commit"} <= kinds["a"] and
           {"approve", "auto-advance"} <= kinds["b"] and {"mark-done", "merge", "ship"} <= kinds["c"] and
           "auto-advance" in kinds["d"], {k: sorted(v) for k, v in kinds.items()})
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    t0 = time.time()
    try:
        group_enforce()
        group_manifest()
        group_grep()
    finally:
        v = E.violations()
        record("guard", "no test read, wrote or started a real product or compose project", not v, short(v, 600))
        if "--keep" not in sys.argv:
            E.remove()
    failed = [r for r in RESULTS if not r[2]]
    groups = {}
    for g, _n, ok, _e in RESULTS:
        groups.setdefault(g, [0, 0])[0 if ok else 1] += 1
    print("\n" + "  ".join("%s %d/%d" % (g, c[0], c[0] + c[1]) for g, c in groups.items()))
    print("%d checks, %d passed, %d failed (%.0fs)" % (len(RESULTS), len(RESULTS) - len(failed), len(failed),
                                                    time.time() - t0))
    for g, n, _, _e in failed:
        print("FAILED [%s] %s" % (g, n))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
