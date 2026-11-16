"""Gap-critic convergence (0.7.0; docs/critic-convergence-design.md, approved with rulings).

Four parts, all gate-side:

  depth      each phase's `depth` block in gate/config/coverage-topics.yaml: what the phase
             decides (a gap there is BLOCKER/MAJOR/MINOR as before) and what it defers, each
             deferral naming a later phase. A gap that matches no `defers` rule is judged at the
             current phase exactly as before 0.7.0; `decides` wins every overlap.
  carries    a CARRY finding names a `defers` rule; the hard rules (carry_problems) are checked
             deterministically. On APPROVE / PROCEED-PAST the gate records the phase's carries in
             the ledger (CARRY-<phase>-<n>); state.replay is the register. The target phase must
             settle each one (coverage-lint), and an open carry blocks the release.
  memory     every critic run is archived and its findings get stable ids (GC-<phase>-<n>). The
             next brief lists earlier findings with a disposition the gate works out (waived,
             carried, ruled, fixed?, open). `same_as` / `regression_of` link a finding to an
             earlier one; the gate checks the claim. A new finding on text that did not change
             since the previous run is marked late (counted and shown, never downgraded).
  waivers    a waiver binds one finding (`gap-critic.GC-...`), with the fingerprint of the cited
             text; it lapses when that text changes. Topic waivers recorded before 0.7.0 keep
             working until expiry, only for findings on text that existed when they were recorded.

Registry: .sdlc/critic/<scope>-<label>.json (gate-owned; agents cannot write .sdlc/).
"""
import hashlib
import json
import os
import re
import subprocess

from . import pathmap, state

GIT = "/usr/bin/git"
GC_ID = re.compile(r"^GC-(?P<prefix>[A-Za-z0-9_.-]+)-(?P<n>\d{1,4})$")
CARRY_ID = re.compile(r"^CARRY-(?P<prefix>[A-Za-z0-9_.-]+)-(?P<n>\d{1,4})$")
CITATION = re.compile(r"^(?P<path>[^:\s][^:]*):(?P<a>\d+)(?:-(?P<b>\d+))?$")
CARRY = "CARRY"
FEATURE_TARGET = "feature"
MAX_TEXT = 1200


# ------------------------------------------------------------------ catalogue
def _cat():
    from . import contract
    return contract.catalogue()


def depth(label):
    from . import contract
    d = (contract.phase_entry(label) or {}).get("depth") or {}
    return {"decides": list(d.get("decides") or []), "defers": list(d.get("defers") or [])}


def rules():
    c = _cat().get("carry") or {}
    return {"classes": [str(x) for x in c.get("classes") or ["security", "privacy", "tenant-isolation", "other"]],
            "protected": [str(x) for x in c.get("protected") or ["security", "privacy", "tenant-isolation"]],
            "protected_last_phase": str(c["protected_last_phase"]),  # declared in the catalogue only
            "class_keywords": {str(k): [str(x) for x in v or []] for k, v in (c.get("class_keywords") or {}).items()},
            "carry_note_ratio": float(c.get("carry_note_ratio") or 0.5)}


def _kw(words, text):
    t = " %s " % norm(text)
    return [w for w in words if re.search(r"(?<![a-z0-9])%s" % re.escape(norm(w)), t)]


# ------------------------------------------------------------------ scope and ids
def scope_key(st):
    return "feature-%s" % st["feature"] if st and st.get("feature") else "product"


def prefix(st, label):
    return "%s.%s" % (st["feature"], label) if st and st.get("feature") else str(label)


def order(st, label):
    """Position of `label` in the scope's phase table (None when it is not a phase there)."""
    if str(label) == FEATURE_TARGET:
        return None
    for i, (_pid, lab, _n, _g) in enumerate(pathmap.scope_phases((st or {}).get("mode"), (st or {}).get("feature"))):
        if lab == str(label):
            return i
    return None


def phase_status(st, label):
    p = next((x for x in (st or {}).get("phases") or [] if x["label"] == str(label)), None)
    return p["status"] if p else None


def closed(status):
    return status in state.DONE


# ------------------------------------------------------------------ text
def norm(s):
    return " ".join(str(s or "").replace("*", " ").replace("`", " ").replace("_", " ").split()).lower()


def sha(s):
    return hashlib.sha256(str(s).encode()).hexdigest()


