"""toolrun -- the gate's runner for its pinned deterministic tools (increment 5).

MOADIX-native (not a v1 port). Shared by the increment-5 validators:
check_contracts (5), check_env (6b), check_scanners (9), check_claude_security
(9), check_load (10c), check_release (11).

  where    <MOADIX_HOME>/tools/<name>-<version>/, the root-owned copy that
           managed/install.sh fetched with managed/fetch_tools.py. Never PATH:
           a session or project setting could change PATH. The version and the
           pin come from gate/config/tools.yaml; a missing or mismatched tool is
           UNKNOWN (exit 2), never a pass.
  how      a fresh scratch HOME and TMPDIR per run, a minimal PATH, none of the
           user's environment (no tokens leak into a scanner). Under
           sandbox-exec when the installed gate runs it: every write denied except
           the scratch and the output directory, and the network denied unless
           the run needs it (a DB download). A fixture gate (tests only, marked by
           _testguard.py) runs unconfined when sandbox-exec cannot nest; the
           installed gate never does: no confinement is UNKNOWN.
  evidence the tool's SARIF or JSON lands in .sdlc/evidence/<phase>/ and one
           line per file is appended to .sdlc/evidence/index.jsonl: tool,
           version, path, sha256, source commit, produced_for. Only the gate's
           worker writes .sdlc/ (the agent's tools and sandbox cannot).
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
GATE = os.path.dirname(HERE)
HOME = os.path.dirname(GATE)                     # <MOADIX_HOME>; a fixture's home/
TOOLS_DIR = os.path.join(HOME, "tools")
PINS = os.path.join(GATE, "config", "tools.yaml")
FIXTURE = os.path.exists(os.path.join(GATE, "_testguard.py"))
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
TRUSTED_BIN = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")
GIT = "/usr/bin/git"
SEVERITIES = ("critical", "high", "medium", "low", "info", "unknown")
# What blocks: v1's rule (high and critical cannot ship), plus `unknown`: a finding whose
# severity the gate cannot read is not let through as if it were low.
BLOCKING = ("critical", "high", "unknown")


def mkdtemp(prefix):
    """A scratch directory. In a fixture gate it sits inside the fixture (the test guard
    requires every process's cwd to be there); installed, in the system temp dir."""
    base = None
    if FIXTURE and os.environ.get("MOADIX_GUARD_ROOT"):
        base = os.path.join(os.environ["MOADIX_GUARD_ROOT"], "tmp")
        os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=base)


def cache_dir(name):
    """A per-user cache for tool databases (trivy's vulnerability DB). Installed:
    ~/Library/Caches/moadix/<name>. A fixture keeps one under ~/.cache so a test run
    does not download the DB again."""
    if FIXTURE:
        d = os.path.join(os.path.expanduser("~"), ".cache", "moadix-fixture-cache", name)
    else:
        d = os.path.join(os.path.expanduser("~"), "Library", "Caches", "moadix", name)
    os.makedirs(d, exist_ok=True)
    return d


class ToolUnavailable(Exception):
    """The instrument is missing or wrong: UNKNOWN (exit 2), never a pass."""


def pins():
    import hlib
    doc = hlib.load_yaml(PINS) or {}
    return {str(t["name"]): t for t in doc.get("tools") or []}


def tool(name):
    """(absolute path of the tool's entry point, pin dict). Raises ToolUnavailable."""
    t = pins().get(name)
    if not t:
        raise ToolUnavailable("%s is not pinned in gate/config/tools.yaml" % name)
    d = os.path.join(TOOLS_DIR, "%s-%s" % (name, t["version"]))
    try:
        with open(os.path.join(d, ".moadix-tool.json")) as f:
            stamp = json.load(f)
    except (OSError, ValueError):
        raise ToolUnavailable("%s %s is not installed at %s (managed/install.sh fetches it)" % (
            name, t["version"], d)) from None
    if stamp.get("version") != str(t["version"]):
        raise ToolUnavailable("%s at %s is version %s, pinned %s" % (name, d, stamp.get("version"), t["version"]))
    p = os.path.join(d, str(t["bin"]))
    if not os.path.exists(p):
        raise ToolUnavailable("%s %s: %s is missing" % (name, t["version"], p))
    if stamp.get("bin_sha256"):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != stamp["bin_sha256"]:
            raise ToolUnavailable("%s %s: the binary does not match the sha256 recorded at install" % (
                name, t["version"]))
    return p, t


