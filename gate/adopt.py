"""ADOPT <code>: product settings the agent proposes, adopted by the operator (ruling 3, increment 3).

The agent may not write .sdlc/. It writes PROPOSALS instead, under
<repo>/.sdlc-proposals/ (always writable, in every phase):

  .sdlc-proposals/config/<name>.yaml   -> .sdlc/config/<name>.yaml   (whole file)
       <name> is one of the product config files the validators read
       (gate/v1/hlib.PRODUCT_CONFIG: product-surface, product-tests, ...)
  .sdlc-proposals/product.yaml         -> merged into .sdlc/product.yaml,
       top-level keys platform, size, app_run, test_targets, park only
       (the product id, created and path_map are never proposable)

The operator types `ADOPT <code>`. The gate validates every proposal (allowed
name, regular file, size, YAML that parses to a mapping, product keys allowed,
`park:` well formed), records ONE signed ledger line naming every adopted file
with the sha256 of the proposal and of the resulting .sdlc/ file, then writes
.sdlc/ and removes the proposals. Nothing is written if validation or the code
fails. STATUS afterwards checks that every adopted .sdlc/ file still has the
sha256 the ledger recorded, so a later hand edit shows as drift.
This replaces editing .sdlc/config and park: in Terminal.
"""
import base64
import hashlib
import os
import re

from . import state

DIR = ".sdlc-proposals"
PRODUCT_KEYS = ("platform", "size", "app_run", "test_targets", "park")
MAX_FILES = 20
MAX_BYTES = 65536
INLINE_LIMIT = 6000  # proposal text is stored in the ledger line when all of it fits


class ProposalError(Exception):
    pass


def _hlib():
    from .v1 import hlib
    return hlib


def proposals_dir(root):
    return os.path.join(root, DIR)


def pending(root):
    """Relative paths of every file under .sdlc-proposals/ (empty list if none)."""
    d = proposals_dir(root)
    out = []
    if not os.path.isdir(d):
        return out
    for dp, dns, fns in os.walk(d):
        dns.sort()
        for f in sorted(fns):
            out.append(os.path.relpath(os.path.join(dp, f), d))
    return out


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _blocks(text):
    """{top-level key: (start, end)} line ranges of a block YAML text."""
    lines = text.splitlines(True)
    out, cur = {}, None
    for i, ln in enumerate(lines):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", ln)
        if m:
            if cur:
                out[cur[0]] = (cur[1], i)
            cur = (m.group(1), i)
        elif cur and ln.strip() and not ln.startswith((" ", "\t", "#")):
            out[cur[0]] = (cur[1], i)
            cur = None
    if cur:
        out[cur[0]] = (cur[1], len(lines))
    # trailing comment/blank lines belong to the next block, not this one
    for k, (a, b) in list(out.items()):
        while b > a + 1 and (not lines[b - 1].strip() or lines[b - 1].lstrip().startswith("#")):
            b -= 1
        out[k] = (a, b)
    return out, lines


def merge_product(current, proposal, keys):
    """current product.yaml text with each `keys` block replaced by the proposal's block."""
    pblocks, plines = _blocks(proposal)
    cblocks, clines = _blocks(current)
    for k in keys:
        a, b = pblocks[k]
        new = [ln if ln.endswith("\n") else ln + "\n" for ln in plines[a:b]]
        if k in cblocks:
            ca, cb = cblocks[k]
            clines[ca:cb] = new
            cblocks, clines = _blocks("".join(clines))
        else:
            if clines and not clines[-1].endswith("\n"):
                clines[-1] += "\n"
            clines += new
    return "".join(clines)


def _validate_park(park):
    """Same rules PARK applies when it runs (opcmd._park_spec), checked at adoption."""
    if park is None:
        return
    if not isinstance(park, dict):
        raise ProposalError("product.yaml: park must be a mapping with stop: and counts:")
    from .opcmd import PARK_VERBS
    stop = park.get("stop")
    counts = park.get("counts")
    for what, argv in [("park.stop", stop)] + [("park.counts.%s" % n, v) for n, v in (counts or {}).items()]:
        if not isinstance(argv, list) or not argv or not all(isinstance(a, (str, int)) for a in argv):
            raise ProposalError("product.yaml: %s must be a non-empty argv list" % what)
        if str(argv[0]) not in PARK_VERBS:
            raise ProposalError("product.yaml: %s starts with %r; PARK only runs %s" % (
                what, argv[0], " or ".join(PARK_VERBS)))
    if not isinstance(counts, dict) or not counts:
        raise ProposalError("product.yaml: park.counts must declare at least one count")
    for n in counts:
        if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", str(n)):
            raise ProposalError("product.yaml: park.counts name %r is not a plain identifier" % n)


