"""hlib — shared primitives for the SDLC harness control layer.

MOADIX v2 change notice: ported from sdlc-harness v1 harness/lib/hlib.py; re-rooted at
the product repo (project_root, config_path, load_phase_doc, load_paths_doc).

Dependency-free by design: the gate hooks must run even when PyYAML, uv, or a
virtualenv is unavailable. A hook that cannot import its own library fails
CLOSED, so every dependency here is a liability. Stdlib only.

Supports the YAML subset the harness actually uses:
  - nested mappings
  - lists of scalars and lists of mappings
  - quoted / unquoted scalars, ints, bools, null
  - '#' comments and blank lines
It is NOT a general YAML parser and will raise on anything outside that subset,
which is deliberate: silently misparsing a gate config is worse than failing.
"""

import os
import re

HARNESS_VERSION = "0.1.0"


# --------------------------------------------------------------------------
# YAML subset parser
# --------------------------------------------------------------------------

class YamlError(ValueError):
    pass


def _split_flow(body):
    """Split an inline flow sequence body on commas outside quotes."""
    out, cur, quote = [], [], None
    for c in body:
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c; cur.append(c)
        elif c == ",":
            out.append("".join(cur)); cur = []
        else:
            cur.append(c)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def _unquote(tok):
    """The value of a quoted scalar (F64).

    Inside double quotes only `\\"` is an escape: it is the one `_emit_scalar`
    writes, and without decoding it a string containing a quote never read back as
    written. Every other backslash stays as it is, because the harness's configs
    keep regexes in double quotes (phase-paths.yaml's front doors, `\\.`) and read
    them raw. Inside single quotes a doubled quote is one quote, as in YAML.
    """
    body = tok[1:-1]
    if tok[0] == "'":
        return body.replace("''", "'")
    return body.replace('\\"', '"')


def _scalar(tok):
    tok = tok.strip()
    if tok == "" or tok == "~" or tok == "null":
        return None
    # Inline flow sequence: ["--phase", "0"] / [a, b]. Without this, `args:` and
    # `requires:` parsed as literal strings -- args broke validator dispatch and
    # requires was silently wrong (nothing read it, so it went unnoticed).
    if len(tok) >= 2 and tok[0] == "[" and tok[-1] == "]":
        inner = tok[1:-1].strip()
        if inner == "":
            return []
        return [_scalar(x) for x in _split_flow(inner)]
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
        return _unquote(tok)
    if tok in ("true", "True", "yes"):
        return True
    if tok in ("false", "False", "no"):
        return False
    if re.match(r"^-?\d+$", tok):
        return int(tok)
    return tok


def _strip_comment(line):
    """Remove a trailing '#' comment that is not inside quotes."""
    out = []
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            out.append(c)
            # F64: an escaped quote inside double quotes does not end the string.
            if quote == '"' and c == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            out.append(c)
        elif c == "#" and (i == 0 or line[i - 1] in (" ", "\t")):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _value_starts(before):
    """True when a quote right after `before` starts a quoted scalar: a value's first character."""
    b = before.rstrip()
    return b == "" or b.endswith((":", "[", ",")) or b == "-" or b.endswith(" -")


def _quote_open(line):
    """True when `line` ends inside a quoted scalar (A-50, second patch).

    YAML lets a single- or double-quoted scalar run onto the next lines; authz-matrix.yaml's
    `note:` does. A quote opens one only where a value starts, so an apostrophe inside a plain
    scalar ("the store's") opens nothing. Inside single quotes `''` is an escaped quote, so
    the scalar stays open across it.
    """
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if quote == "'" and c == "'" and i + 1 < len(line) and line[i + 1] == "'":
                i += 2
                continue
            if quote == '"' and c == "\\" and i + 1 < len(line):
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"') and _value_starts(line[:i]):
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in (" ", "\t")):
            return False
        i += 1
    return quote is not None


