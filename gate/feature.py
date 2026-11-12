"""Feature cycles (increment 6; DESIGN.md Amendment 2).

A feature cycle adds to a product whose baseline is approved (released at phase
11, or onboarded at phase B). It runs the same 16 phases, scoped to the feature.
The agent writes the feature's documents in sdlc/features/<id>/, named like the
product's (00-brd.md, 02-prd.md, 04-threat-model.md, ...), as ADDITIONS:

  00  BRD additions: new business goals (BG-n), the feature's size
  02  PRD additions: new stories (US-n) with EARS acceptance criteria, each
      tracing to a product or feature goal
  03  HLD changes        04  new SEC-IDs (and trust boundaries)
  05  LLD changes        06 UX       6b provisioning     7 tasks
  8   test report        9 security report   10a/b/c verification   11 release

The product's approved documents stay frozen (the path map denies them during a
feature). This module checks each addition against them:

  traceability      every new story traces to a goal that exists (product or
                    feature); every task to a feature story; every feature
                    story has a task, an LLD mention and a test-report line
  no conflicting    a feature never re-uses an ID the product already defines
  SEC-IDs (or IDs)  (BG, US, SEC, TB, T); a new SEC-ID names an existing trust
                    boundary and a mitigation
  no contradicted   an acceptance criterion whose EARS trigger matches an approved
  requirements      one but whose response negates it ("shall X" vs "shall not
                    X"), or an addition that says it supersedes, replaces or
                    removes an approved requirement, is refused: approved
                    requirements are frozen

Approving the feature's phase 11 MERGES the additions of phases 0 to 6b into the
product's documents (each appended under a "Feature <id>" heading; LLD files are
copied into sdlc/05-lld/). The plan, with every file's sha256 before and after,
is in the APPROVE line's payload (the ledger records the merge); the gate then
writes the files and commits them. Tasks, test and verification documents stay in
the feature's folder as its frozen record.
"""
import hashlib
import os
import re
import subprocess

from . import pathmap, state

# Phase label -> the feature document glob for that phase (inside sdlc/features/<id>/): the
# phase's own document glob (the first entry of its path-map allow list, sdlc/NN-*.md).
DOCS = {label: pats[0][len("sdlc/"):] for _i, label, _n, pats in pathmap.PHASES}
# Documents merged into the product at the feature's Release approval: requirements, design,
# threats, UX and provisioning (every phase before Tasks and Implementation).
_TASKS = next(i for i, _l, name, _p in pathmap.PHASES if name == "Tasks and Implementation")
MERGED = tuple(label for i, label, _n, _p in pathmap.PHASES if i < _TASKS)
# Optional: Research (may be collapsed by size) and Store Release (store products only).
OPTIONAL = tuple(label for _i, label, name, _p in pathmap.PHASES if name in ("Research", "Store Release"))
NEGATION = re.compile(r"\b(?:shall\s+not|shall\s+never|must\s+not|will\s+not)\b", re.I)
SUPERSEDES = re.compile(r"^\s*[-*]\s*\*\*(?:Supersedes|Replaces|Removes|Overrides|Contradicts):?\*\*\s*(.+)$",
                        re.I | re.M)
ID_KINDS = ("BG", "US", "NFR", "SEC", "TB", "T", "CON", "SR")
GATE_AUTHOR = ["-c", "user.name=MOADIX gate", "-c", "user.email=gate@moadix.invalid", "-c", "commit.gpgsign=false"]


class FeatureError(Exception):
    pass


def _hl():
    from .v1 import check_handoff
    return check_handoff


def folder(fid):
    return "%s/%s" % (pathmap.FEATURES_DIR, fid)


def _glob(root, rel_dir, pattern):
    d = os.path.join(root, rel_dir)
    if not os.path.isdir(d):
        return []
    rx = pathmap.glob_to_re(pattern)
    return sorted("%s/%s" % (rel_dir, f) for f in os.listdir(d) if rx.match(f) and os.path.isfile(os.path.join(d, f)))


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
        return re.sub(r"<!--.*?-->", "", f.read(), flags=re.S)


def product_doc(root, label):
    """The product's document for a phase (first sdlc/NN-*.md), or None."""
    hits = _glob(root, "sdlc", DOCS[label])
    return hits[0] if hits else None


def feature_doc(root, fid, label):
    hits = _glob(root, folder(fid), DOCS[label])
    return hits[0] if hits else None


def _ids(text, kind):
    """IDs of one kind DEFINED in a document: headings (### US-001) and first table cells (| BG-1 |)."""
    out = set(re.findall(r"^#{2,4}\s+(%s-\d+)\b" % kind, text, re.M))
    out |= set(re.findall(r"^\|\s*(%s-\d+)\s*\|" % kind, text, re.M))
    return out


