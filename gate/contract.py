"""The cross-phase contract (increment 7; docs/AMENDMENT-3.md sections 1-3).

Every phase (Baseline and feature cycles too) leaves, beside its documents:

  sdlc/<label>/COVERAGE.md    every topic ID of the phase, each with a section anchor
                              ([text](doc.md#anchor)) or `N/A: <reason>`
  sdlc/<label>/DISCOVERY.md   the operator's answers, one question at a time, as Q-n
  sdlc/<label>/adr/ADR-nnn-*.md   MADR-style decision records

(in a feature cycle the same files live under sdlc/features/<id>/<label>/). The gate's
linters check them; the agent may run them for feedback, but only the gate's run counts:

  coverage-lint   every topic present once, anchors resolve to a section that is not
                  hollow, N/A reasons real; the size rule's defaults and what it turns on
  discovery-lint  the log exists; each Q-n has 2-4 options, a recommendation, a choice
  adr-lint        the MADR schema (context, >=2 alternatives, criteria, decision,
                  consequences, sources with URL and date)
  trace-lint      every downstream ID points at an existing upstream ID; no dangling
                  references; no ID defined twice; an ID approved once never disappears
  ears-lint       each acceptance criterion matches an EARS template, no vague terms, no
                  compound requirement, an unwanted-behaviour AC per story, every NFR has a
                  number and a unit, a complete role x action matrix with a deny
  cite-lint       every URL carries a date, every research claim carries a source, every
                  link resolves (checked by the gate, cached in .sdlc/cache/links.json)
  critic-schema   CRITIC.json, the gap critic's evidence (gate/config/critic.schema.json)

Output convention (gate/validation.py): FAIL lines block APPROVE, MINOR lines go to the
operator's minor-findings file and never into the summary.

    python3 -I gate/contract.py <lint> <product-root> <phase-label>     (feedback runs)
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

GATE_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG = os.path.join(GATE_DIR, "config", "coverage-topics.yaml")
SCHEMA = os.path.join(GATE_DIR, "config", "critic.schema.json")
GIT = "/usr/bin/git"
OVERRIDES = "coverage-overrides.yaml"  # .sdlc/config/, adopted by the operator (ADOPT)
SIZE_DEFAULT = "size-default"
OPERATOR_NA = "operator"
CRITIC = "gap-critic"
CRITIC_FILE = "CRITIC.json"
CRITIC_SEVERITIES = ("BLOCKER", "MAJOR", "MINOR")
_CACHE: dict = {}

# ------------------------------------------------------------------ catalogue


def _yaml(path):
    sys.path.insert(0, os.path.join(GATE_DIR, "v1"))
    import hlib
    return hlib.load_yaml(path) or {}


def catalogue():
    if "cat" not in _CACHE:
        doc = _yaml(CONFIG)
        if not isinstance(doc.get("phases"), dict) or not doc["phases"]:
            raise ValueError("coverage-topics.yaml has no phases")
        _CACHE["cat"] = doc
    return _CACHE["cat"]


def phase_entry(label):
    return (catalogue()["phases"] or {}).get(str(label))


def gated(label):
    e = phase_entry(label)
    return bool(e) and e.get("gated", True) is not False


def topics(label, feature=False):
    """[(id, title)] of the phase; in a feature cycle the FC topics assigned to it are added."""
    e = phase_entry(label) or {}
    out = [(str(t["id"]), str(t.get("title") or "")) for t in (e.get("topics") or [])]
    if feature:
        for t in (catalogue().get("feature_topics") or {}).get("topics") or []:
            if str(t.get("phase")) == str(label):
                out.append((str(t["id"]), str(t.get("title") or "")))
    return out


def all_topic_ids():
    ids = set()
    for e in catalogue()["phases"].values():
        ids |= {str(t["id"]) for t in e.get("topics") or []}
    ids |= {str(t["id"]) for t in (catalogue().get("feature_topics") or {}).get("topics") or []}
    return ids


# ------------------------------------------------------------------ scope


def doc_dir(st):
    """The repo-relative folder of the scope's documents."""
    if st and st.get("feature"):
        return "sdlc/features/%s" % st["feature"]
    return "sdlc"


def contract_dir(st, label):
    return "%s/%s" % (doc_dir(st), label)


def coverage_rel(st, label):
    return contract_dir(st, label) + "/COVERAGE.md"


def discovery_rel(st, label):
    return contract_dir(st, label) + "/DISCOVERY.md"


def _read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text or "", flags=re.S)


SIZE_RE = re.compile(r"^\s*[-*]\s*\*\*Size:?\*\*:?\s*([SML])\b", re.M | re.I)
RULING_RE = re.compile(r"^\s*[-*]\s*\*\*Target Platform Ruling:?\*\*:?\s*(.+?)\s*$", re.M | re.I)


def _canon_ruling(raw):
    """The ruling as profiles.yaml names it (gate/v1/check_profile.py CANON, the declaring source)."""
    sys.path.insert(0, os.path.join(GATE_DIR, "v1"))
    import check_profile
    return check_profile.CANON.get(raw.upper().replace(" ", "")) or check_profile.CANON.get(raw)


def size_and_ruling(root, st):
    """(size or None, ruling or None) from B19: the BRD's `- **Size:**` and `- **Target
    Platform Ruling:**` fields. A feature cycle reads its own BRD additions first (FC11)."""
    texts = []
    if st and st.get("feature"):
        d = os.path.join(root, doc_dir(st))
        if os.path.isdir(d):
            texts += [_read(root, "%s/%s" % (doc_dir(st), f)) for f in sorted(os.listdir(d)) if re.match(r"^00-.*\.md$", f)]
    texts.append(_read(root, "sdlc/00-brd.md"))
    size = ruling = None
    for t in texts:
        t = _strip_comments(t)
        if size is None:
            m = SIZE_RE.search(t)
            size = m.group(1).upper() if m else None
        if ruling is None:
            m = RULING_RE.search(t)
            ruling = _canon_ruling(m.group(1).strip()) if m else None
    return size, ruling


def overrides(root):
    """The operator's overrides of the size rule (.sdlc/config/coverage-overrides.yaml, written
    only by ADOPT): {"turn_on": set(topic), "na": {topic: reason}}."""
    p = os.path.join(root, ".sdlc", "config", OVERRIDES)
    out = {"turn_on": set(), "na": {}}
    if not os.path.isfile(p):
        return out
    doc = _yaml(p)
    out["turn_on"] = {str(x).strip() for x in (doc.get("turn_on") or [])}
    for e in doc.get("na") or []:
        if isinstance(e, dict) and e.get("topic") and str(e.get("reason") or "").strip():
            out["na"][str(e["topic"]).strip()] = str(e["reason"]).strip()
    return out


def has_mobile(ruling):
    """A ruling plans a mobile client unless its profile rules the store release N/A
    (gate/config/profiles.yaml, `not_applicable` naming check-store-readiness). The default
    profile applies when the ruling is not declared yet."""
    prof = _yaml(os.path.join(GATE_DIR, "config", "profiles.yaml"))
    entry = (prof.get("profiles") or {}).get(ruling or prof.get("default")) or {}
    return not any(str(na.get("validator")) == "check-store-readiness" for na in entry.get("not_applicable") or [])


def _condition_holds(when, ruling):
    if not when:
        return True
    if when == "no-mobile":
        return not has_mobile(ruling)
    # "no-ai" is the default assumption; the operator turns the topic on when the product has AI
    return when == "no-ai"


def defaults(label, size, ruling, ov=None, feature=False):
    """{topic: {"reason", "partial"}} the size rule pre-fills as N/A (partial: only that part is
    N/A and the topic still needs a section), minus the topics the operator turned on."""
    ov = ov or {"turn_on": set(), "na": {}}
    out = {}
    if not size:
        return out
    ids = {t for t, _ in topics(label, feature)}
    for e in ((catalogue().get("sizes") or {}).get(size) or {}).get("na") or []:
        if not _condition_holds(e.get("when"), ruling):
            continue
        targets = [str(e["topic"])] if e.get("topic") else (
            sorted(ids) if str(e.get("phase")) == str(label) else [])
        for t in targets:
            if t in ids and t not in ov["turn_on"]:
                out[t] = {"reason": str(e.get("reason") or "").strip(), "partial": e.get("partial")}
    return out


