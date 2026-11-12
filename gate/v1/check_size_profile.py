#!/usr/bin/env python3
"""check-size-profile — a collapsed gate is not a skipped gate.

WHAT WAS THERE BEFORE

  Constitution 6.1 has said since v0.2 that work is sized S / M / L and that
  "S may collapse phases with an explicit recorded ruling, M and L may not".
  The BRD carries a `Size:` field, check-handoff validates it is one of S|M|L,
  and **nothing has ever read it**. 3.9, inside the sizing rule itself.

THE HEADLINE FINDING THIS CHECK EXISTS BECAUSE OF

  The scorecard's verdict vocabulary was **PASS / FAIL / RELEASABLE / BLOCKED**
  -- one slot for three different claims:

      COLLAPSED  a decision about PROCESS DEPTH        (we chose not to run it)
      N/A        a statement about APPLICABILITY       (it does not apply here)
      PASS       a claim about the PRODUCT             (it ran and was fine)

  Rendering a collapse as PASS would make it indistinguishable from a gate that
  ran and passed. That the vocabulary could not express three states is the
  finding, not an inconvenience, and the fix is to extend it rather than to
  reuse a slot.

AND A COLLAPSE MUST NAME WHAT STOPPED RUNNING

  Otherwise COLLAPSED is a nicer-looking silence. Every entry declares
  `checks_not_run`, each name must resolve to a real registry component, and
  the scorecard prints them. A declaration naming nothing is not a decision
  anyone can review.

Usage: harness/bin/check-size-profile.sh [--quiet]
Exit 0 = clean · 1 = findings · 2 = cannot evaluate.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

# MOADIX v2 (increment 5 fix): the PRODUCT repo (see check_surface_coverage.ROOT).
ROOT = os.environ.get("HARNESS_ROOT") or (hlib.project_root() if os.environ.get("MOADIX_PRODUCT_ROOT") else
                                         os.path.realpath(os.path.join(HERE, "..", "..")))

SIZES = ("S", "M", "L")
SIZE_RE = re.compile(r"^\s*[-*]\s*\*\*Size:?\*\*:?\s*([SML])\b", re.M | re.I)


def declared_size(brd_path):
    """(size, why_not). None size means the BRD does not declare one."""
    if not os.path.exists(brd_path):
        return None, "the BRD does not exist at %s" % brd_path
    with open(brd_path, encoding="utf-8", errors="replace") as fh:
        text = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    m = SIZE_RE.search(text)
    if not m:
        return None, "the BRD declares no `- **Size:** S|M|L` field"
    return m.group(1).upper(), ""


def collapses_for(profiles_doc, size):
    """(entries, declared). `declared` distinguishes 'no collapses' from
    'this size is not described at all' -- two states the sizing rule needs
    kept apart, the same way parsed_set keeps an empty parse from a missing
    source."""
    sizes = (profiles_doc or {}).get("sizes") or {}
    if size not in sizes:
        return [], False
    return list((sizes.get(size) or {}).get("collapse") or []), True


def collapsed_map(root):
    """(state, value) -- the seam other checks use. Delegates to hlib, which is
    the one owner: gate.py's approval ordering and the write gate's
    current-phase resolution read the same function, and a second copy of the
    rule that decides which phases may be skipped is not a thing to have."""
    return hlib.collapsed_phases(root)


def main():
    ap = argparse.ArgumentParser(prog="check-size-profile.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        paths = hlib.load_paths_doc(ROOT) or {}
        profiles = hlib.load_yaml(
            hlib.config_path(ROOT, "profiles.yaml")) or {}
        registry = hlib.load_yaml(
            hlib.config_path(ROOT, "registry.yaml")) or {}
    except Exception as exc:                                    # noqa: BLE001
        print("check-size-profile: cannot read the control files (%r). UNKNOWN "
              "about the INSTRUMENT, not a pass (3.10)." % (exc,), file=sys.stderr)
        return 2
    groot = (paths.get("governed_root") or "").strip("/")

    size, why = declared_size(os.path.join(ROOT, groot, "sdlc", "00-brd.md"))
    if size is None:
        print("check-size-profile: %s. Size drives which phases collapse, so "
              "without it the profile cannot be applied -- UNKNOWN, not a pass "
              "(3.10)." % why, file=sys.stderr)
        return 2

    errs, notes = [], []
    entries, declared = collapses_for(profiles, size)
    if not declared:
        errs.append("profiles.yaml declares no `sizes:` entry for %r. An "
                    "undescribed size is not the same as a size that collapses "
                    "nothing, and only one of them is a decision." % size)
        entries = []

    comps = registry.get("components") or []
    ids = {c.get("id") for c in comps}
    phase_of = {c.get("id"): c.get("phase") for c in comps}
    phase_labels = {str(p.get("label")) for p in (paths.get("phases") or [])}

    if size in ("M", "L") and entries:
        errs.append("size %s declares %d collapse(s). Constitution 6.1: S may "
                    "collapse phases with an explicit recorded ruling, M and L "
                    "MAY NOT." % (size, len(entries)))

    seen = set()
    for e in entries:
        ph = str((e or {}).get("phase") or "").strip()
        reason = str((e or {}).get("reason") or "").strip()
        not_run = [str(x) for x in ((e or {}).get("checks_not_run") or [])]
        if not ph:
            errs.append("a collapse entry for size %s names no phase." % size)
            continue
        if ph in seen:
            errs.append("phase %s is collapsed twice under size %s." % (ph, size))
        seen.add(ph)
        if phase_labels and ph not in phase_labels:
            errs.append("size %s collapses phase %r, which the path map does "
                        "not declare." % (size, ph))
        if not reason:
            errs.append("size %s collapses phase %s with NO reason. 6.1 requires "
                        "an explicit recorded ruling; a collapse without one is "
                        "a skip." % (size, ph))
        if not not_run:
            errs.append(
                "size %s collapses phase %s and names no `checks_not_run`. "
                "Without that the scorecard can say COLLAPSED and nobody can "
                "tell what stopped running -- which makes a size profile a skip "
                "with better paperwork." % (size, ph))
            continue
        missing = [n for n in not_run if n not in ids]
        if missing:
            errs.append("size %s collapses phase %s naming checks_not_run %s, "
                        "which are not registry components. A declaration naming "
                        "nothing is not a decision anyone can review."
                        % (size, ph, ", ".join(missing)))
        # Existence was never the question. A collapse that names real checks
        # belonging to some OTHER phase reads as fully accounted for and
        # accounts for nothing -- 3.11, a check answering "do these names
        # exist" under the name "does this collapse say what it stops". The
        # registry already records which phase each component gates.
        wrong = [n for n in not_run if n in ids and str(phase_of.get(n)) != ph]
        if wrong:
            errs.append(
                "size %s collapses phase %s but names checks_not_run %s, which "
                "gate other phases (%s). Naming a real check that this collapse "
                "does not stop makes the collapse look accounted for while "
                "accounting for nothing."
                % (size, ph, ", ".join(wrong),
                   ", ".join("%s->%s" % (n, phase_of.get(n)) for n in wrong)))
        gated = sorted(n for n, pp in phase_of.items() if str(pp) == ph)
        unnamed = [n for n in gated if n not in not_run]
        if unnamed:
            notes.append("phase %s: the registry also gates %s, not named in "
                         "checks_not_run" % (ph, ", ".join(unnamed)))
        if not missing and not wrong:
            notes.append("phase %s COLLAPSED under size %s -- not run: %s"
                         % (ph, size, ", ".join(not_run)))

    if not args.quiet:
        print("check-size-profile: size %s, %d collapse(s)" % (size, len(entries)))
        for n in notes:
            print("  note  %s" % n)
        if size in ("M", "L"):
            print("  note  size %s collapses nothing by rule (6.1), declared "
                  "explicitly rather than omitted." % size)
        print("  limit COLLAPSED is a decision about process depth. It is not "
              "N/A (a statement about applicability) and not PASS (a claim "
              "about the product), and the scorecard renders all three "
              "separately so a collapse can never read as a gate that ran.")
    for e in errs:
        print("  FAIL  %s" % e)
    if errs:
        return 1
    if not args.quiet:
        print("  PASS  every collapse carries a reason and names the checks it "
              "stops from running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