def _lines(text):
    out = []
    raws = text.splitlines()
    k = 0
    while k < len(raws):
        raw = raws[k]
        k += 1
        # A quoted scalar that runs on is read as one line, folded as YAML folds it: a line
        # break and the next line's indent become one space, an empty line a newline.
        while _quote_open(raw) and k < len(raws):
            nxt = raws[k].strip()
            k += 1
            raw = raw.rstrip() + ("\n" if nxt == "" else " " + nxt)
        if _quote_open(raw):
            raise YamlError("unterminated quoted scalar at %r" % raw.strip()[:60])
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        out.append((indent, line.strip()))
    return out


def _parse_block(rows, i, indent):
    """Parse a block at the given indent. Returns (value, next_index)."""
    if i >= len(rows):
        return None, i
    if rows[i][1].startswith("- "):
        return _parse_list(rows, i, indent)
    return _parse_map(rows, i, indent)


def _parse_list(rows, i, indent):
    items = []
    while i < len(rows):
        ind, txt = rows[i]
        if ind < indent or not txt.startswith("- "):
            break
        if ind > indent:
            raise YamlError("unexpected indent in list at %r" % txt)
        body = txt[2:].strip()
        i += 1
        if ":" in body and not _looks_scalar(body):
            # inline first key of a mapping item, e.g. "- id: 0"
            sub = [(ind + 2, body)]
            while i < len(rows) and rows[i][0] > ind:
                sub.append(rows[i])
                i += 1
            val, _ = _parse_map(sub, 0, ind + 2)
            items.append(val)
        elif body == "":
            sub = []
            while i < len(rows) and rows[i][0] > ind:
                sub.append(rows[i])
                i += 1
            if sub:
                val, _ = _parse_block(sub, 0, sub[0][0])
                items.append(val)
            else:
                items.append(None)
        else:
            items.append(_scalar(body))
    return items, i


def _looks_scalar(body):
    """True when 'a: b' is really a quoted scalar like '"http://x"'."""
    b = body.strip()
    return len(b) >= 2 and b[0] == b[-1] and b[0] in ("'", '"')


def _parse_map(rows, i, indent):
    out = {}
    while i < len(rows):
        ind, txt = rows[i]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError("unexpected indent at %r" % txt)
        if txt.startswith("- "):
            break
        if ":" not in txt:
            raise YamlError("expected 'key: value' at %r" % txt)
        key, _, rest = txt.partition(":")
        key = key.strip()
        # A quoted key keeps its quotes otherwise: '"WEB→APP": {...}' produced the
        # key '"WEB→APP"', so every lookup missed. Keys need the same unquoting
        # values already got.
        if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
            key = key[1:-1]
        rest = rest.strip()
        i += 1
        if rest == "":
            sub = []
            while i < len(rows) and rows[i][0] > ind:
                sub.append(rows[i])
                i += 1
            # a list may sit at the SAME indent as its key (common YAML style)
            if not sub:
                # ... with each item's own lines, deeper than the dash, going with it
                # ("- operation: x" then "  surface: tenant": authz-matrix.yaml, A-50).
                while i < len(rows) and ((rows[i][0] == ind and rows[i][1].startswith("- ")) or (rows[i][0] > ind and sub)):
                    sub.append(rows[i])
                    i += 1
            if sub:
                val, _ = _parse_block(sub, 0, sub[0][0])
                out[key] = val
            else:
                out[key] = None
        elif rest in (">", ">-", ">+", "|", "|-", "|+"):
            # Block scalar. Folded (>) joins continuation lines with spaces;
            # literal (|) keeps newlines. A trailing '-' strips the final
            # newline. Added in v0.3 for harness/config/profiles.yaml, whose
            # requirement text is genuinely multi-line prose.
            body = []
            while i < len(rows) and rows[i][0] > ind:
                body.append(rows[i][1])
                i += 1
            if rest.startswith(">"):
                out[key] = " ".join(body).strip()
            else:
                out[key] = "\n".join(body)
        elif rest == "[]":
            out[key] = []
        elif rest == "{}":
            out[key] = {}
        else:
            out[key] = _scalar(rest)
    return out, i


