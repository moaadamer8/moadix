#!/usr/bin/env python3
"""check-seam — contract test for the BMAD seam (gate/config/bmad-adapter.yaml) and the path map.

MOADIX v2 change notice (increment 6): the BMAD half is re-rooted at the product
(see check_bmad); the v1 adapter checks below the path-map half were replaced.

The adapter is the harness's only knowledge of BMAD. This script proves that
knowledge is still true. Run it now, and run it after every BMAD upgrade: a
failure here is the harness telling you the seam moved before a workflow
silently produces nothing.

Checks:
  1. BMAD is installed where the adapter says, at the pinned version
  2. every adapter path exists
  3. every mapped bmad_skill directory and SKILL.md exists
  4. artifact roots agree with BMAD's own resolved config
  5. the customisation surface exists and is writable
  6. protected paths in phase-paths.yaml actually cover what the adapter says
     must not be touched
  7. upgrade tripwires (WARN only)

Exit 0 = seam intact. 1 = seam broken.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

OK: list = []
BAD: list = []
WARN: list = []


def ok(m):
    OK.append(m)


def bad(m):
    BAD.append(m)


def warn(m):
    WARN.append(m)


def main():
    ap = argparse.ArgumentParser(prog="check-seam.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    root = os.path.dirname(hlib.GATE_DIR)
    check_phase_paths(hlib.load_paths_doc(root))
    apath = os.path.join(hlib.GATE_DIR, "config", "bmad-adapter.yaml")
    if not os.path.exists(apath):
        bad("the BMAD adapter %s is missing; the BMAD half cannot run" % apath)
        return report(args)
    check_bmad(hlib.load_yaml(apath) or {}, hlib.project_root())
    return report(args)


def check_bmad(ad, product):
    """MOADIX v2 (increment 6): the BMAD half, re-rooted. v1 checked a BMAD install
    inside the harness repo; in v2 BMad core's scripts are vendored in the gate
    (gate/bmad/) and the gate installs them into each product's _bmad/ (gate/bmadcore.py).

      1. the pinned version and commit: the adapter, the gate's bmadcore and the
         product's _bmad/MOADIX-BMAD.json agree
      2. every vendored script is byte-identical to the pinned upstream (sha256)
      3. the product's _bmad/ holds exactly what the gate installs (scripts,
         config.toml, manifest): no missing or edited file
      4. artifact roots: each mapped skill's output folder (and config.toml's
         folders) is an sdlc/ path that the phase the skill runs in may write
      5. protected paths: _bmad/ itself is denied to the agent; only _bmad/custom/
         is excepted
    """
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(hlib.GATE_DIR))
    from gate import bmadcore, pathmap, state
    if str(ad.get("bmad_version")) != bmadcore.VERSION or str(ad.get("commit")) != bmadcore.COMMIT:
        bad("BMAD pin drift: adapter %s@%s, gate %s@%s" % (ad.get("bmad_version"), str(ad.get("commit"))[:12],
                                                           bmadcore.VERSION, bmadcore.COMMIT[:12]))
    else:
        ok("BMad core pinned at %s (%s)" % (bmadcore.VERSION, bmadcore.COMMIT[:12]))
    up = bmadcore.upstream()
    for name in bmadcore.SCRIPTS:
        rel = "scripts/" + name
        try:
            with open(os.path.join(bmadcore.SRC, rel), "rb") as fh:
                got = bmadcore.sha256(fh.read())
        except OSError:
            bad("vendored BMad core script %s is missing from the gate" % rel)
            continue
        if up.get(rel) != got:
            bad("vendored %s differs from upstream %s (sha256 %s, pinned %s)" % (rel, bmadcore.VERSION, got[:12],
                                                                            str(up.get(rel))[:12]))
        else:
            ok("vendored %s is byte-identical to BMAD-METHOD %s" % (rel, bmadcore.VERSION))
    if sorted(str(x) for x in (ad.get("scripts") or [])) != sorted(bmadcore.SCRIPTS):
        bad("adapter scripts %s differ from the gate's %s" % (ad.get("scripts"), list(bmadcore.SCRIPTS)))
    if not os.path.isfile(os.path.join(product, ".sdlc", "product.yaml")):
        warn("not run inside a MOADIX product: the product's _bmad/ was not checked")
        pid = None
    else:
        try:
            pid = state.load_product(product)["product"]
        except Exception as exc_:
            bad("the product's .sdlc/product.yaml could not be read (%r)" % (exc_,))
            return
    probs = bmadcore.problems(product, pid) if pid else []
    if probs:
        for path, what in probs:
            bad("%s %s: the gate installs it at INIT and at session start; the BMAD skills' scripts and config "
                "would not resolve" % (path, what))
    elif pid:
        ok("the product's _bmad/ holds exactly what the gate installs (%d files)" % len(bmadcore.expected(pid)))
    # 4. artifact roots
    labels = {lab: i for i, lab in enumerate(pathmap.LABELS)}
    for e in ad.get("skills") or []:
        out = str(e.get("output") or "")
        lab = str(e.get("phase"))
        if lab not in labels:
            bad("adapter maps %s to unknown phase %s" % (e.get("skill"), lab))
            continue
        probe = os.path.join(product, out.replace("{project-root}/", ""), "probe.md")
        d = pathmap.classify(os.path.realpath(os.path.dirname(probe)) + "/probe.md", product, labels[lab])
        if d.allow and d.klass == "phase-current":
            ok("artifact root %-30s for %s is writable in phase %s" % (out, e.get("skill"), lab))
        else:
            bad("artifact root %s for %s is NOT writable in phase %s: %s" % (out, e.get("skill"), lab, d.reason))
    cfg = bmadcore.CONFIG % {"product": pid or "-"}
    for key, lab in (("implementation_artifacts", pathmap.RELEASE),):
        m = re.search(r"^%s = \"([^\"]+)\"" % key, cfg, re.M)
        if not m:
            bad("config.toml has no %s" % key)
            continue
        d = pathmap.classify(os.path.join(product, m.group(1).replace("{project-root}/", ""), "probe.md"),
                             product, labels[lab])
        (ok if d.allow else bad)("config.toml %s = %s is %swritable in phase %s" % (
            key, m.group(1), "" if d.allow else "NOT ", lab))
    # 5. protected paths
    for rel in ad.get("protected") or []:
        d = pathmap.classify(os.path.join(product, str(rel)), product, 0)
        if d.allow or d.klass != "bmad":
            bad("%s is not protected from the agent (%s)" % (rel, d.klass))
        else:
            ok("%s is protected (the agent cannot write BMad core)" % rel)
    d = pathmap.classify(os.path.join(product, "_bmad", "custom", "bmad-prd.toml"), product, 0)
    if d.klass == "bmad":
        bad("_bmad/custom/ (the customisation surface) is protected; it must be excepted")
    else:
        ok("_bmad/custom/ is the customisation surface (not BMad-protected)")


def check_phase_paths(paths_doc):
    """6b. phase path uniqueness and overlap.

    MOADIX v2 (v1 defect: check-seam duplicate globs). v1:
      * reported a glob repeated inside ONE phase as "listed under BOTH phase 7
        and phase 7";
      * compared overlap prefixes with str.startswith on the text before the
        first wildcard, so a pattern whose prefix is empty (`**/x`) or a
        sibling that merely shares leading characters (`sdlc/0` vs `sdlc/05-lld/`)
        was miscounted;
      * and the map it checked listed `tests/**` and `.github/workflows/**`
        under two phases each, so the seam was reported broken by its own map.
    Now: a glob under two phases is SHARED ownership, reported as such (the
    path map honours it); a glob repeated within one phase FAILS as a repeat;
    an overlap is a directory-prefix
    containment (`release/**` contains `release/assets/**`) between different
    phases, reported as a WARN.
    """
    try:
        seen, dup, shared = {}, False, {}
        for ph in (paths_doc.get("phases") or []):
            label = str(ph.get("label"))
            local = set()
            for g in (ph.get("allow") or []):
                g = str(g)
                if g in local:
                    bad("phase path %r is listed twice under phase %s" % (g, label))
                    dup = True
                    continue
                local.add(g)
                if g in seen:
                    # Declared shared ownership: the path map (gate/pathmap.py
                    # phase_owners) makes the glob writable in EACH listed phase.
                    # v1's classifier gave it to the first phase only, which is
                    # why v1's seam had to fail it.
                    shared.setdefault(g, [seen[g]]).append(label)
                else:
                    seen[g] = label
        overlaps = []
        for g1, p1 in seen.items():
            if not g1.endswith("/**"):
                continue
            dir1 = g1[:-2]                      # "release/"
            if not dir1.strip("/") or any(c in dir1 for c in "*?["):
                continue
            for g2, p2 in seen.items():
                if g1 != g2 and p1 != p2 and g2.startswith(dir1):
                    overlaps.append((g1, p1, g2, p2))
        for g1, p1, g2, p2 in overlaps:
            warn("phase path overlap: %r (phase %s) contains %r (phase %s); the earliest owner "
                 "decides, so keep it intentional" % (g1, p1, g2, p2))
        for g, labels in sorted(shared.items()):
            ok("phase path %r is shared by phases %s (writable in each)" % (g, " and ".join(labels)))
        if not dup:
            ok("no phase lists a glob twice (%d patterns, %d shared, %d overlap(s))"
               % (len(seen), len(shared), len(overlaps)))
    except Exception as exc_:
        bad("could not check phase path uniqueness: %r" % (exc_,))


def report(args):
    if not args.quiet:
        for m in OK:
            print("  PASS  %s" % m)
        for m in WARN:
            print("  WARN  %s" % m)
        for m in BAD:
            print("  FAIL  %s" % m)
        print()
    print("check-seam: %d pass, %d warn, %d fail" % (len(OK), len(WARN), len(BAD)))
    if BAD:
        print("SEAM BROKEN - see the FAIL lines above.")
        return 1
    print("SEAM INTACT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