def turned_on(size, ov=None):
    ov = ov or {"turn_on": set(), "na": {}}
    return list(((catalogue().get("turned_on") or {}).get(size) or [])) if size else []


# ------------------------------------------------------------------ markdown


def slug(heading):
    """GitHub's heading anchor."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.U)
    return s.replace(" ", "-")


HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
EXPLICIT_ANCHOR = re.compile(r"\{#([\w-]+)\}|<a\s+(?:id|name)=[\"']([\w-]+)[\"']")


def _lines_no_code(text):
    """Lines with fenced code blocks blanked (line numbers kept)."""
    out, fence = [], False
    for ln in text.splitlines():
        if re.match(r"^\s*(```|~~~)", ln):
            fence = not fence
            out.append("")
            continue
        out.append("" if fence else ln)
    return out


def sections(text):
    """{anchor: (level, title, start line (1-based), body text)} for every heading."""
    lines = _lines_no_code(_strip_comments(text))
    heads = []
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    out, seen = {}, {}
    for k, (i, lvl, title) in enumerate(heads):
        end = len(lines)
        for j, l2, _t in heads[k + 1:]:
            if l2 <= lvl:
                end = j
                break
        body = "\n".join(lines[i + 1:end])
        anchors = [slug(EXPLICIT_ANCHOR.sub("", title))]
        for a, b in EXPLICIT_ANCHOR.findall(title):
            anchors.append(a or b)
        for a in anchors:
            n = seen.get(a, 0)
            seen[a] = n + 1
            key = a if n == 0 else "%s-%d" % (a, n)
            out.setdefault(key, (lvl, title, i + 1, body))
    for i, ln in enumerate(lines):  # explicit anchors on their own line
        for a, b in EXPLICIT_ANCHOR.findall(ln):
            if not HEADING.match(ln):
                out.setdefault(a or b, (7, a or b, i + 1, "\n".join(lines[i + 1:i + 40])))
    return out


def hollow(body):
    """A section with no real content: nothing but blank lines, headings, placeholders."""
    words = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or HEADING.match(s) or re.match(r"^\|?[\s:|-]+\|?$", s):
            continue
        if re.search(r"\{\{|\bTBD\b|\bTODO\b|lorem ipsum", s, re.I):
            continue
        words += re.findall(r"[A-Za-z0-9]{2,}", s)
    return len(words) < 4


# ------------------------------------------------------------------ coverage-lint

ENTRY = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\**(?P<id>[A-Z]{1,3}\d{1,2})\**\s*(?::|—|–|-)\s*(?P<rest>.*)$")
TABLE_ENTRY = re.compile(r"^\s*\|\s*\**(?P<id>[A-Z]{1,3}\d{1,2})\**\s*\|(?P<rest>.*)$")
LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)")
NA = re.compile(r"^\s*\**N/?A\**\s*(?:(?::|—|–|-|\()\s*(?P<reason>.*?)\)?)?\s*$", re.I)
BOILERPLATE = {"", "n/a", "na", "none", "not applicable", "not relevant", "irrelevant", "not needed", "tbd", "todo",
               "tbc", "-", "--", "...", "same as above", "see above", "as above", "nothing", "no", "skip", "skipped",
               "later", "out of scope", "not in scope", "not required", "does not apply", "not applicable here",
               "n/a for now", "not yet", "nope", "na for this product"}


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", s or "")).strip().lower().rstrip(".")


def parse_coverage(text):
    """[(line no, topic id, rest)] in file order (list items and table rows)."""
    out = []
    for n, ln in enumerate(_lines_no_code(_strip_comments(text)), 1):
        m = ENTRY.match(ln) or TABLE_ENTRY.match(ln)
        if m:
            rest = m.group("rest").strip()
            if TABLE_ENTRY.match(ln):
                rest = " ".join(c.strip() for c in rest.strip("|").split("|") if c.strip())
            out.append((n, m.group("id"), rest))
    return out


def _resolve_anchor(root, base_rel, target, scope_root):
    """(file rel, section or None, problem or None)."""
    if re.match(r"^[a-z]+://", target) or target.startswith("mailto:"):
        return None, None, "%s is an external link; a topic anchors a section of this product's documents" % target
    path, _, anchor = target.partition("#")
    rel = os.path.normpath(os.path.join(os.path.dirname(base_rel), path)) if path else base_rel
    if rel.startswith("..") or not (rel == scope_root or rel.startswith("sdlc/")):
        return rel, None, "%s points outside sdlc/" % target
    text = _read(root, rel)
    if text is None:
        return rel, None, "%s: %s does not exist" % (target, rel)
    if not anchor:
        return rel, None, "%s names no section (#anchor)" % target
    sec = sections(text).get(anchor)
    if sec is None:
        return rel, None, "%s: %s has no section #%s" % (target, rel, anchor)
    return rel, sec, None


def coverage_entries(root, st, label):
    """{topic: {"line", "na": reason|None, "sections": [(rel, sec)], "problems": []}} or None
    when COVERAGE.md is missing. Shared by coverage-lint, cite-lint and ears-lint."""
    rel = coverage_rel(st, label)
    text = _read(root, rel)
    if text is None:
        return None
    out = {}
    for n, tid, rest in parse_coverage(text):
        e = {"line": n, "na": None, "sections": [], "problems": [], "dup": tid in out}
        m = NA.match(rest)
        if m:
            e["na"] = (m.group("reason") or "").strip()
        else:
            links = [x.group("target") for x in LINK.finditer(rest)]
            if not links:
                e["problems"].append("neither a section anchor ([text](doc.md#anchor)) nor `N/A: <reason>`")
            for t in links:
                frel, sec, why = _resolve_anchor(root, rel, t, doc_dir(st))
                if why:
                    e["problems"].append(why)
                else:
                    e["sections"].append((frel, sec))
        if e["dup"]:
            out[tid]["dup"] = True
            out[tid]["problems"].append("listed more than once (line %d and line %d)" % (out[tid]["line"], n))
        else:
            out[tid] = e
    return out


def section_text(entry):
    return "\n".join("%s\n%s" % (sec[1], sec[3]) for _rel, sec in (entry or {}).get("sections") or [])


def coverage_lint(root, st, label):
    """(fails, minors, info)."""
    fails, minors = [], []
    feature = bool(st and st.get("feature"))
    want = topics(label, feature)
    rel = coverage_rel(st, label)
    if not want:
        return ["phase %s has no coverage topics in gate/config/coverage-topics.yaml" % label], [], {}
    ents = coverage_entries(root, st, label)
    if ents is None:
        return ["%s is missing: it lists every topic of phase %s (%s) with a section anchor or `N/A: <reason>`" % (
            rel, label, ", ".join(t for t, _ in want))], [], {"topics": len(want)}
    size, ruling = size_and_ruling(root, st)
    ov = overrides(root)
    dfl = defaults(label, size, ruling, ov, feature)
    ids = [t for t, _ in want]
    for tid in ents:
        if tid not in ids:
            fails.append("%s line %d: %s is not a topic of phase %s" % (rel, ents[tid]["line"], tid, label))
    reasons = {}
    na_count = anchored = 0
    for tid, title in want:
        e = ents.get(tid)
        if e is None:
            fails.append("%s: topic %s (%s) is missing" % (rel, tid, title))
            continue
        for p in e["problems"]:
            fails.append("%s line %d: %s: %s" % (rel, e["line"], tid, p))
        if e["na"] is not None:
            na_count += 1
            r = e["na"]
            nr = _norm(r)
            canned = dfl.get(tid)
            if nr in (SIZE_DEFAULT, _norm(canned["reason"]) if canned else None):
                if not size:
                    fails.append("%s: %s claims the size default, but the BRD declares no size (B19)" % (rel, tid))
                elif tid in ov["turn_on"]:
                    fails.append("%s: %s is N/A by default at size %s, but the operator turned it on "
                                 "(.sdlc/config/%s)" % (rel, tid, size, OVERRIDES))
                elif not canned:
                    fails.append("%s: %s is not N/A by default at size %s%s; give a section or a real reason" % (
                        rel, tid, size, " with ruling %s" % ruling if ruling else ""))
                elif canned.get("partial"):
                    fails.append("%s: at size %s only %s of %s is N/A by default; the topic still needs a section "
                                 "(%s)" % (rel, size, canned["partial"], tid, canned["reason"]))
                continue
            if nr == OPERATOR_NA:
                if tid not in ov["na"]:
                    fails.append("%s: %s says the operator ruled it N/A, but .sdlc/config/%s has no such ruling" % (
                        rel, tid, OVERRIDES))
                continue
            if tid in ov["turn_on"] and tid in {t for t, _ in want}:
                pass  # turned on: a real reason is still a valid N/A only if the topic was not turned on
            if nr in BOILERPLATE or len(re.findall(r"[A-Za-z]{2,}", r)) < 4:
                fails.append("%s: %s N/A reason %r is empty or boilerplate; say why the topic does not apply" % (
                    rel, tid, r))
            elif tid in ov["turn_on"]:
                fails.append("%s: the operator turned %s on (.sdlc/config/%s); it cannot be N/A" % (
                    rel, tid, OVERRIDES))
            reasons.setdefault(nr, []).append(tid)
        else:
            anchored += 1
            for frel, sec in e["sections"]:
                if hollow(sec[3]):
                    fails.append("%s: %s anchors %s#%s (line %d), which is hollow (no content under the heading)" % (
                        rel, tid, frel, slug(sec[1]), sec[2]))
    for _nr, tids in sorted(reasons.items()):
        if len(tids) >= 3:
            fails.append("%s: the same N/A reason is given for %s; a copied reason is boilerplate, give each its own" % (
                rel, ", ".join(tids)))
    for item in turned_on(size, ov):
        tid = str(item.get("topic"))
        if tid not in ids:
            continue
        e = ents.get(tid)
        what = "size %s turns on %s (%s)" % (size, item.get("what"), tid)
        if e is None:
            continue  # already reported as missing
        if e["na"] is not None:
            fails.append("%s: %s, so %s cannot be N/A" % (rel, what, tid))
            continue
        txt = section_text(e)
        chk = item.get("check")
        if chk == "mention" and not re.search(str(item.get("arg")), txt):
            fails.append("%s: %s, and the %s section does not mention it" % (rel, what, tid))
        elif chk == "min_percent":
            nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", txt)]
            if not nums or max(nums) < float(item.get("arg")):
                fails.append("%s: %s, and the %s section states no threshold of at least %s%%" % (
                    rel, what, tid, item.get("arg")))
    info = {"topics": len(want), "anchored": anchored, "na": na_count, "size": size, "ruling": ruling,
            "defaults": sorted(dfl)}
    return fails, minors, info


def skeleton(root, st, label):
    """A COVERAGE.md the agent starts from: every topic, the size rule's defaults pre-filled
    with their canned reason (the operator's rulings too)."""
    feature = bool(st and st.get("feature"))
    size, ruling = size_and_ruling(root, st)
    ov = overrides(root)
    dfl = defaults(label, size, ruling, ov, feature)
    e = phase_entry(label) or {}
    L = ["# Coverage: phase %s (%s)" % (label, e.get("name")), "",
         "<!-- Written by the MOADIX gate from gate/config/coverage-topics.yaml. Size %s, ruling %s. Replace each "
         "TODO with a link to the section that covers the topic ([title](../NN-doc.md#section)) or `N/A: <reason>`. "
         "Pre-filled N/A lines are the size rule's defaults; keep or replace them. -->" % (size or "unknown",
                                                                                          ruling or "unknown"), ""]
    for tid, title in topics(label, feature):
        d = dfl.get(tid)
        if tid in ov["na"]:
            L.append("- %s: N/A: %s  <!-- %s; operator ruling: %s -->" % (tid, OPERATOR_NA, title, ov["na"][tid]))
        elif d and not d.get("partial"):
            L.append("- %s: N/A: %s  <!-- %s -->" % (tid, d["reason"], title))
        elif d:
            L.append("- %s: TODO  <!-- %s; %s -->" % (tid, title, d["reason"]))
        else:
            L.append("- %s: TODO  <!-- %s -->" % (tid, title))
    return "\n".join(L) + "\n"


def skeleton_path(root, st, label):
    return os.path.join(root, ".sdlc", "coverage", "%s-%s-COVERAGE.md" % (
        ("feature-%s" % st["feature"]) if st and st.get("feature") else "product", label))


def write_skeleton(root, st):
    """Gate side (Stop hook, never blocking): keep .sdlc/coverage/<scope>-<label>-COVERAGE.md, the
    pre-filled skeleton of the current phase, up to date with the size rule. The agent copies it
    to sdlc/<label>/COVERAGE.md; .sdlc/ stays gate-written."""
    label = (st or {}).get("current_phase")
    if not label or label == "done" or not gated(label) or not topics(label):
        return None
    p = skeleton_path(root, st, label)
    text = skeleton(root, st, label)
    try:
        with open(p) as f:
            if f.read() == text:
                return p
    except OSError:
        pass
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        f.write(text)
    os.replace(p + ".tmp", p)
    return p


# ------------------------------------------------------------------ discovery-lint

Q_HEAD = re.compile(r"^#{2,4}\s+(Q-(\d+))\b\s*[:—–-]?\s*(.*)$")
OPTION = re.compile(r"^\s*[-*]\s+\**(?:Option\s+)?([A-Z])\**\s*[:).—–-]\s*(.+)$")
RECO = re.compile(r"^\s*[-*]?\s*\**Recommend(?:ation|ed)\**\s*:?\**\s*:?\s*\**([A-D])\b", re.I)
CHOSEN = re.compile(r"^\s*[-*]?\s*\**(?:Chosen|Answer|Operator(?:'s)? (?:choice|answer))\**\s*:?\**\s*:?\s*\**([A-D])\b",
                    re.I)


def discovery_lint(root, st, label):
    rel = discovery_rel(st, label)
    text = _read(root, rel)
    if text is None:
        return ["%s is missing: the phase's questions to the operator, one at a time, logged as Q-n with 2-4 options, "
                "a recommendation and the chosen option (or a line `No questions: <reason>`)" % rel], [], {}
    lines = _lines_no_code(_strip_comments(text))
    qs, cur = [], None
    for n, ln in enumerate(lines, 1):
        m = Q_HEAD.match(ln)
        if m:
            cur = {"id": m.group(1), "line": n, "q": m.group(3).strip(), "opts": [], "reco": None, "chosen": None}
            qs.append(cur)
            continue
        if cur is None:
            continue
        if HEADING.match(ln):
            cur = None
            continue
        o = OPTION.match(ln)
        r = RECO.match(ln)
        c = CHOSEN.match(ln)
        if r:
            cur["reco"] = r.group(1).upper()
        elif c:
            cur["chosen"] = c.group(1).upper()
        elif o:
            cur["opts"].append(o.group(1).upper())
    fails = []
    if not qs:
        m = re.search(r"(?im)^\s*No questions:\s*(.+)$", "\n".join(lines))
        if not m or len(re.findall(r"[A-Za-z]{2,}", m.group(1))) < 4:
            fails.append("%s has no Q-n entry and no `No questions: <reason>` line" % rel)
        return fails, [], {"questions": 0}
    seen = {}
    for q in qs:
        where = "%s line %d: %s" % (rel, q["line"], q["id"])
        if q["id"] in seen:
            fails.append("%s is used twice (line %d); Q-n IDs are never reused" % (where, seen[q["id"]]))
        seen.setdefault(q["id"], q["line"])
        if not q["q"]:
            fails.append("%s states no question" % where)
        opts = q["opts"]
        if len(opts) != len(set(opts)):
            fails.append("%s lists an option letter twice" % where)
        if not 2 <= len(set(opts)) <= 4:
            fails.append("%s has %d options; a question offers 2-4" % (where, len(set(opts))))
        if q["reco"] is None:
            fails.append("%s has no `Recommendation: <letter>`" % where)
        elif q["reco"] not in opts:
            fails.append("%s recommends %s, which is not one of its options" % (where, q["reco"]))
        if q["chosen"] is None:
            fails.append("%s has no chosen option (`Chosen: <letter>`): the operator's answer is not logged" % where)
        elif q["chosen"] not in opts:
            fails.append("%s: chosen %s is not one of its options" % (where, q["chosen"]))
    return fails, [], {"questions": len(qs)}


# ------------------------------------------------------------------ adr-lint

ADR_FILE = re.compile(r"^ADR-(\d{3,4})(?:[-_ ].*)?\.md$")
DATE = re.compile(r"\b(20\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
URL = re.compile(r"https?://[^\s)>\]|\"']+")
ADR_SECTIONS = [
    ("context", r"context(?: and problem statement)?|problem"),
    ("alternatives", r"(?:considered )?(?:options|alternatives)(?: considered)?"),
    ("criteria", r"(?:decision )?(?:criteria|drivers)"),
    ("decision", r"decision(?: outcome)?"),
    ("consequences", r"consequences"),
    ("sources", r"sources|references"),
]


def adr_files(root, st):
    """Repo-relative ADR files of the scope (any sdlc/**/adr/ folder, and sdlc/adr/)."""
    base = doc_dir(st)
    out = []
    for a, dirs, fs in os.walk(os.path.join(root, base)):
        rela = os.path.relpath(a, root)
        if not (st and st.get("feature")) and rela.startswith("sdlc/features"):
            dirs[:] = []
            continue
        if os.path.basename(a) == "adr":
            out += ["%s/%s" % (rela, f) for f in sorted(fs) if ADR_FILE.match(f)]
    return sorted(out)


def _parse_date(s):
    m = DATE.search(s or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def adr_lint(root, st, label=None):
    fails = []
    nums = {}
    files = adr_files(root, st)
    for rel in files:
        text = _read(root, rel) or ""
        num = ADR_FILE.match(os.path.basename(rel)).group(1)
        if num in nums:
            fails.append("%s: ADR-%s is also %s; ADR numbers are never reused" % (rel, num, nums[num]))
        nums.setdefault(num, rel)
        first = next((ln for ln in _lines_no_code(text) if HEADING.match(ln)), "")
        if not re.match(r"^#\s+ADR-%s\b" % num, first):
            fails.append("%s: the title must be `# ADR-%s: <decision>` (found %r)" % (rel, num, first[:60]))
        secs = sections(text)
        bytitle = {}
        for _a, (lvl, title, line, body) in secs.items():
            for key, rx in ADR_SECTIONS:
                if lvl == 2 and re.fullmatch(rx, _norm(title)):
                    bytitle.setdefault(key, (line, body))
        for key, _rx in ADR_SECTIONS:
            if key not in bytitle:
                fails.append("%s: no `## %s` section (MADR)" % (rel, key.capitalize()))
                continue
            body = bytitle[key][1]
            if key == "alternatives":
                items = [ln for ln in body.splitlines() if re.match(r"^\s*(?:[-*]|\d+\.)\s+\S", ln)
                         or re.match(r"^###\s+\S", ln)]
                if len(items) < 2:
                    fails.append("%s: Alternatives lists %d option(s); a decision record compares at least two" % (
                        rel, len(items)))
            elif key == "sources":
                items = [ln for ln in body.splitlines() if re.match(r"^\s*(?:[-*]|\d+\.)\s+\S", ln)]
                if not items:
                    fails.append("%s: Sources is empty; each source has a URL and a date" % rel)
                for ln in items:
                    if not URL.search(ln) or not _parse_date(ln):
                        fails.append("%s: source %r needs a URL and a date (YYYY-MM-DD)" % (rel, ln.strip()[:80]))
            elif hollow(body):
                fails.append("%s: the %s section is hollow" % (rel, key.capitalize()))
        m = re.search(r"(?im)^\s*[-*]?\s*\**Supersedes:?\**:?\s*(ADR-\d+)", text)
        if m and not any(os.path.basename(f).startswith(m.group(1)) for f in files):
            fails.append("%s supersedes %s, which does not exist" % (rel, m.group(1)))
    return fails, [], {"adrs": len(files)}


# ------------------------------------------------------------------ trace-lint

# Amendment 3's trace levels; a definition of a level-k ID must reference at least one
# existing ID of a lower level. BG, NFR, TB and CON are MOADIX's built prefixes (v1).
# A SEC-ID cites its trust boundary (TB-n), as the built threat models do (level 4 < 4.5).
# T- and SR- are NOT checked for upstream: the built documents already use T-nnn for
# tasks (phase 7) and SR-n for shared resources (phase 4), while Amendment 3 uses them
# for threats and store-release items. That conflict awaits the operator's ruling
# (docs/increment-7-report.md); duplicates and dangling references are still checked.
LEVELS = {"B": 0, "BR": 0, "BG": 0, "R": 1, "P": 2, "US": 2, "NFR": 2, "H": 3, "ADR": 3, "TB": 4, "SEC": 4.5, "L": 5,
          "U": 6, "V": 7, "TASK": 8, "TS": 9, "SF": 10, "LV": 11, "RG": 12, "CL": 13, "CON": 13, "RL": 14, "RT": 16,
          "BL": 0, "FC": 0, "T": None, "SR": None}
ROOTS = {"B", "BR", "BG", "BL", "FC", "SF", "NFR", "TB", "CON", "T", "SR"}
PREFIXES = sorted(LEVELS, key=len, reverse=True)
TRACE_ID = re.compile(r"(?<![\w/-])(%s)-(\d{1,4})\b(?!-\w)" % "|".join(PREFIXES))
DEF_HEAD = re.compile(r"^#{1,6}\s+\**(%s)-(\d{1,4})\b" % "|".join(PREFIXES))
DEF_LIST = re.compile(r"^\s*[-*]\s+\*\*(%s)-(\d{1,4})\b" % "|".join(PREFIXES))
DEF_ROW = re.compile(r"^\s*\|\s*\**(%s)-(\d{1,4})\**\s*\|" % "|".join(PREFIXES))
AC_DEF = re.compile(r"^\s*[-*]\s*\*\*(AC-\d+)\b", re.I)
SKIP_FILES = ("COVERAGE.md",)
WEAK = "\x00weak\x00"  # a row of an ID table: a register entry, not the ID's own definition


def trace_docs(root, st):
    """Repo-relative markdown documents of the scope: the product's sdlc/ (feature folders
    excluded), plus, in a feature cycle, the active feature's folder."""
    out = []
    for a, dirs, fs in os.walk(os.path.join(root, "sdlc")):
        rela = os.path.relpath(a, root)
        if rela == "sdlc/features":
            dirs[:] = [d for d in dirs if st and st.get("feature") == d]
        dirs.sort()
        out += ["%s/%s" % (rela, f) for f in sorted(fs) if f.endswith(".md") and f not in SKIP_FILES]
    return out


def _definitions(rel, text):
    """[(id, line, context text)] for the IDs a document defines. A table row defines its first
    cell only in a table whose header's first column is `ID`."""
    lines = _lines_no_code(_strip_comments(text))
    out, story, id_table = [], None, False
    heads = [(i, len(HEADING.match(ln).group(1))) for i, ln in enumerate(lines) if HEADING.match(ln)]

    def section_end(i, lvl):
        for j, l2 in heads:
            if j > i and l2 <= lvl:
                return j
        return len(lines)
    for i, ln in enumerate(lines):
        if re.match(r"^\s*\|", ln):
            if i == 0 or not re.match(r"^\s*\|", lines[i - 1]):
                id_table = bool(re.match(r"^\s*\|\s*\**ID\**\s*\|", ln, re.I))
        else:
            id_table = False
        m = DEF_HEAD.match(ln)
        if m:
            lvl = len(HEADING.match(ln).group(1))
            ident = "%s-%s" % (m.group(1), m.group(2))
            out.append((ident, i + 1, "\n".join(lines[i:section_end(i, lvl)])))
            story = ident if m.group(1) in ("US", "NFR") else (None if lvl <= 2 else story)
            continue
        if HEADING.match(ln) and len(HEADING.match(ln).group(1)) <= 2:
            story = None
        a = AC_DEF.match(ln)
        if a and story:
            out.append(("%s/%s" % (story, a.group(1).upper()), i + 1, ln))
            continue
        m = DEF_LIST.match(ln)
        if m:
            ctx = [ln]
            ind = len(ln) - len(ln.lstrip())
            for ln2 in lines[i + 1:]:
                if ln2.strip() and len(ln2) - len(ln2.lstrip()) <= ind:
                    break
                ctx.append(ln2)
            out.append(("%s-%s" % (m.group(1), m.group(2)), i + 1, "\n".join(ctx)))
            continue
        m = DEF_ROW.match(ln)
        if m and id_table:
            out.append(("%s-%s" % (m.group(1), m.group(2)), i + 1, WEAK + ln))
    return out


def _git(root, *args, timeout=20):
    p = subprocess.run([GIT, "-C", root] + list(args), capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout


def _approved_ids(root, st):
    """{id: commit} for IDs defined in sdlc/ at a commit an earlier phase was approved on."""
    commits = []
    for ph in (st or {}).get("phases") or []:
        c = ph.get("commit")
        if c and c not in commits and ph.get("status") in ("APPROVED", "PROCEED-PAST"):
            commits.append(c)
    for ph in (st or {}).get("product_phases") or []:
        c = ph.get("commit")
        if c and c not in commits and ph.get("status") in ("APPROVED", "PROCEED-PAST"):
            commits.append(c)
    out = {}
    for c in commits:
        rc, files = _git(root, "ls-tree", "-r", "--name-only", c, "--", "sdlc")
        if rc != 0:
            continue
        for rel in files.splitlines():
            if not rel.endswith(".md") or os.path.basename(rel) in SKIP_FILES:
                continue
            if rel.startswith("sdlc/features/") and not (st.get("feature") and
                                                         rel.startswith("sdlc/features/%s/" % st["feature"])):
                continue
            rc2, text = _git(root, "show", "%s:%s" % (c, rel))
            if rc2 == 0:
                for ident, _n, ctx in _definitions(rel, text):
                    if not ctx.startswith(WEAK):
                        out.setdefault(ident, c)
    return out


def trace_lint(root, st, label=None):
    fails = []
    defs = {}
    refs = []
    weak = set()
    docs = trace_docs(root, st)
    for rel in docs:
        text = _read(root, rel) or ""
        for ident, n, ctx in _definitions(rel, text):
            defs.setdefault(ident, []).append((rel, n, ctx))
        for n, ln in enumerate(_lines_no_code(_strip_comments(text)), 1):
            for m in TRACE_ID.finditer(ln):
                refs.append(("%s-%s" % (m.group(1), m.group(2)), rel, n))
    for ident in list(defs):
        strong = [w for w in defs[ident] if not w[2].startswith(WEAK)]
        defs[ident] = strong or [defs[ident][0]]
        if not strong:
            weak.add(ident)  # only in register tables: counted as defined, but not checked for upstream
    for ident, where in sorted(defs.items()):
        if len(where) > 1:
            fails.append("%s is defined %d times (%s); an ID is defined once and never reused" % (
                ident, len(where), ", ".join("%s:%d" % (r, n) for r, n, _c in where[:4])))
    defined_prefixes = {i.split("-", 1)[0] for i in defs if "/" not in i}
    for ident, rel, n in refs:
        pre = ident.split("-", 1)[0]
        if pre in defined_prefixes and ident not in defs and pre not in ("SF",):
            fails.append("%s:%d references %s, which no document defines (dangling)" % (rel, n, ident))
    for ident, where in sorted(defs.items()):
        if "/" in ident:
            continue
        pre = ident.split("-", 1)[0]
        lvl = LEVELS.get(pre)
        if pre in ROOTS or lvl is None or ident in weak:
            continue
        rel, n, ctx = where[0]
        ups = {"%s-%s" % (m.group(1), m.group(2)) for m in TRACE_ID.finditer(ctx)} - {ident}
        ok = [u for u in ups if u in defs and LEVELS.get(u.split("-", 1)[0]) is not None
              and LEVELS[u.split("-", 1)[0]] < lvl]
        if not ok:
            fails.append("%s:%d: %s points at no existing upstream ID (an orphan; it must cite one of %s)" % (
                rel, n, ident, ", ".join(sorted(p for p, v in LEVELS.items() if v is not None and v < lvl))))
    try:
        approved = _approved_ids(root, st)
    except (OSError, subprocess.SubprocessError) as e:
        return fails + ["the approved documents could not be read from git (%s)" % e], [], {}
    for ident, commit in sorted(approved.items()):
        if ident not in defs:
            fails.append("%s was defined when an earlier phase was approved (commit %s) and is gone now; IDs are never "
                         "reused or deleted: keep it and mark it withdrawn" % (ident, commit[:12]))
    return fails, [], {"defined": len(defs), "references": len(refs), "documents": len(docs)}


# ------------------------------------------------------------------ ears-lint

AC_LINE = re.compile(r"^\s*[-*]\s*\*\*(AC-\d+)\s*(?:\(([^)]*)\))?\s*:?\*\*\s*:?\s*(?P<text>.*)$", re.I)
STORY_HEAD = re.compile(r"^#{2,4}\s+(US-\d+)\b")
NFR_HEAD = re.compile(r"^#{2,4}\s+(NFR-\d+)\b")
EARS = [
    ("unwanted", re.compile(r"^(?:while\s+[^,]+,\s*)?if\s+.+?,\s*then\s+(?:the\s+)?\S.*?\s+shall\s+\S", re.I)),
    ("complex", re.compile(r"^while\s+[^,]+,\s*when\s+.+?,\s*(?:the\s+)?\S.*?\s+shall\s+\S", re.I)),
    ("event", re.compile(r"^when\s+.+?,\s*(?:the\s+)?\S.*?\s+shall\s+\S", re.I)),
    ("state", re.compile(r"^while\s+.+?,\s*(?:the\s+)?\S.*?\s+shall\s+\S", re.I)),
    ("optional", re.compile(r"^where\s+.+?,\s*(?:the\s+)?\S.*?\s+shall\s+\S", re.I)),
    ("ubiquitous", re.compile(r"^the\s+\S.*?\s+shall\s+\S", re.I)),
]
VAGUE = re.compile(r"\b(fast|faster|quick|quickly|user[- ]friendly|appropriate|appropriately|etc\.?|tbd|tbc|easy|"
                   r"easily|simple|simply|intuitive|robust|efficient|efficiently|flexible|adequate|reasonable|"
                   r"reasonably|as needed|if possible|as appropriate|seamless|seamlessly|optimal|sufficient|"
                   r"and/or|should|may|might|could|user friendly|modern|nice)\b", re.I)
UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|sec|seconds?|min|minutes?|h|hours?|days?|%|percent|"
                  r"req/s|requests?(?:/s| per second)?|rps|qps|users?|MB|GB|KB|kB|TB|MiB|GiB|items?|concurrent|"
                  r"errors?|x|times|connections?|rows?|records?|bytes?|chars?|characters?|px|pt|:1)\b", re.I)
ALLOW_CELL = re.compile(r"^(?:✓|✔|✅|yes|y|allow|allowed|permit|permitted|own|own only|read|write|r|w|rw|crud)$", re.I)
DENY_CELL = re.compile(r"^(?:✗|✘|❌|×|no|n|deny|denied|forbidden|none|must not)$", re.I)


def prd_docs(root, st):
    base = doc_dir(st)
    d = os.path.join(root, base)
    if not os.path.isdir(d):
        return []
    return ["%s/%s" % (base, f) for f in sorted(os.listdir(d)) if re.match(r"^02-.*\.md$", f)]


def _matrix(root, st, label, docs):
    """The role x action matrix (P3): the table in the section COVERAGE.md anchors for P3, or
    else under a heading naming roles and actions. Returns (rows, where) or (None, why)."""
    body = None
    ents = coverage_entries(root, st, label) or {}
    if ents.get("P3") and ents["P3"]["na"] is None and ents["P3"]["sections"]:
        body = ents["P3"]["sections"][0][1][3]
        where = "%s#%s" % (ents["P3"]["sections"][0][0], slug(ents["P3"]["sections"][0][1][1]))
    else:
        for rel in docs:
            for _a, (_lvl, title, line, sbody) in sections(_read(root, rel) or "").items():
                if re.search(r"role.*(action|permission)|(authori[sz]ation|permission|access)\s+matrix", title, re.I):
                    body, where = sbody, "%s:%d" % (rel, line)
                    break
            if body is not None:
                break
    if body is None:
        return None, "no role x action matrix (P3): a table with a row per role and a column per action"
    rows = [ln for ln in body.splitlines() if re.match(r"^\s*\|", ln)]
    rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\s*\|[\s:|-]+\|?\s*$", r)]
    if len(rows) < 2 or len(rows[0]) < 2:
        return None, "the role x action matrix at %s has no table with roles and actions" % where
    return rows, where


def ears_lint(root, st, label):
    fails, minors = [], []
    docs = prd_docs(root, st)
    baseline = label == "B"
    if not docs:
        return ["no PRD (%s/02-*.md) to check" % doc_dir(st)], [], {}
    acs = []
    stories = {}
    nfrs = []
    for rel in docs:
        lines = _lines_no_code(_strip_comments(_read(root, rel) or ""))
        story = None
        for n, ln in enumerate(lines, 1):
            m = STORY_HEAD.match(ln)
            if m:
                story = m.group(1)
                stories.setdefault(story, [])
                continue
            m = NFR_HEAD.match(ln)
            if m:
                story = None
                body = []
                for ln2 in lines[n:]:
                    if HEADING.match(ln2):
                        break
                    body.append(ln2)
                nfrs.append((m.group(1), rel, n, ln + "\n" + "\n".join(body)))
                continue
            if HEADING.match(ln) and len(HEADING.match(ln).group(1)) <= 2:
                story = None
            a = AC_LINE.match(ln)
            if a and story:
                acs.append((story, a.group(1).upper(), rel, n, a.group("text").strip()))
    out_acs = []
    for story, ac, rel, n, text in acs:
        where = "%s:%d %s/%s" % (rel, n, story, ac)
        plain = re.sub(r"[*_`]", "", text).strip()
        if baseline and re.search(r"\(as-is, not EARS:\s*\S", plain):
            out_acs.append({"ac": "%s/%s" % (story, ac), "template": "as-is", "path": rel, "line": n})
            continue
        kind = next((k for k, rx in EARS if rx.match(plain)), None)
        if not kind:
            fails.append("%s does not match an EARS template (The/When/While/If ... then/Where ..., the <system> "
                         "shall <response>): %r" % (where, plain[:100]))
        v = VAGUE.findall(plain)
        if v:
            fails.append("%s uses vague term(s) %s; state a measurable response" % (where, ", ".join(sorted({x.lower() for x in v}))))
        if len(re.findall(r"\bshall\b", plain, re.I)) > 1:
            fails.append("%s is a compound requirement (more than one `shall`); split it" % where)
        stories.setdefault(story, []).append(kind)
        out_acs.append({"ac": "%s/%s" % (story, ac), "template": kind, "path": rel, "line": n})
    for story, kinds in sorted(stories.items()):
        if not kinds:
            fails.append("%s has no acceptance criteria" % story)
        elif "unwanted" not in kinds and not baseline:
            fails.append("%s has no unwanted-behaviour AC (`If <condition>, then the <system> shall ...`) (P16)" % story)
    for nid, rel, n, body in nfrs:
        if not UNIT.search(re.sub(r"^#+\s+NFR-\d+", "", body)):
            fails.append("%s:%d %s states no number with a unit (ms, %%, req/s, ...): an NFR must be measurable" % (
                rel, n, nid))
    if not baseline:
        rows, where = _matrix(root, st, label, docs)
        if rows is None:
            fails.append(where)
        else:
            head, body = rows[0], rows[1:]
            deny = 0
            for r in body:
                if len(r) < len(head):
                    r = r + [""] * (len(head) - len(r))
                for c, cell in zip(head[1:], r[1:]):
                    v = re.sub(r"[*_`]", "", cell).strip()
                    if ALLOW_CELL.match(v):
                        continue
                    if DENY_CELL.match(v):
                        deny += 1
                        continue
                    fails.append("role x action matrix (%s): %s / %s is %r; each cell is allow (✓) or deny (✗)" % (
                        where, r[0] or "?", c or "?", cell))
            if not body:
                fails.append("role x action matrix (%s) has no role rows" % where)
            elif deny == 0:
                fails.append("role x action matrix (%s) denies nothing: it must say who must not (P3)" % where)
    return fails, minors, {"acs": out_acs, "stories": len(stories), "nfrs": len(nfrs)}


# ------------------------------------------------------------------ cite-lint

CLAIM_TOPICS = ("R2", "R3", "R4", "R5", "R6", "R7", "R8", "R11", "R12", "R13", "R14")
FOOTNOTE_REF = re.compile(r"\[\^([\w-]+)\]")
FOOTNOTE_DEF = re.compile(r"^\s*\[\^([\w-]+)\]:\s*(.*)$")
LINK_TTL_DAYS = 30
LINK_TIMEOUT = 8.0
LINK_BUDGET = 90.0


def research_docs(root, st):
    base = doc_dir(st)
    out = []
    d = os.path.join(root, base)
    if os.path.isdir(d):
        out += ["%s/%s" % (base, f) for f in sorted(os.listdir(d)) if re.match(r"^01-.*\.md$", f)]
    cd = os.path.join(root, contract_dir(st, "1"))
    for a, _d, fs in os.walk(cd):
        out += [os.path.relpath(os.path.join(a, f), root) for f in sorted(fs)
                if f.endswith(".md") and f not in ("COVERAGE.md", "DISCOVERY.md")]
    return out


def links_cache(root):
    return os.path.join(root, ".sdlc", "cache", "links.json")


def _load_links(root):
    try:
        with open(links_cache(root)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _probe(url):
    """HTTP status, or None when the host could not be reached (unknown, never a pass)."""
    if not re.match(r"^https?://", url):
        return None
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "moadix-cite-lint/1"})  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=LINK_TIMEOUT) as r:  # noqa: S310 (http/https only, checked)
                return int(r.status)
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return int(e.code)
        except (urllib.error.URLError, OSError, ValueError):
            if method == "HEAD":
                continue
            return None
    return None


def resolve_links(root, urls, write):
    """{url: status or None}. A gate run probes URLs not checked in the last LINK_TTL_DAYS and
    records them in .sdlc/cache/links.json; a feedback run reads the cache only."""
    cache = _load_links(root)
    now = time.time()
    out, changed = {}, False
    t0 = time.time()
    for u in sorted(set(urls)):
        e = cache.get(u) or {}
        if e.get("status") and now - float(e.get("checked") or 0) < LINK_TTL_DAYS * 86400:
            out[u] = int(e["status"])
            continue
        if not write or time.time() - t0 > LINK_BUDGET:
            out[u] = None
            continue
        st = _probe(u)
        out[u] = st
        if st is not None:
            cache[u] = {"status": st, "checked": now}
            changed = True
    if write and changed:
        p = links_cache(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump(cache, f, indent=1, sort_keys=True)
        os.replace(p + ".tmp", p)
    return out


def cite_lint(root, st, label="1", write_cache=False, today=None):
    """(fails, minors, info, unknown): unknown lists links whose status could not be learned."""
    fails, minors = [], []
    today = today or datetime.date.today()
    docs = research_docs(root, st)
    if not docs:
        if st and st.get("feature"):  # a feature's research additions are optional (Amendment 2, as built)
            return [], [], {"documents": 0}, []
        return ["no research document (%s/01-*.md) to check" % doc_dir(st)], [], {}, []
    urls = []
    footdefs = {}
    for rel in docs:
        lines = _lines_no_code(_strip_comments(_read(root, rel) or ""))
        for n, ln in enumerate(lines, 1):
            m = FOOTNOTE_DEF.match(ln)
            if m:
                footdefs[m.group(1)] = (rel, n, m.group(2))
            for u in URL.findall(ln):
                u = u.rstrip(".,;:")
                urls.append((u, rel, n))
                d = _parse_date(ln)
                if d is None and not (m and _parse_date(m.group(2))):
                    fails.append("%s:%d: %s has no retrieval date (YYYY-MM-DD) on its line" % (rel, n, u))
                elif d and d > today:
                    fails.append("%s:%d: the date %s is in the future" % (rel, n, d.isoformat()))
    for key, (rel, n, txt) in sorted(footdefs.items()):
        if not URL.search(txt) or not _parse_date(txt):
            fails.append("%s:%d: source [^%s] needs a URL and a date" % (rel, n, key))
    ents = coverage_entries(root, st, "1") or {}
    claims = 0
    for tid in CLAIM_TOPICS:
        e = ents.get(tid)
        if not e or e["na"] is not None:
            continue
        for frel, sec in e["sections"]:
            for k, ln in enumerate(sec[3].splitlines()):
                s = ln.strip()
                is_item = re.match(r"^(?:[-*]|\d+\.)\s+\S", s) or (re.match(r"^\|", s) and
                                                                     not re.match(r"^\|[\s:|-]+\|?$", s))
                if not is_item:
                    continue
                if re.match(r"^\|", s) and k + 1 < len(sec[3].splitlines()) and \
                        re.match(r"^\s*\|[\s:|-]+\|?\s*$", sec[3].splitlines()[k + 1]):
                    continue  # table header
                claims += 1
                ok = bool(URL.search(s) and _parse_date(s))
                for fn in FOOTNOTE_REF.findall(s):
                    if fn in footdefs and URL.search(footdefs[fn][2]) and _parse_date(footdefs[fn][2]):
                        ok = True
                if not ok:
                    sev = "legal" if tid == "R4" else "cost" if tid == "R7" else "research"
                    fails.append("%s line %d (%s): this %s claim has no source with a URL and a date: %r" % (
                        frel, sec[2] + k + 1, tid, sev, s[:90]))
    status = resolve_links(root, [u for u, _r, _n in urls], write_cache)
    unknown = []
    for u, rel, n in urls:
        code = status.get(u)
        if code is None:
            unknown.append("%s:%d %s" % (rel, n, u))
        elif code in (404, 410) or code >= 500:
            fails.append("%s:%d: %s does not resolve (HTTP %d)" % (rel, n, u, code))
    return fails, minors, {"urls": len(urls), "claims": claims, "documents": len(docs)}, unknown


# ------------------------------------------------------------------ critic schema


def schema():
    if "schema" not in _CACHE:
        with open(SCHEMA) as f:
            _CACHE["schema"] = json.load(f)
    return _CACHE["schema"]


def _type_ok(v, t):
    return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
            "integer": isinstance(v, int) and not isinstance(v, bool), "boolean": isinstance(v, bool)}.get(t, False)


def validate_schema(v, s, where="CRITIC.json"):
    """The JSON Schema subset critic.schema.json uses: type, required, properties,
    additionalProperties false, enum, pattern, minLength, maxLength, items, maxItems,
    uniqueItems."""
    out = []
    if "type" in s and not _type_ok(v, s["type"]):
        return ["%s is not of type %s" % (where, s["type"])]
    if "enum" in s and v not in s["enum"]:
        out.append("%s is %r, not one of %s" % (where, v, ", ".join(map(str, s["enum"]))))
    if isinstance(v, str):
        if "minLength" in s and len(v.strip()) < s["minLength"]:
            out.append("%s is empty" % where if s["minLength"] == 1 else "%s is too short" % where)
        if "maxLength" in s and len(v) > s["maxLength"]:
            out.append("%s is longer than %d characters" % (where, s["maxLength"]))
        if "pattern" in s and not re.search(s["pattern"], v):
            out.append("%s %r does not match %s" % (where, v[:60], s["pattern"]))
    if isinstance(v, dict):
        for k in s.get("required") or []:
            if k not in v:
                out.append("%s has no %r" % (where, k))
        props = s.get("properties") or {}
        if s.get("additionalProperties") is False:
            extra = sorted(set(v) - set(props))
            if extra:
                out.append("%s has keys the schema does not allow: %s (findings only, never a verdict)" % (
                    where, ", ".join(extra)))
        for k, sub in props.items():
            if k in v:
                out += validate_schema(v[k], sub, "%s.%s" % (where, k))
    if isinstance(v, list):
        if "maxItems" in s and len(v) > s["maxItems"]:
            out.append("%s has more than %d items" % (where, s["maxItems"]))
        if s.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
            out.append("%s has duplicate items" % where)
        if "items" in s:
            for i, x in enumerate(v):
                out += validate_schema(x, s["items"], "%s[%d]" % (where, i))
    return out


def _quote_in(root, hd, citation, quote):
    m = re.match(r"^(?P<path>[^:\s][^:]*):(?P<a>\d+)(?:-(?P<b>\d+))?$", citation or "")
    if not m:
        return False
    rc, text = _git(root, "show", "%s:%s" % (hd, m.group("path")))
    if rc != 0:
        return False
    lines = text.splitlines()
    a, b = int(m.group("a")), int(m.group("b") or m.group("a"))
    win = " ".join(lines[max(0, a - 3):min(len(lines), b + 2)])

    def norm(s):
        return re.sub(r"\s+", " ", re.sub(r"[*_`>|#]", " ", s)).strip().lower()
    return norm(quote) in norm(win)


def critic_check(root, st, label, ev, hd, citation_problem, active_waivers):
    """(problems, blocking, info) for the gap critic's CRITIC.json: the schema, every topic of
    the phase checked, each finding's topic one of them, its citation resolving at HEAD and
    its quote found there. BLOCKERs block; MAJORs block unless WAIVEd (`gap-critic.<topic>`);
    MINORs go to the operator's file."""
    probs = validate_schema(ev, schema())
    feature = bool(st and st.get("feature"))
    want = {t for t, _ in topics(label, feature)}
    if ev.get("phase") != str(label):
        probs.append("phase %r, expected %r" % (ev.get("phase"), str(label)))
    checked = set(ev.get("topics_checked") or []) if isinstance(ev.get("topics_checked"), list) else set()
    miss = sorted(want - checked)
    if miss:
        probs.append("topics_checked misses %s: a gap critic checks every topic of the phase" % ", ".join(miss))
    blocking, majors, minors, waived = [], [], [], []
    for i, f in enumerate(ev.get("findings") or []):
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "#%d" % (i + 1))
        tid = str(f.get("topic") or "")
        if tid not in want:
            probs.append("finding %s: topic %r is not a topic of phase %s" % (fid, tid, label))
        why = citation_problem(f.get("citation"))
        if why:
            probs.append("finding %s: %s" % (fid, why))
        elif f.get("quote") and not _quote_in(root, hd, str(f.get("citation")), str(f.get("quote"))):
            probs.append("finding %s: its quote is not at %s (evidence must quote the document)" % (
                fid, f.get("citation")))
        sev = f.get("severity")
        line = "%s %s (%s): %s" % (sev, fid, tid, str(f.get("quote") or "")[:100])
        if f.get("fix"):
            line += " -> fix: %s" % str(f["fix"])[:120]
        if sev == "BLOCKER":
            blocking.append(line)
        elif sev == "MAJOR":
            if "%s.%s" % (CRITIC, tid) in active_waivers:
                waived.append(line)
            else:
                majors.append(line)
        elif sev == "MINOR":
            minors.append(line)
    info = {"blockers": blocking, "majors": majors, "minors": minors, "waived": waived,
            "topics": len(want), "findings": len(ev.get("findings") or [])}
    return probs, blocking + ["%s (WAIVE %s.%s with a reason, or fix it)" % (m, CRITIC, m.split("(", 1)[1].split(")")[0])
                              for m in majors], info