def parse_yaml(text):
    rows = _lines(text)
    if not rows:
        return {}
    val, _ = _parse_block(rows, 0, rows[0][0])
    return val


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return parse_yaml(fh.read())


# --------------------------------------------------------------------------
# YAML emitter (only the shapes we write back)
# --------------------------------------------------------------------------

def _emit_scalar(v, force_str=False):
    if force_str and v is not None:
        return '"%s"' % str(v).replace('"', '\\"')
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{}]|^\s|\s$", s):
        return '"%s"' % s.replace('"', '\\"')
    return s


def dump_yaml(obj, indent=0):
    pad = " " * indent
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict) and v:
                out.append("%s%s:" % (pad, k))
                out.append(dump_yaml(v, indent + 2))
            elif isinstance(v, list):
                if not v:
                    out.append("%s%s: []" % (pad, k))
                else:
                    out.append("%s%s:" % (pad, k))
                    out.append(dump_yaml(v, indent + 2))
            elif isinstance(v, dict):
                out.append("%s%s: {}" % (pad, k))
            else:
                out.append("%s%s: %s" % (pad, k, _emit_scalar(v, force_str=(k == "label"))))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                body = dump_yaml(item, indent + 2)
                first = body.split("\n", 1)
                head = first[0].lstrip()
                out.append("%s- %s" % (pad, head))
                if len(first) > 1:
                    out.append(first[1])
            else:
                out.append("%s- %s" % (pad, _emit_scalar(item)))
    else:
        out.append("%s%s" % (pad, _emit_scalar(obj)))
    return "\n".join(x for x in out if x != "")


# --------------------------------------------------------------------------
# Glob matching (POSIX-ish, '**' crosses '/', '*' does not)
# --------------------------------------------------------------------------

def glob_to_re(pattern):
    i = 0
    out = ["^"]
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return re.compile("".join(out))


_GLOB_CACHE: dict = {}


def glob_match(pattern, path):
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        rx = glob_to_re(pattern)
        _GLOB_CACHE[pattern] = rx
    return bool(rx.match(path))


