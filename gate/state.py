""".sdlc/ state: product.yaml, phase.yaml, ledger.jsonl.

The ledger is the truth. Each line is produced by the checker after a valid
TOTP code:  {"body": "<json>", "hash": sha256(body), "hmac": HMAC(key, body)}
body = {"seq", "prev", "ts", "product", "action", "payload_b64"}.
The checker also keeps the anchor (last seq + hash, MAC'd) in the Keychain,
so neither truncation nor a rewritten chain goes unnoticed.

phase.yaml is derived: replay(ledger) rendered by yamlite.emit. STATUS
recomputes it and compares byte for byte.
"""
import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import time

from . import pathmap, yamlite

SDLC = ".sdlc"
PHASE_HEADER = "# MOADIX gate state, derived from ledger.jsonl. Written only by the gate.\n"
# Bumped when the rendering changes. A phase.yaml with an OLDER version line is
# regenerated from the verified ledger (a gate update), not reported as drift.
RENDER_VERSION = 4
GIT = "/usr/bin/git"
GATE_FILES = ("product", "phase", "ledger")


class GateError(Exception):
    pass


def checker_path():
    """<MOADIX_HOME>/bin/moadix-checker, where MOADIX_HOME is the directory this
    gate package was installed into (root-owned in production:
    /Library/Application Support/ClaudeCode/moadix). Deliberately NOT taken
    from an environment variable: a project settings file can set `env`, and
    a Docker mount can write one (Amendment 1 §4)."""
    home = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    p = os.path.join(home, "bin", "moadix-checker")
    if not os.path.exists(p):
        raise GateError("checker not installed at %s (run managed/install.sh)" % p)
    return p