def product_text(root):
    """All of the product's approved documents (sdlc/*.md, not the feature folders)."""
    sd = os.path.join(root, "sdlc")
    if not os.path.isdir(sd):
        return ""
    return "\n".join(_read(root, "sdlc/" + f) for f in sorted(os.listdir(sd))
                     if f.endswith(".md") and os.path.isfile(os.path.join(sd, f)))


def _ears_parts(ac):
    """(trigger, response, negated) of an EARS sentence, normalised; None if not EARS-shaped."""
    # Parenthetical asides (citations such as "(code: src/app.js:4)", notes) are not part of
    # the requirement: "shall refuse it (code: x:4)" and "shall not refuse it" contradict.
    s = " ".join(re.sub(r"\([^)]*\)", " ", ac).strip().rstrip(".").lower().split())
    m = re.match(r"^(?:(when|while|where|if)\s+(.+?),\s*(?:then\s+)?)?the\s+(.+?)\s+(shall\s+not|shall\s+never|shall)\s+"
                 r"(.+)$", s)
    if not m:
        return None
    trigger = "%s %s" % (m.group(1) or "", re.sub(r"[^a-z0-9 ]", "", m.group(2) or "").strip())
    response = re.sub(r"[^a-z0-9 ]", "", m.group(5)).strip()
    response = re.sub(r"^(?:not|never)\s+", "", response)
    negated = m.group(4) != "shall" or bool(re.match(r"^(?:not|never)\b", m.group(5)))
    return (trigger.strip(), m.group(3).strip(), response, negated)


def acceptance(text):
    """[(story id, ac id, sentence)] from a PRD text."""
    hl = _hl()
    out = []
    blk = {}
    blk.update(hl.blocks(text, "US"))
    blk.update(hl.blocks(text, "NFR"))
    for sid, b in blk.items():
        for m in re.finditer(r"^\s*[-*]\s*\*\*(AC-\d+):?\*\*\s*(.+?)\s*$", b, re.M):
            out.append((sid, m.group(1), m.group(2)))
    return out


def contradictions(product_prd, feature_prd):
    """[(feature ref, product ref, why)] for additions that contradict approved requirements."""
    out = []
    approved = {}
    for sid, ac, sent in acceptance(product_prd):
        parts = _ears_parts(sent)
        if parts:
            approved.setdefault((parts[0], parts[1], parts[2]), []).append(("%s/%s" % (sid, ac), parts[3], sent))
    for sid, ac, sent in acceptance(feature_prd):
        parts = _ears_parts(sent)
        if not parts:
            continue
        for pref, neg, _psent in approved.get((parts[0], parts[1], parts[2]), []):
            if neg != parts[3]:
                out.append(("%s/%s" % (sid, ac), pref, "under the same condition it says the %s %s, where the "
                            "approved requirement says it %s" % (parts[1], "shall NOT" if parts[3] else "shall",
                                                                 "shall NOT" if neg else "shall")))
    known = {"%s/%s" % (s, a) for s, a, _x in acceptance(product_prd)} | set(re.findall(
        r"^#{2,4}\s+((?:US|NFR)-\d+)\b", product_prd, re.M))
    for m in SUPERSEDES.finditer(feature_prd):
        for ref in re.findall(r"\b(?:US|NFR)-\d+(?:/AC-\d+)?\b", m.group(1)):
            if ref in known:
                out.append(("(declared)", ref, "the addition declares that it supersedes/replaces/removes it"))
    return out


