"""Validator results, computed ahead of time and cached per commit.

APPROVE must answer inside the UserPromptSubmit hook's timeout, and the ported
v1 validators take seconds to minutes (check-lld provisions PyYAML through uv).
So the validators never run inside APPROVE:

  the gate       starts a detached worker (gate/validate.py) for the current
                 phase when the agent's turn ends (Stop hook) or when the agent
                 calls /moadix:request-review, if the tree is clean and there is
                 no fresh result (ruling 2, increment 3). Only the gate starts
                 it; only the worker writes the cache.
  REVIEW <phase> optional and read-only: prints what the cache holds.
  APPROVE        reads the cache only. Missing, running, stale or dirty
                 counts as a FAILURE, never as a pass. The ledger line records
                 the sha256 of the exact cache file it relied on (`digest`).

A cache entry is fresh only when every part of its key still holds:
  commit      HEAD of the product repo when the run started
  clean       the working tree had no changes outside .sdlc/ (tracked or
              untracked; gitignored files are not part of the key)
  gate        sha256 of the gate's own code and config (an update invalidates)
  config      sha256 of .sdlc/product.yaml and .sdlc/config/*
  ledger      the ledger's length and head hash (a waiver changes results)
  verifiers   sha256 of .sdlc/cache/verify/<phase>/ (increment 4): a verifier's
              new evidence or a new launch makes the result stale

Exit-code contract (v1, kept): 0 pass, 2 unknown (the instrument could not
run), anything else fail. `n/a-by-profile` is recorded, never counted as a pass
or a failure. The verdict is "pass" only when no result is fail or unknown.

The cache lives in .sdlc/cache/, which the agent cannot write (hook + sandbox).
"""
import hashlib
import json
import os
import subprocess
import sys
import time

from . import state

GATE_DIR = os.path.dirname(os.path.realpath(__file__))
WORKER = os.path.join(GATE_DIR, "validate.py")
STALE_LOCK_SECONDS = 3 * 3600  # increment 5: phase 9's scanners and 10c's load test run long


def cache_dir(root):
    return os.path.join(root, state.SDLC, "cache")


def cache_file(root, label):
    return os.path.join(cache_dir(root), "validation-%s.json" % label)


def lock_file(root, label):
    return os.path.join(cache_dir(root), "validation-%s.lock" % label)


def _git(root, *args):
    try:
        p = subprocess.run([state.GIT, "-C", root] + list(args), capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def tree_state(root):
    """(head or None, [changed paths outside .sdlc/ and .sdlc-proposals/]).
    .sdlc-proposals/ holds settings the agent proposes for ADOPT; validators do
    not read it, so a pending proposal does not make results stale."""
    rc, out = _git(root, "rev-parse", "--verify", "HEAD")
    head = out.strip() if rc == 0 and out.strip() else None
    rc, out = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", ".", ":(exclude).sdlc",
                   ":(exclude).sdlc-proposals")
    if rc != 0:
        return head, ["(git status failed)"]
    return head, [ln[3:] for ln in out.splitlines() if ln.strip()]


def _digest_files(paths):
    h = hashlib.sha256()
    for p in paths:
        h.update(p.encode() + b"\0")
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"(missing)")
        h.update(b"\0")
    return h.hexdigest()


