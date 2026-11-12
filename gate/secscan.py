#!/usr/bin/python3
"""Claude Security as the phase-9 finding source (increment 5; DESIGN.md §5).

Claude Security (claude-security@claude-plugins-official, force-enabled by the
managed policy) cannot run as a MOADIX subagent: its orchestrator is a main
agent that dispatches its own researchers and verifier panel through the
Workflow tool, and its agent file says it must never be dispatched as a
subagent. So the GATE schedules it as a headless session of its own:

  when     the agent calls /moadix:request-review in phase 9 (never on the Stop
           hook: a scan costs real time and tokens), with a clean tree and no
           scan for HEAD yet. One scan per commit.
  where    a clone of the product at HEAD under
           ~/Library/Caches/moadix/claude-security/<product>/<head12>/repo, with
           a sparse checkout that leaves out .sdlc/ (gate state is not product
           code, and without .sdlc/product.yaml MOADIX treats the scan session as
           outside a product). `git status` there is clean and HEAD is the
           product's HEAD, so the scan's revision stamp names exactly that commit.
           The builder cannot write there: its Bash sandbox has no write rule for
           it and the PreToolUse hook denies its file tools (check_path).
  how      `claude -p --agent claude-security:claude-security --permission-mode
           auto` with a fixed prompt that names the job and accepts the token
           cost (the plugin's documented way to skip its start confirmation).
  result   the gate reads CLAUDE-SECURITY-*/CLAUDE-SECURITY-RESULTS.sarif and the
           CLAUDE-SECURITY-REVISION-<sha12>.json stamp, refuses a stamp for
           another commit or a -dirty one, copies the SARIF into the evidence
           index with the commit, and turns each result into a FINDING with a
           stable SF-n id (.sdlc/evidence/sf-register.json maps the plugin's
           claudeSecurityPluginFindingId to SF-n, append-only). Findings only,
           never a verdict: check_claude_security (phase 9) decides.

Severity: the plugin's own (CRITICAL/HIGH/MEDIUM/LOW); none readable is
`unknown`. Confirmation (increment 6, ruling 1): a finding the plugin could not
confirm (no complete verifier panel, or LOW confidence) is recorded with
`confirmed: false`, whatever its severity. It blocks phase 9 until EITHER the
gate-scheduled fresh-context verifier moadix:sf-triager triages it as confirmed
or rejected, with evidence citing path:line at HEAD, OR the operator waives it
with a reason. It is never unwaivable merely for being unconfirmed. A CONFIRMED
critical or high finding (by the plugin's panel or by the triager) stays
unwaivable.
"""
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

GATE_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(GATE_DIR))
sys.path.insert(0, os.path.join(GATE_DIR, "v1"))

from gate import state  # noqa: E402

PHASE = "9"
ROLE = "claude-security"
PLUGIN_AGENT = "claude-security:claude-security"
PROMPT = ("Scan the codebase: the whole repository, at %s effort. I understand it will use a lot of tokens. "
          "Do not suggest patches. Write the report and stop.")
EFFORTS = ("low", "medium", "high")
TIMEOUT = 4 * 3600
SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
LEVEL = {"error": "high", "warning": "medium"}
FIXTURE = os.path.exists(os.path.join(GATE_DIR, "_testguard.py"))


def scan_base():
    if FIXTURE and os.environ.get("MOADIX_GUARD_ROOT"):
        return os.path.join(os.environ["MOADIX_GUARD_ROOT"], "scans")
    return os.path.join(os.path.expanduser("~"), "Library", "Caches", "moadix", "claude-security")


def _git(root, *args, check=True):
    p = subprocess.run([state.GIT, "-C", root] + list(args), capture_output=True, text=True, timeout=120)
    if check and p.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args[:2]), p.stderr.strip()[:200]))
    return p.stdout.strip()


def gate_dir(root):
    return os.path.join(root, state.SDLC, "cache", "verify", PHASE, ROLE)


def result_file(root):
    return os.path.join(gate_dir(root), "result.json")


def lock_file(root):
    return os.path.join(gate_dir(root), "scan.lock")


def scan_dir(root, head):
    pid = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16]
    return os.path.join(scan_base(), pid, head[:12])


def claude_bin():
    """Claude Code for the headless scan: the trusted directories, then ~/.local/bin (the
    native installer's link). Never PATH."""
    from gate.v1 import hlib
    dirs = []
    try:
        dirs = [str(d) for d in (hlib.load_yaml(os.path.join(GATE_DIR, "config", "trusted-bin.yaml")) or {}).get(
            "dirs") or []]
    except Exception:
        dirs = []
    if not FIXTURE:
        dirs.append(os.path.join(os.path.expanduser("~"), ".local", "bin"))
    for d in dirs:
        p = os.path.join(d, "claude")
        if os.access(p, os.X_OK):
            return p
    return None


def effort(root):
    from gate.v1 import toolrun
    e = str((toolrun.product_tools(root).get("claude_security") or {}).get("effort") or "medium")
    return e if e in EFFORTS else "medium"


# ---------------------------------------------------------------- schedule (hook side)
STARTING_SECONDS = 120


