#!/usr/bin/python3
"""Validator worker: `validate.py <product-root> <phase-label>`.

Started detached by the gate (REVIEW), never by the agent: it writes
.sdlc/cache/, which the agent cannot write. Runs every validator registered
for the phase (gate/config/registry.yaml, ported from v1) exactly as v1's
gate.py run_validators did, and writes one cache file keyed per commit
(gate/validation.py).

The validators are the ported v1 modules in gate/v1/. They read files only;
the one that can execute product code (check-surface-coverage's enumerator)
does so under sandbox-exec with a deny-all-writes profile and fails closed when
that is unavailable. The live probe is off in gate runs (MOADIX_GATE_RUN).
"""
import contextlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

GATE_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(GATE_DIR))
sys.path.insert(0, os.path.join(GATE_DIR, "v1"))

with contextlib.suppress(ImportError):  # only in test fixtures' gate copies; never installed
    importlib.import_module("gate._testguard")  # exists only in test fixtures
from gate import state, validation  # noqa: E402
import hlib  # noqa: E402

V1 = os.path.join(GATE_DIR, "v1")
LAUNCH = os.path.join(V1, "_launch.py")
GUARD_KEYS = ("MOADIX_GUARD_ROOT", "MOADIX_GUARD_REPO", "MOADIX_GUARD_SHIM")
TRUSTED_BIN = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")
TIMEOUT = 180
# check-lld needs PyYAML + openapi-spec-validator; v1's check-lld.sh provisioned
# them with `uv run --with`, and refused (exit 127, a failure) without uv.
UV_PACKAGES = {"check_lld": ["pyyaml", "openapi-spec-validator"]}


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def trusted(name):
    for d in TRUSTED_BIN:
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    return None


def validators_for(label):
    reg = hlib.load_yaml(os.path.join(GATE_DIR, "config", "registry.yaml")) or {}
    return [c for c in (reg.get("components") or [])
            if str(c.get("kind")) == "validator" and str(c.get("phase")) == str(label)]


def profile_na(root):
    """{validator_id: (reason, phase)} the Target Platform Ruling makes N/A (v1
    gate.profile_na_validators). Fails OPEN to "nothing is N/A" on any error:
    over-verifying is the safe direction."""
    try:
        import check_profile
        ruling, _err = check_profile.read_ruling(os.path.join(root, "sdlc"))
        if not ruling:
            return None, {}
        prof = hlib.load_yaml(hlib.config_path(root, "profiles.yaml"))
        entry = ((prof.get("profiles") or {}).get(ruling) or {})
        out = {}
        for na in (entry.get("not_applicable") or []):
            if na.get("validator"):
                out[str(na["validator"])] = (str(na.get("reason") or "").strip(), str(na.get("phase")))
        return ruling, out
    except Exception:
        return None, {}


def argv_for(c):
    mod = str(c.get("module"))
    path = os.path.join(V1, mod + ".py")
    args = [str(a) for a in (c.get("args") or [])]
    if mod in UV_PACKAGES:
        uv = trusted("uv")
        if not uv:
            return None, "uv is required (it provisions %s); refusing to pass an unvalidated contract" % (
                ", ".join(UV_PACKAGES[mod]))
        argv = [uv, "run", "--quiet", "--no-project"]
        for pkg in UV_PACKAGES[mod]:
            argv += ["--with", pkg]
        return argv + ["python3", "-I", LAUNCH, path] + args, None
    return [sys.executable, "-I", LAUNCH, path] + args, None


def run_one(root, c, env):
    argv, why = argv_for(c)
    if argv is None:
        return 127, why
    try:
        p = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=TIMEOUT,
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "validator timed out after %ds" % TIMEOUT
    except OSError as exc:
        return 127, "validator could not be executed: %r" % (exc,)


def result_of(rc):
    return "pass" if rc == 0 else "unknown" if rc == 2 else "fail"


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: validate.py <product-root> <phase-label>\n")
        return 2
    root, label = os.path.realpath(sys.argv[1]), sys.argv[2]
    if not re.match(r"^\d{1,2}[a-z]?$", label):
        return 2
    os.makedirs(validation.cache_dir(root), exist_ok=True)
    lf = validation.lock_file(root, label)
    if validation.running(root, label) is not None:
        return 0
    with open(lf, "w") as f:
        f.write("%d %f" % (os.getpid(), time.time()))
    try:
        st, problems = state.current_state(root)
        if problems:
            sys.stderr.write("gate state failed its integrity check; not validating: %s\n" % "; ".join(problems))
            return 1
        k = validation.key(root, st)
        started = now()
        with tempfile.TemporaryDirectory(prefix="moadix-validate-") as tmp:
            doc_path = os.path.join(tmp, "phase-doc.json")
            with open(doc_path, "w") as f:
                json.dump(hlib.v1_phase_doc(st), f)
            env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": os.environ.get("HOME", "/var/empty"),
                   "LANG": "en_US.UTF-8", "TMPDIR": tmp, "MOADIX_PRODUCT_ROOT": root,
                   "MOADIX_PHASE_DOC": doc_path, "MOADIX_GATE_RUN": "yes"}
            if os.path.exists(os.path.join(GATE_DIR, "_testguard.py")):  # test fixtures only
                env.update({k: os.environ[k] for k in GUARD_KEYS if k in os.environ})
            ruling, na = profile_na(root)
            results = []
            for c in validators_for(label):
                vid = str(c.get("id"))
                cmd = " ".join([str(c.get("module"))] + [str(a) for a in (c.get("args") or [])])
                if vid in na and na[vid][1] == str(label):
                    results.append({"validator": vid, "command": cmd, "exit_code": None, "result": "n/a-by-profile",
                                    "first_line": ("ruling %s: %s" % (ruling, na[vid][0]))[:200], "output": ""})
                    continue
                rc, out = run_one(root, c, env)
                first = next((ln for ln in out.splitlines() if ln.strip()), "")
                results.append({"validator": vid, "command": cmd, "exit_code": rc, "result": result_of(rc),
                                "first_line": first[:200], "output": out[-6000:]})
        verdict = "pass" if all(r["result"] in ("pass", "n/a-by-profile") for r in results) else (
            "unknown" if any(r["result"] == "unknown" for r in results) and
            not any(r["result"] == "fail" for r in results) else "fail")
        data = {"version": 1, "phase": label, "key": k, "started_at": started, "finished_at": now(),
                "verdict": verdict, "results": results}
        tmpf = validation.cache_file(root, label) + ".tmp"
        with open(tmpf, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmpf, validation.cache_file(root, label))
        return 0
    finally:
        with contextlib.suppress(OSError):
            os.unlink(lf)


if __name__ == "__main__":
    sys.exit(main())