def check_phase(root, fid, label):
    """(errors, notes) for the feature's documents up to and including `label`, against the
    product's approved documents. Cumulative: an earlier, approved addition is re-checked
    because a later one may now conflict with it."""
    hl = _hl()
    errs, notes = [], []
    labels = pathmap.LABELS
    upto = labels[:labels.index(label) + 1]
    prod = product_text(root)
    fdocs = {lab: feature_doc(root, fid, lab) for lab in labels}
    ftext = {lab: _read(root, p) if p else "" for lab, p in fdocs.items()}
    for lab in upto:
        if not fdocs[lab] and lab not in OPTIONAL:
            errs.append("phase %s: no feature document %s/%s (the feature's additions for this phase)" % (
                lab, folder(fid), DOCS[lab]))
    allf = "\n".join(ftext.values())
    # no conflicting IDs (SEC-IDs and every other ID the product defines)
    for kind in ID_KINDS:
        clash = sorted(_ids(allf, kind) & _ids(prod, kind))
        if clash:
            errs.append("ID conflict: the feature defines %s, which the product's approved documents already define; "
                        "new %s IDs must be new" % (", ".join(clash), kind))
    goals = _ids(prod, "BG") | _ids(ftext["0"], "BG")
    if "0" in upto and fdocs["0"] and \
            not re.search(r"^\s*[-*]\s*\*\*Size:?\*\*:?\s*[SML]\b", ftext["0"], re.M | re.I):
        errs.append("%s: no '- **Size:** S|M|L' (the feature's size decides what its cycle may collapse)" % fdocs["0"])
    fstories = {}
    if "2" in upto and fdocs["2"]:
        fstories.update(hl.blocks(ftext["2"], "US"))
        fstories.update(hl.blocks(ftext["2"], "NFR"))
        if not fstories:
            errs.append("%s: no stories ('### US-nnn — <title>')" % fdocs["2"])
        for sid, blk in sorted(fstories.items()):
            g = hl.field(blk, "BRD goal") or ""
            refs = re.findall(r"\bBG-\d+\b", g)
            if not refs:
                errs.append("%s: no '**BRD goal:**' naming a BG-n (traceability)" % sid)
            for r in refs:
                if r not in goals:
                    errs.append("%s traces to %s, which neither the product nor the feature BRD defines" % (sid, r))
            acs = re.findall(r"^\s*[-*]\s*\*\*AC-\d+:?\*\*\s*(.+?)\s*$", blk, re.M)
            if not acs:
                errs.append("%s: no acceptance criteria" % sid)
            for i, ac in enumerate(acs, 1):
                ok, why = hl.is_ears(ac)
                if not ok:
                    errs.append("%s AC-%d is not EARS (%s)" % (sid, i, why))
        prd = "\n".join(_read(root, p) for p in _glob(root, "sdlc", DOCS["2"]))
        for fref, pref, why in contradictions(prd, ftext["2"]):
            errs.append("CONTRADICTION: %s contradicts the approved requirement %s (%s). Approved requirements "
                        "are frozen; a feature may add to them, never contradict them" % (fref, pref, why))
    if "4" in upto and fdocs["4"]:
        tbs = _ids(prod, "TB") | _ids(ftext["4"], "TB")
        secs = hl.blocks(ftext["4"], "SEC")
        for sid, blk in sorted(secs.items()):
            tb = hl.field(blk, "Trust boundary") or ""
            refs = re.findall(r"\bTB-\d+\b", tb)
            if not refs or any(r not in tbs for r in refs):
                errs.append("%s: '**Trust boundary:**' must name an existing TB-n (product or feature): %r" % (sid, tb))
            if not hl.field(blk, "Mitigation requirement"):
                errs.append("%s: no '**Mitigation requirement:**'" % sid)
        for ref in sorted(set(re.findall(r"\bSEC-\d+\b", ftext["4"])) - set(secs) - _ids(prod, "SEC")):
            errs.append("%s mentions %s, which neither the product nor the feature defines" % (fdocs["4"], ref))
    sec_known = _ids(prod, "SEC") | _ids(ftext["4"], "SEC")
    if "5" in upto and fdocs["5"]:
        for sid in sorted(fstories):
            if sid not in ftext["5"]:
                errs.append("%s does not mention the feature story %s (every story needs a design)" % (fdocs["5"], sid))
    if "7" in upto and fdocs["7"]:
        tasks = hl.blocks(ftext["7"], "T")
        if not tasks:
            errs.append("%s: no tasks ('### T-nnn — <title>')" % fdocs["7"])
        covered = set()
        for tid, blk in sorted(tasks.items()):
            st_ = re.findall(r"\b(?:US|NFR)-\d+\b", hl.field(blk, "Story") or "")
            if not st_:
                errs.append("%s: no '**Story:**' naming a feature story" % tid)
            for r in st_:
                if r not in fstories:
                    errs.append("%s: story %s is not one of this feature's stories" % (tid, r))
                covered.add(r)
            sat = hl.field(blk, "Satisfies SEC-IDs")
            if sat is None:
                errs.append("%s: no '**Satisfies SEC-IDs:**' (write `none` if it satisfies none)" % tid)
            else:
                for r in re.findall(r"\bSEC-\d+\b", sat):
                    if r not in sec_known:
                        errs.append("%s satisfies %s, which neither the product nor the feature defines" % (tid, r))
        for sid in sorted(set(fstories) - covered):
            errs.append("feature story %s has no task in %s" % (sid, fdocs["7"]))
    if "8" in upto and fdocs["8"]:
        for sid, ac, _s in acceptance(ftext["2"]):
            if "%s/%s" % (sid, ac) not in ftext["8"]:
                errs.append("%s does not account for %s/%s (every feature acceptance criterion needs a test result)"
                            % (fdocs["8"], sid, ac))
    if "9" in upto and fdocs["9"]:
        for r in sorted(_ids(ftext["4"], "SEC")):
            if r not in ftext["9"]:
                errs.append("%s does not account for the feature's %s" % (fdocs["9"], r))
    if label == pathmap.RELEASE:
        try:
            plan = merge_plan(root, fid)
            notes.append("merge preview: %s" % ", ".join("%s (+%d bytes)" % (f["target"], f["added_bytes"])
                                                       for f in plan["files"]))
        except FeatureError as e:
            errs.append("the merge into the product documents would fail: %s" % e)
    return errs, notes


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _strip_title(text):
    lines = text.splitlines()
    while lines and (not lines[0].strip() or lines[0].startswith("# ")):
        lines.pop(0)
    return "\n".join(lines).rstrip() + "\n"


