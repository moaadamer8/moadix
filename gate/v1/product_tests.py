#!/usr/bin/env python3
"""product_tests — builds the run plan for harness/bin/run-product-tests.sh.

Kept in python so it uses the same hlib parsing the gate uses, and so the
path-clamping logic lives next to the rest of the control layer.

TWO LEVELS, BECAUSE ONE LEVEL WAS A FALSE GREEN

  v0.4's toy-mobile suite was 17/17 green for four approved phases while a
  user-visible wrong number was live. It was testing the right function through
  the wrong entry point: `applyConversion` was covered thoroughly, and nothing
  could observe whether a keystroke CALLED it. The defect lived in
  `.onChange(of: value)`, inside a `body` the test build has to strip to
  compile at all.

  So a target now declares its LEVEL:

    unit  the code under test is called directly by the test
    ui    the test drives the real running product -- bindings, lifecycle,
          gestures, navigation. Playwright against a browser; Maestro or
          XCUITest against a booted simulator.

  A unit target cannot satisfy an acceptance criterion that is about a UI state
  transition, and check-traceability now refuses to pretend otherwise.

STRIPPING IS A DECLARED PROPERTY, NOT A SECRET

  A target that compiles a MODIFIED copy of the product sets
  `strips_source: true` and must emit `test-results/strip-manifest.txt` naming
  what it removed. toy-mobile already generated exactly that file, accurately,
  and nothing read it -- a declaration nothing reads is not a control
  (Constitution 3.9). check-traceability reads it now.

THE PLAN FORMAT

  Tab-separated records on stdout, one target after another:

      TARGET<TAB>id<TAB>level<TAB>strips(0|1)
      WORKDIR<TAB>absolute
      ARTIFACT<TAB>absolute, clamped inside the governed root
      ARGV<TAB>element            (repeated)

  Everything is derived from protected configuration. Nothing is taken from the
  caller: the shell wrapper refuses arguments entirely.
"""

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

# Built-in runners. `custom` takes an explicit argv from the config file.
BUILTIN = {
    "node-test": lambda cfg: [
        "node", "--test",
        "--test-reporter=junit",
        "--test-reporter-destination=%s" % cfg["_artifact"],
        *cfg["_globs"],
    ],
    "pytest": lambda cfg: [
        "python3", "-m", "pytest", "-q",
        "--junitxml=%s" % cfg["_artifact"],
        *cfg["_globs"],
    ],
}

LEVELS = ("unit", "ui")

# The unit target keeps the historic filename so every existing consumer --
# check-traceability's default glob, the scorecard's aggregate -- keeps working
# unchanged. Other targets get a suffixed sibling.
ARTIFACT_DIR = "test-results"
STRIP_MANIFEST = os.path.join(ARTIFACT_DIR, "strip-manifest.txt")


def fail(msg, code=2):
    sys.stderr.write("run-product-tests: %s\n" % msg)
    sys.exit(code)


def artifact_name(target_id):
    return "junit.xml" if target_id == "unit" else "junit-%s.xml" % target_id


def normalise(cfg):
    """[target dict] from either schema.

    A v1 file -- a bare `runner:` at the top level -- is one `unit` target.
    Accepting it is not politeness: every product in the tree is v1 today, and
    a config change that silently stops the suite running would be a far worse
    failure than the one this is fixing.
    """
    targets = cfg.get("targets")
    if isinstance(targets, list) and targets:
        return [dict(t) for t in targets if isinstance(t, dict)]
    if cfg.get("runner"):
        one = {k: v for k, v in cfg.items() if k != "targets"}
        one.setdefault("id", "unit")
        one.setdefault("level", "unit")
        return [one]
    return []


