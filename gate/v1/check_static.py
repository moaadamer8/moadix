#!/usr/bin/env python3
"""check-static — static analysis of the CONTROL LAYER itself.

Everything the harness does to a product it had never done to itself. The
enforcement code was tested behaviourally -- 198 attack cases -- and never read
by a tool that understands Python.

WHAT IT FOUND ON ITS FIRST RUN

  `re.split(pattern, s, 1)` in three places, two of them in gatecore: the glob
  specificity computation that decides WHICH PHASE OWNS A PATH, and the seam
  checker's overlap detector. Positional `maxsplit` has been deprecated since
  Python 3.13 and becomes a TypeError. It is a DeprecationWarning on 3.14 today,
  which no test could see, because a warning is not a failure. The decision
  engine was on a countdown that behavioural testing structurally cannot detect.

  And `export HARNESS_ROOT="$(cd "$DIR/.." && pwd)"` in twenty-two front doors.
  `export` discards the substitution's exit status, so a failed `cd` sets an
  EMPTY root and every path below resolves against `/` -- silently, in the
  direction that matters, since the gate reads its own config from there.

THREE TOOLS, EACH FOR WHAT IT IS GOOD AT

  ruff        defect-focused rule set over harness/lib/** and harness/hooks/**
  mypy        calls that cannot work, names that do not exist
  shellcheck  harness/bin/** and harness/hooks/** -- the shell half, which ruff
              and mypy cannot see at all and which is where the front doors live

Run through `uv`, the same way check-lld runs openapi-spec-validator: no global
install, pinned invocation, and a missing `uv` is reported as UNKNOWN rather
than passed over. A static-analysis gate that silently does nothing when its
tool is absent is worse than not having one, because the green tick is still
there.

Exit 0 = clean · 1 = findings · 2 = cannot evaluate.
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

# MOADIX v2 change notice: the control layer is now the gate package and the
# installer, so these are the targets (v1: harness/lib, harness/hooks, harness/bin).
PY_TARGETS = ["gate"]
SH_TARGETS = ["managed", "checker"]


def run(argv, root, timeout=300):
    try:
        p = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 127, "could not run %r: %r" % (argv[0], exc)


def sh_files(root):
    out = []
    for d in SH_TARGETS:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if f.endswith(".sh"):
                out.append(os.path.join(d, f))
    return out


def main():
    ap = argparse.ArgumentParser(prog="check-static.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--tool", choices=["ruff", "mypy", "shellcheck"], default=None,
                    help="run only one tool (diagnostics; the gate runs all three)")
    args = ap.parse_args()

    # A self-check of the gate's own code: the root is the gate's repo/install
    # directory, never a product.
    root = os.path.dirname(hlib.GATE_DIR)
    errs, notes = [], []

    if not shutil.which("uv"):
        print("check-static: `uv` is not on PATH, so no analyser could be run.\n"
              "  A static-analysis gate that silently does nothing when its tool is missing "
              "is worse than not having one: the green tick is still there.\n"
              "  Install uv (https://docs.astral.sh/uv/) or run the three tools yourself.",
              file=sys.stderr)
        return 2

    targets = [d for d in PY_TARGETS if os.path.isdir(os.path.join(root, d))]
    cfg = os.path.join("gate", "config", "ruff.toml")
    mypy_cfg = os.path.join("gate", "config", "mypy.ini")

    if args.tool in (None, "ruff"):
        if not os.path.exists(os.path.join(root, cfg)):
            errs.append("gate/config/ruff.toml is missing; the rule selection and every "
                        "suppression live there, so without it the run would silently mean "
                        "something else.")
        else:
            rc, out = run(["uvx", "ruff", "check", "--config", cfg,
                           "--output-format", "concise", "--quiet"] + targets, root)
            if rc == 0:
                notes.append("ruff: clean over %s" % ", ".join(targets))
            else:
                for line in out.strip().splitlines():
                    if line.strip():
                        errs.append("ruff  %s" % line.strip())

    if args.tool in (None, "mypy"):
        rc, out = run(["uvx", "mypy", "--config-file", mypy_cfg] + targets, root)
        if rc == 0:
            notes.append("mypy: clean")
        else:
            for line in out.strip().splitlines():
                if ": error:" in line or ": note:" in line:
                    errs.append("mypy  %s" % line.strip())
            if not any(e.startswith("mypy") for e in errs):
                errs.append("mypy exited %d without a parseable finding: %s" % (rc, out[-300:]))

    if args.tool in (None, "shellcheck"):
        files = sh_files(root)
        if not files:
            notes.append("shellcheck: no shell scripts found")
        else:
            rc, out = run(["uvx", "--from", "shellcheck-py", "shellcheck",
                           "--severity=warning", "--format=gcc"] + files, root)
            if rc == 0:
                notes.append("shellcheck: clean over %d script(s)" % len(files))
            else:
                for line in out.strip().splitlines():
                    if ":" in line and ("warning" in line or "error" in line):
                        errs.append("shell %s" % line.strip())
                if not any(e.startswith("shell") for e in errs):
                    errs.append("shellcheck exited %d without a parseable finding: %s"
                                % (rc, out[-300:]))

    if not args.quiet:
        print("check-static: %s" % root)
        for n in notes:
            print("  note  %s" % n)
        for e in errs[:60]:
            print("  FAIL  %s" % e)
        if len(errs) > 60:
            print("  ...   and %d more" % (len(errs) - 60))
        if not errs:
            print("  PASS  ruff, mypy and shellcheck are clean over the control layer.")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
