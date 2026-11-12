#!/usr/bin/env python3
"""check-load -- phase 10c gate-run load test (k6) plus the product's invariant check.

MOADIX-native (increment 5). Two checks, both required:

1. k6 (pinned, gate/config/tools.yaml). For each script in `load.scripts`
   (.sdlc/config/product-tools.yaml), committed at HEAD, the gate runs k6 on
   an export of HEAD through its own wrapper (gate/config/k6/wrapper.js): the
   product's options and functions run unchanged, the gate's handleSummary
   writes the full summary (JSON) and every threshold as a JUnit test case.
   A script with no thresholds fails: a load test that cannot fail is not a
   test. The verdict is k6's EXIT CODE (99 = a threshold crossed), cross-checked
   against the JUnit: an exit 0 with a failed case, or a non-zero exit with every
   case passing, is a failure, never a pass.
   Network: loopback only. The product's base URL (`load.base_url`, passed as
   __ENV.BASE_URL) must be http(s)://127.0.0.1|localhost|[::1]; and k6 runs with
   --blacklist-ip covering every non-loopback IPv4 and IPv6 address, so a script
   that names a production host is refused by k6 itself, whatever its URL.
2. The product's own SQL invariant check (`load.invariant_check`: argv of a
   committed script, run from the HEAD export after the load). It must exist and
   exit 0. It is product code, so it runs confined (no writes, loopback only).

Exit 0 pass, 1 fail, 2 UNKNOWN (k6 missing, or nothing configured to run).
"""
import html
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import toolrun  # noqa: E402
from check_scanners import export_head  # noqa: E402

PHASE = "10c"
WRAPPER = os.path.join(toolrun.GATE, "config", "k6", "wrapper.js")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
TRUSTED_RUNNERS = {"node", "python3", "sh", "bash", "psql", "sqlite3", "mysql"}


def non_loopback_ranges():
    """The complement of 127.0.0.0/8 and ::1/128, as CIDR blocks (k6 --blacklist-ip)."""
    v4 = list(ipaddress.ip_network("0.0.0.0/0").address_exclude(ipaddress.ip_network("127.0.0.0/8")))
    v6 = list(ipaddress.ip_network("::/0").address_exclude(ipaddress.ip_network("::1/128")))
    return ",".join(str(n) for n in sorted(v4) + sorted(v6))


def loopback_url(url):
    sp = urllib.parse.urlsplit(str(url or ""))
    return sp.scheme in ("http", "https") and (sp.hostname or "") in LOOPBACK


def runner(argv0):
    """A trusted absolute path for the invariant check's interpreter, or None."""
    b = os.path.basename(str(argv0))
    if b not in TRUSTED_RUNNERS:
        return None
    for d in toolrun.TRUSTED_BIN + ("/bin",):
        p = os.path.join(d, b)
        if os.access(p, os.X_OK):
            return p
    return None


def junit_cases(xml):
    return [(html.unescape(m.group(1)), bool(m.group(2))) for m in
            re.finditer(r'<testcase [^>]*name="([^"]*)">(<failure[^>]*/>)?</testcase>', xml)]


def run_script(root, tree, out, rel, base_url, notes, errs):
    work = os.path.join(out, re.sub(r"[^A-Za-z0-9]+", "-", rel).strip("-"))
    os.makedirs(work)
    with open(WRAPPER) as f:
        w = f.read().replace("__PRODUCT_SCRIPT__", "./" + rel)
    wrapper = os.path.join(tree, ".moadix-k6-wrapper-%s.js" % os.path.basename(work))
    with open(wrapper, "w") as f:
        f.write(w)
    rc, so, se, info = toolrun.run("k6", [
        "run", "--quiet", "--no-color", "--no-usage-report", "--address", "", "--blacklist-ip", non_loopback_ranges(),
        "-e", "MOADIX_OUT=" + work, "-e", "BASE_URL=" + base_url, os.path.basename(wrapper)],
        cwd=tree, writable=[out], network="loopback", timeout=1800)
    junit = os.path.join(work, "junit.xml")
    if not os.path.exists(junit):
        errs.append("%s: k6 exited %d and wrote no summary: %s" % (rel, rc, (se or so).strip()[-300:]))
        return None
    with open(junit) as f:
        cases = junit_cases(f.read())
    failed = [n for n, bad in cases if bad]
    if not cases:
        errs.append("%s declares no thresholds: a load test that cannot fail is not a test (k6 options.thresholds)"
                    % rel)
    for n in failed:
        errs.append("%s: threshold crossed: %s" % (rel, n))
    if rc == 99 and not failed:
        errs.append("%s: k6 exited 99 (thresholds crossed) but no JUnit case failed: the summary disagrees with "
                    "the exit code" % rel)
    elif rc == 0 and failed:
        errs.append("%s: a JUnit case failed but k6 exited 0: the exit code disagrees with the summary" % rel)
    elif rc not in (0, 99):
        errs.append("%s: k6 exited %d (not a threshold verdict): %s" % (rel, rc, (se or "").strip()[-300:]))
    notes.append("%s: k6 exit %d, %d threshold case(s), %d failed" % (rel, rc, len(cases), len(failed)))
    return work, info, rc, len(cases), len(failed)


