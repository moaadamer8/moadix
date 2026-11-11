#!/usr/bin/env python3
"""check-store-readiness — Phase 11b validator (mobile store release).

Applies ONLY under a WEB→APP or APP-FIRST ruling; a no-op PASS under WEB, since
there is no store to release to.

The interesting check is the last one. A store's privacy / data-safety form is
the one place a product states, under penalty, what data it handles — and it is
usually filled in by whoever is doing the submission, from memory. This validator
cross-checks it against the **Phase 4 threat model's data classification**, so
the declaration and the security analysis cannot quietly disagree.

Checks:
  1. signing configured for every target platform (never a committed key)
  2. versioning present: marketing version + per-platform build numbers
  3. required store assets declared AND the files exist on disk
  4. privacy declarations cross-checked against the threat model
  5. every permission carries a justification
  6. the review-rejection risk checklist is fully assessed

Exit 0 = ready, non-zero = not ready.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

RISKS = ["incomplete metadata", "crashes on reviewer device", "broken or placeholder links",
         "login required", "private/undocumented api", "in-app purchase",
         "privacy declaration mismatch", "minimum os version"]
SECRETISH = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\.p12\b|\.keystore\b|\.jks\b")


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)


def field(text, name):
    m = re.search(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+?)\s*$" % re.escape(name), text or "", re.I | re.M)
    return m.group(1).strip() if m else None


def table_rows(text, ncols):
    """Data rows only.

    The previous version returned the HEADER row too, so it reported
    "rejection risk 'Risk' is not assessed (got 'Assessed')" -- complaining
    about the column titles. A separator row (|---|---|) marks the end of the
    header, so everything up to and including it is dropped.
    """
    out, seen_sep = [], False
    for line in (text or "").splitlines():
        st = line.strip()
        if not st.startswith("|"):
            if out:
                seen_sep = False      # a new table starts after a blank/prose gap
            continue
        cells = [c.strip() for c in st.strip("|").split("|")]
        if set("".join(cells)) <= set("-: ") and cells:
            seen_sep = True           # separator: the row before it was a header
            continue
        if not seen_sep:
            continue                  # header row (or a table without a separator)
        if len(cells) >= ncols:
            out.append(cells)
    return out


def section(text, title):
    m = re.search(r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(title), text or "",
                  re.I | re.M | re.S)
    return m.group(1) if m else ""


ASSET_RE = re.compile(r"\.(png|jpg|jpeg|webp|pdf)$", re.I)


def asset_paths(ev):
    return [t.strip().strip("`") for t in re.split(r"[,\s]+", ev) if ASSET_RE.search(t)]


def claim_id(asset_name):
    """A store-asset name as a claim id a PRODUCER could legally declare.

    provenance.CLAIM_RE allows [A-Za-z0-9._-] after the phase prefix. The asset
    row "Splash / launch" was rendering as `11b:splash-/-launch`, which stamp()
    rejects -- so the checker was demanding a claim no capture could ever carry.
    A checker whose required form is unwriteable is not a gate, it is a trap.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(asset_name).strip()).strip("-.")
    return "11b:%s" % (slug or "asset")


def citations(root, groot, d, text=None):
    """[(claim_id, relpath)] for every declared store asset. ONE parser."""
    if text is None:
        text = read(os.path.join(d, "11b-store-release.md")) or ""
    out = []
    for r in table_rows(section(text, "Store assets"), 4):
        for rel in asset_paths(r[3]):
            out.append((claim_id(r[0]), rel))
    return out


