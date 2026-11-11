#!/usr/bin/env python3
"""check-seam — contract test for harness/adapters/bmad.yaml against the live install.

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

    # MOADIX v2 change notice: the seam is checked from the gate's own tree.
    # Section 6b (phase path uniqueness) runs against gate/pathmap.py. The BMAD
    # adapter sections need gate/config/bmad-adapter.yaml, which arrives with
    # increment 3 (BMAD vendored into the plugin); until then they are reported
    # as not yet applicable, and only the path-map half is judged.
    root = os.path.dirname(hlib.GATE_DIR)
    apath = os.path.join(root, "gate", "config", "bmad-adapter.yaml")
    check_phase_paths(hlib.load_paths_doc(root))
    if not os.path.exists(apath):
        warn("BMAD adapter checks not run: %s does not exist yet (increment 3)" % apath)
        return report(args)
    ad = hlib.load_yaml(apath)

    bmad_root = os.path.join(root, ad.get("bmad_root") or "")
    if not os.path.isdir(bmad_root):
        bad("bmad_root '%s' does not exist" % ad.get("bmad_root"))
        report(args); return 1
    ok("bmad_root present: %s" % ad.get("bmad_root"))

    # ---- 1. version -----------------------------------------------------
    manifest_rel = (ad.get("paths") or {}).get("manifest")
    expected = str(ad.get("bmad_version"))
    mpath = os.path.join(root, manifest_rel) if manifest_rel else None
    if mpath and os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as fh:
            txt = fh.read()
        m = re.search(r"^\s*version:\s*([0-9][^\s]*)", txt, re.M)
        got = m.group(1) if m else None
        if got == expected:
            ok("BMAD version matches pin: %s" % expected)
        else:
            bad("BMAD version drift: adapter pins %s, install reports %s. "
                "Re-verify every capability below before trusting the adapter." % (expected, got))
        mods = re.findall(r"-\s+name:\s+(\S+)\s+version:\s+(\S+)", txt)
        if mods:
            ok("modules installed: %s" % ", ".join("%s@%s" % (a, b) for a, b in mods))
    else:
        bad("manifest not found at %s" % manifest_rel)

    # ---- 2. adapter paths ----------------------------------------------
    for key, rel in sorted((ad.get("paths") or {}).items()):
        p = os.path.join(root, rel)
        (ok if os.path.exists(p) else bad)("path %-22s %s %s" % (key, "->" if os.path.exists(p) else "MISSING", rel))

    # ---- 3. mapped skills ----------------------------------------------
    for cap in ad.get("capabilities") or []:
        ph = cap.get("harness_phase")
        skill = cap.get("bmad_skill")
        if not skill:
            ok("phase %-3s %-14s no BMAD skill mapped (status: %s) - harness-owned"
               % (ph, cap.get("harness_name"), cap.get("status")))
            continue
        sd = os.path.join(root, (ad.get("paths") or {}).get("skills_dir", ""), skill)
        sf = os.path.join(root, cap.get("skill_file") or "")
        if not os.path.isdir(sd):
            bad("phase %s: skill directory missing: %s" % (ph, sd))
            continue
        if not os.path.exists(sf):
            bad("phase %s: SKILL.md missing: %s" % (ph, cap.get("skill_file")))
            continue
        cf = cap.get("customize_file")
        if cf and not os.path.exists(os.path.join(root, cf)):
            warn("phase %s: customize.toml missing (%s) - skill may not be customisable" % (ph, cf))
        # deprecation tripwire: a shim would silently redirect our capability
        with open(sf, encoding="utf-8") as fh:
            head = fh.read(1500)
        if re.search(r"deprecated", head, re.I):
            bad("phase %s: '%s' is now a DEPRECATED SHIM. The adapter maps a skill that forwards "
                "elsewhere; re-map it before relying on its outputs." % (ph, skill))
        else:
            ok("phase %-3s %-14s -> %-22s SKILL.md present, not deprecated"
               % (ph, cap.get("harness_name"), skill))
        dc = cap.get("deterministic_check")
        if dc and not os.path.exists(os.path.join(root, dc)):
            warn("phase %s: deterministic check missing: %s" % (ph, dc))

    # ---- 4. artifact roots vs BMAD's own config -------------------------
    cfg_rel = (ad.get("paths") or {}).get("config_module")
    roots = ad.get("artifact_roots") or {}
    if cfg_rel and os.path.exists(os.path.join(root, cfg_rel)):
        with open(os.path.join(root, cfg_rel), encoding="utf-8") as fh:
            cfg = fh.read()
        for key in ("planning_artifacts", "implementation_artifacts"):
            m = re.search(r"^%s:\s*\"?([^\"\n]+)\"?" % key, cfg, re.M)
            if not m:
                warn("BMAD config does not define %s" % key)
                continue
            declared = m.group(1).strip().replace("{project-root}/", "")
            adapter_val = str(roots.get(key, "")).replace((ad.get("bmad_root") or "") + "/", "")
            if declared == adapter_val:
                ok("artifact root %-24s agrees with BMAD config (%s)" % (key, declared))
            else:
                bad("artifact root %s drift: adapter says %r, BMAD config says %r"
                    % (key, adapter_val, declared))
    else:
        bad("BMAD module config not readable: %s" % cfg_rel)

    # ---- 5. customisation surface ---------------------------------------
    cs = (ad.get("customisation") or {}).get("surface")
    csp = os.path.join(root, cs or "")
    if cs and os.path.isdir(csp) and os.access(csp, os.W_OK):
        ok("customisation surface writable: %s" % cs)
    else:
        bad("customisation surface missing or not writable: %s" % cs)

    # ---- 6. protection actually enforced --------------------------------
    try:
        paths_doc = hlib.load_paths_doc(root)
        prot = paths_doc.get("protected_always") or []
        exc = paths_doc.get("protected_exceptions") or []
        probes = [
            (os.path.join(ad.get("bmad_root"), "_bmad", "config.toml"), True),
            (os.path.join(ad.get("bmad_root"), ".claude", "skills", "bmad-prd", "SKILL.md"), True),
            (os.path.join(ad.get("bmad_root"), "_bmad", "custom", "bmad-agent-pm.toml"), False),
        ]
        # bmad_root is "." once BMAD lives at the repo root, which makes
        # os.path.join produce "./_bmad/...". The globs are repo-relative with
        # no leading "./", so normalise before matching (the gate itself
        # normalises via hlib.rel_to_root; only this probe needed it).
        probes = [(os.path.normpath(r), b) for r, b in probes]
        for rel, should_block in probes:
            blocked = hlib.any_glob(prot, rel) and not hlib.any_glob(exc, rel)
            if blocked == should_block:
                ok("gate protection correct for %s (blocked=%s)" % (rel, blocked))
            else:
                bad("gate protection WRONG for %s: blocked=%s, expected %s"
                    % (rel, blocked, should_block))
    except Exception as exc_:
        bad("could not evaluate gate protection: %r" % (exc_,))

    # ---- 6c. known upstream installer bugs -------------------------------
    # Assert the workaround still holds. If a BMAD upgrade fixes (or worsens)
    # the bmb+tea output-path leak, the seam test says so instead of us finding
    # out when TEA artifacts land somewhere unexpected.
    for bug in (ad.get("known_installer_bugs") or []):
        want = str(bug.get("assert_test_artifacts") or "")
        tea_cfg = os.path.join(root, ad.get("bmad_root") or ".", "_bmad", "tea", "config.yaml")
        tea_cfg = os.path.normpath(tea_cfg)
        if not want:
            continue
        if not os.path.exists(tea_cfg):
            warn("known bug %s: tea config not present (module not installed?)" % bug.get("id"))
            continue
        with open(tea_cfg, encoding="utf-8") as fh:
            tcfg = fh.read()
        m = re.search(r'^test_artifacts:\s*"?([^"\n]+)"?', tcfg, re.M)
        got = (m.group(1).strip() if m else None)
        if got == want:
            ok("known bug %s: workaround holds (test_artifacts = %s)" % (bug.get("id"), want))
        else:
            bad("known bug %s: test_artifacts is %r, expected %r. The bmb+tea output-path leak "
                "has changed shape -- re-check the workaround before trusting TEA artifacts."
                % (bug.get("id"), got, want))
        for key in (bug.get("known_divergent_keys") or []):
            m2 = re.search(r"^%s:\s*(\S+)" % re.escape(str(key)), tcfg, re.M)
            if m2 and not m2.group(1).startswith("skills/"):
                warn("known bug %s: %s is now %r -- previously divergent (skills/...). The "
                     "upstream bug may be fixed; revisit the workaround."
                     % (bug.get("id"), key, m2.group(1)))

    # ---- 7. tripwires ----------------------------------------------------
    for sig in (ad.get("upgrade_signals") or {}).get("v7_breaking") or []:
        warn("v7 tripwire: %s" % sig)

    return report(args)


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