def main():
    root = hlib.project_root()
    cfg = (toolrun.product_tools(root).get("load") or {})
    notes, errs, unknown = [], [], []
    scripts = [str(s) for s in (cfg.get("scripts") or [])]
    base_url = str(cfg.get("base_url") or "")
    inv = cfg.get("invariant_check")
    if not scripts:
        errs.append("no load scripts: declare load.scripts in .sdlc/config/product-tools.yaml (ADOPT)")
    if not loopback_url(base_url):
        errs.append("load.base_url %r is not a loopback http(s) URL. The gate never load-tests anything but the "
                    "local test instance, never a production URL" % base_url)
    if not (isinstance(inv, list) and inv and all(isinstance(x, str) for x in inv)):
        errs.append("no load.invariant_check: the product's own SQL invariant check (argv list) is a required "
                    "second check after the load")
    if errs:
        return toolrun.report("check-load (phase 10c, gate-run k6)", notes, [], errs, unknown)
    tracked = set(toolrun.tracked(root))
    out = toolrun.mkdtemp("moadix-load-")
    try:
        tree = os.path.join(out, "tree")
        os.makedirs(tree)
        export_head(root, tree)
        try:
            _p, pin = toolrun.tool("k6")
            for rel in scripts:
                if rel not in tracked:
                    errs.append("load script %s is not committed at HEAD" % rel)
                    continue
                r = run_script(root, tree, out, rel, base_url, notes, errs)
                if not r:
                    continue
                work, info, rc, n, nf = r
                for name in ("summary.json", "junit.xml"):
                    with open(os.path.join(work, name), "rb") as f:
                        data = f.read()
                    stem = re.sub(r"[^A-Za-z0-9]+", "-", rel).strip("-")
                    erel, digest = toolrun.record(root, PHASE, "k6", str(pin["version"]), "k6-%s-%s" % (stem, name),
                                                  data, "check-load", {"exit_code": rc, "cases": n, "failed": nf})
                    notes.append("evidence %s (sha256 %s)" % (erel, digest[:12]))
        except toolrun.ToolUnavailable as e:
            unknown.append(str(e))
        # 2. the product's invariant check, after the load
        if not unknown:
            exe = runner(inv[0])
            script = inv[1] if len(inv) > 1 else None
            if not exe:
                errs.append("load.invariant_check runs %r; allowed interpreters are %s (from trusted directories)" % (
                    inv[0], ", ".join(sorted(TRUSTED_RUNNERS))))
            elif script and script not in tracked:
                errs.append("load.invariant_check script %s is not committed at HEAD" % script)
            else:
                rc, so, se = run_invariant(tree, out, [exe] + inv[1:], base_url)
                text = ((so or "") + (se or "")).strip()
                erel, digest = toolrun.record(root, PHASE, "invariant-check", "product", "invariant-check.txt",
                                              "argv: %s\nexit: %d\n\n%s\n" % (json.dumps(inv), rc, text[-20000:]),
                                              "check-load", {"exit_code": rc})
                notes.append("invariant check exit %d; evidence %s (sha256 %s)" % (rc, erel, digest[:12]))
                if rc != 0:
                    errs.append("the product's invariant check failed (exit %d): %s" % (rc, text[-300:]))
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return toolrun.report("check-load (phase 10c, gate-run k6)", notes, [], errs, unknown)


def run_invariant(tree, out, argv, base_url):
    """Product code: confined like a tool run (no writes outside scratch, loopback only)."""
    conf, why = toolrun.confinement()
    env = {"PATH": "/usr/bin:/bin", "HOME": out, "TMPDIR": out, "BASE_URL": base_url, "LANG": "en_US.UTF-8"}
    if conf:
        prof = os.path.join(out, "invariant.sb")
        with open(prof, "w") as f:
            f.write(toolrun._profile(out, [], "loopback"))
        argv = [toolrun.SANDBOX_EXEC, "-f", prof] + argv
    elif not toolrun.FIXTURE:
        return 2, "", "refusing to run the invariant check unconfined: %s" % why
    try:
        p = subprocess.run(argv, cwd=tree, env=env, capture_output=True, text=True, timeout=600,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", "the invariant check could not run: %r" % (e,)


if __name__ == "__main__":
    sys.exit(main())