def build(root, governed, t, seen_ids):
    """(record_lines) for one target, or fail() with a reason."""
    tid = str(t.get("id") or "").strip()
    if not tid or not tid.replace("-", "").replace("_", "").isalnum():
        fail("target id %r must be non-empty and alphanumeric (- and _ allowed)" % tid)
    if tid in seen_ids:
        fail("duplicate target id %r; artifacts would overwrite each other" % tid)
    seen_ids.add(tid)

    level = str(t.get("level") or "unit").strip()
    if level not in LEVELS:
        fail("target %r declares level %r; expected one of %s" % (tid, level, ", ".join(LEVELS)))

    artifact = os.path.realpath(os.path.join(governed, ARTIFACT_DIR, artifact_name(tid)))
    # The path is not read from config at all, so a traversal planted there
    # cannot move it -- assert it anyway, so a future edit that DOES make it
    # configurable inherits the clamp.
    if not (artifact == governed or artifact.startswith(governed + os.sep)):
        fail("refusing artifacts path %s -- outside the governed root %s" % (artifact, governed))

    runner = str(t.get("runner") or "").strip()
    if not runner:
        fail("target %r declares no `runner`" % tid)

    globs = t.get("test_globs") or t.get("test_glob") or []
    if isinstance(globs, str):
        globs = [globs]
    globs = [str(g) for g in globs]
    for g in globs:
        if g.startswith("/") or ".." in g.split("/"):
            fail("test glob %r escapes the product tree" % g)

    t["_artifact"] = artifact
    t["_globs"] = globs

    if runner == "custom":
        argv = t.get("command")
        if not isinstance(argv, list) or not argv:
            fail("target %r: runner: custom requires a `command:` argv list" % tid)
        argv = [str(a).replace("{artifact}", artifact) for a in argv]
    elif runner in BUILTIN:
        argv = BUILTIN[runner](t)
    else:
        fail("target %r: unknown runner %r (expected: %s, custom)"
             % (tid, runner, ", ".join(sorted(BUILTIN))))

    if not shutil.which(argv[0]):
        fail("target %r: test runner %r not found on PATH" % (tid, argv[0]), code=127)

    workdir = governed
    wd = t.get("workdir")
    if wd:
        cand = os.path.realpath(os.path.join(governed, str(wd)))
        if not (cand == governed or cand.startswith(governed + os.sep)):
            fail("target %r: workdir %r escapes the governed root" % (tid, wd))
        workdir = cand

    strips = "1" if bool(t.get("strips_source")) else "0"
    rec = ["TARGET\t%s\t%s\t%s" % (tid, level, strips),
           "WORKDIR\t%s" % workdir,
           "ARTIFACT\t%s" % artifact]
    rec += ["ARGV\t%s" % a for a in argv]
    for line in rec:
        if "\n" in line:
            fail("run plan element contains a newline; refusing")
        if line.count("\t") != (1 if line.startswith(("WORKDIR", "ARTIFACT", "ARGV")) else 3):
            fail("run plan element contains a tab; refusing (%r)" % line)
    return rec


def main():
    ap = argparse.ArgumentParser(prog="product_tests.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="emit the run plan and exit")
    args = ap.parse_args()
    if not args.plan:
        ap.print_help()
        return 2

    root = hlib.project_root()

    try:
        paths_doc = hlib.load_paths_doc(root)
    except Exception as exc:
        fail("cannot read harness/config/phase-paths.yaml (%r)" % (exc,))
    groot = (paths_doc or {}).get("governed_root") or ""
    if not groot:
        fail("phase-paths.yaml declares no governed_root")
    governed = os.path.realpath(os.path.join(root, groot))
    if not os.path.isdir(governed):
        fail("governed root %r does not exist" % groot)

    cfg_path = hlib.config_path(root, "product-tests.yaml")
    if not os.path.exists(cfg_path):
        fail("no harness/config/product-tests.yaml. The operator configures what runs; "
             "the agent does not choose it.")
    try:
        cfg = hlib.load_yaml(cfg_path) or {}
    except Exception as exc:
        fail("product-tests.yaml does not parse (%r)" % (exc,))

    targets = normalise(cfg)
    if not targets:
        fail("product-tests.yaml declares neither `targets:` nor a top-level `runner`")

    out, seen = [], set()
    for t in targets:
        out += build(root, governed, t, seen)
    # Trailing newline is REQUIRED, not cosmetic. Without it `while read` in the
    # wrapper silently drops the final record -- which cost the last target its
    # test glob, so `node --test` fell back to running every test in the tree
    # and reported MORE cases, not fewer. A truncation that inflates the count
    # is the worst shape a truncation can take.
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
