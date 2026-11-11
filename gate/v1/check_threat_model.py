#!/usr/bin/env python3
"""check-threat-model — Phase 4 validator.

Reads the threat-model artifact off disk and checks it mechanically. It never
accepts an agent's claim that a threat model exists or is complete; it parses
the file. Registered in harness/registry.yaml as the phase-4 validator, so
`gate.sh approve 4` runs it and refuses approval on a non-zero exit.

Contract enforced (the artifact format the harness-threat-model skill emits):

  ## Trust Boundaries
  | TB-1 | <name> | <description> |

  ### SEC-001 - <title>
  - **Trust boundary:** TB-1
  - **STRIDE:** Spoofing|Tampering|Repudiation|Information Disclosure|
                Denial of Service|Elevation of Privilege
  - **Threat:** ...
  - **Mitigation requirement:** ...
  - **Owner phase:** 5 | 7 | 9
  - **Verification method:** ...

CONTENTION -- the second dimension the harness structurally could not see

  Constitution 4.3 has said since v0.5 that "contended resources carry CON-NNN
  IDs on the same terms" as SEC-NNN. Nothing read that sentence, which is 3.9
  exactly: a declaration nothing reads is not a control. This is the reader.

  Every threat model must now answer, in writing, whether the product has
  shared mutable state reached by more than one caller at a time -- and
  answering "no" is a legitimate answer that must be WRITTEN, not left to
  silence. Silence on contention is the same failure as silence on a threat.

  ## Shared resources
  | SR-1 | <resource> | <who writes it> |

  ### CON-001 - <title>
  - **Resource:** SR-1
  - **Operations:** POST /convert, GET /count
  - **Contention:** true | false
  - **Invariant:** the property that must hold no matter the interleaving
  - **Idempotency:** none | client-key | natural
  - **Owner phase:** 5 | 7
  - **Verification method:** what phase 10c must actually do

  Or, when there genuinely is none:

  ## Shared resources
  _none_ - <why: stateless request handling, no shared store, no cache>

Exit 0 = pass. Any non-zero = fail (with reasons on stdout).
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

STRIDE = {
    "spoofing", "tampering", "repudiation",
    "information disclosure", "denial of service", "elevation of privilege",
}
OWNER_PHASES = {"5", "7", "9"}
REQUIRED = ["trust boundary", "stride", "threat", "mitigation requirement",
            "owner phase", "verification method"]

# CON-NNN: the contention dimension (Constitution 4.3).
CON_OWNER_PHASES = {"5", "7"}
CON_REQUIRED = ["resource", "operations", "contention", "invariant", "idempotency",
                "owner phase", "verification method"]
IDEMPOTENCY = {"none", "client-key", "natural"}
BOOLS = {"true": True, "false": False, "yes": True, "no": False}


def parse_blocks(text, prefix="SEC"):
    """Split into <PREFIX>-NNN blocks keyed by id."""
    blocks, cur, cur_id = {}, [], None
    head = re.compile(r"^#{2,4}\s+(%s-\d{3})\b(.*)$" % prefix)
    same = re.compile(r"^#{2,4}\s+%s-" % prefix)
    for line in text.splitlines():
        m = head.match(line.strip())
        if m:
            if cur_id:
                blocks[cur_id] = "\n".join(cur)
            cur_id = m.group(1)
            cur = [line]
        elif cur_id:
            if re.match(r"^#{1,4}\s+", line.strip()) and not same.match(line.strip()):
                blocks[cur_id] = "\n".join(cur)
                cur_id, cur = None, []
            else:
                cur.append(line)
    if cur_id:
        blocks[cur_id] = "\n".join(cur)
    return blocks


def check_contention(text, errs, warns):
    """CON-NNN blocks, on the same terms as SEC-NNN (Constitution 4.3).

    The design decision that matters: a product with no shared mutable state
    must SAY SO. Allowing the section to be absent would make "we thought about
    concurrency and there is none" indistinguishable from "nobody thought about
    it", which is the state phase 4 exists to end for threats and had no
    equivalent for contention.
    """
    has_section = re.search(r"^##\s+Shared resources\s*$", text, re.I | re.M)
    if not has_section:
        errs.append("no '## Shared resources' section. Every threat model must state whether "
                    "the product has shared mutable state reached by more than one caller at "
                    "a time -- and 'none' is a legitimate answer that has to be WRITTEN. "
                    "Silence on contention is the same failure as silence on a threat "
                    "(Constitution 4.3).")
        return

    body = text[has_section.end():]
    body = re.split(r"^##\s+(?!#)", body, maxsplit=1, flags=re.M)[0]
    resources = set(re.findall(r"\b(SR-\d+)\b", body))
    declared_none = re.search(r"^\s*_?none_?\b", body.strip(), re.I | re.M) is not None

    blocks = parse_blocks(text, "CON")

    if declared_none and not resources:
        if blocks:
            errs.append("'## Shared resources' declares _none_ but %d CON-ID(s) are defined "
                        "(%s). One of the two is wrong." % (len(blocks), ", ".join(sorted(blocks))))
        elif not re.search(r"_?none_?\s*[-—:]\s*\S", body, re.I):
            errs.append("'## Shared resources' says _none_ with no reason. State WHY there is "
                        "no shared mutable state -- stateless handling, no shared store, no "
                        "cache -- so a later reader can tell the claim from an omission.")
        return

    if not resources:
        errs.append("'## Shared resources' names no SR-<n> rows and does not declare _none_.")
        return

    if not blocks:
        errs.append("%d shared resource(s) declared (%s) but no CON-IDs. Expected at least one "
                    "'### CON-001 - <title>'. A named shared resource with no contention "
                    "analysis is an unexamined race." % (len(resources), ", ".join(sorted(resources))))
        return

    covered = set()
    for cid in sorted(blocks):
        blk = blocks[cid]
        for key in CON_REQUIRED:
            val = field(blk, key.title()) or field(blk, key)
            if not val:
                errs.append("%s: missing required field '**%s:**'." % (cid, key.title()))
                continue
            low = val.strip().lower().rstrip(".")
            if key == "resource":
                refs = re.findall(r"\bSR-\d+\b", val)
                if not refs:
                    errs.append("%s: resource field names no SR-<n>." % cid)
                for ref in refs:
                    if ref not in resources:
                        errs.append("%s: references undeclared shared resource %s." % (cid, ref))
                covered.update(refs)
            elif key == "contention":
                if low.split()[0] not in BOOLS:
                    errs.append("%s: contention %r is not true or false. A maybe is an "
                                "unanswered question." % (cid, val))
            elif key == "idempotency":
                if low.split()[0] not in IDEMPOTENCY:
                    errs.append("%s: idempotency %r is not one of %s."
                                % (cid, val, sorted(IDEMPOTENCY)))
            elif key == "owner phase":
                owner = val.split()[0].strip().rstrip(".")
                if owner not in CON_OWNER_PHASES:
                    errs.append("%s: owner phase %r is not one of %s."
                                % (cid, owner, sorted(CON_OWNER_PHASES)))
            elif key == "invariant" and len(low) < 12:
                errs.append("%s: invariant %r says nothing checkable. Name the property that "
                            "must hold NO MATTER THE INTERLEAVING -- that is what phase 10c "
                            "races against." % (cid, val))

    for sr in sorted(resources - covered):
        errs.append("shared resource %s has no CON-ID covering it. A resource named as shared "
                    "and never analysed is an unexamined race." % sr)

    nums = sorted(int(c.split("-")[1]) for c in blocks)
    for a, b in zip(nums, nums[1:], strict=False):
        if b != a + 1:
            warns.append("CON-ID sequence gap between CON-%03d and CON-%03d." % (a, b))
    live = [c for c in blocks
            if (field(blocks[c], "Contention") or "").strip().lower().rstrip(".") in ("true", "yes")]
    if live:
        warns.append("%d contended resource(s) (%s) -- phase 10c must race each one."
                     % (len(live), ", ".join(sorted(live))))


def field(block, name):
    rx = re.compile(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+?)\s*$" % re.escape(name), re.I | re.M)
    m = rx.search(block)
    return m.group(1).strip() if m else None


def check(path):
    errs, warns = [], []

    if not os.path.exists(path):
        return ["threat-model artifact not found at '%s'. Phase 4 cannot be approved without it." % path], []

    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    if not text.strip():
        return ["threat-model artifact '%s' is empty." % path], []

    boundaries = set(re.findall(r"\b(TB-\d+)\b", text))
    if not boundaries:
        errs.append("no trust boundaries found. Expected at least one 'TB-<n>' row under '## Trust Boundaries'.")

    blocks = parse_blocks(text)
    if not blocks:
        errs.append("no SEC-IDs found. Expected at least one '### SEC-001 - <title>' section. "
                    "A threat model with no identified threats is not a threat model.")
        return errs, warns

    ids = sorted(blocks)
    for sid in ids:
        blk = blocks[sid]
        for key in REQUIRED:
            val = field(blk, key.title()) or field(blk, key)
            if not val:
                errs.append("%s: missing required field '**%s:**'." % (sid, key.title()))
                continue
            if key == "owner phase":
                owner = val.split()[0].strip().rstrip(".")
                if owner not in OWNER_PHASES:
                    errs.append("%s: owner phase %r is not one of %s. Every threat must be owned by the "
                                "phase that discharges it." % (sid, owner, sorted(OWNER_PHASES)))
            elif key == "stride":
                cats = [c.strip().lower() for c in re.split(r"[,/]", val) if c.strip()]
                bad = [c for c in cats if c not in STRIDE]
                if bad:
                    errs.append("%s: unrecognised STRIDE category/categories %s." % (sid, bad))
            elif key == "trust boundary":
                refs = re.findall(r"\bTB-\d+\b", val)
                if not refs:
                    errs.append("%s: trust boundary field names no TB-<n>." % sid)
                for ref in refs:
                    if boundaries and ref not in boundaries:
                        errs.append("%s: references undefined trust boundary %s." % (sid, ref))

    # id hygiene
    nums = sorted(int(s.split("-")[1]) for s in ids)
    if nums and nums[0] != 1:
        warns.append("SEC-IDs start at %03d rather than 001." % nums[0])
    for a, b in zip(nums, nums[1:], strict=False):
        if b != a + 1:
            warns.append("SEC-ID sequence gap between SEC-%03d and SEC-%03d." % (a, b))

    # coverage: every declared boundary should carry at least one threat
    covered = set()
    for _sid, blk in blocks.items():
        v = field(blk, "Trust boundary") or ""
        covered.update(re.findall(r"\bTB-\d+\b", v))
    for tb in sorted(boundaries - covered):
        errs.append("trust boundary %s has no SEC-ID covering it. STRIDE is performed per boundary; "
                    "an uncovered boundary is an unexamined boundary." % tb)

    check_contention(text, errs, warns)

    return errs, warns


def main():
    ap = argparse.ArgumentParser(
        prog="check-threat-model.sh", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", default=None,
                    help="path to the threat-model artifact (default: <governed_root>/sdlc/04-threat-model.md)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    path = args.path
    if not path:
        try:
            paths_doc = hlib.load_paths_doc(root)
            groot = paths_doc.get("governed_root") or ""
        except Exception:
            groot = ""
        path = os.path.join(root, groot, "sdlc", "04-threat-model.md")

    errs, warns = check(path)

    if not args.quiet:
        print("check-threat-model: %s" % path)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            with open(path, "r", encoding="utf-8") as fh:
                n = len(parse_blocks(fh.read()))
            print("  PASS  %d SEC-ID(s), all with trust boundary, STRIDE category, "
                  "mitigation, owner phase and verification method." % n)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