PROXY_ENV = {"https_proxy", "http_proxy", "no_proxy", "all_proxy"}
# /usr/bin/git on macOS is the xcrun shim: where it cannot write its per-user cache it fails
# and gitleaks then scans NOTHING (measured: "scanned ~0 bytes ... no leaks found"). The
# real, root-owned git goes first on a tool's PATH.
REAL_GIT_DIRS = ("/Library/Developer/CommandLineTools/usr/bin", "/Applications/Xcode.app/Contents/Developer/usr/bin")


def tool_path():
    dirs = [d for d in REAL_GIT_DIRS if os.access(os.path.join(d, "git"), os.X_OK)][:1]
    return ":".join(dirs + ["/usr/bin", "/bin", "/usr/sbin", "/sbin"])


def node():
    for d in TRUSTED_BIN:
        p = os.path.join(d, "node")
        if os.access(p, os.X_OK):
            return p
    raise ToolUnavailable("node is required for the npm-packaged tools and was not found in %s" % (
        ", ".join(TRUSTED_BIN)))


GITHUB_KEYCHAIN_SERVICE = "moadix-github-readonly"


def github_token():
    """The operator's read-only GitHub token, read by the GATE from the login Keychain
    (increment 6, ruling 2): never from PATH or the environment, and never exported in
    the shell the agent runs in. Needed only once a product reaches phase 11; until then
    its absence is not an error anywhere else. Fixture gates read a test variable."""
    if FIXTURE:
        return os.environ.get("MOADIX_TEST_GITHUB_TOKEN") or None
    try:
        p = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", GITHUB_KEYCHAIN_SERVICE, "-w"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return (p.stdout.strip() or None) if p.returncode == 0 else None


def argv_for(name, args):
    p, t = tool(name)
    if t["kind"] == "npm":
        return [node(), p] + list(args), t
    return [p] + list(args), t


def _profile(scratch, writable, network):
    allow = ['(subpath "%s")' % os.path.realpath(x).replace('"', '\\"') for x in [scratch] + list(writable)]
    lines = ["(version 1)", "(allow default)", "(deny file-write*)",
             "(allow file-write* %s (literal \"/dev/null\") (literal \"/dev/stdout\") (literal \"/dev/stderr\")"
             " (literal \"/dev/tty\") (literal \"/dev/dtracehelper\"))" % " ".join(allow)]
    if network == "none":
        lines.append("(deny network*)")
    elif network == "loopback":
        lines += ["(deny network*)", '(allow network* (remote ip "localhost:*"))',
                  '(allow network* (local ip "localhost:*"))']
    return "\n".join(lines) + "\n"