def plan(root):
    """Validate every proposal. Returns [(rel, target_abs, new_bytes, info)] or raises ProposalError."""
    hlib = _hlib()
    d = proposals_dir(root)
    rels = pending(root)
    if not rels:
        raise ProposalError("there is nothing to adopt: %s/ is empty or missing" % DIR)
    if len(rels) > MAX_FILES:
        raise ProposalError("%d files proposed; at most %d per ADOPT" % (len(rels), MAX_FILES))
    out = []
    for rel in rels:
        full = os.path.join(d, rel)
        st = os.lstat(full)
        if not os.path.isfile(full) or os.path.islink(full) or st.st_nlink > 1:
            raise ProposalError("%s/%s is not a plain file (links are refused)" % (DIR, rel))
        if st.st_size > MAX_BYTES:
            raise ProposalError("%s/%s is %d bytes; the limit is %d" % (DIR, rel, st.st_size, MAX_BYTES))
        with open(full, "rb") as f:
            raw = f.read()
        try:
            text = raw.decode("utf-8")
            doc = hlib.parse_yaml(text)
        except Exception as e:
            raise ProposalError("%s/%s is not valid YAML (%s)" % (DIR, rel, e)) from None
        if not isinstance(doc, dict) or not doc:
            raise ProposalError("%s/%s must be a non-empty YAML mapping" % (DIR, rel))
        parts = rel.split(os.sep)
        if len(parts) == 2 and parts[0] == "config" and parts[1] in hlib.PRODUCT_CONFIG:
            target = os.path.join(root, state.SDLC, "config", parts[1])
            out.append((rel, target, raw, {"kind": "config"}))
        elif rel == "product.yaml":
            bad = sorted(k for k in doc if k not in PRODUCT_KEYS)
            if bad:
                raise ProposalError("product.yaml may only set %s; refused key(s): %s" % (
                    ", ".join(PRODUCT_KEYS), ", ".join(bad)))
            if "park" in doc:
                _validate_park(doc["park"])
            target = state.paths(root)["product"]
            with open(target, encoding="utf-8") as f:
                current = f.read()
            merged = merge_product(current, text, list(doc))
            after = hlib.parse_yaml(merged) or {}
            before = hlib.parse_yaml(current) or {}
            for k in doc:
                if after.get(k) != doc[k]:
                    raise ProposalError("product.yaml: merging %s did not reproduce the proposed value" % k)
            for k in before:
                if k not in doc and after.get(k) != before.get(k):
                    raise ProposalError("product.yaml: merging would change %s, which was not proposed" % k)
            if state.yamlite.parse_flat(merged).get("product") != state.yamlite.parse_flat(current).get("product"):
                raise ProposalError("product.yaml: the merge would change the product id")
            out.append((rel, target, merged.encode("utf-8"), {"kind": "product", "keys": sorted(doc)}))
        else:
            raise ProposalError("%s/%s is not adoptable. Allowed: product.yaml (keys %s) and config/<name> for %s" % (
                DIR, rel, ", ".join(PRODUCT_KEYS), ", ".join(sorted(hlib.PRODUCT_CONFIG))))
    return out


def payload(root, items):
    files = []
    inline = sum(os.path.getsize(os.path.join(proposals_dir(root), r)) for r, _t, _n, _i in items)
    for rel, target, new, info in items:
        with open(os.path.join(proposals_dir(root), rel), "rb") as f:
            prop = f.read()
        e = {"proposal": "%s/%s" % (DIR, rel), "target": os.path.relpath(target, root), "kind": info["kind"],
             "proposal_sha256": _sha(prop), "result_sha256": _sha(new), "bytes": len(prop)}
        if info.get("keys"):
            e["keys"] = info["keys"]
        if inline <= INLINE_LIMIT:
            e["content_b64"] = base64.b64encode(prop).decode()
        files.append(e)
    return {"files": files}


def apply(root, items):
    for _rel, target, new, _info in items:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".adopt.tmp"
        with open(tmp, "wb") as f:
            f.write(new)
        os.replace(tmp, target)
    for rel, _t, _n, _i in items:
        os.unlink(os.path.join(proposals_dir(root), rel))
    for dp, _dns, _fns in sorted(os.walk(proposals_dir(root)), key=lambda x: -len(x[0])):
        if not os.listdir(dp):
            os.rmdir(dp)


def drift(root, entries):
    """Problems: an adopted .sdlc/ file whose bytes differ from what its last ADOPT recorded."""
    last = {}
    for e in entries:
        if e["action"].split(" ", 1)[0] == "ADOPT":
            for f in state.decode_payload(e).get("files") or []:
                last[f.get("target")] = (f.get("result_sha256"), e["seq"])
    out = []
    for target, (sha, seq) in sorted(last.items()):
        p = os.path.join(root, target)
        try:
            with open(p, "rb") as f:
                cur = _sha(f.read())
        except OSError:
            cur = None
        if cur != sha:
            out.append("%s differs from what ADOPT recorded at ledger seq %d (%s)" % (
                target, seq, "missing" if cur is None else "edited outside ADOPT"))
    return out
