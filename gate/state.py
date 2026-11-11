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
    doc = yamlite.parse_flat(open(paths(root)["product"]).read())
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


def replay(product_id, entries):
    """Phase state from verified ledger entries."""
    phases = [{"id": pid, "label": label, "name": name, "status": "draft", "seq": None, "at": None, "note": None}
              for pid, label, name, _ in pathmap.PHASES]
    waivers, parked = {}, None
    for e in entries:
        verb = e["action"].split(" ", 1)[0]
        pl = decode_payload(e)
        ph = next((p for p in phases if p["label"] == pl.get("phase")), None)
        if verb == "APPROVE" and ph:
            ph.update(status="APPROVED", seq=e["seq"], at=e["ts"], note=None)
        elif verb == "PROCEED-PAST" and ph:
            ph.update(status="PROCEED-PAST", seq=e["seq"], at=e["ts"], note=pl.get("reason"))
        elif verb == "REOPEN" and ph:
            for p in phases:
                if p["id"] >= ph["id"]:
                    p.update(status="draft", seq=None, at=None, note=None)
            ph.update(status="REOPENED", seq=e["seq"], at=e["ts"], note=pl.get("reason"))
        elif verb == "WAIVE":
            waivers[pl.get("id")] = {"id": pl.get("id"), "owner": pl.get("owner"), "expiry": pl.get("expiry"),
                                     "reason": pl.get("reason"), "seq": e["seq"]}
        elif verb == "UNWAIVE":
            waivers.pop(pl.get("id"), None)
        elif verb == "PARK":
            parked = {"seq": e["seq"], "at": e["ts"]}
    current = next((p for p in phases if p["status"] not in ("APPROVED", "PROCEED-PAST")), None)
    head = entries[-1] if entries else None
    return {
        "version": 2,
        "product": product_id,
        "ledger_seq": len(entries),
        "current_phase": current["label"] if current else "done",
        "current_phase_id": current["id"] if current else len(phases) - 1,
        "phases": [{k: v for k, v in p.items() if v is not None} for p in phases],
        "waivers": sorted(waivers.values(), key=lambda w: w["seq"]),
        "parked": parked,
        "_head_ts": head["ts"] if head else None,
    }


def render_phase(st):
    doc = {k: v for k, v in st.items() if not k.startswith("_") and k != "current_phase_id"}
    return PHASE_HEADER + yamlite.emit(doc) + "\n"


def current_state(root):
    """(state, problems). On any problem the state is the last verified prefix's; callers fail closed."""
    prod = load_product(root)
    ok, problems, entries = verify_ledger(root, prod["product"])
    st = replay(prod["product"], entries if ok else [])
    p = paths(root)["phase"]
    if ok:
        on_disk = open(p).read() if os.path.exists(p) else ""
        if on_disk != render_phase(st):
            problems.append("phase.yaml differs from the state the ledger replays to (drift)")
    return st, problems


def append_line(root, line_json):
    p = paths(root)
    with open(p["ledger"], "a") as f:
        f.write(line_json.rstrip("\n") + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_phase(root, st):
    p = paths(root)["phase"]
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(render_phase(st))
    os.replace(tmp, p)


def init_product(root, product_id):
    """Operator-only setup (managed/install.sh or a terminal), never the agent."""
    if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", product_id):
        raise GateError("invalid product id")
    p = paths(root)
    if os.path.exists(p["product"]):
        raise GateError(".sdlc/ already exists")
    os.makedirs(p["evidence"], exist_ok=True)
    with open(p["product"], "w") as f:
        f.write("# MOADIX product definition. Gate-owned.\n"
                "product: %s\ncreated: \"%s\"\npath_map: default\nplatform: null\nsize: null\n"
                "app_run: null\ntest_targets: null\n" % (product_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    open(p["ledger"], "a").close()
    for name, text in (("knowledge", "# Operational knowledge (read by verification)\n"),
                       ("untested", "# Acceptance criteria known to be untested; 10a reads this.\nuntested: []\n")):
        if not os.path.exists(p[name]):
            with open(p[name], "w") as f:
                f.write(text)
    write_phase(root, replay(product_id, []))