def main():
    ap = argparse.ArgumentParser(prog="check-store-readiness.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    d = args.dir or os.path.join(root, groot, "sdlc")

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
    # invoked check-store-readiness directly under a ruling that retires it -- a caller
    # mistake, which must be visible. Exit 2: cannot evaluate, never 0.
    mobile = check_profile.has_mobile_surface(ruling)
    if mobile is not True:
        why = ("the platform ruling is %r, which has no mobile surface"
               % (ruling,)) if mobile is False else (
              "no platform ruling has been recorded yet, so applicability "
              "cannot be decided")
        print("check-store-readiness: NOT APPLICABLE -- %s. A store release is not required here.\n"
              "  This is N/A, NOT a pass: profiles.yaml owns this decision and "
              "gate.sh honours it, so a direct invocation under this ruling is a "
              "caller mistake rather than a clean run." % why, file=sys.stderr)
        return 2

    errs, warns, notes = [], [], []
    citations_seen = []   # (claim_id, relpath) for the provenance audit
    path = os.path.join(d, "11b-store-release.md")
    text = read(path)
    if text is None:
        errs.append("store-release document not found at %s. Phase 11b cannot be approved "
                    "without it." % path)
        text = ""

    if SECRETISH.search(text):
        errs.append("the store-release document appears to embed a private key or keystore. "
                    "Never commit signing material; reference the CI secret by name instead.")

    # 1. signing
    sign = table_rows(section(text, "Signing"), 4)
    plats = {r[0].lower() for r in sign if r[0].lower() in ("ios", "android")}
    if not plats:
        errs.append("no signing rows for ios/android under '## Signing'.")
    for r in sign:
        if r[0].lower() in ("ios", "android") and r[1].lower() not in ("yes", "y", "true"):
            errs.append("signing is not configured for %s." % r[0])
    if plats:
        notes.append("signing declared for: %s" % ", ".join(sorted(plats)))

    # 2. versioning
    if not field(text, "Marketing version"):
        errs.append("no '**Marketing version:**'.")
    if "ios" in plats and not field(text, "Build number (ios)"):
        errs.append("no iOS '**Build number (ios):**'.")
    if "android" in plats and not field(text, "Version code (android)"):
        errs.append("no '**Version code (android):**'.")

    # 3. assets must exist on disk, not merely be declared
    assets = table_rows(section(text, "Store assets"), 4)
    if not assets:
        errs.append("no rows under '## Store assets'.")
    for r in assets:
        name, present, ev = r[0], r[2].lower(), r[3]
        if present not in ("yes", "y", "true"):
            errs.append("store asset %r is not present." % name)
            continue
        rels = asset_paths(ev)
        if not rels:
            errs.append("store asset %r claims present but cites no file." % name)
        for rel in rels:
            citations_seen.append((claim_id(name), rel))
            fp = os.path.join(root, groot, rel) if not rel.startswith(groot) else os.path.join(root, rel)
            if not os.path.exists(fp) and not os.path.exists(os.path.join(root, rel)):
                errs.append("store asset %r cites %s, which does not exist on disk." % (name, rel))

    # Provenance audit -- the shared implementation (Constitution 4.5). This is
    # the case that motivated it: real 10a QA screenshots would have satisfied
    # this existence check, and only a session's judgement stopped them.
    import provenance
    _pe, _pw, _pn = provenance.audit(root, groot, citations_seen)
    errs += _pe
    warns += _pw
    notes += _pn

    # 4. privacy vs the threat model
    tm = read(os.path.join(d, "04-threat-model.md")) or ""
    priv = table_rows(section(text, "Privacy declarations / data safety"), 6)
    if not priv:
        errs.append("no rows under '## Privacy declarations / data safety'. The store form must be "
                    "derived from the Phase 4 data classification, not from memory.")
    for r in priv:
        ref = r[5] if len(r) > 5 else ""
        secs = re.findall(r"\bSEC-\d{3}\b", ref)
        if r[0].lower() != "none" and not secs:
            errs.append("privacy row %r cites no threat-model SEC-ID. Every declared data type must "
                        "trace to the Phase 4 classification." % r[0])
        for sid in secs:
            if tm and sid not in tm:
                errs.append("privacy row %r references %s, which is not in the threat model."
                            % (r[0], sid))
    if priv:
        notes.append("privacy rows: %d" % len(priv))

    # 5. permissions
    perms = table_rows(section(text, "Permissions justification"), 3)
    if not perms:
        errs.append("no rows under '## Permissions justification' (use a 'none' row if the app "
                    "requests none).")
    for r in perms:
        if r[0].lower() != "none" and not r[1].strip():
            errs.append("permission %r has no justification. A permission with no reason is a "
                        "review rejection waiting to happen." % r[0])

    # 6. rejection risks
    risks = section(text, "Review-rejection risk checklist").lower()
    for want in RISKS:
        if want not in risks:
            errs.append("review-rejection checklist does not cover %r." % want)
    for r in table_rows(section(text, "Review-rejection risk checklist"), 3):
        if r[1].lower() not in ("yes", "y", "true", "n/a", "na"):
            errs.append("rejection risk %r is not assessed (got %r)." % (r[0], r[1]))

    if not args.quiet:
        print("check-store-readiness: %s" % path)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  signing, versioning, assets on disk, privacy cross-checked against the "
                  "threat model, permissions justified, rejection risks assessed.")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