def gate_version():
    """sha256 over the gate's code and config, by path relative to the gate."""
    h = hashlib.sha256()
    for d, dirs, fs in os.walk(GATE_DIR):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(fs):
            if f.endswith((".py", ".yaml", ".toml", ".ini", ".js")):  # .js: the k6 wrapper (increment 5)
                full = os.path.join(d, f)
                h.update(os.path.relpath(full, GATE_DIR).encode() + b"\0")
                with open(full, "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()


def config_digest(root):
    p = state.paths(root)
    cfg = os.path.join(p["dir"], "config")
    files = [p["product"]]
    if os.path.isdir(cfg):
        files += [os.path.join(cfg, f) for f in sorted(os.listdir(cfg))]
    return _digest_files(files)


def key(root, st, label=None):
    from . import verify
    head, dirty = tree_state(root)
    lines = state.read_ledger(root)
    lhead = lines[-1].get("hash") if lines else "GENESIS"
    return {"commit": head, "clean": not dirty, "dirty": dirty[:20], "gate": gate_version(),
            "config": config_digest(root), "ledger": "%d:%s" % (st["ledger_seq"], lhead),
            "verifiers": verify.evidence_digest(root, label or st.get("current_phase")),
            "scope": scope_of(st)}


def scope_of(st):
    """Increment 6: which phase table the result belongs to. A feature's phase 3 and the
    product's phase 3 share a label, never a result."""
    return "feature:%s" % st["feature"] if st.get("feature") else "product"


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def running(root, label):
    """Seconds the worker has been running, or None."""
    lf = lock_file(root, label)
    try:
        with open(lf) as f:
            pid, started = f.read().split()
        pid, started = int(pid), float(started)
    except (OSError, ValueError):
        return None
    if not _pid_alive(pid) or time.time() - started > STALE_LOCK_SECONDS:
        return None
    return time.time() - started


def read(root, label, st):
    """(status, data, detail). status: fresh | missing | running | stale | dirty | unreadable."""
    now_key = key(root, st, label)
    try:
        with open(cache_file(root, label), "rb") as f:
            raw = f.read()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        data["_digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()  # what APPROVE records it relied on
    except FileNotFoundError:
        data = None
    except (OSError, ValueError) as e:
        return "unreadable", None, "the cached result could not be read (%s)" % type(e).__name__
    run_for = running(root, label)
    if not now_key["commit"]:
        return "stale", data, "the repository has no commit yet; validators run against a commit"
    if not now_key["clean"]:
        return "dirty", data, "the working tree has uncommitted changes (%s); commit them first" % (
            ", ".join(now_key["dirty"][:5]))
    if data is None:
        if run_for is not None:
            return "running", None, "validators started %ds ago for commit %s" % (run_for, now_key["commit"][:12])
        return "missing", None, "no validator results for commit %s" % now_key["commit"][:12]
    k = data.get("key") or {}
    for field, what in (("commit", "a different commit (%s)" % str(k.get("commit"))[:12]),
                        ("clean", "a working tree with uncommitted changes"),
                        ("gate", "a different version of the gate"),
                        ("config", "a different .sdlc/product.yaml or .sdlc/config/"),
                        ("ledger", "a different ledger (an operator action was recorded since)"),
                        ("verifiers", "different verifier evidence (a verifier ran or was launched since)"),
                        ("scope", "another scope (the product's phases, or a different feature)")):
        if k.get(field) != now_key[field]:
            if run_for is not None:
                return "running", data, "validators started %ds ago for commit %s" % (run_for, now_key["commit"][:12])
            return "stale", data, "the cached results describe %s" % what
    if data.get("phase") != label:
        return "stale", data, "the cached results are for another phase"
    return "fresh", data, "validators ran %s on commit %s" % (data.get("finished_at"), now_key["commit"][:12])


def ensure(root, st):
    """Gate-side trigger (Stop hook, request-review): start the current phase's
    validators when its result is missing or stale and the tree is clean.
    Returns (started, status, detail). Never raises."""
    label = st.get("current_phase")
    if not label or label == "done":
        return False, "done", "every phase is approved"
    try:
        status, _data, detail = read(root, label, st)
    except Exception as e:  # best effort: APPROVE fails closed on a missing result anyway
        return False, "error", repr(e)
    if status in ("missing", "stale"):
        return start(root, label), status, detail
    return False, status, detail


def start(root, label):
    """Start the worker unless one is running. Never raises."""
    if running(root, label) is not None:
        return False
    try:
        os.makedirs(cache_dir(root), exist_ok=True)
        with open(os.path.join(cache_dir(root), "validation-%s.log" % label), "w") as log:
            subprocess.Popen([sys.executable, "-I", WORKER, root, label], cwd=root, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True, close_fds=True)
        return True
    except OSError:
        return False


def wait(root, label, st, budget):
    deadline = time.time() + budget
    while True:
        status, data, detail = read(root, label, st)
        if status != "running" and not (status in ("missing", "stale") and running(root, label) is not None):
            return status, data, detail
        if time.time() >= deadline:
            return status, data, detail
        time.sleep(0.25)


def summary(data, limit=8):
    """Operator-facing lines for a result set."""
    rows = []
    for r in (data or {}).get("results") or []:
        line = "%s: %s" % (r.get("validator"), r.get("result").upper())
        if r.get("result") not in ("pass",):
            line += " (%s)" % (r.get("first_line") or "").strip()[:160]
        rows.append(line)
    if not rows:
        rows.append("no validators are registered for this phase")
    return rows[:limit] + (["... and %d more" % (len(rows) - limit)] if len(rows) > limit else [])


def findings(data, limit=6):
    """The failing/unknown validators' own output lines (the 'findings')."""
    out = []
    for r in (data or {}).get("results") or []:
        if r.get("result") in ("fail", "unknown"):
            lines = [ln.strip() for ln in (r.get("output") or "").splitlines()
                     if ln.strip().startswith(("FAIL", "ERR", "MISSING", "UNKNOWN")) or "FAIL" in ln[:12]]
            out.append("%s %s: %s" % (r.get("validator"), r.get("result").upper(),
                                       "; ".join(lines[:limit]) or (r.get("first_line") or "")[:200]))
    return out
