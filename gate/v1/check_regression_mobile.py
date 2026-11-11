#!/usr/bin/env python3
"""check-regression-mobile — Phase 10b validator, mobile (Maestro).

The mobile sibling of `check_regression`. Same two questions, one extra
dimension:

  1. **Does every story that PASSED 10a-mobile have a committed flow?** Coverage
     is computed from the 10a-mobile report per platform, not claimed. A story
     that passed on iOS and has no flow is the case that regresses.
  2. **Is every quarantined flow tracked?** Quarantine is the sanctioned
     alternative to deleting a flake; without a tracking id, an owner and a
     reason it is a deletion with better manners.

It also lints flow quality: Maestro flows that tap raw coordinates
(`tapOn: {point: ...}`) are brittle in exactly the way the accessibility-tree
approach exists to avoid, so `id:`/`text:` selectors are required.

Exit 0 = pass, non-zero = fail.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

FLOW_EXT = (".yaml", ".yml")
BRITTLE = [
    ("raw coordinate tap", re.compile(r"tapOn:\s*\n\s*point:", re.M)),
    ("percentage-point tap", re.compile(r"point:\s*\d+%?,\s*\d+%?")),
]
STABLE = re.compile(r"\b(id|text|accessibilityText)\s*:")


def read(p):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def live_mobile_verdicts(path):
    """{(story, platform): verdict} from the 10a-mobile table."""
    text = read(path)
    if not text:
        return None
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\|\s*((?:US|NFR)-\d+)\s*\|\s*([A-Za-z]+)\s*\|\s*([A-Z-]+)\s*\|",
                     line.strip())
        if m:
            out[(m.group(1), m.group(2).lower())] = m.group(3).upper()
    return out


def collect_flows(d):
    out = {}
    if not os.path.isdir(d):
        return out
    for base, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in ("node_modules", ".git")]
        for fn in sorted(files):
            if fn.endswith(FLOW_EXT) and fn != "quarantine.yaml":
                p = os.path.join(base, fn)
                out[p] = read(p)
    return out


def main():
    ap = argparse.ArgumentParser(prog="check-regression-mobile.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--flows", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    d = args.dir or os.path.join(root, groot, "sdlc")
    fdir = args.flows or os.path.join(root, groot, "e2e-mobile")

    sys.path.insert(0, HERE)
    import check_profile
    ruling, _ = check_profile.read_ruling(d)
    # NOT APPLICABLE IS NOT A PASS.
    #
    # This used to be `if ruling == "WEB": print("PASS (no-op)"); return 0` --
    # a SECOND implementation of a decision profiles.yaml already owns, and the
    # one that produced v0.4's `result: pass` recorded into approval evidence
    # for a validator that never ran. Silently passing and being N/A looked
    # identical, which is exactly what 6.3 forbids.
    #
    # profiles.yaml declares this validator not_applicable under a ruling with
    # no mobile surface, and gate.sh honours that declaration, so in normal
    # operation this branch is never reached. Reaching it means something
    # invoked check-regression-mobile directly under a ruling that retires it -- a caller
    # mistake, which must be visible. Exit 2: cannot evaluate, never 0.
    mobile = check_profile.has_mobile_surface(ruling)
    if mobile is not True:
        why = ("the platform ruling is %r, which has no mobile surface"
               % (ruling,)) if mobile is False else (
              "no platform ruling has been recorded yet, so applicability "
              "cannot be decided")
        print("check-regression-mobile: NOT APPLICABLE -- %s. A mobile regression suite is not required here.\n"
              "  This is N/A, NOT a pass: profiles.yaml owns this decision and "
              "gate.sh honours it, so a direct invocation under this ruling is a "
              "caller mistake rather than a clean run." % why, file=sys.stderr)
        return 2

    errs, warns, notes = [], [], []

    verdicts = live_mobile_verdicts(os.path.join(d, "10a-live-verification-mobile.md"))
    if verdicts is None:
        errs.append("no 10a-mobile report at %s/10a-live-verification-mobile.md; cannot know which "
                    "stories passed on which platform." % d)
        verdicts = {}
    passed = sorted({s for (s, p), v in verdicts.items() if v == "PASS"})
    notes.append("10a-mobile: %d verdict(s), %d story/stories PASS somewhere"
                 % (len(verdicts), len(passed)))

    flows = collect_flows(fdir)
    if not flows:
        errs.append("no Maestro flows under %s. Phase 10b-mobile commits the regression suite; an "
                    "empty directory is not one." % fdir)
    else:
        notes.append("flows: %d file(s)" % len(flows))

    covered = {}
    for path, body in flows.items():
        for sid in set(re.findall(r"\b((?:US|NFR)[-_]\d+)\b", body)):
            covered.setdefault(sid.upper().replace("_", "-"), []).append(path)
    for sid in passed:
        if sid not in covered:
            errs.append("story %s PASSED 10a-mobile but has no committed Maestro flow naming it."
                        % sid)

    # quarantine tracking
    qpath = os.path.join(fdir, "quarantine.yaml")
    tracked = {}
    if os.path.exists(qpath):
        try:
            qdoc = hlib.load_yaml(qpath) or {}
        except Exception as exc:
            errs.append("e2e-mobile/quarantine.yaml does not parse (%r)" % (exc,))
            qdoc = {}
        for item in (qdoc.get("quarantined") or []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("flow") or item.get("test") or "")
            missing = [f for f in ("tracking_id", "reason", "owner")
                       if not str(item.get(f) or "").strip()]
            if missing:
                errs.append("quarantine entry %r is missing %s. Quarantine without a tracking id, "
                            "a reason and an owner is a deletion with better manners."
                            % (key or "(unnamed)", ", ".join(missing)))
            if key:
                tracked[key] = item

    tagged = 0
    for path, body in flows.items():
        rel = os.path.relpath(path, root)
        if re.search(r"^\s*-?\s*quarantine\s*$|tags:\s*\[[^\]]*quarantine", body, re.M):
            tagged += 1
            if not any(k in rel or k in body for k in tracked):
                errs.append("%s is tagged quarantine but has no entry in "
                            "e2e-mobile/quarantine.yaml." % rel)
    if tracked or tagged:
        notes.append("quarantine: %d tagged, %d tracked" % (tagged, len(tracked)))

    for path, body in flows.items():
        rel = os.path.relpath(path, root)
        for name, rx in BRITTLE:
            if rx.search(body):
                errs.append(
                    "%s uses a brittle locator (%s). Maestro flows must select by id/text "
                            "from the accessibility tree, which is the whole reason mobile-mcp "
                            "drives by that tree at 10a." % (rel, name))
        if not STABLE.search(body):
            warns.append("%s uses no id/text selector; check it is not coordinate-based." % rel)

    if not args.quiet:
        print("check-regression-mobile: %s" % fdir)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  all %d 10a-mobile-PASSED story/stories have a committed flow; "
                  "quarantine tracked; selectors stable." % len(passed))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