def any_glob(patterns, path):
    return any(glob_match(p, path) for p in patterns or [])


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def project_root():
    """MOADIX v2 (change notice): the product repo, i.e. the nearest ancestor of
    MOADIX_PRODUCT_ROOT (set by gate/validate.py) or of the cwd that holds
    .sdlc/product.yaml. v1 returned the harness repo and read the product from
    phase-paths.yaml's governed_root; in v2 governed_root is "" (the repo root)."""
    start = os.environ.get("MOADIX_PRODUCT_ROOT") or os.getcwd()
    d = os.path.realpath(start)
    while True:
        if os.path.isfile(os.path.join(d, ".sdlc", "product.yaml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.realpath(start)
        d = parent


# MOADIX v2: where v1's harness/config/* lives now.
#   product config  -> <repo>/.sdlc/config/<name>  (gate-owned, per product)
#   harness config  -> <gate>/config/<name>        (root-owned when installed)
GATE_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PRODUCT_CONFIG = frozenset({
    "product-surface.yaml", "product-tests.yaml", "product-app.yaml", "concurrency.yaml",
    "mobile.yaml", "traceability-exemptions.yaml", "hardcoded-state-exemptions.yaml",
})


def config_path(root, name):
    if name in PRODUCT_CONFIG:
        return os.path.join(root, ".sdlc", "config", name)
    return os.path.join(GATE_DIR, "config", name)


def validator_argv(name, *args):
    """v1 ran harness/bin/<name>.sh; v2 runs the ported module with this interpreter."""
    import sys as _sys
    mod = name[:-3] if name.endswith(".sh") else name
    mod = mod.replace("-", "_")
    if mod == "build_scorecard":
        mod = "build_scorecard"
    return [_sys.executable, os.path.join(os.path.dirname(os.path.realpath(__file__)), mod + ".py")] + list(args)


def rel_to_root(path, root, cwd=None):
    """Normalise any path (absolute or cwd-relative) to a root-relative path.

    Returns None when the path escapes the project root.
    """
    if not path:
        return None
    p = os.path.expanduser(str(path).strip())
    if not os.path.isabs(p):
        base = cwd or root
        p = os.path.join(base, p)
    p = os.path.normpath(p)
    root = os.path.normpath(root)
    # Resolve symlinks on the existing prefix so a symlinked path cannot
    # masquerade as being outside the governed tree.
    probe = p
    while probe != os.path.dirname(probe) and not os.path.exists(probe):
        probe = os.path.dirname(probe)
    if os.path.exists(probe):
        real_probe = os.path.realpath(probe)
        p = os.path.join(real_probe, os.path.relpath(p, probe)) if probe != p else real_probe
        p = os.path.normpath(p)
    root_real = os.path.realpath(root) if os.path.exists(root) else root
    for base in (root, root_real):
        if p == base:
            return "."
        if p.startswith(base + os.sep):
            return os.path.relpath(p, base)
    return None


# --------------------------------------------------------------------------
# Phase model
# --------------------------------------------------------------------------

STATUSES = ("draft", "in-review", "APPROVED")


def load_phase_doc(root):
    """MOADIX v2: v1's phase.yaml shape, derived from the gate's verified state.
    gate/validate.py writes it (MOADIX_PHASE_DOC) after the ledger passed its
    integrity check; outside the gate it is read from .sdlc/phase.yaml."""
    import json as _json
    p = os.environ.get("MOADIX_PHASE_DOC")
    if p and os.path.isfile(p):
        with open(p) as fh:
            return _json.load(fh)
    return v1_phase_doc(load_yaml(os.path.join(root, ".sdlc", "phase.yaml")) or {})


def _ledger_approvals(entries):
    """{phase label: approval facts} from verified ledger bodies (MOADIX v2, increment 3).

    The scorecard used to read these from v1's phase.yaml fields and v1's git
    history. In v2 the signed ledger is the record:
      approval_sha    the APPROVE line's source_commit (the commit the gate's
                      validator run was keyed to)
      approval_dirty  False: the gate refuses to run validators on a dirty tree,
                      so a gate-recorded approval is always from a clean tree
      approval_mode   "interactive": every v2 APPROVE is the operator's typed
                      command with a one-time authenticator code
      evidence        the validator results the APPROVE line carries; source
                      "gate" means the gate ran EVERY validator registered for
                      the phase at that moment, so a registered validator absent
                      from it was registered later
    Imported v1 lines (onlineMarket migration, increment 7) carry
    payload.imported = {"from": "v1", "approval_sha", "approval_dirty",
    "approval_mode", "approver", "evidence": [...], "registered": [...]}; their
    facts are taken as recorded, and a missing field stays unknown.
    A REOPEN clears that phase and every later one, as in the replay."""
    import base64 as _b64
    import json as _json
    out = {}
    order = []
    for e in entries or []:
        verb = str(e.get("action") or "").split(" ", 1)[0]
        try:
            pl = _json.loads(_b64.b64decode(e.get("payload_b64") or "e30=").decode())
        except Exception:
            pl = {}
        label = str(pl.get("phase")) if pl.get("phase") is not None else None
        if verb == "REOPEN" and label in order:
            for lb in order[order.index(label):]:
                out.pop(lb, None)
            order = order[:order.index(label)]
            continue
        if verb != "APPROVE" or label is None:
            continue
        imp = pl.get("imported") if isinstance(pl.get("imported"), dict) else None
        if imp:
            fact = {"approval_sha": imp.get("approval_sha") or "unknown",
                    "approval_dirty": imp.get("approval_dirty") if isinstance(imp.get("approval_dirty"), bool)
                    else "unknown",
                    "approval_mode": imp.get("approval_mode") or "unknown",
                    "approver": imp.get("approver") or "unknown",
                    "evidence": list(imp.get("evidence") or []), "evidence_source": "imported-v1",
                    "registered_at_approval": imp.get("registered"), "ledger_seq": e.get("seq")}
        else:
            val = pl.get("validation") or {}
            fact = {"approval_sha": val.get("commit") or pl.get("source_commit") or "unknown",
                    "approval_dirty": False if val else "unknown",
                    "approval_mode": "interactive", "approver": "operator",
                    "evidence": [{"validator": r.get("validator"), "result": r.get("result"),
                                  "exit_code": r.get("exit_code"), "checked_at": val.get("finished_at")}
                                 for r in (val.get("results") or [])],
                    "evidence_source": "gate" if val else "none", "validation_digest": val.get("digest"),
                    "ledger_seq": e.get("seq")}
        out[label] = fact
        if label in order:
            order.remove(label)
        order.append(label)
    return out


def v1_phase_doc(st):
    """v2 replay state (.sdlc/phase.yaml) -> v1 phase.yaml shape. With the
    verified ledger entries (st["_entries"], set by gate/state.replay) the
    approval facts come from the signed ledger (_ledger_approvals)."""
    facts = _ledger_approvals(st.get("_entries"))
    phases = []
    for i, p in enumerate(st.get("phases") or []):
        status = str(p.get("status") or "draft")
        ph = {"id": int(p.get("id", i)), "label": str(p.get("label")), "name": p.get("name"),
              "status": "APPROVED" if status == "APPROVED" else
                        ("in-review" if status == "PROCEED-PAST" else "draft"),
              "approver": "operator" if status == "APPROVED" else None,
              "timestamp": p.get("at"), "evidence": []}
        if status == "APPROVED" and str(p.get("label")) in facts:
            ph.update(facts[str(p.get("label"))])
        phases.append(ph)
    waivers = []
    for w in st.get("waivers") or []:
        waivers.append({"rule": w.get("rule") or "waiver", "path": w.get("id"), "reason": w.get("reason"),
                        "approver": "operator", "owner": w.get("owner"), "scope": w.get("scope"),
                        "expires": w.get("expiry"), "timestamp": w.get("at")})
    return {"version": 1, "project": st.get("product"), "governed_root": "", "phases": phases,
            "waivers": waivers}


def load_paths_doc(root):
    """MOADIX v2: v1's phase-paths.yaml shape, from gate/pathmap.py (one owner)."""
    import sys as _sys
    if GATE_DIR not in _sys.path:
        _sys.path.insert(0, os.path.dirname(GATE_DIR))
    from gate import pathmap as _pm
    return _pm.v1_paths_doc()


def phases_of(doc):
    ph = (doc or {}).get("phases") or []
    return sorted(ph, key=lambda p: int(p.get("id", 0)))


SIZE_RE = re.compile(r"^\s*[-*]\s*\*\*Size:?\*\*:?\s*([SML])\b", re.M | re.I)


def collapsed_phases(root_dir):
    """(state, value) -- which phases the declared size profile collapses.

    state 'ok'      -> value is {label: {"size", "reason", "checks_not_run"}}
    state 'unknown' -> value is a sentence saying why it could not be answered

    THE ONE OWNER. It lives here rather than in check_size_profile because
    approval ordering (gate.py), the current-phase resolution the write gate
    reads, and the scorecard all need the same answer, and check_size_profile
    imports this module. A second copy of a rule that decides which phases may
    be skipped is not a thing to have.

    'unknown' is never an empty set. A caller that cannot tell whether a phase
    was collapsed on purpose or simply not done must say so (3.10); the
    collapse is a RULING, and a ruling nobody can read is not one.
    """
    try:
        paths = load_paths_doc(root_dir) or {}
        profiles = load_yaml(config_path(root_dir, "profiles.yaml")) or {}
    except Exception as exc:                                    # noqa: BLE001
        return "unknown", "the control files could not be read (%r)" % (exc,)
    groot = (paths.get("governed_root") or "").strip("/")
    brd = os.path.join(root_dir, groot, "sdlc", "00-brd.md")
    if not os.path.exists(brd):
        return "unknown", "the BRD does not exist at %s" % brd
    try:
        with open(brd, encoding="utf-8", errors="replace") as fh:
            text = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    except OSError as exc:
        return "unknown", "the BRD could not be read (%r)" % (exc,)
    m = SIZE_RE.search(text)
    if not m:
        return "unknown", "the BRD declares no `- **Size:** S|M|L` field"
    size = m.group(1).upper()
    sizes = (profiles or {}).get("sizes") or {}
    if size not in sizes:
        return "unknown", ("profiles.yaml describes no `sizes:` entry for size %s, "
                           "so whether it collapses anything is undeclared rather "
                           "than empty" % size)
    out = {}
    for e in ((sizes.get(size) or {}).get("collapse") or []):
        lbl = str((e or {}).get("phase") or "").strip()
        if lbl:
            out[lbl] = {"size": size,
                        "reason": str((e or {}).get("reason") or "").strip(),
                        "checks_not_run": [str(x) for x in
                                           ((e or {}).get("checks_not_run") or [])]}
    return "ok", out


def collapsed_labels(root_dir):
    """Just the labels, empty on 'unknown'.

    Safe ONLY where an unknown profile and an empty collapse set lead to the
    same conservative behaviour -- i.e. where the caller's fallback is "this
    phase still has to be approved". Anywhere the answer decides whether
    something is EXCUSED, call collapsed_phases() and handle 'unknown'.
    """
    state, val = collapsed_phases(root_dir)
    return set(val) if state == "ok" else set()


def current_phase_id(doc, root_dir=None):
    """Lowest phase id whose status is not APPROVED. None when all approved.

    A phase the size profile collapses is not a phase to do, so it is not the
    current one either. Without this, a declared collapse renders in the
    scorecard as COLLAPSED and the lifecycle still stops dead on it: the only
    ways past would be to do the work anyway (making COLLAPSED a lie) or to
    approve it without doing it (which is the skip COLLAPSED exists to be
    distinguishable from). A gate that renders a decision it cannot act on is
    a declaration nothing reads -- 3.9, inside the control built to close 3.9.

    root_dir is optional so every existing caller keeps working; without it the
    collapse set is empty and behaviour is exactly what it was before.
    """
    skip = collapsed_labels(root_dir) if root_dir else set()
    for p in phases_of(doc):
        if str(p.get("status")) != "APPROVED" and str(p.get("label")) not in skip:
            return int(p["id"])
    return None


def phase_by_id(doc, pid):
    for p in phases_of(doc):
        if int(p.get("id", -1)) == int(pid):
            return p
    return None


# The lib modules gate.sh must have on disk to reach a decision at all.
#
# Declared HERE, once, because every scratch-root test fixture used to enumerate
# them by hand -- so when gate.py grew a dependency on coherence.py in v0.5, two
# suites broke silently and the failure surfaced as a wrong diagnosis three tasks
# later. A fixture that has to GUESS the dependency set is a fixture that is
# wrong the next time the set changes.
GATE_REQUIRED_MODULES = ("hlib", "gatecore", "coherence", "check_profile",
                         "product_tests", "waivers",
                         # v0.5 Stage C: cmd_approve computes an input digest over
                         # the phase's registry `verifies:` globs, which it reads
                         # through provenance.verifies_map. Added here the moment
                         # gate.py grew the dependency -- the whole point of the
                         # declaration, and the omission that broke five suites
                         # when coherence.py was added without it.
                         "provenance",
    # v0.8 P27: the front doors refuse to run product code without
    # these, so a scratch root without them is not a harness root.
    "sandbox", "sandbox_profile", "registered_suites",
)


def missing_lib_modules(lib_dir=None, required=None):
    """Required modules absent from harness/lib. Empty list when all present.

    Answers "is this a complete harness installation", which is a DIFFERENT
    question from "do the control files agree", and was being reported as the
    latter.
    """
    lib_dir = lib_dir or os.path.dirname(os.path.realpath(__file__))
    return [m for m in (required or GATE_REQUIRED_MODULES)
            if not os.path.exists(os.path.join(lib_dir, m + ".py"))]


def waiver_expired(w, today=None):
    """True when a waiver carries an 'expires' date that has already passed.

    A waiver with no 'expires' never expires, so every waiver recorded before
    this field existed keeps working unchanged.

    An UNPARSEABLE 'expires' counts as EXPIRED. A typo in a date must not
    quietly buy a permanent exception -- that is the same fail-closed stance
    the rest of the gate takes, and the failure is loud and easy to fix.

    ISO-8601 dates compare correctly as strings, so no date parsing (and no
    dependency) is needed. The waiver is still valid ON its expiry date.
    """
    exp = w.get("expires")
    if exp in (None, ""):
        return False
    exp = str(exp).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", exp):
        return True
    if today is None:
        import datetime
        today = datetime.date.today().isoformat()
    return exp < today


def waiver_events(w):
    """The waiver's history, oldest first, as an ordered list of events.

    P49. A waiver can be granted, revoked, and granted again, and a field pair
    silently loses everything but the last transition -- so the record is a
    SEQUENCE from the start rather than a pair retrofitted after the first
    re-grant.

    Waivers written before `events` existed are read as a single implied grant
    from the fields they already carry. Nothing is rewritten on disk to make
    this work: an absent `events` list is not a waiver with no history, it is a
    waiver whose only event is the grant its top-level fields describe.
    """
    evs = list((w or {}).get("events") or [])
    if not evs:
        return [{"action": "granted", "by": (w or {}).get("approver"),
                 "at": (w or {}).get("timestamp"),
                 "reason": (w or {}).get("reason"), "implied": True}]
    return evs


def waiver_revoked(w):
    """The revocation event if the waiver's LAST transition was a revocation.

    Returns the event dict, or None. Reading the last event rather than "is
    there a revocation anywhere" is what makes re-granting expressible: a
    waiver granted, revoked and re-granted is LIVE, and its middle is still in
    the record.
    """
    evs = waiver_events(w)
    last = evs[-1] if evs else None
    return last if (last or {}).get("action") == "revoked" else None


def waiver_state(w, today=None):
    """'live' | 'revoked' | 'expired'. THREE states, never two.

    Revoked and expired are DIFFERENT FACTS about how an exception ended:
    expired lapsed by time and nobody decided anything; revoked was withdrawn
    by a named human on a stated date. A reader who sees only "not in force"
    has the record this version exists to remove -- so callers that RENDER must
    use this, not `waivers_for`'s absence.

    Revocation is checked FIRST: a waiver withdrawn before its expiry date
    ended by a decision, and that is the fact worth keeping.
    """
    if waiver_revoked(w):
        return "revoked"
    if waiver_expired(w, today):
        return "expired"
    return "live"


def waivers_for(doc, rule):
    """Every LIVE waiver for a rule. Expired waivers are not returned, so a
    dated exception stops granting anything the day after it lapses without
    each validator having to know about expiry."""
    out = []
    for w in (doc or {}).get("waivers") or []:
        # P49 rides the expiry predicate that already exists here. A revoked
        # waiver is PRESENT in phase.yaml and grants nothing -- exactly what an
        # expired one already does -- so all twelve callers inherit revocation
        # without any of them learning a new concept.
        if str(w.get("rule")) == rule and waiver_state(w) == "live":
            out.append(w)
    return out


def expired_waivers(doc):
    """Waivers that have lapsed -- reported by `gate.sh current` so a gate that
    started failing again names the reason instead of just saying 'no waiver'."""
    return [w for w in (doc or {}).get("waivers") or [] if waiver_expired(w)]


# --------------------------------------------------------------------------
# git — THE ONLY PLACE THE HARNESS SHELLS OUT TO IT
# --------------------------------------------------------------------------
#
# hlib is otherwise stdlib-only by design: a hook that cannot import its own
# library fails CLOSED, so every dependency is a liability (see the module
# docstring). git is a real dependency for provenance, so it is isolated here
# behind three functions and never called directly from a validator.
#
# EVERY function degrades rather than raises. A product tree that is not a git
# checkout -- a fresh `bootstrap`, an exported tarball, a CI job with no history
# -- must still be gateable. The degraded answer is "unknown", never "fail", and
# it is the RELEASE gate's job to decide that unknown is not good enough. That
# split is deliberate: fail-closed here would make provenance a prerequisite for
# using the harness at all, which is how a good control becomes a reason not to
# adopt it.

def _git(root, *args):
    """Run a read-only git command. Returns (ok, stdout). Never raises."""
    import subprocess
    try:
        p = subprocess.run(["git"] + list(args), cwd=root, capture_output=True,
                           text=True, timeout=30)
        return (p.returncode == 0), (p.stdout or "").strip()
    except Exception:
        return False, ""


def git_available(root):
    """True when `root` is inside a usable git work tree."""
    ok, out = _git(root, "rev-parse", "--is-inside-work-tree")
    return ok and out == "true"


def git_head_sha(root):
    """Full HEAD sha, or None when unknowable (no git, no commits, no repo)."""
    if not git_available(root):
        return None
    ok, out = _git(root, "rev-parse", "HEAD")
    return out if (ok and len(out) == 40) else None


def git_tree_dirty(root, paths=None):
    """True when the work tree has uncommitted changes.

    None means UNKNOWN, which is not the same as clean -- callers must not read
    a falsy return as 'the tree was clean'.
    """
    if not git_available(root):
        return None
    args = ["status", "--porcelain"]
    if paths:
        args += ["--"] + list(paths)
    ok, out = _git(root, *args)
    return bool(out.strip()) if ok else None


def git_is_ancestor(root, sha, of="HEAD"):
    """True when `sha` is an ancestor of `of`.

    None means UNKNOWN (no git, or the sha is not an object this repo has).
    False is a positive finding: the artifact describes a tree that is not in
    this history -- a reverted, rebased or abandoned build.
    """
    if not sha or not git_available(root):
        return None
    ok, _ = _git(root, "cat-file", "-e", "%s^{commit}" % sha)
    if not ok:
        return None
    ok, _ = _git(root, "merge-base", "--is-ancestor", sha, of)
    return bool(ok)


def git_paths_changed_since(root, sha, paths):
    """Paths under `paths` that changed between `sha` and HEAD.

    Returns None when unknowable. An empty list means nothing changed; that is
    a real answer and must be distinguished from None.
    """
    if not sha or not paths or not git_available(root):
        return None
    ok, out = _git(root, "diff", "--name-only", sha, "HEAD", "--", *paths)
    if not ok:
        return None
    return [l.strip() for l in out.splitlines() if l.strip()]


def parsed_set(items, source_exists, what, source, errs):
    """A parse-to-set result, with the EMPTY case made explicit.

    THE CLASS. A function that parses a set out of an artifact has three
    outcomes, and code repeatedly collapses them into two:

        source missing          -> nothing to read
        source present, N items -> the set
        source present, 0 items -> THE PARSER FOUND NOTHING

    The third is the dangerous one: downstream code written as `for x in items:`
    treats it as "no work to do", and every per-item check becomes vacuously
    satisfied. Two real instances:

      * check_authz_matrix's first role regex required the colon OUTSIDE the
        bold while the template writes it inside. Zero roles in a PRD declaring
        two -- reported as NOT-APPLICABLE: a parse failure wearing the costume
        of "this product has no roles".
      * check_live_verification's story parse. Worse, because `if stories:`
        guarded the summary line, so the zero case printed NOTHING AT ALL --
        a vacuous pass that does not even announce itself.

    check_traceability:314 already did the right thing one file over, which is
    why this is an inconsistency rather than a design gap, and why the fix
    belongs somewhere every parser can reach instead of in one caller.

    Returns the items, and appends an error when the source exists and parsed
    to nothing.
    """
    if items:
        return items
    if source_exists:
        errs.append(
            "%s: the file exists and %s parsed to NOTHING. That is not the same "
            "as having none -- every per-item check below is vacuously "
            "satisfied, so it is reported rather than passed silently. Check "
            "the format the parser expects." % (source, what))
    return items if items is not None else []
