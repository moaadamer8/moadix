#!/usr/bin/env python3
"""check-authz-matrix — a verdict per role x resource, on evidence that could differ.

THE V0.3 PRECEDENT IS THE SPECIFICATION

  `unauthorized-access` was one global row in the 10a report, and it was
  satisfied by a plain page-load screenshot -- an artifact identical whether or
  not authorization existed. One checkbox standing in for a matrix, evidenced by
  something that could not disagree.

WHAT THE MEASUREMENT ADDED, AND IT CHANGED THE RULE

  1. **A file-type change alone is inert.** check_live_verification.verify_file
     validates magic bytes only for IMAGE extensions; for anything else it
     checks existence and non-emptiness. `unauth-403.json` containing `{}`
     passes exactly as a screenshot does. "Record the exchange instead of
     screenshotting" would have LOOKED like a fix and changed nothing, so the
     evidence rule here is about CONTENT, not format (4.5).

  2. **Screenshots are the only 10a evidence vocabulary this project has.** All
     16 artifacts cited in toy-product's 10a report are PNGs; none encodes a
     status or a body. v0.3 was not a bad choice on one row -- it was the only
     form available. A screenshot IS discriminating for mobile-viewport or
     negative-inputs, and structurally cannot be for unauthorized-access.

  3. **Discrimination needs a CONTRAST.** A lone recorded 403 is equally
     consistent with "this route always 403s", "the server was down" and "that
     path does not exist". What makes a denial attributable to the ROLE is the
     same resource observed as permitted for a different principal.

SO A CELL PASSES ONLY IF ITS EVIDENCE COULD HAVE DIFFERED

  deny cell  -> a denying observation for this role AND a permitting one for
                some other role on the SAME resource. Both are read; both must
                carry a status.
  allow cell -> a permitting observation for this role.
  neither    -> UNKNOWN. A resource no role may reach has no positive control,
                so nothing separates "correctly denied" from "broken", and
                calling that a pass is the v0.3 failure with better paperwork.
                NOT-APPLICABLE is available only when the product DECLARES the
                resource has no permitted principal by design, with a reason and
                an owner -- the same escape-hatch shape as 3a's `registered:`.

The check prints, per cell, WHAT MAKES ITS EVIDENCE DISCRIMINATING, or why it
cannot be.

Usage: harness/bin/check-authz-matrix.sh [--quiet]
Exit 0 = clean · 1 = findings · 2 = cannot evaluate.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import check_surface_coverage as _surface  # noqa: E402

ROOT = os.environ.get("HARNESS_ROOT") or os.path.realpath(
    os.path.join(HERE, "..", ".."))

# The PRD's role axis. It did not exist before v0.7: the template said
# "As a {role}, ..." in prose only, and nothing declared a role SET. The matrix
# needs a machine-readable axis, so this is an addition rather than a read.
# The colon may sit INSIDE the bold (`**R-1:**`) or outside it (`**R-1**:`).
# The first cut only matched the second form and silently found ZERO roles
# in a PRD that declared two -- which then read as the NOT-APPLICABLE
# path, i.e. a parse failure wearing the costume of "this product has no
# roles". A row axis that can vanish quietly is the wrong shape for an
# axis, so the mismatch now shows up as "declares no entries" instead.
ROLE_RE = re.compile(r"^\s*[-*]\s*\*\*(R-\d+):?\*\*:?\s*[:—-]?\s*([A-Za-z0-9_-]+)", re.M)
ROLES_HEADING = re.compile(r"^##\s+Roles\s*$", re.M)

DENY_STATUS = (401, 403)

# onlineMarket phase 10a (Operator ruling 2026-10-30). Some cells declare
# `deny_status: 404` -- the PRD wants 404, not 401/403, when a principal of an
# ALLOWED role reaches a resource that belongs to somebody else (another
# customer's address, another driver's run, another store's token). That denial
# is not on the role axis at all: the role is permitted, the owner is not. The
# first cut ignored the field, so the 16 cells that carry it were passed on
# their cross-role cells alone and the intra-role denial was never examined.
#
# Those observations carry the role with this suffix (`customer:other-owner`)
# so they can never be read as the role's own ALLOW observation -- `find()`
# matches the principal exactly, and a 404 matched there would fail the cell
# for the wrong reason.
OTHER_OWNER = "other-owner"


def prd_roles(path):
    """(roles, why_not). roles is None when the PRD declares no Roles section."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    except OSError:
        return None, "the PRD does not exist at %s" % path
    if not ROLES_HEADING.search(text):
        return None, "the PRD declares no `## Roles` section"
    out = []
    for m in ROLE_RE.finditer(text):
        out.append((m.group(1), m.group(2).strip().rstrip(":")))
    return out, ("the `## Roles` section declares no `- **R-n:** name` entries"
                 if not out else "")


