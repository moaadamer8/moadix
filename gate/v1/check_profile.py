#!/usr/bin/env python3
"""check-profile — enforces the Target Platform Ruling's phase-specific demands.

Until v0.3 the ruling was a field in the BRD that nothing read. This validator is
what makes it binding. It is registered for the phases that carry extra
obligations under a non-WEB ruling and is a **no-op under WEB**, which is what
"the ruling decides" actually means: WEB projects are not made to answer mobile
questions, and WEB→APP / APP-FIRST projects cannot skip them.

The ruling is read from `sdlc/00-brd.md` — the single source of truth. Nothing
re-declares it, so it cannot drift.

Per-phase obligations come from `harness/config/profiles.yaml`:

  phase 3  app-architecture-sections
           offline, push, deep links, and an explicit app/API split. These are
           the four things a web-only design gets wrong for free and that are
           expensive to retrofit once a native client exists.

  phase 5  no-frontend-business-logic
           an explicit, argued declaration that business logic sits behind the
           API so the native client can reuse it. Partly manual by design: the
           check requires a stated position, not a checkbox, because "is this
           business logic?" is a judgement no regex should pretend to make.

Exit 0 = pass (including "nothing required for this ruling"). Non-zero = fail.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

CANON = {"WEB": "WEB", "WEB→APP": "WEB→APP", "WEB->APP": "WEB→APP", "APP-FIRST": "APP-FIRST"}

# ---- capability, not vocabulary -------------------------------------------
#
# Code does not care what a ruling is CALLED. It cares whether the product has
# a web surface or a mobile one -- that is the question behind every
# `if ruling == "WEB"` in the tree. Branching on the spelling put the same
# decision in five places and let three validators disable themselves in a
# fourth, which produced v0.4's `result: pass` for a validator that never ran.
#
# CANON owns the vocabulary; this owns the DECISIONS taken from it. Stage A
# moved two copies of the vocabulary here; this moves the branching.
CAPABILITIES = {
    "WEB":       {"web": True,  "mobile": False},
    "WEB→APP":   {"web": True,  "mobile": True},
    "APP-FIRST": {"web": False, "mobile": True},
}

# The two tables must not drift: a ruling CANON accepts and CAPABILITIES does
# not describe would raise UnknownRuling on a perfectly valid product, and one
# CAPABILITIES describes that CANON rejects is unreachable. Asserted at import
# so a third copy cannot appear quietly -- which is how the vocabulary came to
# have three divergent copies before Stage A.
# Raised, not asserted: `python -O` strips assert statements, so a guard
# written as one is a guard that can be optimised out of existence. A drift
# check that disappears under a flag is the shape of everything else this
# version has been closing.
if set(CANON.values()) != set(CAPABILITIES):
    raise RuntimeError(
        "check_profile: CANON and CAPABILITIES disagree: %s vs %s. A ruling "
        "CANON accepts but CAPABILITIES does not describe would raise "
        "UnknownRuling on a valid product; one CAPABILITIES describes but CANON "
        "rejects is unreachable."
        % (sorted(set(CANON.values())), sorted(CAPABILITIES)))

MOBILE_KINDS = ("mobile-ios", "mobile-android")
WEB_KINDS = ("web",)


class UnknownRuling(ValueError):
    """A ruling that is not in CANON. NOT the same as no ruling at all."""


def canonical(ruling):
    """The canonical spelling, or None when no ruling has been made yet.

    None is the phase-0-not-done case and is legitimate: UNKNOWN about the
    SUBJECT. A non-empty string CANON does not recognise is a control file
    saying something nobody defined -- UNKNOWN about the INSTRUMENT -- and
    raises (3.10).
    """
    if ruling is None or not str(ruling).strip():
        return None
    raw = str(ruling).strip()
    got = CANON.get(raw.upper().replace(" ", "")) or CANON.get(raw)
    if got is None:
        raise UnknownRuling(
            "%r is not a platform ruling. Known: %s. An unrecognised ruling used "
            "to read as COHERENT -- _kind_matches_ruling('web', 'APP-ONLY') "
            "returned (True, None) -- so a typo in a control file passed every "
            "capability question ever asked of it."
            % (raw, ", ".join(sorted(set(CANON.values())))))
    return got


def has_web_surface(ruling):
    """True/False. None ruling -> None: not yet decided, which is not 'no'."""
    c = canonical(ruling)
    return None if c is None else CAPABILITIES[c]["web"]


def has_mobile_surface(ruling):
    """True/False. None ruling -> None: not yet decided, which is not 'no'."""
    c = canonical(ruling)
    return None if c is None else CAPABILITIES[c]["mobile"]


def kind_matches(kind, ruling):
    """(ok, why) -- does product-app.yaml's `kind` fit the ruling's surfaces?

    WEB→APP ACCEPTS EITHER, and getting that wrong is why this note exists.
    The first version required a mobile kind for WEB→APP. It passed the live
    tree while product-app.yaml was `mobile-ios`, then flagged the operator's
    CORRECT restoration to `kind: web` and refused every gate command. A WEB→APP
    product has BOTH surfaces by definition -- that is what the arrow means --
    and which front door is live depends on where the transition has got to.
    A check that cries wolf at the operator for doing the right thing gets
    disabled.
    """
    try:
        c = canonical(ruling)
    except UnknownRuling as exc:
        return False, str(exc)
    if c is None:
        return True, None
    k = (kind or "").lower()
    allowed = ()
    if CAPABILITIES[c]["web"]:
        allowed += WEB_KINDS
    if CAPABILITIES[c]["mobile"]:
        allowed += MOBILE_KINDS
    if k in allowed:
        return True, None
    return False, ("the BRD rules this product %s, whose surfaces are %s, but "
                   "product-app.yaml starts a %r app"
                   % (c, " and ".join(s for s in ("web", "mobile")
                                      if CAPABILITIES[c][s]), k))


def strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return strip_comments(fh.read())


def read_ruling(sdlc_dir):
    text = read(os.path.join(sdlc_dir, "00-brd.md"))
    if text is None:
        return None, "BRD not found at %s/00-brd.md" % sdlc_dir
    m = re.search(r"^\s*[-*]\s*\*\*Target Platform Ruling:?\*\*\s*(.+?)\s*$", text, re.I | re.M)
    if not m:
        return None, "BRD records no '**Target Platform Ruling:**'"
    raw = m.group(1).strip()
    canon = CANON.get(raw.upper().replace(" ", ""))or CANON.get(raw)
    if not canon:
        return None, "Target Platform Ruling %r is not one of WEB | WEB→APP | APP-FIRST" % raw
    return canon, None


def main():
    ap = argparse.ArgumentParser(prog="check-profile.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", required=True, help="harness phase label (e.g. 3, 5)")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    d = args.dir or os.path.join(root, groot, "sdlc")

    prof_path = hlib.config_path(root, "profiles.yaml")
    try:
        profiles = (hlib.load_yaml(prof_path) or {}).get("profiles") or {}
    except Exception as exc:
        print("check-profile: cannot read profiles.yaml (%r)" % (exc,))
        return 2

    ruling, err = read_ruling(d)
    errs, notes = [], []
    if err:
        errs.append(err + " — the ruling drives every profile-conditional gate.")
        ruling = None

    if ruling:
        notes.append("ruling: %s" % ruling)
        prof = profiles.get(ruling) or {}
        checks = [c for c in (prof.get("extra_checks") or [])
                  if str(c.get("phase")) == str(args.phase)]
        if not checks:
            notes.append("no extra checks for phase %s under %s" % (args.phase, ruling))
        for c in checks:
            cid = c.get("id")
            if cid == "app-architecture-sections":
                # During a TRANSITION the app architecture lives in the delta, not
                # in the original HLD -- the HLD is read-only precisely so a delta
                # pass cannot rewrite it. Accept either source: requiring it in the
                # HLD would force a transition to violate its own read-only rule.
                sources = [read(os.path.join(d, "03-hld.md")) or ""]
                tdir = os.path.join(os.path.dirname(d), "transition")
                if os.path.isdir(tdir):
                    for base, _dirs, files in os.walk(tdir):
                        for fn in files:
                            if fn.endswith(".md") and "03-delta" in fn:
                                sources.append(read(os.path.join(base, fn)) or "")
                hld = "\n".join(x for x in sources if x)
                if not hld:
                    errs.append("%s: no HLD at %s/03-hld.md and no 03-delta-*.md in the transition "
                                "workspace" % (cid, d))
                    continue
                low = hld.lower()
                missing = [s for s in (c.get("required_sections") or [])
                           if str(s).lower() not in low]
                if missing:
                    errs.append("%s: the HLD does not cover %s. Under %s these are required: they "
                                "are what a web-only design gets wrong for free and cannot be "
                                "retrofitted cheaply." % (cid, missing, ruling))
                else:
                    notes.append("%s: all required sections present" % cid)
            elif cid == "no-frontend-business-logic":
                blob = ""
                for search in (os.path.join(d, "05-lld"),
                               os.path.join(os.path.dirname(d), "transition")):
                    if not os.path.isdir(search):
                        continue
                    for base, _dirs, files in os.walk(search):
                        for fn in files:
                            if fn.endswith(".md"):
                                blob += (read(os.path.join(base, fn)) or "")
                if not blob:
                    errs.append("%s: no LLD module docs and no transition delta to read" % cid)
                    continue
                needle = str(c.get("required_declaration") or "business logic").lower()
                if needle not in blob.lower():
                    errs.append("%s: the LLD makes no explicit statement about where business "
                                "logic lives. Under %s the native client must be able to reuse "
                                "it, so state the position and argue it — a checkbox is not a "
                                "design." % (cid, ruling))
                else:
                    notes.append("%s: declaration present (content is a human judgement)" % cid)
            elif cid == "portability-scoring":
                notes.append("%s: enforced by check-handoff-1" % cid)
            else:
                notes.append("%s: no automated check in v0.3 (declared only)" % cid)

        for na in (prof.get("not_applicable") or []):
            if str(na.get("phase")) == str(args.phase):
                notes.append("N/A here: %s — %s" % (na.get("id"), (na.get("reason") or "")[:90]))

    if not args.quiet:
        print("check-profile (phase %s): %s" % (args.phase, d))
        for n in notes:
            print("  note  %s" % n)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  profile obligations for phase %s satisfied." % args.phase)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