def run_checker(args, stdin=None, timeout=8):
    p = subprocess.run([checker_path()] + args, input=stdin, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip()


def find_root(start):
    """The product repo root: nearest ancestor holding .sdlc/product.yaml."""
    d = os.path.realpath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, SDLC, "product.yaml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def paths(root):
    s = os.path.join(root, SDLC)
    return {"dir": s, "product": os.path.join(s, "product.yaml"), "phase": os.path.join(s, "phase.yaml"),
            "ledger": os.path.join(s, "ledger.jsonl"), "evidence": os.path.join(s, "evidence"),
            "knowledge": os.path.join(s, "knowledge.md"), "untested": os.path.join(s, "untested.yaml")}


def load_product(root):
    with open(paths(root)["product"]) as f:
        doc = yamlite.parse_flat(f.read())
    pid = str(doc.get("product") or "")
    if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", pid):
        raise GateError("product.yaml: invalid product id")
    return doc


def read_ledger(root):
    p = paths(root)["ledger"]
    if not os.path.exists(p):
        return []
    out = []
    with open(p) as f:
        for n, raw in enumerate(f, 1):
            raw = raw.rstrip("\n")
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except ValueError:
                out.append({"_malformed": raw, "_line": n})
    return out


def verify_ledger(root, product_id):
    """(ok, problems, entries). Checks structure, chain, HMACs and the anchor."""
    lines = read_ledger(root)
    problems, entries, prev = [], [], "GENESIS"
    for i, ln in enumerate(lines, 1):
        if "_malformed" in ln or not all(isinstance(ln.get(k), str) for k in ("body", "hash", "hmac")):
            problems.append("line %d: malformed" % i)
            continue
        body = ln["body"]
        if hashlib.sha256(body.encode()).hexdigest() != ln["hash"]:
            problems.append("line %d: hash does not match body" % i)
        try:
            b = json.loads(body)
        except ValueError:
            problems.append("line %d: body is not JSON" % i)
            continue
        if b.get("seq") != i:
            problems.append("line %d: seq %r out of order" % (i, b.get("seq")))
        if b.get("prev") != prev:
            problems.append("line %d: chain broken (prev does not match line %d)" % (i, i - 1))
        if b.get("product") != product_id:
            problems.append("line %d: belongs to product %r" % (i, b.get("product")))
        prev = ln["hash"]
        entries.append(b)
    if lines:
        feed = "".join("%s %s\n" % (binascii.hexlify(l.get("body", "").encode()).decode(), l.get("hmac", ""))
                       for l in lines if isinstance(l.get("body"), str))
        rc, out = run_checker(["verify"], stdin=feed)
        if rc != 0:
            problems.append("signature check unavailable: %s" % out)
        else:
            for i, verdict in enumerate(out.splitlines(), 1):
                if verdict != "ok":
                    problems.append("line %d: signature invalid (not written by the checker)" % i)
    rc, out = run_checker(["anchor", "--product", product_id])
    m = re.match(r"^OK (\d+) (\S+)$", out)
    if rc != 0 or not m:
        problems.append("anchor unavailable: %s" % out)
    else:
        aseq, ahash = int(m.group(1)), m.group(2)
        if aseq != len(lines) or ahash != prev:
            problems.append("anchor mismatch: Keychain anchor says seq %d, ledger has %d lines%s" % (
                aseq, len(lines), "" if aseq != len(lines) else " with a different head"))
    return (not problems), problems, entries


def decode_payload(entry):
    try:
        return json.loads(base64.b64decode(entry.get("payload_b64") or "e30=").decode())
    except (ValueError, binascii.Error):
        return {}


DONE = ("APPROVED", "PROCEED-PAST", "COLLAPSED")
PHASE_VERBS = ("APPROVE", "PROCEED-PAST", "REOPEN", "COLLAPSE")


def _fresh_phases(table):
    return [{"id": pid, "label": label, "name": name, "status": "draft", "seq": None, "at": None, "note": None,
             "commit": None, "evidence": None}
            for pid, label, name, _ in table]


def _apply(phases, verb, e, pl):
    """One phase-state line (APPROVE, PROCEED-PAST, REOPEN, COLLAPSE) onto a phase list."""
    ph = next((p for p in phases if p["label"] == pl.get("phase")), None)
    if ph is None:
        return
    if verb == "APPROVE":
        val = pl.get("validation") or {}
        ph.update(status="APPROVED", seq=e["seq"], at=e["ts"], note=None, commit=pl.get("source_commit"),
                  evidence=[{"validator": r.get("validator"), "result": r.get("result"),
                             "exit_code": r.get("exit_code")} for r in (val.get("results") or [])] or None)
    elif verb == "PROCEED-PAST":
        ph.update(status="PROCEED-PAST", seq=e["seq"], at=e["ts"], note=pl.get("reason"),
                  commit=pl.get("source_commit"),
                  evidence=[{"validator": v, "result": "fail"} for v in (pl.get("failing") or [])] or None)
    elif verb == "COLLAPSE":
        # Increment 6 (item C): a size-profile collapse is a RECORDED ruling, not a silent skip.
        ph.update(status="COLLAPSED", seq=e["seq"], at=e["ts"], note=pl.get("reason"), commit=pl.get("source_commit"),
                  evidence=[{"validator": v, "result": "not-run (collapsed)"} for v in (pl.get("checks_not_run") or [])]
                  or None)
    elif verb == "REOPEN":
        for p in phases:
            if p["id"] >= ph["id"]:
                p.update(status="draft", seq=None, at=None, note=None, commit=None, evidence=None)
        ph.update(status="REOPENED", seq=e["seq"], at=e["ts"], note=pl.get("reason"))


def _current(phases):
    return next((p for p in phases if p["status"] not in DONE), None)


def _clean(phases):
    return [{k: v for k, v in p.items() if v is not None} for p in phases]


def replay(product_id, entries):
    """Phase state from verified ledger entries.

    Increment 6 (Amendment 2): INIT's payload says whether the product was onboarded
    (mode onboarding: one product phase, B). FEATURE <id> starts a feature cycle with
    its own 16 phases; every later phase line whose payload names that feature applies
    to the feature, not the product. One feature is active at a time; it closes when all
    its phases are done. `phases`/`current_phase` describe the scope in force (the active
    feature's, else the product's); `product_phases` and `features` hold the rest."""
    mode = "greenfield"
    product = _fresh_phases(pathmap.PHASES)
    features, order, active = {}, [], None
    waivers, parked = {}, None
    for e in entries:
        verb = e["action"].split(" ", 1)[0]
        pl = decode_payload(e)
        if verb == "INIT":
            if pl.get("mode") == "onboarding":
                mode = "onboarding"
                product = _fresh_phases(pathmap.BASELINE)
            continue
        if verb == "FEATURE":
            fid = str(pl.get("feature") or "")
            if fid and fid not in features:
                features[fid] = {"id": fid, "status": "active", "seq": e["seq"], "at": e["ts"],
                                 "commit": pl.get("source_commit"), "phases": _fresh_phases(pathmap.PHASES),
                                 "merged": None}
                order.append(fid)
                active = fid
            continue
        fid = pl.get("feature")
        if verb in PHASE_VERBS:
            if fid:
                if fid not in features or features[fid]["status"] != "active":
                    continue  # a line for a feature that is not running applies to nothing
                _apply(features[fid]["phases"], verb, e, pl)
                if verb == "APPROVE" and pl.get("merge"):
                    features[fid]["merged"] = {"seq": e["seq"], "at": e["ts"],
                                               "files": [f.get("target") for f in (pl["merge"].get("files") or [])]}
                if _current(features[fid]["phases"]) is None:
                    features[fid]["status"] = "done"
                    if active == fid:
                        active = None
            else:
                _apply(product, verb, e, pl)
        elif verb == "WAIVE":
            waivers[pl.get("id")] = {"id": pl.get("id"), "owner": pl.get("owner"), "scope": pl.get("scope"),
                                     "expiry": pl.get("expiry"), "reason": pl.get("reason"), "seq": e["seq"],
                                     "at": e["ts"], "feature": fid}
        elif verb == "UNWAIVE":
            waivers.pop(pl.get("id"), None)
        elif verb == "PARK":
            parked = {"seq": e["seq"], "at": e["ts"], "commit": pl.get("source_commit"),
                      "counts": pl.get("counts") or {}}
    scope = features[active]["phases"] if active else product
    current = _current(scope)
    head = entries[-1] if entries else None
    return {
        "version": RENDER_VERSION,
        "product": product_id,
        "mode": mode,
        "ledger_seq": len(entries),
        "feature": active,
        "current_phase": current["label"] if current else "done",
        "current_phase_id": current["id"] if current else None,
        "phases": _clean(scope),
        "product_phases": _clean(product),
        "features": [{k: v for k, v in {
            "id": f["id"], "status": f["status"], "seq": f["seq"], "at": f["at"], "commit": f["commit"],
            "current_phase": (_current(f["phases"]) or {}).get("label", "done"),
            "merged_seq": (f["merged"] or {}).get("seq")}.items() if v is not None}
            for f in (features[x] for x in order)],
        "waivers": [{k: v for k, v in w.items() if v is not None}
                    for w in sorted(waivers.values(), key=lambda w: w["seq"])],
        "parked": parked,
        "scope_base": features[active]["commit"] if active else None,
        "_feature_phases": {fid: _clean(features[fid]["phases"]) for fid in order},
        "_feature_merged": {fid: features[fid]["merged"] for fid in order},
        "_head_ts": head["ts"] if head else None,
        "_entries": list(entries),  # verified ledger bodies (not rendered): payload digests, scorecard
    }


def scope_table(st):
    """The path-map phase table in force for this state (pathmap.scope_phases)."""
    return pathmap.scope_phases(st.get("mode"), st.get("feature"))


def render_phase(st):
    """.sdlc/phase.yaml: the PRODUCT's state (its phases, and a summary of each feature)."""
    doc = {"version": st["version"], "product": st["product"], "mode": st.get("mode", "greenfield"),
           "ledger_seq": st["ledger_seq"], "feature": st.get("feature"), "current_phase": st["current_phase"],
           "phases": st.get("product_phases", st["phases"]), "features": st.get("features") or [],
           "waivers": st["waivers"], "parked": st["parked"]}
    return PHASE_HEADER + yamlite.emit(doc) + "\n"


def feature_phase_path(root, fid):
    return os.path.join(paths(root)["dir"], "features", fid, "phase.yaml")


def render_feature(st, fid):
    """.sdlc/features/<fid>/phase.yaml, rebuilt from the ledger like the product's (Amendment 2 §6)."""
    f = next(x for x in st["features"] if x["id"] == fid)
    doc = {"version": st["version"], "product": st["product"], "feature": fid, "status": f["status"],
           "started_seq": f["seq"], "started_commit": f.get("commit"), "current_phase": f["current_phase"],
           "merged": st["_feature_merged"].get(fid), "phases": st["_feature_phases"][fid]}
    return PHASE_HEADER + yamlite.emit(doc) + "\n"


def rendered_files(root, st):
    """{absolute path: text} of every derived state file."""
    out = {paths(root)["phase"]: render_phase(st)}
    for f in st.get("features") or []:
        out[feature_phase_path(root, f["id"])] = render_feature(st, f["id"])
    return out


def hardlinked(root):
    """Gate files with more than one directory entry. A hard link made from
    outside .sdlc/ is a second, unprotected path to the same bytes, so writes
    through it pass both the hook and the sandbox's .sdlc/ rule."""
    p = paths(root)
    out = []
    for k in GATE_FILES:
        try:
            if os.lstat(p[k]).st_nlink > 1:
                out.append(os.path.relpath(p[k], root))
        except OSError:
            pass
    return out


def _render_version(text):
    m = re.search(r"^version: (\d+)$", text, re.M)
    return int(m.group(1)) if m else 0


def current_state(root):
    """(state, problems). On any problem the state is the last verified prefix's; callers fail closed."""
    prod = load_product(root)
    ok, problems, entries = verify_ledger(root, prod["product"])
    if ok:
        from . import adopt  # late: adopt imports this module
        problems.extend(adopt.drift(root, entries))
    links = hardlinked(root)
    if links:
        problems.append("hard link(s) to gate state: %s (a second path to these bytes bypasses .sdlc/ "
                        "protection)" % ", ".join(links))
    st = replay(prod["product"], entries if ok else [])
    if ok:
        for path, want in rendered_files(root, st).items():
            on_disk = ""
            if os.path.exists(path):
                with open(path) as f:
                    on_disk = f.read()
            if on_disk == want:
                continue
            if on_disk and _render_version(on_disk) < RENDER_VERSION and not links:
                write_phase(root, st)  # gate update: re-derive from the verified ledger
                break
            name = os.path.relpath(path, paths(root)["dir"])
            problems.append("phase.yaml differs from the state the ledger replays to (drift)%s" % (
                "" if name == "phase.yaml" else " in %s" % name))
    return st, problems


def append_line(root, line_json):
    p = paths(root)
    with open(p["ledger"], "a") as f:
        f.write(line_json.rstrip("\n") + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_phase(root, st):
    """Write every derived state file: .sdlc/phase.yaml and each feature's phase.yaml."""
    for p, text in rendered_files(root, st).items():
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, p)


PRODUCT_TEMPLATE = """# MOADIX product definition. Gate-owned: created by INIT; agents cannot write
# .sdlc/. Settings change only through ADOPT <code>: the agent proposes them in
# .sdlc-proposals/product.yaml (keys platform, size, app_run, test_targets, park).
product: %s
created: "%s"
path_map: default
platform: null
size: null
app_run: null
test_targets: null
# PARK stops the stack, measures the declared counts, records them and tags.
# argv lists (no shell); argv[0] must be docker or podman, resolved from the
# gate's trusted directories. A count command prints one integer. Example:
#   park:
#     stop: [docker, compose, -p, myproduct, stop]
#     counts:
#       orders: [docker, compose, -p, myproduct, run, --rm, db, psql, -tAc, "select count(*) from orders"]
park: null
"""


def init_product(root, product_id):
    """Creates .sdlc/ (INIT, recorded by the hook; or sdlc_init.py from a terminal)."""
    if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", product_id):
        raise GateError("invalid product id")
    p = paths(root)
    if os.path.exists(p["product"]):
        raise GateError(".sdlc/ already exists")
    os.makedirs(p["evidence"], exist_ok=True)
    with open(p["product"], "w") as f:
        f.write(PRODUCT_TEMPLATE % (product_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    open(p["ledger"], "a").close()
    for name, text in (("knowledge", "# Operational knowledge (read by verification)\n"),
                       ("untested", "# Acceptance criteria known to be untested; 10a reads this.\nuntested: []\n")):
        if not os.path.exists(p[name]):
            with open(p[name], "w") as f:
                f.write(text)
    with open(os.path.join(p["dir"], ".gitignore"), "w") as f:
        f.write("# validator results are a per-machine cache\ncache/\n")
    write_phase(root, replay(product_id, []))
