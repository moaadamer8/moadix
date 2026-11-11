#!/usr/bin/env python3
"""check-live-verification-mobile — Phase 10a validator, mobile platforms.

The mobile sibling of `check_live_verification`. Same discipline, one extra
dimension: a verdict is required **per story PER PLATFORM**, so a product that
works on iOS and crashes on Android cannot report a single green tick.

Platform-neutrality is the point (v0.4 constraint): the story IDs come from the
SAME `sdlc/02-prd.md` the web run uses. There is no mobile PRD and no forked
story list — if a story means something different on mobile, that is a PRD
problem, not a reason to keep two lists that drift.

Checks:
  1. every PRD story has a verdict for every ENABLED platform
  2. every verdict cites evidence that resolves on disk (PNG magic bytes for
     screenshots; device logs must be non-empty)
  3. every mandatory mobile check is present per platform: permission
     grant/deny, offline, background/resume, kill/relaunch, deep link,
     gestures, rotation, small-screen
  4. FAIL / BLOCKED need a waiver; **NA-ENVIRONMENT does NOT** — it is recorded
     as an environment gap and blocks the release under a mobile ruling, because
     "we could not test this platform" is not a pass

Exit 0 = pass, non-zero = fail.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

VERDICTS = {"PASS", "FAIL", "BLOCKED", "NA", "NA-ENVIRONMENT"}
IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")

MANDATORY = [
    ("permission-grant", r"permission[ -]grant"),
    ("permission-deny", r"permission[ -]deny"),
    ("offline", r"offline|airplane"),
    ("background-resume", r"background[ -]resume|background\s*/\s*resume"),
    # Distinct from background-resume: an app can restore its state perfectly
    # on resume and STILL have leaked that state into the OS app-switcher
    # snapshot taken on the way out. Restoring correctly and redacting before
    # the snapshot are two different controls, and only the first was checked.
    # Found as SF-2 on unitc (v0.4): .keyboardType hardening was present, the
    # scenePhase blanking was not, and no mandatory check would have caught it.
    ("background-snapshot", r"background[ -]snapshot|app[ -]switcher"),
    ("kill-relaunch", r"kill[ -]relaunch|kill\s*/\s*relaunch"),
    ("deep-link", r"deep[ -]link"),
    ("gestures", r"gestures?"),
    ("rotation", r"rotation"),
    ("small-screen", r"small[ -]screen"),
]


def strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return strip_comments(fh.read())


def prd_story_ids(path):
    text = read(path)
    if text is None:
        return None
    return sorted(set(re.findall(r"^#{2,4}\s+((?:US|NFR)-\d+)\b", text, re.M)))


def enabled_platforms(root):
    """{platform: enabled} from harness/config/mobile.yaml."""
    p = hlib.config_path(root, "mobile.yaml")
    if not os.path.exists(p):
        return {"ios": True, "android": False}
    try:
        cfg = hlib.load_yaml(p) or {}
    except Exception:
        return {"ios": True, "android": False}
    out = {}
    for name, spec in (cfg.get("platforms") or {}).items():
        out[str(name).lower()] = bool((spec or {}).get("enabled"))
    return out or {"ios": True, "android": False}


def verify_file(root, rel):
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        return "does not exist"
    if os.path.getsize(p) == 0:
        return "is empty"
    if re.search(r"\.(png|jpg|jpeg|gif|webp)$", rel, re.I):
        with open(p, "rb") as fh:
            head = fh.read(8)
        if not any(head.startswith(m) for m in IMAGE_MAGIC):
            return "is not a real image (bad magic bytes)"
    return None


def evidence_paths(spec):
    out = []
    for tok in re.split(r"[,\s]+", spec or ""):
        tok = tok.strip().strip("`'\"()[]")
        if tok and re.search(r"\.(png|jpg|jpeg|txt|log|json|md)$", tok, re.I):
            out.append(tok)
    return out


def rows(text):
    """Parse the per-story-per-platform verdict table.

    | Story | Platform | Verdict | Evidence | Notes |
    """
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^\|\s*((?:US|NFR)-\d+)\s*\|\s*([A-Za-z]+)\s*\|\s*([A-Z-]+)\s*\|([^|]*)\|",
                     line.strip())
        if m:
            out.append({"story": m.group(1), "platform": m.group(2).lower(),
                        "verdict": m.group(3).upper(), "evidence": m.group(4).strip()})
    return out


def mandatory_rows(text):
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^\|\s*([a-z-]+)\s*\|\s*([A-Za-z]+)\s*\|\s*([A-Z-]+)\s*\|([^|]*)\|",
                     line.strip())
        if m:
            out.append({"check": m.group(1).lower(), "platform": m.group(2).lower(),
                        "verdict": m.group(3).upper(), "evidence": m.group(4).strip()})
    return out


def waivers(root, rule="live-verification-mobile"):
    try:
        doc = hlib.load_phase_doc(root)
    except Exception:
        return {}
    return {str(w.get("path")): w for w in hlib.waivers_for(doc, rule)
            if w.get("reason") and w.get("approver")}


def citations(root, groot, d, text=None):
    """[(claim_id, relpath)] this report cites, for the provenance audit.

    ONE parser, two callers: this validator and the phase-11 scorecard. See the
    web sibling for why this is a function rather than an inline accumulator.
    """
    if text is None:
        text = read(os.path.join(d, "10a-live-verification-mobile.md")) or ""
    out = []
    for r in rows(text):
        for rel in evidence_paths(r["evidence"]):
            out.append(("10a:%s:%s" % (r["story"], r["platform"]), rel))
    for r in mandatory_rows(text):
        for rel in evidence_paths(r["evidence"]):
            out.append(("10a:%s:%s" % (r["check"], r["platform"]), rel))
    return out


def main():
    ap = argparse.ArgumentParser(prog="check-live-verification-mobile.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        paths_doc = hlib.load_paths_doc(root) or {}
    except Exception:
        paths_doc = {}
    groot = paths_doc.get("governed_root") or ""
    d = args.dir or os.path.join(root, groot, "sdlc")

    # Profile gate: mobile verification only applies under a mobile ruling.
    sys.path.insert(0, HERE)
    import check_profile
    ruling, _err = check_profile.read_ruling(d)
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
    # invoked check-live-verification-mobile directly under a ruling that retires it -- a caller
    # mistake, which must be visible. Exit 2: cannot evaluate, never 0.
    mobile = check_profile.has_mobile_surface(ruling)
    if mobile is not True:
        why = ("the platform ruling is %r, which has no mobile surface"
               % (ruling,)) if mobile is False else (
              "no platform ruling has been recorded yet, so applicability "
              "cannot be decided")
        print("check-live-verification-mobile: NOT APPLICABLE -- %s. Mobile live verification is not required here.\n"
              "  This is N/A, NOT a pass: profiles.yaml owns this decision and "
              "gate.sh honours it, so a direct invocation under this ruling is a "
              "caller mistake rather than a clean run." % why, file=sys.stderr)
        return 2

    errs, warns, notes = [], [], []
    wv = waivers(root)
    plats = enabled_platforms(root)
    notes.append("platforms: %s" % ", ".join("%s=%s" % (k, "enabled" if v else "NOT-AVAILABLE")
                                             for k, v in sorted(plats.items())))

    stories = prd_story_ids(os.path.join(d, "02-prd.md"))
    if stories is None:
        errs.append("PRD not found at %s/02-prd.md. Mobile verification uses the SAME "
                    "platform-neutral stories as web; there is no mobile PRD." % d)
        stories = []

    report = os.path.join(d, "10a-live-verification-mobile.md")
    text = read(report)
    if text is None:
        errs.append("mobile live-verification report not found at %s." % report)
        text = ""

    if not re.search(r"\*\*Device[s]?:?\*\*", text, re.I):
        errs.append("report records no '**Devices:**' line (which simulator/emulator, which OS "
                    "version). A mobile verdict without a device is not reproducible.")

    seen = {(r["story"], r["platform"]): r for r in rows(text)}
    total_ev = bad_ev = 0

    for sid in stories:
        for plat, on in sorted(plats.items()):
            r = seen.get((sid, plat))
            if r is None:
                errs.append("story %s has no verdict for platform %s. A single green tick across "
                            "platforms hides a per-platform failure." % (sid, plat))
                continue
            v = r["verdict"]
            if v not in VERDICTS:
                errs.append("%s/%s: verdict %r is not one of %s." % (sid, plat, v, sorted(VERDICTS)))
                continue
            if v == "NA-ENVIRONMENT":
                if on:
                    errs.append("%s/%s is NA-ENVIRONMENT but %s is marked ENABLED in "
                                "harness/config/mobile.yaml — either the platform is available and "
                                "must be tested, or the config is wrong." % (sid, plat, plat))
                else:
                    notes.append("%s/%s NA-ENVIRONMENT (host cannot run %s)" % (sid, plat, plat))
                continue
            if not on:
                warns.append("%s/%s has verdict %s though %s is not enabled." % (sid, plat, v, plat))
            paths = evidence_paths(r["evidence"])
            if v in ("PASS", "FAIL") and not paths:
                errs.append("%s/%s is %s but cites no evidence file." % (sid, plat, v))
            for rel in paths:
                total_ev += 1
                why = verify_file(root, rel)
                if why:
                    bad_ev += 1
                    errs.append("%s/%s evidence %s %s." % (sid, plat, rel, why))
            if v in ("FAIL", "BLOCKED"):
                key = "%s:%s" % (sid, plat)
                if key not in wv and sid not in wv:
                    errs.append("%s/%s is %s with no waiver (use --path %s)." % (sid, plat, v, key))

    mrows = {(r["check"], r["platform"]): r for r in mandatory_rows(text)}
    for name, _pat in MANDATORY:
        for plat, on in sorted(plats.items()):
            r = mrows.get((name, plat))
            if r is None:
                errs.append("mandatory mobile check %r missing for %s." % (name, plat))
                continue
            if r["verdict"] == "NA-ENVIRONMENT" and not on:
                continue
            for rel in evidence_paths(r["evidence"]):
                total_ev += 1
                why = verify_file(root, rel)
                if why:
                    bad_ev += 1
                    errs.append("mandatory %r/%s evidence %s %s." % (name, plat, rel, why))
            if r["verdict"] in ("FAIL", "BLOCKED") and ("mandatory:%s:%s" % (name, plat)) not in wv:
                errs.append("mandatory %r/%s is %s with no waiver." % (name, plat, r["verdict"]))

    # Provenance audit -- ONE shared implementation, five lines per caller.
    # Existence was checked above; this asks the two questions existence cannot:
    # does the artifact still describe this tree, and was it produced for the
    # claim it is cited for (Constitution 4.5).
    import provenance
    pe, pw, pn = provenance.audit(root, groot, citations(root, groot, d, text))
    errs += pe
    warns += pw
    notes += pn

    if total_ev:
        notes.append("evidence referenced: %d, resolved: %d" % (total_ev, total_ev - bad_ev))
    unavailable = [p for p, on in plats.items() if not on]
    if unavailable:
        notes.append("NOTE: %s reported NA-ENVIRONMENT. Under ruling %s the phase-11 scorecard "
                     "treats that as blocking, not as a pass." % (", ".join(unavailable), ruling))

    if not args.quiet:
        print("check-live-verification-mobile: %s" % report)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  %d story/platform verdict(s) and %d mandatory check(s), evidence resolves."
                  % (len(stories) * len(plats), len(MANDATORY) * len(plats)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
