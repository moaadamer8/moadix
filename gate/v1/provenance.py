#!/usr/bin/env python3
"""provenance — an artifact records the tree it describes and the claim it supports.

Constitution 4.5. Two questions no evidence check could previously answer:

  Does this artifact still describe the current tree?   (C11, artifact-sha-binding)
  Was it produced for the claim it is cited for?        (C13, evidence-provenance)

Both are the same missing idea -- an artifact is not self-describing -- so one
sidecar carries both.

THE CASES THAT FORCED THIS

  A PASSING 10a report sat in the approval queue across two rounds of fixes,
  describing a binary that no longer existed. Its screenshots opened cleanly:
  they were real captures of a real past build, so every integrity check the
  harness had succeeded on them.

  10a QA screenshots would have satisfied phase 11b's store-screenshot check.
  The 11b session declined on the merits -- "not composed for a store listing"
  -- but the GATE could not tell, so the next session might not decline.

  A green test named "SF-1 handleDeepLink rejects an unrecognized from
  parameter" asserted a claim about the product in a build where the binding
  that broke it had been compiled out.

THE SIDECAR

  <artifact>.provenance.yaml, beside the artifact:

    produced_by:  harness-live-verify-mobile      # skill or script
    produced_for:                                 # one or more claim IDs
      - "10a:US-001:ios"
      - "10a:offline"
    method:       "xcrun simctl io screenshot"
    source_sha:   9f9fb3a1c...                    # HEAD at capture
    source_dirty: true                            # uncommitted changes present
    captured_at:  "2026-09-01T12:31:22Z"

WHO STAMPS IT

  The PRODUCING skill, never the checking one. A checker that writes provenance
  for an artifact it is about to validate is self-certification (3.1), and it
  would make the whole mechanism a formality. `stamp()` refuses to run from a
  module whose name begins with `check_`; that is a guardrail, not a security
  boundary -- the real protection is that checkers have no reason to import it.

MULTIPLE CLAIMS ARE LEGITIMATE

  One offline capture honestly evidences US-001 AC-4 and the `offline` mandatory
  check: one observation, two requirements. So `produced_for` is a LIST. What is
  forbidden is SILENT reuse -- citing an artifact for a claim that is not in its
  list. `cite_ok()` is the whole rule.

DEGRADATION

  No sidecar is UNKNOWN, not INVALID. Phase validators warn; the release gate
  blocks. A tree with no git is UNKNOWN too. Bootstrapping a new product must
  work, and a control that cannot be adopted incrementally will not be adopted.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

SIDECAR_SUFFIX = ".provenance.yaml"

# A claim id is  <phase>:<id>[:<qualifier>]  e.g. 10a:US-001:ios, 9:SEC-004,
# 11b:screenshots-ios, 10c:CON-001. The phase prefix is what lets a checker ask
# "was this made for MY phase" without knowing anything else about the claim.
CLAIM_RE = re.compile(r"^[0-9]{1,2}[a-z]?:[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9._-]+)?$")

UNKNOWN = "unknown"


def sidecar_path(artifact_path):
    return artifact_path + SIDECAR_SUFFIX


def read(artifact_path):
    """Provenance for an artifact, or None when it has none (UNKNOWN)."""
    p = sidecar_path(artifact_path)
    if not os.path.exists(p):
        return None
    try:
        doc = hlib.load_yaml(p) or {}
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    pf = doc.get("produced_for")
    if isinstance(pf, str):
        pf = [pf]
    doc["produced_for"] = [str(x) for x in (pf or [])]
    return doc


def stamp(artifact_path, produced_by, produced_for, method, root=None):
    """Write the sidecar. Called by the PRODUCING skill, never by a checker.

    Returns the sidecar path. Raises on misuse -- a malformed claim id or a
    checker calling it are both bugs worth failing loudly, at capture time,
    where the author can fix them.
    """
    caller = os.path.basename(getattr(sys.modules.get("__main__"), "__file__", "") or "")
    if caller.startswith("check_") or caller.startswith("check-"):
        raise RuntimeError(
            "provenance.stamp() called from %r. A checker must never stamp provenance for "
            "an artifact it validates -- that is self-certification (Constitution 3.1). "
            "The producing skill stamps; the checker only reads." % caller)

    if isinstance(produced_for, str):
        produced_for = [produced_for]
    produced_for = [str(x).strip() for x in (produced_for or []) if str(x).strip()]
    if not produced_for:
        raise ValueError("produced_for must name at least one claim this artifact supports")
    bad = [c for c in produced_for if not CLAIM_RE.match(c)]
    if bad:
        raise ValueError("malformed claim id(s) %r; expected <phase>:<id>[:<qualifier>], "
                         "e.g. 10a:US-001:ios" % bad)

    root = root or hlib.project_root()
    sha = hlib.git_head_sha(root)
    dirty = hlib.git_tree_dirty(root)

    doc = {
        "produced_by": str(produced_by),
        "produced_for": produced_for,
        "method": str(method),
        "source_sha": sha or UNKNOWN,
        # None (unknown) is recorded as the string, never coerced to false --
        # "we could not tell" and "it was clean" must not look the same.
        "source_dirty": UNKNOWN if dirty is None else bool(dirty),
        "captured_at": _now(),
    }
    out = sidecar_path(artifact_path)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# Written by provenance.stamp() at capture time. Do not hand-edit:\n"
                 "# a checker reads this to decide whether the artifact beside it may be\n"
                 "# cited for a given claim (Constitution 4.5).\n")
        fh.write(hlib.dump_yaml(doc) + "\n")
    return out


def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cite_ok(prov, claim):
    """May this artifact be cited for `claim`?

    (True, note)   -- declared, or provenance unknown (degraded, caller decides)
    (False, why)   -- provenance exists and does NOT name this claim: silent reuse
    """
    if prov is None:
        return True, UNKNOWN
    declared = prov.get("produced_for") or []
    if not declared:
        # An empty list is not "no opinion" -- stamp() refuses to write one, so
        # a sidecar with none has been truncated, hand-edited or corrupted. Say
        # that, rather than reporting it as a claim mismatch.
        return False, ("its provenance sidecar declares no produced_for at all (truncated or "
                       "hand-edited?). Re-stamp the artifact at capture time.")
    if claim in declared:
        return True, "declared"
    # phase-level match: an artifact stamped 11b:screenshots-ios may be cited by
    # a claim the checker phrases differently, PROVIDED the phase agrees. This is
    # deliberately narrow -- it stops a 10a capture satisfying an 11b check,
    # which is the case that motivated the rule, without demanding that every
    # checker and every skill agree on claim spelling.
    cphase = claim.split(":", 1)[0]
    if any(d.split(":", 1)[0] == cphase for d in declared):
        return True, "phase-match"
    return False, ("produced_for %s does not include %r, and no declared claim is even from "
                   "the same phase. Citing an artifact for a claim it was not produced for is "
                   "silent reuse (Constitution 4.5)." % (declared, claim))


def tree_status(root, prov):
    """Does this artifact still describe the current tree?

    ('ok', note) | ('unknown', why) | ('stale', why)
    """
    if prov is None:
        return UNKNOWN, "no provenance sidecar"
    sha = str(prov.get("source_sha") or "").strip()
    if not sha or sha == UNKNOWN:
        return UNKNOWN, "provenance records no source_sha"
    anc = hlib.git_is_ancestor(root, sha)
    if anc is None:
        return UNKNOWN, ("source_sha %s is not an object in this repository (no git, or a "
                         "reverted/rebased commit)" % sha[:12])
    if not anc:
        return "stale", ("source_sha %s is NOT an ancestor of HEAD: this artifact describes a "
                         "tree that is not in this history" % sha[:12])
    return "ok", "source_sha %s is an ancestor of HEAD" % sha[:12]


def is_dirty(prov):
    """True / False / None(unknown) for the capture-time working tree."""
    if prov is None:
        return None
    v = prov.get("source_dirty")
    if isinstance(v, bool):
        return v
    return None


def audit(root, groot, citations, strict_unknown=False):
    """Audit a set of evidence citations. Returns (errs, warns, notes).

    ONE implementation, called by every validator that cites evidence. Each
    caller supplies `citations` as [(claim_id, repo_relative_path), ...] and
    gains about five lines. A per-validator copy of this logic is how two
    parsers drift apart -- this file already carries three findings caused by
    exactly that.

    `strict_unknown` is the release gate's switch: during a phase, missing
    provenance WARNs so a product can adopt the mechanism incrementally; at
    release it is an error, because "we cannot tell what this evidence
    describes" is not a basis for shipping.

    Three findings, in order of severity:

      SILENT REUSE    an artifact cited for a claim its provenance does not
                      declare. The 11b case: real 10a screenshots would have
                      satisfied the store-asset check, and only a session's
                      judgement stopped it.
      STALE TREE      source_sha is not an ancestor of HEAD -- the artifact
                      describes a tree not in this history.
      DUPLICATE BYTES two DIFFERENT paths with identical content, cited for
                      different claims, without a declared `duplicate_of`.
                      One artifact cited twice is fine and common; two copies
                      pretending to be independent evidence is not.
    """
    errs, warns, notes = [], [], []
    seen = {}          # digest -> (claim, relpath)
    unknown = []       # (relpath, claim, why) -- reported once, in aggregate

    for claim, rel in citations:
        full = os.path.join(root, groot, rel) if groot and not rel.startswith(groot) \
            else os.path.join(root, rel)
        if not os.path.exists(full):
            full_alt = os.path.join(root, rel)
            full = full_alt if os.path.exists(full_alt) else full
        if not os.path.exists(full):
            continue          # existence is the caller's own check; not ours to duplicate

        prov = read(full)

        ok, why = cite_ok(prov, claim)
        if not ok:
            errs.append("evidence %s is cited for %s but %s" % (rel, claim, why))

        st, swhy = tree_status(root, prov)
        if st == "stale":
            errs.append("evidence %s: %s. It cannot support %s." % (rel, swhy, claim))
        elif st == UNKNOWN:
            # Collected, not reported per citation. One sentence repeated
            # twenty-two times with a different filename in it is not more
            # information; the aggregate below still names every file.
            unknown.append((rel, claim, swhy))

        if is_dirty(prov):
            (errs if strict_unknown else notes).append(
                "evidence %s was captured from a DIRTY working tree; it may not correspond "
                "to any commit.%s" % (rel, "" if not strict_unknown else
                                      " A release may not rest on it."))

        d = digest(full)
        if d:
            prev = seen.get(d)
            if prev and prev[1] != rel:
                declared = (prov or {}).get("duplicate_of")
                pprov = read(os.path.join(root, groot, prev[1])) or {}
                if declared != prev[1] and pprov.get("duplicate_of") != rel:
                    errs.append(
                        "evidence %s and %s are byte-identical but are cited as separate "
                        "evidence (%s vs %s). Two copies are not two observations. If the "
                        "duplication is deliberate, declare `duplicate_of` in the provenance "
                        "sidecar." % (rel, prev[1], claim, prev[0]))
            elif not prev:
                seen[d] = (claim, rel)

    if unknown:
        shown = ", ".join(sorted({r for r, _c, _w in unknown})[:8])
        n_files = len({r for r, _c, _w in unknown})
        if n_files > 8:
            shown += " (+%d more)" % (n_files - 8)
        if strict_unknown:
            errs.append(
                "%d citation(s) across %d file(s) have UNKNOWN provenance: %s. The release gate "
                "cannot accept evidence whose origin it cannot establish (Constitution 4.5). "
                "Re-capture with provenance.stamp(), or waive per file with a reason and an "
                "approver." % (len(unknown), n_files, shown))
        else:
            warns.append(
                "%d citation(s) across %d file(s) have no provenance sidecar: %s. Stamp them at "
                "capture time with provenance.stamp()." % (len(unknown), n_files, shown))
            notes.append("unstamped evidence passes NOW and BLOCKS at the release gate.")
    return errs, warns, notes


def verifies_map(registry_doc):
    """{phase_label: [glob, ...]} from registry `verifies:`.

    A phase's own allow-globs are the wrong question: phase 10a verifies phase
    7's OUTPUT, not its own report. `verifies:` is what each validator declares
    it actually looks at, so that is what an approval's freshness is measured
    against.
    """
    out = {}
    for comp in ((registry_doc or {}).get("components") or []):
        if str(comp.get("kind")) != "validator" or str(comp.get("status")) != "active":
            continue
        for g in (comp.get("verifies") or []):
            out.setdefault(str(comp.get("phase")), set()).add(str(g))
    return {k: sorted(v) for k, v in out.items()}


def approval_status(root, phase, specs):
    """Does an APPROVED phase still describe the tree it approved?

    `specs` are repo-relative pathspecs (the phase's `verifies:` globs prefixed
    with the governed root). Returns (state, detail):

      'current'  every verified path is unchanged since the approval commit
      'stale'    at least one changed -- the approval describes a tree that is
                 no longer there. THE motivating case: a PASSING 10a report sat
                 in the approval queue across two rounds of fixes, describing a
                 binary that no longer existed.
      'dirty'    nothing committed has changed, but verified paths have
                 uncommitted edits, so the approval commit is not what is there
      'unknown'  no approval_sha, or the commit is not in this repository.
                 UNKNOWN is never coerced to 'current': the caller decides
                 whether it degrades or blocks.
    """
    sha = str((phase or {}).get("approval_sha") or "").strip()
    if not sha or sha == UNKNOWN:
        return UNKNOWN, "the approval records no commit"
    changed = hlib.git_paths_changed_since(root, sha, specs)
    if changed is None:
        return UNKNOWN, ("cannot compare approval commit %s against HEAD (no git, or that "
                         "commit is not an object in this repository)" % sha[:12])
    if changed:
        shown = ", ".join(changed[:5])
        if len(changed) > 5:
            shown += " (+%d more)" % (len(changed) - 5)
        return "stale", ("%d path(s) it verifies changed since %s: %s"
                         % (len(changed), sha[:12], shown))
    if hlib.git_tree_dirty(root, specs):
        return "dirty", ("paths it verifies carry uncommitted changes; approval commit %s does "
                         "not describe what is on disk" % sha[:12])
    return "current", "approval commit %s still describes every path it verifies" % sha[:12]


def digest(path):
    """SHA-256 of a file, for the duplicate-evidence check. None if unreadable."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None
