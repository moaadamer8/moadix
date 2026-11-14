"""Increment 7 fixtures: the cross-phase contract (docs/AMENDMENT-3.md section 1) for a phase.

Every gated phase now needs, beside its documents, sdlc/<label>/COVERAGE.md and DISCOVERY.md,
and clean evidence from the phase's gap critic (moadix:gap-critic). Suites written before
increment 7 call `ready(E, path, label)` before the gate runs a phase's validators (fixtures.Env
review_until_fresh does it), so their products keep meeting the contract they never knew about.

Nothing here weakens a check: the files are what an agent would write for a product that
exercises none of the phase's topics (each N/A with its own reason), the size rule's defaults
stay `N/A: size-default`, and every topic the size turns on gets a real section.
"""
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)
from gate import contract  # noqa: E402

GIT = "/usr/bin/git"
NOTES = ("Fixture coverage for {tid} ({title}): ASVS L2 applies at level 2; pytm and PASTA model the threats; "
         "a soak test runs for an hour; one formal invariant is stated; SLSA provenance is attached; the Stryker "
         "mutation threshold is 85%; this section exists so the size rule's turned-on topics are covered.")


def _git(p, *args):
    return subprocess.run([GIT, "-C", p] + list(args), capture_output=True, text=True)


def dirty(p):
    """The working tree as the gate sees it (gate state and proposals excluded)."""
    return _git(p, "status", "--porcelain=v1", "--untracked-files=all", "--", ".", ":(exclude).sdlc",
                ":(exclude).sdlc-proposals").stdout.strip()


def scope_of(p, E=None):
    """(state, size, ruling) of the product: the state from the fixture gate's own copy (its
    checker verifies the ledger), the size and ruling from the BRD (B19)."""
    code = ("import json, sys; sys.path.insert(0, %r); from gate import state; st, pr = state.current_state(%r); "
            "print(json.dumps({'st': {k: st.get(k) for k in ('current_phase', 'feature', 'phases', 'mode', "
            "'product_phases', 'product')}, 'problems': pr}))" % (E.home, p))
    r = subprocess.run(["/usr/bin/python3", "-I", "-c", code], capture_output=True, text=True, env=E.env())
    st = json.loads(r.stdout)["st"]
    size, ruling = contract.size_and_ruling(p, st)
    return st, size, ruling


def files(label, st, size, ruling, reason=None):
    """{rel: text} for COVERAGE.md, DISCOVERY.md and the notes the turned-on topics anchor."""
    feature = bool(st and st.get("feature"))
    d = contract.contract_dir(st, label)
    dfl = contract.defaults(label, size, ruling, {"turn_on": set(), "na": {}}, feature)
    on = {str(x["topic"]) for x in contract.turned_on(size)}
    cov = ["# Coverage: phase %s" % label, ""]
    notes = ["# Fixture notes, phase %s" % label, ""]
    for tid, title in contract.topics(label, feature):
        dd = dfl.get(tid)
        if tid in on or (dd and dd.get("partial")):
            notes += ["## Topic %s" % tid, "", NOTES.format(tid=tid, title=title), ""]
            cov.append("- %s: [%s](notes.md#topic-%s)" % (tid, title, tid.lower()))
        elif dd:
            cov.append("- %s: N/A: %s" % (tid, contract.SIZE_DEFAULT))
        else:
            cov.append("- %s: N/A: %s" % (tid, (reason or "this fixture product exercises nothing of topic {tid} "
                                                "({title}), so the gate's own checks are what it tests").format(
                tid=tid, title=title)))
    out = {d + "/COVERAGE.md": "\n".join(cov) + "\n",
           d + "/DISCOVERY.md": "# Discovery, phase %s\n\nNo questions: the fixture product raises no open question "
                                "for the operator in this phase.\n" % label}
    if len(notes) > 2:
        out[d + "/notes.md"] = "\n".join(notes) + "\n"
    return out


def write(p, rel_files):
    for rel, text in rel_files.items():
        full = os.path.join(p, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


def commit(p, msg="contract files"):
    _git(p, "add", "-A")
    return _git(p, "-c", "user.email=fixture@example.invalid", "-c", "user.name=fixture", "commit", "-qm", msg)


def seed_links(p, st):
    """The gate checks that research links resolve (cite-lint) and caches the answer in
    .sdlc/cache/links.json; fixtures never reach the network, so they record the answer."""
    import time
    urls = []
    for rel in contract.research_docs(p, st):
        with open(os.path.join(p, rel), encoding="utf-8", errors="replace") as f:
            urls += [u.rstrip(".,;:") for u in contract.URL.findall(f.read())]
    if not urls:
        return
    path = contract.links_cache(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    for u in urls:
        cache.setdefault(u, {"status": 200, "checked": time.time()})
    with open(path, "w") as f:
        json.dump(cache, f)


def critic(E, p, label, findings=(), topics_checked=None, extra=None, agent="moadix:gap-critic"):
    """Launch the gap critic through the gate's PreToolUse hook (the gate writes the brief and the
    receipt), then write its CRITIC.json as the critic would. Returns (decision, reason, prompt)."""
    rc, out, err = E.hook("pretool", {"hook_event_name": "PreToolUse", "session_id": "c7", "cwd": p,
                                      "tool_name": "Agent",
                                      "tool_input": {"subagent_type": agent, "prompt": "find gaps", "description": "x"}})
    hs = out.get("hookSpecificOutput") or {}
    d, why, ui = hs.get("permissionDecision", "none"), hs.get("permissionDecisionReason", ""), hs.get("updatedInput")
    if d != "allow" or not ui:
        return d, why, None
    prompt = ui["prompt"]
    bh = re.search(r"^brief_sha256: ([0-9a-f]+)$", prompt, re.M).group(1)
    rcp = re.search(r"^receipt: ([0-9a-f]+)$", prompt, re.M).group(1)
    hd = re.search(r"^source_commit: ([0-9a-f]+)$", prompt, re.M).group(1)
    req = re.findall(r"^- (\S+)$", prompt.split("## Required evidence paths")[1].split("\n## ")[0], re.M)
    tops = re.findall(r"^- ([A-Z]{1,3}\d{1,2}) ", prompt.split("## Topics of phase")[1].split("\n## ")[0], re.M)
    ev = {"role": "gap-critic", "phase": label, "source_commit": hd, "brief_sha256": bh, "receipt": rcp,
          "reviewed": req, "topics_checked": tops if topics_checked is None else topics_checked,
          "findings": list(findings)}
    ev.update(extra or {})
    edir = os.path.join(p, ".sdlc", "cache", "verify", label, "gap-critic", "evidence")
    os.makedirs(edir, exist_ok=True)
    with open(os.path.join(edir, "CRITIC.json"), "w") as f:
        json.dump(ev, f)
    return d, why, prompt


def ready(E, p, label, with_critic=True):
    """Make phase `label` of the product at p meet the contract: write the contract files when
    they are missing and commit them (only on a clean tree, so a test's deliberately dirty
    tree stays dirty), seed the research links, and give the gap critic clean evidence."""
    try:
        st, size, ruling = scope_of(p, E)
    except Exception:
        return
    if not st or st.get("current_phase") != label or not contract.gated(label) or not contract.topics(label):
        return
    clean = not dirty(p)
    want = {rel: text for rel, text in files(label, st, size, ruling).items() if not os.path.exists(os.path.join(p, rel))}
    if want and clean:
        write(p, want)
        commit(p, "contract files, phase %s" % label)
    if label == "1":
        seed_links(p, st)
    if with_critic and not dirty(p):
        critic(E, p, label)