# ------------------------------------------------------------------ the phase's lints


def lints_for(label, feature=False):
    """The lints the gate runs for a phase (in this order)."""
    out = ["coverage", "discovery", "adr", "trace"]
    if label in ("2", "B"):
        out.append("ears")
    if label == "1":
        out.append("cite")
    return out


def run(root, st, label, which=None, write_cache=False):
    """[(lint, fails, minors, info, unknown)]."""
    feature = bool(st and st.get("feature"))
    out = []
    for lint in which or lints_for(label, feature):
        unknown = []
        if lint == "coverage":
            f, m, i = coverage_lint(root, st, label)
        elif lint == "discovery":
            f, m, i = discovery_lint(root, st, label)
        elif lint == "adr":
            f, m, i = adr_lint(root, st, label)
        elif lint == "trace":
            f, m, i = trace_lint(root, st, label)
        elif lint == "ears":
            f, m, i = ears_lint(root, st, label)
        elif lint == "cite":
            f, m, i, unknown = cite_lint(root, st, label, write_cache=write_cache)
        else:
            raise ValueError("unknown lint %r" % lint)
        out.append((lint, f, m, i, unknown))
    return out


def coverage_doc():
    """commands/coverage.md, generated from the catalogue (tests/inc7 checks the file matches)."""
    cat = catalogue()
    L = ["---",
         "description: How the MOADIX cross-phase contract works in every phase (COVERAGE.md, DISCOVERY.md, ADRs, the "
         "gap critic, the size rule) and the coverage topics of each phase. Changes no gate state.",
         "---",
         "<!-- Generated from gate/config/coverage-topics.yaml by gate/contract.py coverage_doc(). Do not edit. -->",
         "Every phase (Baseline and feature cycles too) leaves three things beside its documents, in `sdlc/<label>/` "
         "(`sdlc/features/<id>/<label>/` in a feature cycle). The gate checks them; your own runs are feedback only.",
         "",
         "1. **Discovery, one question at a time.** Ask the operator one question per message, with 2-4 options and "
         "your recommendation. Log each answer in `DISCOVERY.md`:",
         "",
         "   ```",
         "   ## Q-1: <the question>",
         "   - A: <option>",
         "   - B: <option>",
         "   Recommendation: B, <why>",
         "   Chosen: B",
         "   ```",
         "",
         "   If the phase raises no question, write `No questions: <why>`. Q-n IDs are never reused.",
         "2. **Coverage.** `COVERAGE.md` lists every topic ID of the phase (below), each as `- <ID>: [title](../NN-doc.md"
         "#section)` pointing at the section that covers it, or `- <ID>: N/A: <reason>`. coverage-lint refuses a "
         "missing or duplicated ID, an anchor that does not resolve, a hollow section, and an empty, boilerplate or "
         "copied reason. The gate keeps a pre-filled skeleton at `.sdlc/coverage/<scope>-<label>-COVERAGE.md`: copy "
         "it and fill it in.",
         "3. **Decision records.** Each decision is `adr/ADR-nnn-<slug>.md` (MADR): `# ADR-nnn: <decision>`, then "
         "`## Context`, `## Alternatives` (at least two), `## Criteria`, `## Decision`, `## Consequences`, "
         "`## Sources` (each with a URL and a date, YYYY-MM-DD). A superseding record says `Supersedes: ADR-nnn`.",
         "",
         "**Trace IDs.** Every downstream ID cites an existing upstream ID in its own section or item (trace-lint): "
         "B-/BR-/BG- -> R- -> P-/US-(/AC-) -> H-/ADR- -> SEC- -> L- -> U- -> V- -> TASK- -> TS- -> LV-/RG-/CL- -> "
         "RL- -> RT-. An ID is defined once (a heading or a bold list item; a row of a table whose first column is "
         "`ID` is a register entry), never reused, and never deleted once a phase was approved: mark it withdrawn.",
         "",
         "**Phase 2** (ears-lint): each acceptance criterion is EARS (`The <system> shall ...`, `When <trigger>, the "
         "<system> shall ...`, `While <state>, ...`, `If <condition>, then the <system> shall ...`, `Where <feature>, "
         "...`), one `shall`, no vague words (fast, user-friendly, appropriate, etc., TBD, should, ...); every story "
         "has an `If ..., then ...` AC; every NFR has a number and a unit; the role x action matrix (P3) marks every "
         "cell allow or deny and denies something. **Phase 1** (cite-lint): every URL carries a retrieval date on its "
         "line, every research claim has a source, and every link resolves.",
         "",
         "**The gap critic.** When the phase is committed, launch `moadix:gap-critic` (the gate writes its brief). Its "
         "findings are BLOCKER (refuses APPROVE, cannot be waived), MAJOR (refuses APPROVE until the operator types "
         "`WAIVE gap-critic.<topic> owner=... expiry=... reason=...`) or MINOR (a file for the operator). Fix the "
         "documents, commit, and launch it again. It never passes a phase.",
         "",
         "**The size rule.** The size and platform ruling come from B19 (the BRD's `- **Size:**` and `- **Target "
         "Platform Ruling:**`). Topics N/A by default at that size may stay `N/A: size-default` (the skeleton fills "
         "in the canned reason); `partial` defaults still need a section. The operator can turn a default back on or "
         "rule a topic N/A through `ADOPT` of `.sdlc-proposals/config/coverage-overrides.yaml` (`turn_on: [ID]`, "
         "`na: [{topic: ID, reason: ...}]`); then write `N/A: operator`.",
         ""]
    for size in ("S", "M", "L"):
        z = (cat.get("sizes") or {}).get(size) or {}
        na = []
        for e in z.get("na") or []:
            t = e.get("topic") or "all of phase %s" % e.get("phase")
            if e.get("partial"):
                t += " (%s only)" % e["partial"]
            if e.get("when"):
                t += " if %s" % str(e["when"]).replace("-", " ")
            na.append(t)
        on = ", ".join("%s (%s)" % (x.get("what"), x.get("topic")) for x in (cat.get("turned_on") or {}).get(size) or [])
        L.append("- **%s** (%s). N/A by default: %s. Turned on: %s." % (
            size, z.get("profile"), ", ".join(na) or "none", on or "nothing"))
    L += ["", "## Topics per phase", ""]
    for label, e in cat["phases"].items():
        L.append("### Phase %s %s (role: %s)%s" % (label, e.get("name"), e.get("role"), "" if e.get("gated", True)
                                                  is not False else ", not gated in MOADIX (no APPROVE 12)"))
        L += ["", " · ".join("%s %s" % (t["id"], t["title"]) for t in e.get("topics") or []), ""]
        if e.get("blockers"):
            L += ["Critic BLOCKER: %s" % e["blockers"], ""]
    ft = cat.get("feature_topics") or {}
    L += ["### Feature cycles (each in the feature's COVERAGE.md of the phase shown)", "",
          " · ".join("%s %s (phase %s)" % (t["id"], t["title"], t["phase"]) for t in ft.get("topics") or []), "",
          "Critic BLOCKER: %s" % ft.get("blockers"), ""]
    return "\n".join(L)


def main(argv):
    if len(argv) == 1 and argv[0] == "doc":
        sys.stdout.write(coverage_doc())
        return 0
    if len(argv) != 3:
        print("usage: contract.py <coverage|discovery|adr|trace|ears|cite|skeleton> <product-root> <phase-label>")
        return 2
    lint, root, label = argv
    sys.path.insert(0, os.path.dirname(GATE_DIR))
    from gate import state
    st, problems = state.current_state(root)
    if problems:
        print("UNKNOWN gate state failed its integrity check: %s" % "; ".join(problems))
        return 2
    if lint == "skeleton":
        sys.stdout.write(skeleton(root, st, label))
        return 0
    bad = 0
    for name, fails, minors, _info, unknown in run(root, st, label, [lint]):
        for x in fails:
            print("FAIL %s-lint: %s" % (name, x))
        for x in minors:
            print("MINOR %s-lint: %s" % (name, x))
        for x in unknown:
            print("UNKNOWN %s-lint: link status not known yet (the gate's run checks it): %s" % (name, x))
        bad += len(fails)
    if not bad:
        print("OK %s-lint: phase %s" % (lint, label))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
