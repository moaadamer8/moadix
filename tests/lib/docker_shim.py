#!/usr/bin/python3
"""TEST DOUBLE for docker/podman, installed in a fixture's trusted bin directory.

It never runs a container engine. It records every call and, for compose
projects that are not fixtures, records a guard violation (the suite fails):
  * the working directory must be inside the fixture base;
  * `-p/--project-name` (or COMPOSE_PROJECT_NAME) must start with "moadixfx";
  * every `-f/--file` must be inside the fixture base.
Behaviour for fixture projects, driven by files next to this shim:
  stop          exit 0, or exit 1 when fail-stop exists
  anything else print counts.json[last argv] (an integer), or exit 1
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
GUARD = os.path.dirname(HERE)  # the shim lives in <fixture base>/shim-bin


def violation(detail):
    with open(os.path.join(GUARD, "guard-violations.log"), "a") as f:
        f.write(json.dumps({"pid": os.getpid(), "argv0": sys.argv[0], "kind": "docker-real-project",
                            "detail": detail}) + "\n")


def main():
    argv = sys.argv[1:]
    cwd = os.path.realpath(os.getcwd())
    with open(os.path.join(HERE, "calls.log"), "a") as f:
        f.write(json.dumps({"argv": [os.path.basename(sys.argv[0])] + argv, "cwd": cwd}) + "\n")
    bad = []
    if not (cwd == GUARD or cwd.startswith(GUARD + "/")):
        bad.append("cwd %s is outside the fixture" % cwd)
    proj = os.environ.get("COMPOSE_PROJECT_NAME")
    for i, a in enumerate(argv):
        if a in ("-p", "--project-name") and i + 1 < len(argv):
            proj = argv[i + 1]
        if a in ("-f", "--file") and i + 1 < len(argv):
            p = os.path.realpath(os.path.join(cwd, argv[i + 1]))
            if not p.startswith(GUARD + "/"):
                bad.append("compose file %s is outside the fixture" % p)
    if "compose" in argv and not (proj or "").startswith("moadixfx"):
        bad.append("compose project %r is not a fixture project" % proj)
    if bad:
        violation("; ".join(bad) + " :: " + " ".join(argv))
        print("docker shim: refused: " + "; ".join(bad), file=sys.stderr)
        return 1
    if "stop" in argv or "down" in argv:
        return 1 if os.path.exists(os.path.join(HERE, "fail-stop")) else 0
    try:
        with open(os.path.join(HERE, "counts.json")) as f:
            counts = json.load(f)
        print(int(counts[argv[-1]]))
        return 0
    except (OSError, ValueError, KeyError):
        print("docker shim: no count for %r" % (argv[-1] if argv else ""), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