def _show(root, commit, path):
    if not commit or not path or path.startswith("/") or ".." in path.split("/"):
        return None
    try:
        p = subprocess.run([GIT, "-C", root, "show", "%s:%s" % (commit, path)], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _section(lines, n):
    from . import contract
    for i in range(min(n, len(lines)) - 1, -1, -1):
        m = contract.HEADING.match(lines[i])
        if m:
            return contract.slug(m.group(2))
    return ""


def fingerprint(root, commit, citation, memo=None):
    """{path, section, text, text_sha} of the cited lines at `commit`, or None."""
    m = CITATION.match(str(citation or "").strip())
    if not m:
        return None
    path = m.group("path")
    key = (commit, path)
    memo = {} if memo is None else memo
    if key not in memo:
        memo[key] = _show(root, commit, path)
    text = memo[key]
    if text is None:
        return None
    lines = text.splitlines()
    a, b = int(m.group("a")), int(m.group("b") or m.group("a"))
    cited = norm(" ".join(lines[max(0, a - 1):b]))[:MAX_TEXT]
    key, body = section_of(text, a)
    return {"path": path, "section": _section(lines, a), "text": cited, "text_sha": sha(cited),
            "skey": key, "section_sha": sha(body) if body is not None else None}


def present(root, commit, path, ntext, memo=None):
    """True when the normalized text still appears in path at commit (line moves do not matter)."""
    if not ntext:
        return False
    memo = {} if memo is None else memo
    key = (commit, path)
    if key not in memo:
        memo[key] = _show(root, commit, path)
    whole = memo[key]
    return whole is not None and ntext in norm(whole.replace("\n", " "))


# ------------------------------------------------------------------ 0.7.2: sections (design §10.1, §10.2)
def _sections(text):
    """[(key, first line, last line, normalized body)] for each heading-bounded section. The key is
    "<anchor>#<k>" (k counts equal anchors); the text before the first heading is "#0". The heading
    line belongs to its section; the body excludes it, so a renamed heading is a new key."""
    from . import contract
    lines = (text or "").splitlines()
    out, seen = [], {}
    key, start, buf = "#0", 1, []
    for i, ln in enumerate(lines, 1):
        m = contract.HEADING.match(ln)
        if m:
            out.append((key, start, i - 1, norm(" ".join(buf))))
            s_ = contract.slug(m.group(2))
            seen[s_] = seen.get(s_, -1) + 1
            key, start, buf = "%s#%d" % (s_, seen[s_]), i, []
        else:
            buf.append(ln)
    out.append((key, start, len(lines), norm(" ".join(buf))))
    return out


def section_of(text, n):
    """(key, normalized body) of the section holding line n, or (None, None)."""
    for key, a, b, body in _sections(text):
        if a <= n <= b:
            return key, body
    return None, None


def _text(root, commit, path, memo):
    key = (commit, path)
    if key not in memo:
        memo[key] = _show(root, commit, path)
    return memo[key]


def section_body(root, commit, path, skey, memo):
    """The normalized body of section `skey` of path at commit; None when it does not exist there."""
    text = _text(root, commit, path, memo)
    if text is None:
        return None
    return next((body for key, _a, _b, body in _sections(text) if key == skey), None)


def frozen(root, path, skey, commits, memo):
    """True when section `skey` of path exists, with the same body, at every one of `commits`."""
    bodies = [section_body(root, c, path, skey, memo) for c in commits]
    return bool(commits) and all(b is not None for b in bodies) and len(set(bodies)) == 1


def changed_sections(root, old, new, paths, memo):
    """[(path, key, first line, last line, status)] for the sections of `paths` that differ between two
    commits: status "changed" (or new) at `new`, or "removed" (present only at `old`)."""
    out = []
    for p in paths:
        a, b = _text(root, old, p, memo), _text(root, new, p, memo)
        if b is None and a is None:
            continue
        olds = {k: body for k, _x, _y, body in _sections(a)} if a is not None else {}
        news = _sections(b) if b is not None else []
        for k, x, y, body in news:
            if olds.get(k) != body and (y >= x or k not in olds):
                out.append((p, k, x, y, "changed"))
        for k in olds:
            if k not in {n[0] for n in news} and olds[k]:
                out.append((p, k, 0, 0, "removed"))
    return out


# ------------------------------------------------------------------ 0.7.2: frozen-text exceptions, claims (§10.1, §10.3, §10.4)
EXCEPTIONS = {"security": "security", "privacy": "privacy", "tenant": "tenant-isolation"}
CLAIM_CLASSES = ("legal", "cost", "security", "feasibility", "other")
BIG_CLASSES = ("legal", "cost", "security", "feasibility")
QUOTE_RE = re.compile(r'^\s*>\s*\S|"[^"\n]{12,}"|\u201c[^\u201d\n]{12,}\u201d')
URL_RE = re.compile(r"https?://")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
FOOTREF = re.compile(r"\[\^([^\]\s]+)\]")


def upstream_phase(st, path):
    """The label of an earlier phase that is APPROVED or PROCEED-PAST and whose path map owns `path`
    (in a feature cycle, any closed product phase too), or None."""
    path = path.lstrip("./")
    feature = (st or {}).get("feature")
    cur = order(st, (st or {}).get("current_phase"))
    cands = []
    for i, (_pid, lab, _n, globs) in enumerate(pathmap.scope_phases((st or {}).get("mode"), feature)):
        if cur is not None and i < cur:
            cands.append((lab, globs, phase_status(st, lab)))
    if feature:
        for _pid, lab, _n, globs in pathmap.scope_phases((st or {}).get("mode"), None):
            p = next((x for x in (st or {}).get("product_phases") or [] if x["label"] == lab), None)
            cands.append((lab, globs, p["status"] if p else None))
    for lab, globs, status in cands:
        if status in ("APPROVED", "PROCEED-PAST") and pathmap.any_glob(globs, path):
            return lab
    return None


def frozen_exception(root, st, f, commit, memo):
    """None when a new finding on frozen text passes an exception (§10.1), else the reason it does not."""
    if f.get("severity") != "BLOCKER":
        return "only a BLOCKER under an exception may be raised on frozen text"
    exc = f.get("exception")
    if exc in EXCEPTIONS:
        words = rules()["class_keywords"].get(EXCEPTIONS[exc]) or []
        if _kw(words, "%s %s" % (f.get("quote") or "", f.get("fix") or "")):
            return None
        return "exception %s claimed, but its quote and fix name none of the catalogue's %s words" % (
            exc, EXCEPTIONS[exc])
    if exc == "upstream":
        m = CITATION.match(str(f.get("upstream") or "").strip())
        if not m:
            return "exception upstream needs `upstream: path:line`"
        text = _text(root, commit, m.group("path"), memo)
        if text is None or int(m.group("b") or m.group("a")) > len(text.splitlines()):
            return "upstream %s does not exist at the reviewed commit" % f.get("upstream")
        if not upstream_phase(st, m.group("path")):
            return "upstream %s is not a document of an earlier phase that is APPROVED or PROCEED-PAST" % (
                f.get("upstream"))
        return None
    return "no exception claimed (security, privacy, tenant or upstream)"


def decision_ids(root, commit):
    """Ids a claim's `decision` may name at commit: Q-n headings in any DISCOVERY.md, ADR-nnn files,
    and every decides rule of the catalogue."""
    out = {str(r["id"]) for e in (_cat().get("phases") or {}).values()
           for r in ((e or {}).get("depth") or {}).get("decides") or []}
    try:
        p = subprocess.run([GIT, "-C", root, "ls-tree", "-r", "--name-only", commit], capture_output=True,
                           text=True, timeout=15)
        names = p.stdout.splitlines() if p.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        names = []
    memo = {}
    for n in names:
        m = re.search(r"(?:^|/)(ADR-\d{3,4})-", n)
        if m:
            out.add(m.group(1))
        if n.endswith("DISCOVERY.md"):
            out |= set(re.findall(r"^##\s+(Q-\d+)\b", _text(root, commit, n, memo) or "", re.M))
    return out


def _line_cited(lines, a, b, whole):
    """True when one of lines a..b carries a source as cite-lint reads it: a URL with a date on the
    line, or a footnote reference whose definition has one."""
    for ln in lines[max(0, a - 1):b]:
        if URL_RE.search(ln) and DATE_RE.search(ln):
            return True
        for ref in FOOTREF.findall(ln):
            d = re.search(r"^\[\^%s\]:(.*)$" % re.escape(ref), whole, re.M)
            if d and URL_RE.search(d.group(1)) and DATE_RE.search(d.group(1)):
                return True
    return False


def claim_rule(root, f, commit, ids, memo):
    """(severity the gate records, problems) for a claim finding (`kind` uncited or support, §10.3 and
    §10.4); (None, []) for any other finding. The severity is the table's, from the two fields."""
    kind = f.get("kind")
    if not kind:
        return None, []
    probs = []
    cls, dec = f.get("claim_class"), str(f.get("decision") or "")
    if cls not in CLAIM_CLASSES:
        probs.append("kind %s needs claim_class (%s)" % (kind, ", ".join(CLAIM_CLASSES)))
    if not dec:
        probs.append("kind %s needs decision (a Q-n, an ADR-nnn, a decides rule id, or none)" % kind)
    elif dec != "none" and dec not in ids:
        probs.append("decision %s does not exist (no Q-n heading in a DISCOVERY.md, ADR file or decides rule "
                     "with that id at the reviewed commit)" % dec)
    terms = [w for k in ("security", "privacy", "tenant-isolation") for w in rules()["class_keywords"].get(k) or []]
    if cls in CLAIM_CLASSES and cls != "security" and _kw(terms, f.get("quote") or ""):
        probs.append("the quote names security, privacy or tenant terms, so claim_class is security (§10.3)")
    big, dep = cls in BIG_CLASSES, dec not in ("", "none")
    table = "BLOCKER" if big and dep else "MAJOR" if (big or dep) else "MINOR"
    m = CITATION.match(str(f.get("citation") or "").strip())
    text = _text(root, commit, m.group("path"), memo) if m else None
    lines = (text or "").splitlines()
    a = int(m.group("a")) if m else 0
    b = int(m.group("b") or a) if m else 0
    sec = next(((x, y) for _k, x, y, _body in _sections(text) if x <= a <= y), (a, b)) if text else (a, b)
    hasq = any(QUOTE_RE.search(ln) for ln in lines[max(0, sec[0] - 1):sec[1]])
    basis = f.get("basis")
    sev = table
    if kind == "uncited":
        if basis not in (None, "no-citation"):
            probs.append("an uncited claim has basis no-citation, not %s" % basis)
        if text is not None and _line_cited(lines, a, b, text):
            probs.append("the cited line carries a source (a URL with a date, or a footnote with one), which "
                         "cite-lint accepts: it is not uncited; judge its support from a quoted sentence (§10.4)")
    elif kind == "support":
        if basis not in ("quote-contradicts", "quote-insufficient", "no-quote"):
            probs.append("kind support needs basis quote-contradicts, quote-insufficient or no-quote")
        elif basis != "no-quote" and not hasq:
            probs.append("basis %s, but the cited section quotes no source text: you cannot see the page, so "
                         "support is judged only from a quote in the document (§10.4)" % basis)
        elif basis == "no-quote":
            if hasq:
                probs.append("basis no-quote, but the cited section quotes its source")
            if not (big and dep):
                probs.append("no-quote is a finding only for a legal, cost, security or feasibility claim a "
                             "decision depends on")
            sev = "MAJOR"
        elif basis == "quote-contradicts":
            sev = "BLOCKER" if big and dep else "MAJOR"
    else:
        probs.append("kind %r is not uncited or support" % kind)
    return sev, probs


# ------------------------------------------------------------------ registry
def registry_path(root, st, label):
    return os.path.join(root, state.SDLC, "critic", "%s-%s.json" % (scope_key(st), label))


def load(root, st, label):
    try:
        with open(registry_path(root, st, label)) as f:
            reg = json.load(f)
        if isinstance(reg, dict) and isinstance(reg.get("runs"), list) and isinstance(reg.get("findings"), dict):
            return reg
    except (OSError, ValueError):
        pass
    return {"version": 1, "next": 1, "runs": [], "findings": {}}


def _save(root, st, label, reg):
    p = registry_path(root, st, label)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump(reg, f, indent=1, sort_keys=True)
        os.replace(p + ".tmp", p)
        return True
    except OSError:
        return False  # a feedback run in the agent's sandbox: computed, not stored


def ingest(root, st, label, ev, receipt_sha, evidence_sha):
    """Archive one stamped CRITIC.json as a run and give its findings stable ids. Idempotent per
    receipt. Returns the run: {n, commit, map {C-id: GC-id}, late [GC], regressions [GC],
    problems [str], prints {GC: fingerprint}}."""
    reg = load(root, st, label)
    for r in reg["runs"]:
        if r.get("receipt_sha256") == receipt_sha:
            return r
    prev = reg["runs"][-1] if reg["runs"] else None
    commit = str(ev.get("source_commit") or "")
    run = {"n": len(reg["runs"]) + 1, "commit": commit, "receipt_sha256": receipt_sha,
           "evidence_sha256": evidence_sha, "map": {}, "late": [], "regressions": [], "problems": [], "prints": {},
           "counts": {}, "frozen": {}, "severity": {}, "demoted": []}
    memo = {}
    pre = prefix(st, label)
    # 0.7.2 (§10.1): from run 3 a new finding on a section unchanged since run n-2 needs an exception
    frozen_at = [reg["runs"][-2].get("commit"), reg["runs"][-1].get("commit"), commit] if run["n"] >= 3 else []
    ids = None
    for i, f in enumerate(ev.get("findings") or []):
        if not isinstance(f, dict):
            continue
        cid = str(f.get("id") or "#%d" % (i + 1))
        sev = str(f.get("severity") or "")
        run["counts"][sev] = run["counts"].get(sev, 0) + 1
        fp = fingerprint(root, commit, f.get("citation"), memo)
        gid, bad = None, None
        if f.get("same_as") and f.get("regression_of"):
            bad = "finding %s names both same_as and regression_of; a finding is one or the other" % cid
        for key in ("same_as", "regression_of"):
            v = f.get(key)
            if bad or not v:
                continue
            old = reg["findings"].get(str(v))
            if old is None:
                bad = "finding %s: %s %s is not a finding of an earlier run on phase %s" % (cid, key, v, label)
            elif str(old.get("topic")) != str(f.get("topic")):
                bad = "finding %s: %s %s was on topic %s, this finding is on %s" % (cid, key, v, old.get("topic"),
                                                                                f.get("topic"))
            elif key == "same_as" and fp and old.get("section") != fp["section"]:
                bad = ("finding %s: same_as %s cited section #%s, this finding cites #%s; a finding elsewhere is a "
                       "new finding" % (cid, v, old.get("section"), fp["section"]))
            elif key == "regression_of" and fp and not (old.get("path") == fp["path"] and
                                                        old.get("section") == fp["section"]) and \
                    frozen(root, fp["path"], fp.get("skey"), [old.get("commit"), commit], memo):
                # 0.7.2 (§10.1, MF-18): a regression cites the original's section or text changed since it
                run["demoted"].append("finding %s: regression_of %s cites #%s in %s, neither the section %s cited "
                                      "nor text changed since; it counts as a new finding" % (
                                          cid, v, fp["section"], fp["path"], v))
            else:
                gid = str(v)
                if key == "regression_of":
                    run["regressions"].append(gid)
        if bad:
            run["problems"].append(bad)
            continue
        if gid is None:
            gid = "GC-%s-%d" % (pre, reg["next"])
            reg["next"] += 1
            if prev and fp and present(root, prev.get("commit"), fp["path"], fp["text"], memo):
                run["late"].append(gid)
            if frozen_at and fp and fp.get("skey") and frozen(root, fp["path"], fp["skey"], frozen_at, memo):
                why = frozen_exception(root, st, f, commit, memo)
                if why:
                    run["frozen"][gid] = why
        if f.get("kind"):
            if ids is None:
                ids = decision_ids(root, commit)
            eff, cprobs = claim_rule(root, f, commit, ids, memo)
            run["problems"] += ["finding %s: %s" % (cid, p) for p in cprobs]
            if eff and sev in ("BLOCKER", "MAJOR", "MINOR") and eff != sev:
                run["severity"][gid] = eff
        old = reg["findings"].get(gid) or {}
        reg["findings"][gid] = {
            "topic": str(f.get("topic")), "severity": sev, "quote": str(f.get("quote") or "")[:600],
            "citation": str(f.get("citation") or ""), "commit": commit, "path": (fp or {}).get("path"),
            "section": (fp or {}).get("section"), "text": (fp or {}).get("text"), "text_sha": (fp or {}).get("text_sha"),
            "first_run": old.get("first_run", run["n"]), "last_run": run["n"],
            "defer_rule": f.get("defer_rule"), "to": f.get("to"), "class": f.get("class"),
            "fix": str(f.get("fix") or "")[:600], "ac": f.get("ac"), "skey": (fp or {}).get("skey"),
            "section_sha": (fp or {}).get("section_sha")}
        run["map"][cid] = gid
        if fp:
            run["prints"][gid] = fp
    reg["runs"].append(run)
    _save(root, st, label, reg)
    return run


def latest_run(root, st, label):
    reg = load(root, st, label)
    return (reg["runs"][-1] if reg["runs"] else None), reg


# ------------------------------------------------------------------ waivers
def waiver_info(st):
    return (st or {}).get("_waiver_payload") or {}


def waiver_covers(root, st, label, gid, topic, fp, active):
    """(covered, lapsed waiver id or None). New-style: gap-critic.<GC id> whose fingerprint still
    matches. Legacy (pre-0.7.0) topic waivers: only for findings in the phase they were recorded in,
    on text that already existed at the waiver's commit (ruling Q3)."""
    wid = "gap-critic.%s" % gid
    info = waiver_info(st)
    if wid in active:
        want = ((info.get(wid) or {}).get("fingerprints") or {}).get(wid) or {}
        if not fp or (want.get("text_sha") and want["text_sha"] != fp.get("text_sha")):
            return False, wid  # the cited text is gone or changed: the waiver has lapsed
        return True, None
    tw = "gap-critic.%s" % topic
    if tw in active:
        w = info.get(tw) or {}
        if w.get("fingerprints"):
            return False, None
        if str(w.get("phase_at")) == str(label) and fp and w.get("source_commit") and \
                present(root, w["source_commit"], fp["path"], fp["text"]):
            return True, None
    return False, None


def lapsed_waivers(root, st, hd, active):
    """[(waiver id, path)] of active finding waivers whose cited text is gone at HEAD."""
    out = []
    memo = {}
    for wid, w in sorted(waiver_info(st).items()):
        if wid not in active:
            continue
        for fid, fp in sorted((w.get("fingerprints") or {}).items()):
            if fid == wid and fp.get("path") and not present(root, hd, fp["path"], fp.get("text"), memo):
                out.append((wid, fp["path"]))
    return out


# ------------------------------------------------------------------ carries
def carries(st):
    return (st or {}).get("_carries") or {}


def carry_waived(cid, active):
    return cid in active


def open_carries(st, active, to_label=None, scope=None):
    """Carries not closed and not waived, optionally only those addressed to (scope, label)."""
    out = []
    for cid, c in sorted(carries(st).items()):
        if c.get("status") != "open" or carry_waived(cid, active):
            continue
        if to_label is not None and (str(c.get("to")) != str(to_label) or c.get("scope") != scope):
            continue
        out.append((cid, c))
    return out


def carries_in(st, label, active):
    """The open carries addressed to the current scope's phase `label`."""
    return open_carries(st, active, label, (st or {}).get("feature") or "product")


def overdue_carries(st, active):
    """Open carries whose target phase is already closed (approved, proceeded past, collapsed):
    release blockers (ruling Q5)."""
    out = []
    for cid, c in open_carries(st, active):
        scope = c.get("scope")
        if scope == "product":
            phases = st.get("product_phases") or st.get("phases") or []
        else:
            phases = (st.get("_feature_phases") or {}).get(scope) or []
        p = next((x for x in phases if x["label"] == str(c.get("to"))), None)
        if p and closed(p["status"]):
            out.append((cid, c))
    return out


def story_priorities(root, st):
    """{AC id (US-001/AC-2 and AC-2): P1 bool} from the scope's PRD (`- **Priority:** must|P1`)."""
    from . import verify
    rel_dir = "sdlc" if not (st and st.get("feature")) else "%s/%s" % (pathmap.FEATURES_DIR, st["feature"])
    out = {}
    sd = os.path.join(root, rel_dir)
    if not os.path.isdir(sd):
        return out
    for fn in sorted(f for f in os.listdir(sd) if re.match(r"^02-.*\.md$", f)):
        cur, p1 = None, False
        with open(os.path.join(sd, fn), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"^#{2,4}\s+((?:US|NFR)-\d+)\b", line.strip())
                if m:
                    cur, p1 = m.group(1), False
                    continue
                pm = re.match(r"^\s*[-*]\s*\**Priority:?\**\s*:?\s*(.+)$", line, re.I)
                if pm and cur:
                    p1 = bool(re.match(r"^\W*(must|p1|1)\b", pm.group(1).strip(), re.I))
                a = verify.AC_RE.match(line)
                if a and cur:
                    ac = a.group(1).upper()
                    out["%s/%s" % (cur, ac)] = p1
                    out[ac] = out.get(ac, False) or p1
    return out


def carry_problems(root, st, label, f, prios=None):
    """The hard rules for one CARRY finding of phase `label`. [] when it may carry."""
    out = []
    fid = str(f.get("id"))
    d = depth(label)
    rule = next((r for r in d["defers"] if str(r.get("id")) == str(f.get("defer_rule"))), None)
    R = rules()
    text = "%s %s" % (f.get("quote") or "", f.get("fix") or "")
    if rule is None:
        return ["finding %s: CARRY names defer_rule %r, which is not a defers rule of phase %s (%s); a gap that "
                "matches no defers rule is judged at this phase" % (fid, f.get("defer_rule"), label,
                                                                   ", ".join(str(r["id"]) for r in d["defers"]) or "none")]
    to = str(rule.get("to"))
    if str(f.get("to")) != to:
        out.append("finding %s: %s carries to phase %s, not %r" % (fid, rule["id"], to, f.get("to")))
    cls = str(f.get("class") or "")
    if cls not in R["classes"]:
        out.append("finding %s: class %r is not one of %s" % (fid, f.get("class"), ", ".join(R["classes"])))
    if to == FEATURE_TARGET:
        if (st or {}).get("mode") != "onboarding" or (st or {}).get("feature"):
            out.append("finding %s: %s carries to the next feature cycle, which only an onboarded product's "
                       "baseline does" % (fid, rule["id"]))
    else:
        o_from, o_to = order(st, label), order(st, to)
        if o_to is None or o_from is None or o_to <= o_from:
            out.append("finding %s: phase %s is not a later phase of this scope" % (fid, to))
        elif closed(phase_status(st, to)):
            out.append("finding %s: phase %s is already closed; a carry goes to a phase still to come" % (fid, to))
    for r in d["decides"]:
        hit = _kw([str(k) for k in r.get("keywords") or []], f.get("quote") or "")
        if hit:
            out.append("finding %s: the quote touches %s (%s: %s); decides wins every overlap, so it is judged at "
                       "phase %s" % (fid, r["id"], r.get("what"), ", ".join(hit), label))
    for c, words in sorted(R["class_keywords"].items()):
        hit = _kw(words, text)
        if hit and cls not in R["protected"] and c in R["protected"]:
            out.append("finding %s: it names %s terms (%s) but is classed %r; class it %s" % (
                fid, c, ", ".join(hit[:3]), cls, c))
    if cls in R["protected"]:
        last = order(st, R["protected_last_phase"])
        o_to = order(st, to)
        if to == FEATURE_TARGET or o_to is None or last is None or o_to > last:
            out.append("finding %s: a %s gap is never carried past phase %s" % (fid, cls, R["protected_last_phase"]))
    if rule.get("known_issue"):
        if cls in R["protected"]:
            out.append("finding %s: a %s defect cannot be a known issue in the release notes" % (fid, cls))
        ac = str(f.get("ac") or "").strip()
        if not ac:
            out.append("finding %s: a known issue names the acceptance criterion it affects (`ac`: US-n/AC-n, or "
                       "`none`)" % fid)
        prios = story_priorities(root, st) if prios is None else prios
        named = set(re.findall(r"\b(?:US-\d+/)?AC-\d+\b", "%s %s" % (ac, text), re.I))
        p1 = sorted(a for a in named if prios.get(a.upper()))
        if p1:
            out.append("finding %s: the defect breaks P1 acceptance criteria %s, so it cannot be a known issue" % (
                fid, ", ".join(p1)))
    return out


# ------------------------------------------------------------------ the brief's sections
def _ruled_ids(root, st, label, hd):
    """GC ids a ruling cites (`Rules: GC-...`) in the phase's DISCOVERY.md or ADRs at HEAD."""
    from . import contract
    cdir = contract.contract_dir(st, label)
    try:
        p = subprocess.run([GIT, "-C", root, "ls-tree", "-r", "--name-only", hd, "--", cdir], capture_output=True,
                           text=True, timeout=15)
        files = [x for x in p.stdout.splitlines() if x.endswith(".md")]
    except (OSError, subprocess.SubprocessError):
        files = []
    out = set()
    for rel in files:
        if not (rel.endswith("/DISCOVERY.md") or "/adr/" in rel):
            continue
        for ln in (_show(root, hd, rel) or "").splitlines():
            if re.match(r"^\s*[-*]?\s*\**Rules?\**\s*:", ln, re.I):
                out |= set(re.findall(r"\bGC-[A-Za-z0-9_.-]+-\d{1,4}\b", ln))
    return out


def dispositions(root, st, label, hd, active):
    """[(GC id, finding, disposition)] for every finding of earlier runs on this phase."""
    _run, reg = latest_run(root, st, label)
    ruled = _ruled_ids(root, st, label, hd)
    uncarried = set((st or {}).get("_uncarried") or [])
    memo = {}
    out = []
    defers = {str(r["id"]) for r in depth(label)["defers"]}
    for gid in sorted(reg["findings"], key=lambda g: int(GC_ID.match(g).group("n")) if GC_ID.match(g) else 0):
        f = reg["findings"][gid]
        lines_here = bool(f.get("path")) and present(root, hd, f["path"], f.get("text"), memo)
        # 0.7.2 (§10.2, MF-17, MF-22): the finding's text changed when its cited lines are gone OR its section
        # changed (lines added next to it, a renamed heading). A waiver still lapses on the cited lines only (A2).
        same_section = True
        if f.get("skey") and f.get("section_sha"):
            body = section_body(root, hd, f["path"], f["skey"], memo)
            same_section = body is not None and sha(body) == f["section_sha"]
        here = lines_here and same_section
        covered, _lapse = waiver_covers(root, st, label, gid, f.get("topic"),
                                        {"path": f.get("path"), "text": f.get("text"), "text_sha": f.get("text_sha")}
                                        if lines_here else None, active)
        if covered:
            disp = "waived"
        elif f.get("severity") == CARRY and lines_here and gid not in uncarried and \
                str(f.get("defer_rule")) in defers:
            disp = "carried"
        elif gid in ruled:
            disp = "ruled"
        elif not here:
            disp = "fixed?"
        else:
            disp = "open"
        out.append((gid, f, disp))
    return out


DISPOSITION_RULE = {
    "waived": "do not raise it again. If the cited text changed, the waiver has lapsed: judge the new text as new.",
    "carried": "do not raise it again at this phase.",
    "ruled": "check that the documents now say what the ruling chose; if not, raise a regression "
             "(regression_of: <GC id>).",
    "fixed?": "check the fix. Closed: say nothing. Not closed: raise a regression (regression_of: <GC id>).",
    "open": "raise it again with the same id (same_as: <GC id>).",
}


def brief_sections(root, st, label, hd, active, paths=()):
    """Lines for the critic's brief: the phase's depth, earlier runs, carries in, and (0.7.2) the claim
    rules and, from run 3, the run's scope."""
    d = depth(label)
    R = rules()
    L = ["", "## Depth of phase %s (what it decides, what it defers)" % label,
         "A gap on something this phase decides is BLOCKER, MAJOR or MINOR as the severity rules say. A gap that "
         "matches a defers rule below is a CARRY to the phase it names. A gap that matches no defers rule is judged "
         "at this phase exactly as before. Decides wins every overlap: if a gap touches anything this phase decides, "
         "it is not a CARRY, whatever detail it also contains.",
         "Decides:"]
    L += ["- %s %s" % (r["id"], r.get("what")) for r in d["decides"]] or ["- (everything in the phase's scope)"]
    L.append("Defers:")
    L += ["- %s %s -> phase %s%s" % (r["id"], r.get("what"), r.get("to"),
                                      " (known issue: name the affected AC in `ac`, or `none`)"
                                      if r.get("known_issue") else "")
          for r in d["defers"]] or ["- (nothing: this phase carries nothing)"]
    L += ["Hard rules (the gate checks each; a CARRY that breaks one fails the evidence):",
          "- defer_rule is one of the rules above and `to` is the phase it names, a later phase not yet closed;",
          "- `class` is one of %s; a gap naming security, privacy or tenant terms is classed so, and such a gap is "
          "never carried past phase %s;" % (", ".join(R["classes"]), R["protected_last_phase"]),
          "- nothing this phase decides and nothing in its BLOCKER rules is carried (the gate checks the quote "
          "against each decides rule's words);",
          "- a known issue breaks no P1 acceptance criterion and is not a security, privacy or tenant-isolation "
          "defect."]
    # 0.7.1 (task-tracker MF-14): the ids are fixed when the brief is written (the previous run was
    # archived at this launch), so the critic can print them and the operator can WAIVE at once.
    reg0 = load(root, st, label)
    nxt, pre = reg0["next"], prefix(st, label)
    L += ["", "## The ids your findings will get",
          "The gate numbers your NEW findings (no same_as, no regression_of) in the order they appear in "
          "`findings`: the first becomes %s, the second %s, and so on. A finding with same_as or regression_of "
          "keeps that GC id (a regression_of the gate does not accept as one takes the next id instead). In your "
          "final message, list each finding as `C<k> = GC-...` so the operator can type a WAIVE without waiting "
          "for REVIEW." % ("GC-%s-%d" % (pre, nxt), "GC-%s-%d" % (pre, nxt + 1))]
    L += ["", "## Claims and citations",
          "You have no network. Never state what a cited page says unless the document quotes it. Judge support "
          "only from quoted text; the gate's link check decides whether a citation exists and resolves.",
          "- A claim with no citation: set \"kind\": \"uncited\", \"claim_class\" (legal, cost, security, "
          "feasibility or other) and \"decision\" (the Q-n, ADR-nnn or decides rule id whose choice rests on the "
          "claim, or \"none\"). The gate sets the severity: legal, cost, security or feasibility with a decision is "
          "BLOCKER; one of the two is MAJOR; neither is MINOR. A quote naming security, privacy or tenant terms is "
          "claim_class security. A line that carries a URL with a date (or a footnote with one) is not uncited.",
          "- A cited claim its source may not support: set \"kind\": \"support\", the two fields above, and "
          "\"basis\": \"quote-contradicts\" (the document's quote of the source says otherwise), "
          "\"quote-insufficient\" (it covers only part of the claim) or \"no-quote\" (a legal, cost, security or "
          "feasibility claim a decision depends on, cited without the source's sentence). quote-* needs a quote "
          "(a `>` line or a quoted sentence) in the cited section."]
    if reg0["runs"] and len(reg0["runs"]) + 1 >= 3:
        r1, r2 = reg0["runs"][-2], reg0["runs"][-1]
        L += ["", "## Scope of this run (run %d)" % (len(reg0["runs"]) + 1),
              "Runs 1 and 2 reviewed everything. This run reviews only (1) the earlier findings below and (2) the "
              "sections changed since run %d (commit %s), listed here in full. Read any other document only to "
              "judge a change against it." % (r2["n"], str(r2.get("commit"))[:12]),
              "Frozen text: a section unchanged since run %d (commit %s). The gate refuses to count a NEW finding "
              "there unless it is a BLOCKER with \"exception\": \"security\", \"privacy\" or \"tenant\" (its quote "
              "or fix names that class's terms), or \"exception\": \"upstream\" with \"upstream\": \"path:line\" "
              "in an approved earlier phase's document it contradicts. Without one it goes to the operator's MINOR "
              "file and blocks nothing. A finding about missing text cites the nearest line where the text belongs."
              % (r1["n"], str(r1.get("commit"))[:12])]
        memo = {}
        ch = changed_sections(root, r2.get("commit"), hd, list(paths), memo)
        if not ch:
            L.append("- (no section changed since run %d)" % r2["n"])
        budget = 40000
        for path, key, a, b, status in ch:
            if status == "removed":
                L.append("- %s §%s: removed since run %d" % (path, key.split("#")[0] or "(top)", r2["n"]))
                continue
            body = "\n".join((_text(root, hd, path, memo) or "").splitlines()[a - 1:b][:120])
            if budget <= 0:
                L.append("- %s §%s (lines %d-%d): changed; read it there" % (path, key.split("#")[0], a, b))
                continue
            budget -= len(body)
            L += ["", "### %s §%s (lines %d-%d, changed)" % (path, key.split("#")[0] or "(top)", a, b), "```",
                  body, "```"]
    rows = dispositions(root, st, label, hd, active)
    L += ["", "## Earlier runs on this phase"]
    if not rows:
        L.append("- (none: this is the first run)")
    else:
        L.append("Each finding with the disposition the gate worked out, and what you do with it:")
        for gid, f, disp in rows[:200]:
            L.append("- %s [%s] %s %s at %s (run %s, commit %s): \"%s\" -> %s %s" % (
                gid, disp, f.get("severity"), f.get("topic"), f.get("citation"), f.get("last_run"),
                str(f.get("commit"))[:12], str(f.get("quote"))[:160], disp, DISPOSITION_RULE[disp]))
        L.append("A new finding on text that has not changed since the last run is marked late by the gate; it still "
                 "counts at its severity.")
    ins = carries_in(st, label, active)
    L += ["", "## Carried into this phase"]
    if not ins:
        L.append("- (none)")
    else:
        L.append("The phase's COVERAGE.md must list each one (`- CARRY-...: [section](doc.md#anchor)` or `N/A: "
                 "<reason>`). Check each: left unsettled -> MAJOR with topic set to the carry id; cannot be settled "
                 "here -> BLOCKER. Also ask: should it have been decided earlier? If yes, raise a MAJOR \"decided too "
                 "late\" on the carry id, naming the decides rule it falls under. List every carry id under "
                 "topics_checked.")
        for cid, c in ins:
            L.append("- %s (from phase %s, rule %s, class %s): \"%s\" at %s, commit %s. Fix asked: %s" % (
                cid, c.get("from"), c.get("rule"), c.get("class"), str(c.get("quote"))[:200], c.get("citation"),
                str(c.get("commit"))[:12], str(c.get("fix"))[:200]))
    return L


# ------------------------------------------------------------------ the ledger's carry lines
def carries_out(root, st, label, run, ev, active):
    """The CARRY findings of the phase's current run that may carry, as ledger items."""
    if not run or not isinstance(ev, dict):
        return []
    uncarried = set((st or {}).get("_uncarried") or [])
    pre = prefix(st, label)
    have = [c for c in carries(st) if c.startswith("CARRY-%s-" % pre)]
    n = max([int(CARRY_ID.match(c).group("n")) for c in have if CARRY_ID.match(c)] or [0])
    prios = story_priorities(root, st)
    out = []
    items = [(run["map"].get(str(f.get("id"))), f) for f in ev.get("findings") or []
             if isinstance(f, dict) and f.get("severity") == CARRY]
    # 0.7.2 (task-tracker MF-21): a CARRY of an earlier run that the next brief marked [carried] (so the
    # critic rightly did not raise it again) is recorded too, from the archive, with its text at that run.
    seen = {g for g, _f in items} | set(run["map"].values())
    _r, reg = latest_run(root, st, label)
    for gid, disp in [(g, d) for g, _x, d in dispositions(root, st, label, run.get("commit"), active)]:
        if disp == "carried" and gid not in seen:
            r = reg["findings"][gid]
            items.append((gid, {"id": gid, "topic": r.get("topic"), "severity": CARRY, "quote": r.get("quote"),
                                "citation": r.get("citation"), "fix": r.get("fix") or "(see the earlier run)",
                                "defer_rule": r.get("defer_rule"), "to": r.get("to"), "class": r.get("class"),
                                "ac": r.get("ac"), "_commit": r.get("commit")}))
    for gid, f in items:
        if not gid or gid in uncarried or carry_problems(root, st, label, f, prios):
            continue
        n += 1
        to = str(f.get("to"))
        out.append({"id": "CARRY-%s-%d" % (pre, n), "gc": gid, "from": str(label), "to": to,
                    "rule": str(f.get("defer_rule")), "class": str(f.get("class")), "topic": str(f.get("topic")),
                    "quote": str(f.get("quote") or "")[:600], "citation": str(f.get("citation") or ""),
                    "fix": str(f.get("fix") or "")[:600], "commit": f.get("_commit") or run.get("commit")})
    return out


def carries_closing(st, label, ev, active):
    """Carries addressed to this phase that its APPROVE closes: the critic raised no finding on them."""
    raised = {str(f.get("topic")) for f in (ev or {}).get("findings") or [] if isinstance(f, dict)}
    return [cid for cid, _c in carries_in(st, label, active) if cid not in raised]