def load_observations(root, groot):
    """[obs] from evidence/authz/*.json -- the recorded exchanges.

    Read for CONTENT. A file that exists and parses but carries no status is
    not evidence of anything, and says so.
    """
    d = os.path.join(root, groot, "evidence", "authz")
    obs, bad = [], []
    if not os.path.isdir(d):
        return obs, bad, False
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        try:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception as exc:                                # noqa: BLE001
            bad.append("%s does not parse (%r)" % (name, exc))
            continue
        missing = [k for k in ("principal", "method", "path", "status")
                   if doc.get(k) in (None, "")]
        if missing:
            bad.append("%s is missing %s -- an evidence file that carries no "
                       "status records nothing that could have differed"
                       % (name, ", ".join(missing)))
            continue
        obs.append({
            "principal": str(doc["principal"]),
            "method": str(doc["method"]).upper(),
            "path": str(doc["path"]),
            "status": int(doc["status"]),
            "file": os.path.join(groot, "evidence", "authz", name),
        })
    return obs, bad, True


def find(obs, principal, meth, path):
    for o in obs:
        if o["principal"] == principal and o["method"] == meth and o["path"] == path:
            return o
    return None


def single_principal(root):
    """(declared, reason, owner) -- does the product SAY it has one principal?

    v0.7 Task 8b found this missing. This check's own registry entry says
    "NOT-APPLICABLE is available only when the product declares it with a reason
    AND an owner" and then, one sentence later, "Fewer than two roles reports
    NOT-APPLICABLE with a reason". The declaration discipline was written for
    CELLS and abandoned for the MATRIX AS A WHOLE, in the same paragraph.

    So a product that simply never wrote a `## Roles` section got a permanent
    rc 0 from the authorization gate, on an N/A nobody declared and nobody
    signed. Measured against every other N/A in the harness on the same tree:

        check-live-verification-mobile   declared (platform ruling)   rc 2
        check-regression-mobile          declared (platform ruling)   rc 2
        check-store-readiness            declared (platform ruling)   rc 2
        check-surface-coverage/screens   declared (reason + owner)    rc 1
        check-authz-matrix               INFERRED FROM AN ABSENCE     rc 0

    It was the only one inferring N/A from a missing thing, and the only one
    returning a pass on that path.

    The declaration lives in product-surface.yaml, which is protected_always, so
    the operator writes it. It deliberately does NOT live in the PRD: the PRD is
    agent-writable at phase 2, and a silencer the agent can write is not a
    declaration, it is an off switch.
    """
    try:
        doc = hlib.load_yaml(hlib.config_path(root, "product-surface.yaml")) or {}
    except Exception:                                            # noqa: BLE001
        return False, "", ""
    p = (doc or {}).get("principals") or {}
    if str(p.get("method") or "").strip() != "single":
        return False, "", ""
    return True, str(p.get("reason") or "").strip(), str(p.get("owner") or "").strip()