def confinement():
    """(available, why). The installed gate requires it; a fixture may run without it."""
    if not os.access(SANDBOX_EXEC, os.X_OK):
        return False, "%s is not available" % SANDBOX_EXEC
    try:
        p = subprocess.run([SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        return False, "sandbox-exec could not start: %r" % (e,)
    if p.returncode != 0:
        return False, "sandbox-exec cannot apply here (%s)" % (p.stderr or b"").decode(errors="replace").strip()[:120]
    return True, ""


def run(name, args, cwd, writable=(), network="none", timeout=600, env=None):
    """Run a pinned tool. Returns (rc, stdout, stderr, info). Raises ToolUnavailable.

    network: none | loopback | any (only for a scanner's own DB download)."""
    argv, t = argv_for(name, args)
    scratch = mkdtemp("moadix-tool-%s-" % name)
    try:
        e = {"PATH": tool_path(), "HOME": scratch, "TMPDIR": scratch, "LANG": "en_US.UTF-8",
             "NO_COLOR": "1", "CI": "1"}
        if network == "any":
            # A scanner's own database download honours the machine's proxy settings (a
            # corporate proxy, or a sandbox's). Never for loopback runs: k6's IP blocklist
            # must see the real destination, not a proxy.
            e.update({k: v for k, v in os.environ.items() if k.lower() in PROXY_ENV})
        e.update(env or {})
        conf, why = confinement()
        info = {"tool": name, "version": str(t["version"]), "confined": conf}
        if conf:
            prof = os.path.join(scratch, "profile.sb")
            with open(prof, "w") as f:
                f.write(_profile(scratch, writable, network))
            argv = [SANDBOX_EXEC, "-f", prof] + argv
        elif not FIXTURE:
            raise ToolUnavailable("refusing to run %s unconfined: %s" % (name, why))
        else:
            info["unconfined_reason"] = why
        try:
            p = subprocess.run(argv, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise ToolUnavailable("%s timed out after %ds" % (name, timeout)) from None
        except OSError as exc:
            raise ToolUnavailable("%s could not be executed: %r" % (name, exc)) from None
        return p.returncode, p.stdout, p.stderr, info
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- evidence
def head(root):
    p = subprocess.run([GIT, "-C", root, "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def evidence_dir(root, phase):
    return os.path.join(root, ".sdlc", "evidence", str(phase))


def record(root, phase, name, version, filename, data, produced_for, extra=None):
    """Write one evidence file and append its index line. Returns (relpath, sha256)."""
    commit = head(root)
    d = evidence_dir(root, phase)
    os.makedirs(d, exist_ok=True)
    stem, ext = os.path.splitext(filename)
    fn = "%s-%s%s" % (stem, (commit or "nocommit")[:12], ext)
    path = os.path.join(d, fn)
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    with open(path + ".tmp", "wb") as f:
        f.write(raw)
    os.replace(path + ".tmp", path)
    digest = hashlib.sha256(raw).hexdigest()
    rel = os.path.relpath(path, root)
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "phase": str(phase), "tool": name,
            "version": version, "path": rel, "sha256": digest, "source_commit": commit,
            "produced_for": produced_for}
    line.update(extra or {})
    with open(os.path.join(root, ".sdlc", "evidence", "index.jsonl"), "a") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
    return rel, digest


# ---------------------------------------------------------------- product config
def product_tools(root):
    """.sdlc/config/product-tools.yaml (adopted by the operator with ADOPT), or {}."""
    import hlib
    p = os.path.join(root, ".sdlc", "config", "product-tools.yaml")
    if not os.path.exists(p):
        return {}
    return hlib.load_yaml(p) or {}


def tracked(root, *pathspecs):
    """Tracked files at HEAD matching git pathspecs (the gate judges the commit, not stray files)."""
    p = subprocess.run([GIT, "-C", root, "ls-files", "-z", "--"] + list(pathspecs), capture_output=True)
    return sorted(x for x in p.stdout.decode("utf-8", "replace").split("\0") if x)


def score_severity(score):
    """CVSS base score -> severity (CVSS v3/v4 qualitative scale)."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if s >= 9.0:
        return "critical"
    if s >= 7.0:
        return "high"
    if s >= 4.0:
        return "medium"
    if s > 0:
        return "low"
    return "info"


def report(title, notes, findings, errs, unknown, out=print):
    """Print the validator's lines. findings: [(severity, id, text)]. Returns the exit code."""
    out("%s" % title)
    for n in notes:
        out("  note  %s" % n)
    for sev, fid, text in sorted(findings, key=lambda f: (SEVERITIES.index(f[0]) if f[0] in SEVERITIES else 9, f[1])):
        tag = "FAIL" if sev in BLOCKING else "find"
        out("  %s  [%s] %s %s" % (tag, sev, fid, text))
    for e in errs:
        out("  FAIL  %s" % e)
    for u in unknown:
        out("  UNKNOWN  %s" % u)
    blocking = [f for f in findings if f[0] in BLOCKING]
    if errs or blocking:
        return 1
    if unknown:
        return 2
    out("  PASS  %d finding(s), none at %s" % (len(findings), "/".join(BLOCKING)))
    return 0