def merge_plan(root, fid, seq=None):
    """What APPROVE 11 of the feature writes into the product: {"files": [{target, sources,
    before_sha256, after_sha256, added_bytes}], "contents": {target: bytes}}. Raises
    FeatureError when a merge would overwrite or collide."""
    files, contents = [], {}
    for lab in MERGED:
        src = feature_doc(root, fid, lab)
        if not src:
            continue
        target = product_doc(root, lab) or "sdlc/%s" % os.path.basename(src)
        before = b""
        tp = os.path.join(root, target)
        if os.path.exists(tp):
            with open(tp, "rb") as f:
                before = f.read()
        with open(os.path.join(root, src), "rb") as f:
            add = f.read().decode("utf-8", errors="replace")
        marker = "<!-- MOADIX merge: feature %s -->" % fid
        if marker.encode() in before:
            raise FeatureError("%s already holds a merge of feature %s" % (target, fid))
        block = "\n\n%s\n## Feature %s%s\n\n%s" % (marker, fid, " (ledger seq %d)" % seq if seq else "",
                                                     _strip_title(add))
        after = (before.rstrip(b"\n") + b"\n" if before else b"") + block.lstrip("\n" if not before else "").encode()
        contents[target] = after
        files.append({"target": target, "sources": [src], "before_sha256": _sha(before),
                      "after_sha256": _sha(after), "added_bytes": len(after) - len(before)})
    lld = os.path.join(root, folder(fid), "05-lld")
    if os.path.isdir(lld):
        for a, _d, fs in os.walk(lld):
            for fn in sorted(fs):
                srcp = os.path.join(a, fn)
                rel = os.path.relpath(srcp, lld)
                target = "sdlc/05-lld/%s" % rel
                if os.path.exists(os.path.join(root, target)):
                    raise FeatureError("%s already exists in the product; a feature's LLD file must have a new name"
                                       % target)
                with open(srcp, "rb") as f:
                    data = f.read()
                contents[target] = data
                files.append({"target": target, "sources": [os.path.relpath(srcp, root)], "before_sha256": _sha(b""),
                              "after_sha256": _sha(data), "added_bytes": len(data)})
    if not files:
        raise FeatureError("the feature has no documents to merge (%s/00-*.md ... 06b-*.md)" % folder(fid))
    return {"files": files, "contents": contents}


def apply_merge(root, fid, plan, seq):
    """Write the merged product documents (the plan recomputed with the ledger seq, checked
    against the recorded before-hashes) and commit them as the gate. Returns (commit, note)."""
    fresh = merge_plan(root, fid, seq)
    for rec, now in zip(plan["files"], fresh["files"]):
        if rec["target"] != now["target"] or rec["before_sha256"] != now["before_sha256"] or \
                rec["after_sha256"] != now["after_sha256"]:
            raise FeatureError("%s changed between APPROVE and the merge" % rec["target"])
    for target, data in fresh["contents"].items():
        p = os.path.join(root, target)
        if os.path.islink(p) or os.path.islink(os.path.dirname(p)):
            raise FeatureError("%s is a symbolic link; refusing to write through it" % target)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".moadix-tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
    targets = sorted(fresh["contents"])
    git = [state.GIT, "-C", root]
    subprocess.run(git + ["add", "--"] + targets, capture_output=True, text=True, timeout=60, check=True)
    p = subprocess.run(git + GATE_AUTHOR + ["commit", "--no-verify", "-q", "-m",
                                            "MOADIX: merge feature %s into the product documents (ledger seq %d)" % (
                                                fid, seq), "--"] + targets,
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise FeatureError("git commit failed: %s" % (p.stderr or p.stdout).strip()[:200])
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, timeout=20).stdout.strip()
    return head, [{"target": t, "after_sha256": _sha(fresh["contents"][t])} for t in targets]