def main():
    ap = argparse.ArgumentParser(prog="check-authz-matrix.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        paths = hlib.load_paths_doc(ROOT) or {}
    except Exception as exc:                                    # noqa: BLE001
        print("check-authz-matrix: cannot read the path map (%r). UNKNOWN about "
              "the INSTRUMENT (3.10)." % (exc,), file=sys.stderr)
        return 2
    groot = (paths.get("governed_root") or "").strip("/")
    d = os.path.join(ROOT, groot, "sdlc")

    errs, notes = [], []

    # ---- the row axis: roles ---------------------------------------------
    roles, why = prd_roles(os.path.join(d, "02-prd.md"))
    mpath = os.path.join(d, "05-lld", "authz-matrix.yaml")
    have_matrix = os.path.exists(mpath)

    # ---- the column axis: resources, from the 3a enumerator --------------
    # Reused rather than re-enumerated: one owner for "what does this product
    # ship", the way check_profile owns the ruling decision.
    scfg_path = hlib.config_path(ROOT, "product-surface.yaml")
    resources, surface_state = [], "missing"
    if os.path.exists(scfg_path):
        try:
            scfg = hlib.load_yaml(scfg_path) or {}
            surface_state, resources, _detail = _surface.run_enumerator(
                ROOT, groot, (scfg.get("enumerate") or {}).get("api"))
        except Exception as exc:                                # noqa: BLE001
            errs.append("the surface enumerator could not be consulted (%r). The "
                        "resource axis comes from check-surface-coverage; without "
                        "it there is no matrix. UNKNOWN (3.10)." % (exc,))

    # ---- the NOT-APPLICABLE path -----------------------------------------
    if roles is None or len(roles) < 2:
        if have_matrix:
            errs.append("an authz matrix exists at %s but the PRD declares "
                        "fewer than two roles (%s). A matrix with one row is a "
                        "checkbox." % (os.path.relpath(mpath, ROOT), why or "1 role"))
        n = 0 if roles is None else len(roles)
        declared, sp_reason, sp_owner = single_principal(ROOT)
        if declared and not (sp_reason and sp_owner):
            errs.append("product-surface.yaml declares `principals: method: "
                        "single` without %s. Putting the WHOLE authorization "
                        "matrix out of scope cannot need less than putting one "
                        "surface outside the contract, which needs both."
                        % (" and ".join([x for x, v in (("a reason", sp_reason),
                                                        ("an owner", sp_owner))
                                         if not v])))
        elif not declared:
            errs.append(
                "the product declares %d role(s) and NOBODY HAS DECLARED THAT IT "
                "NEEDS NONE (%s). An N/A inferred from a missing `## Roles` "
                "section is not a decision anyone made: it is indistinguishable "
                "from a PRD that forgot, from a parser that failed, and from a "
                "product whose authorization was never designed -- and it is the "
                "verdict nobody re-examines, because it reads like a ruling. "
                "Every other N/A in this harness traces to something a person "
                "wrote down. If this product genuinely has one principal, say so "
                "in harness/config/product-surface.yaml:  principals: {method: "
                "single, reason: <why, by design>, owner: <who is accountable>}"
                % (n, why or "no roles found"))
        # NOT APPLICABLE only when somebody declared it. Printing that phrase
        # beside a FAIL would be two verdicts side by side -- the same ambiguity
        # the COLLAPSED work was about, one check over.
        head = "NOT APPLICABLE" if declared else "NO MATRIX"
        if surface_state != "declared" or not resources:
            notes.append("%s: %d role(s) declared and no enumerated API surface. "
                         "Both axes are absent, so there is no role x resource "
                         "matrix to verdict -- stated, not passed silently (6.3). "
                         "%s" % (head, n, why))
        else:
            notes.append("%s: %d role(s) declared (%s), so every resource has the "
                         "same single principal and no cell can distinguish one "
                         "role from another. The %d enumerated resource(s) are not "
                         "a matrix without a second role."
                         % (head, n, why or "one role", len(resources)))
        if declared and sp_reason and sp_owner:
            notes.append("single principal DECLARED by %s: %s" % (sp_owner, sp_reason))
        if not args.quiet:
            print("check-authz-matrix: %s" % (groot or "?"))
            for x in notes:
                print("  note  %s" % x)
        for e in errs:
            print("  FAIL  %s" % e)
        if errs:
            # 2, not 1: "I could not evaluate this", not "I evaluated it and it
            # is wrong". The role axis is missing, so no cell was ever examined.
            return 2 if not have_matrix else 1
        return 0

    # ---- a real matrix ----------------------------------------------------
    if not have_matrix:
        print("check-authz-matrix: the PRD declares %d roles and there is no "
              "authz matrix at %s.\n  Every role x resource cell needs a "
              "verdict; with no matrix there is nothing to check against, which "
              "is UNKNOWN and not a pass (3.10)."
              % (len(roles), os.path.relpath(mpath, ROOT)), file=sys.stderr)
        return 2
    try:
        matrix = hlib.load_yaml(mpath) or {}
    except Exception as exc:                                    # noqa: BLE001
        print("check-authz-matrix: %s does not parse (%r). UNKNOWN about the "
              "INSTRUMENT (3.10)." % (mpath, exc), file=sys.stderr)
        return 2

    obs, bad, have_dir = load_observations(ROOT, groot)
    for b in bad:
        errs.append("evidence: %s" % b)
    if not have_dir:
        errs.append("no %s/evidence/authz/ directory. Every deny cell needs a "
                    "recorded exchange; a screenshot cannot carry a status, and "
                    "that is what would have differed." % groot)

    declared = {}
    for cell in (matrix.get("cells") or []):
        key = (str((cell or {}).get("method") or "").upper(),
               str((cell or {}).get("path") or ""))
        declared[key] = cell
    nopp = {}
    for e in (matrix.get("no_permitted_principal") or []):
        key = (str((e or {}).get("method") or "").upper(),
               str((e or {}).get("path") or ""))
        nopp[key] = e

    # onlineMarket phase 10a (Operator ruling 2026-10-31): resources no principal can
    # exercise live (a signed WebAuthn assertion needs an authenticator the browser
    # tooling lacks). Each is recorded with a reason and an owner; every cell of the
    # resource is then NOT APPLICABLE here, and the reason names the tests that cover it.
    nlv = {}
    for e in (matrix.get("not_live_verifiable") or []):
        nlv[(str((e or {}).get("method") or "").upper(),
             str((e or {}).get("path") or ""))] = e

    role_names = [r[1] for r in roles]
    # A suffixed label the matrix cannot place is a typo or an invented axis,
    # and either way it would otherwise be skipped without a word.
    for o in obs:
        base, sep, suffix = o["principal"].partition(":")
        if sep and (suffix != OTHER_OWNER or base not in role_names):
            errs.append("evidence: %s records principal %r. A suffixed label must "
                        "be `<role>:%s` for a role the PRD declares; anything else "
                        "is an observation no cell can read."
                        % (o["file"], o["principal"], OTHER_OWNER))
    for meth, path in resources:
        key = (meth, path)
        cell = declared.get(key)
        if not cell:
            errs.append("%s %s is a shipped resource with no row in the authz "
                        "matrix. Every role x resource cell requires a verdict; "
                        "a missing row is not an implicit allow." % (meth, path))
            continue
        e = nlv.get(key)
        if e and str(e.get("reason") or "").strip() and str(e.get("owner") or "").strip():
            notes.append("%s %s: NOT APPLICABLE for live verification (%s): %s"
                         % (meth, path, str(e.get("owner")).strip(), " ".join(str(e.get("reason")).split())))
            continue
        if e:
            errs.append("%s %s is listed under `not_live_verifiable:` without a reason or an "
                        "owner. An exemption is recorded or it is not one." % (meth, path))
        allowed = [str(x) for x in (cell.get("allow") or [])]
        unknown_roles = [r for r in allowed if r not in role_names]
        if unknown_roles:
            errs.append("%s %s allows %s, which the PRD does not declare as a "
                        "role." % (meth, path, ", ".join(unknown_roles)))
        if not allowed:
            e = nopp.get(key)
            if e and str(e.get("reason") or "").strip() and str(e.get("owner") or "").strip():
                notes.append("%s %s: NOT APPLICABLE -- declared as having no "
                             "permitted principal by design (%s)"
                             % (meth, path, str(e.get("owner")).strip()))
            else:
                errs.append(
                    "%s %s has no permitted principal, so no cell for it can be "
                    "verified: with no positive control, a denial is "
                    "indistinguishable from a broken route or a stopped server. "
                    "UNKNOWN, not passed. Declare it under "
                    "`no_permitted_principal:` with a reason and an owner if "
                    "that is by design." % (meth, path))
            continue

        # a permitting observation is the contrast every deny cell needs
        contrast = None
        for r in allowed:
            o = find(obs, r, meth, path)
            if o and 200 <= o["status"] < 400:
                contrast = o
                break
        for _role_id, role in roles:
            if role in allowed:
                o = find(obs, role, meth, path)
                if not o:
                    errs.append("%s %s / %s is declared ALLOW with no recorded "
                                "exchange." % (meth, path, role))
                elif not (200 <= o["status"] < 400):
                    errs.append("%s %s / %s is declared ALLOW but the recorded "
                                "exchange returned %d (%s)."
                                % (meth, path, role, o["status"], o["file"]))
                else:
                    notes.append("%s %s / %s ALLOW -- discriminating: status %d "
                                 "in %s" % (meth, path, role, o["status"], o["file"]))
                continue
            o = find(obs, role, meth, path)
            if not o:
                errs.append("%s %s / %s is declared DENY with no recorded "
                            "exchange. A cell with no observation is UNKNOWN."
                            % (meth, path, role))
                continue
            # `role_deny_status` (Operator ruling 3, phase 10a): the status a denied role gets
            # where the resource belongs to another session (404), accepted as its denial.
            rds = str(cell.get("role_deny_status") or "")
            if o["status"] not in DENY_STATUS + ((int(rds),) if rds.isdigit() else ()):
                errs.append("%s %s / %s is declared DENY but the recorded "
                            "exchange returned %d, which is not a denial (%s)."
                            % (meth, path, role, o["status"], o["file"]))
                continue
            if contrast is None:
                errs.append(
                    "%s %s / %s recorded %d, but NO permitted principal has a "
                    "successful exchange for the same resource. Without that "
                    "contrast the %d is equally consistent with 'this route "
                    "always denies', 'the server was down' and 'that path does "
                    "not exist' -- UNKNOWN, not a pass."
                    % (meth, path, role, o["status"], o["status"]))
                continue
            notes.append("%s %s / %s DENY -- discriminating: %d as %s vs %d as "
                         "%s on the same resource"
                         % (meth, path, role, o["status"], role,
                            contrast["status"], contrast["principal"]))

        # ---- deny_status: an allowed role, somebody else's resource -------
        # The contrast is the SAME role's own permitted exchange: what separates
        # "another owner's resource is hidden" from "this route 404s" is that
        # the role reached its own. One allowed role suffices -- the matrix's
        # `deny_status_applies_to` is prose, and for some cells it names only
        # one of the allowed roles (a driver-only caller, not tenant_admin).
        ds = cell.get("deny_status")
        if ds in (None, ""):
            continue
        try:
            ds = int(ds)
        except (TypeError, ValueError):
            errs.append("%s %s declares deny_status %r, which is not an HTTP "
                        "status." % (meth, path, ds))
            continue
        seen = False
        for r in allowed:
            o = find(obs, "%s:%s" % (r, OTHER_OWNER), meth, path)
            if not o:
                continue
            seen = True
            own = find(obs, r, meth, path)
            if o["status"] != ds:
                errs.append("%s %s / %s:%s returned %d; the matrix declares %d for "
                            "another owner's resource (%s)."
                            % (meth, path, r, OTHER_OWNER, o["status"], ds, o["file"]))
            elif not own or not (200 <= own["status"] < 400):
                errs.append("%s %s / %s:%s recorded %d, but %s has no successful "
                            "exchange of its own on the same resource. Without it "
                            "the %d is equally consistent with 'this route always "
                            "404s' -- UNKNOWN, not a pass."
                            % (meth, path, r, OTHER_OWNER, o["status"], r, ds))
            else:
                notes.append("%s %s / %s:%s DENY %d -- discriminating: %d as "
                             "another owner vs %d as %s on its own"
                             % (meth, path, r, OTHER_OWNER, ds, o["status"],
                                own["status"], r))
        if not seen:
            errs.append("%s %s declares deny_status %d (%s) and no allowed role "
                        "has a `<role>:%s` exchange. The intra-role denial is the "
                        "one this field exists for; unobserved, it is UNKNOWN."
                        % (meth, path, ds,
                           str(cell.get("deny_status_applies_to") or "no scope given"),
                           OTHER_OWNER))

    if not args.quiet:
        print("check-authz-matrix: %s -- %d role(s) x %d resource(s)"
              % (groot or "?", len(roles), len(resources)))
        for n in notes:
            print("  note  %s" % n)
        print("  limit a cell passes only when its evidence COULD HAVE DIFFERED: "
              "a deny needs a denying status AND a permitting one for another "
              "principal on the same resource. Evidence is read for CONTENT -- a "
              "file that exists and parses but carries no status records nothing.")
    for e in errs:
        print("  FAIL  %s" % e)
    if errs:
        return 1
    if not args.quiet:
        print("  PASS  every role x resource cell has a verdict backed by "
              "evidence that could have differed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