def running(root):
    """True while a scan worker holds the lock (or is starting: pid 0, briefly)."""
    try:
        with open(lock_file(root)) as f:
            pid, started = f.read().split()
        age = time.time() - float(started)
        if int(pid) == 0:
            return age < STARTING_SECONDS
        os.kill(int(pid), 0)
        return age < TIMEOUT + 600
    except (OSError, ValueError):
        return False


def status(root):
    """(state, detail): none | running | done (for which head)."""
    if running(root):
        return "running", "a Claude Security scan is running"
    try:
        with open(result_file(root)) as f:
            r = json.load(f)
        return "done", r.get("head")
    except (OSError, ValueError):
        return "none", None


def schedule(root, st):
    """Start a scan for HEAD in phase 9 when none exists. Never raises; returns a short note."""
    try:
        if st.get("current_phase") != PHASE:
            return "not phase 9"
        head = _git(root, "rev-parse", "--verify", "HEAD")
        dirty = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", ".", ":(exclude).sdlc",
                     ":(exclude).sdlc-proposals")
        if dirty:
            return "tree is dirty; no scan"
        s, h = status(root)
        if s == "running" or (s == "done" and h == head):
            return "scan %s" % s
        os.makedirs(gate_dir(root), exist_ok=True)
        # Taken BEFORE the spawn (pid 0 = "starting", honoured for STARTING_SECONDS), so a second
        # request-review sees it at once; the worker rewrites it with its pid and removes it at the end.
        with open(lock_file(root), "w") as f:
            f.write("0 %f" % time.time())
        with open(os.path.join(gate_dir(root), "scan.log"), "w") as log:
            subprocess.Popen([sys.executable, "-I", os.path.realpath(__file__), root, head], cwd=root,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
        return "scan started for %s" % head[:12]
    except Exception as e:  # never block the request-review call
        return "scan not started: %r" % (e,)


# ---------------------------------------------------------------- worker
def clone(root, head, dest):
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    subprocess.run([state.GIT, "clone", "--quiet", "--no-local", "--no-checkout", root, dest], check=True,
                   capture_output=True, timeout=600)
    _git(dest, "sparse-checkout", "set", "--no-cone", "/*", "!/.sdlc/")
    _git(dest, "checkout", "--quiet", "--detach", head)
    if _git(dest, "rev-parse", "HEAD") != head:
        raise RuntimeError("the clone is not at %s" % head)
    if os.path.exists(os.path.join(dest, state.SDLC)):
        raise RuntimeError("the sparse checkout left .sdlc/ in the scan clone")


def find_report(repo):
    dirs = sorted(d for d in os.listdir(repo) if d.startswith("CLAUDE-SECURITY-") and
                  os.path.isdir(os.path.join(repo, d)))
    if not dirs:
        return None, None, None
    d = os.path.join(repo, dirs[-1])
    sarif = os.path.join(d, "CLAUDE-SECURITY-RESULTS.sarif")
    stamps = [f for f in os.listdir(d) if re.match(r"^CLAUDE-SECURITY-REVISION-[0-9a-f]{12}(-dirty)?\.json$", f)]
    return d, sarif if os.path.exists(sarif) else None, stamps


def severity_of(result):
    """(severity, confirmed, raw). Unconfirmed findings keep the plugin's severity and
    carry confirmed=False; check_claude_security blocks them until triaged or waived."""
    rec = ((result.get("properties") or {}).get("claudeSecurityPlugin") or {})
    raw = str(rec.get("severity") or "").upper()
    sev = SEV.get(raw) or LEVEL.get(str(result.get("level") or ""))
    conf = str(rec.get("confidence") or "").upper()
    panel = (rec.get("verification") or {}).get("panel")
    complete = isinstance(panel, dict) and isinstance(panel.get("voters"), int) and panel.get("voters", 0) > 0 \
        and panel.get("true", 0) * 2 > panel.get("voters", 0)
    confirmed = complete and conf in ("HIGH", "MEDIUM")
    if not sev:
        sev = "unknown"
    return sev, confirmed, raw or str(result.get("level") or "")


RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def judge(fd, tri):
    """(state, severity) of one gate finding given its sf-triager entry (or None).
    state: confirmed | unconfirmed | rejected. A finding the triager confirms takes the
    higher of the plugin's and the triager's severity; unknown only if neither is known."""
    sev = str(fd.get("severity") or "unknown")
    if fd.get("confirmed"):
        return "confirmed", sev
    if not tri:
        return "unconfirmed", sev
    if tri.get("assessment") == "rejected":
        return "rejected", sev
    known = [x for x in (sev, str(tri.get("severity") or "")) if x in RANK]
    return "confirmed", (max(known, key=RANK.get) if known else "unknown")


def register(root, results):
    """Assign stable SF-n ids (append-only) to the plugin's finding ids."""
    p = os.path.join(root, state.SDLC, "evidence", "sf-register.json")
    try:
        with open(p) as f:
            reg = json.load(f)
    except (OSError, ValueError):
        reg = {"next": 1, "ids": {}}
    out = []
    for r in results:
        rec = ((r.get("properties") or {}).get("claudeSecurityPlugin") or {})
        pid = str(rec.get("claudeSecurityPluginFindingId") or "")
        if not pid:
            loc = ((r.get("locations") or [{}])[0].get("physicalLocation") or {})
            pid = "loc:" + hashlib.sha256(json.dumps([r.get("ruleId"), loc], sort_keys=True).encode()).hexdigest()
        if pid not in reg["ids"]:
            reg["ids"][pid] = "SF-%d" % reg["next"]
            reg["next"] += 1
        out.append((reg["ids"][pid], pid))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        json.dump(reg, f, indent=1, sort_keys=True)
    os.replace(p + ".tmp", p)
    return out


def ingest(root, head, sarif_path, stamp, meta):
    from gate.v1 import toolrun
    with open(sarif_path, "rb") as f:
        raw = f.read()
    doc = json.loads(raw.decode("utf-8"))
    results = [r for run in doc.get("runs") or [] for r in run.get("results") or []]
    ids = register(root, results)
    findings = []
    for r, (sf, pid) in zip(results, ids):
        sev, confirmed, rawsev = severity_of(r)
        loc = ((r.get("locations") or [{}])[0].get("physicalLocation") or {})
        path = ((loc.get("artifactLocation") or {}).get("uri") or "?")
        line = (loc.get("region") or {}).get("startLine")
        findings.append({"id": sf, "plugin_id": pid, "severity": sev, "plugin_severity": rawsev,
                         "confirmed": confirmed, "rule": r.get("ruleId"), "location": "%s:%s" % (path, line),
                         "summary": ((r.get("message") or {}).get("text") or "")[:300]})
    rel, digest = toolrun.record(root, PHASE, ROLE, meta.get("plugin_version") or "unknown",
                                 "claude-security.sarif", raw, "check-claude-security",
                                 {"stamp": stamp, "effort": meta.get("effort")})
    res = {"version": 1, "head": head, "stamp": stamp, "sarif": rel, "sarif_sha256": digest,
           "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "findings": findings}
    res.update(meta)
    return res


def write_result(root, data):
    os.makedirs(gate_dir(root), exist_ok=True)
    with open(result_file(root) + ".tmp", "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(result_file(root) + ".tmp", result_file(root))


def worker(root, head):
    os.makedirs(gate_dir(root), exist_ok=True)
    with open(lock_file(root), "w") as f:
        f.write("%d %f" % (os.getpid(), time.time()))
    meta = {"effort": effort(root)}
    try:
        exe = claude_bin()
        if not exe:
            raise RuntimeError("Claude Code was not found in the trusted directories or ~/.local/bin")
        d = scan_dir(root, head)
        repo = os.path.join(d, "repo")
        clone(root, head, repo)
        argv = [exe, "-p", PROMPT % meta["effort"], "--agent", PLUGIN_AGENT, "--permission-mode", "auto",
                "--output-format", "json"]
        env = {k: v for k, v in os.environ.items() if k in ("HOME", "USER", "LOGNAME", "LANG", "TERM")}
        env.update({"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": d})
        if FIXTURE:
            env.update({k: os.environ[k] for k in os.environ if k.startswith("MOADIX_")})
        t0 = time.time()
        p = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=TIMEOUT,
                           stdin=subprocess.DEVNULL)
        meta.update({"claude_exit": p.returncode, "seconds": int(time.time() - t0), "argv": argv[:1] + argv[2:]})
        with open(os.path.join(d, "session.json"), "w") as f:
            f.write(p.stdout or "")
        rdir, sarif, stamps = find_report(repo)
        if not rdir:
            raise RuntimeError("the scan wrote no CLAUDE-SECURITY-* report (claude exited %d: %s)" % (
                p.returncode, ((p.stderr or "") + (p.stdout or ""))[-300:]))
        if not sarif:
            raise RuntimeError("the report %s has no CLAUDE-SECURITY-RESULTS.sarif" % os.path.basename(rdir))
        want = "CLAUDE-SECURITY-REVISION-%s.json" % head[:12]
        if stamps != [want]:
            raise RuntimeError("the revision stamp is %s, expected exactly %s (a scan of another commit, or of a "
                               "dirty tree, is not evidence for this one)" % (stamps or "missing", want))
        with open(os.path.join(rdir, want)) as f:
            meta["revision_stamp"] = json.load(f)
        meta["plugin_version"] = plugin_version()
        write_result(root, ingest(root, head, sarif, want, meta))
    except Exception as e:
        write_result(root, {"version": 1, "head": head, "error": str(e)[:600], "findings": [], **meta})
    finally:
        with contextlib.suppress(OSError):
            os.unlink(lock_file(root))


def plugin_version():
    """The installed claude-security plugin's version, from the plugin cache (read-only)."""
    if FIXTURE:
        return "fixture"
    base = os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache", "claude-plugins-official",
                        "claude-security")
    try:
        return sorted(os.listdir(base))[-1]
    except OSError:
        return "unknown"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.stderr.write("usage: secscan.py <product-root> <head>\n")
        sys.exit(2)
    worker(os.path.realpath(sys.argv[1]), sys.argv[2])
