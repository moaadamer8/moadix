"""sandbox — confine product code that a ported validator executes.

MOADIX v2 change notice: ported from sdlc-harness v1 harness/lib/sandbox.py.
v1's profile was `(allow default)` minus writes to the control surface, which
was enough while the harness itself ran with the agent's privileges. In v2 the
validators run in a worker the gate's hook starts, OUTSIDE Claude Code's
sandbox, so v1's profile would let product code write anything the user can
(~/.zshrc, ~/.claude, other repos). The v2 profile therefore denies EVERY write
except one per-run scratch directory and the standard streams, and denies all
network.

Only check_surface_coverage's enumerator uses this (the one place a ported
validator executes product code). If sandbox-exec is missing or refuses to
apply (for example when nested inside another sandbox), wrap() raises and the
caller reports the enumerator as failed: product code never runs unconfined.
"""

import os
import tempfile

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def available():
    if not os.path.exists(SANDBOX_EXEC):
        return False, "%s is not present (deprecated by Apple; may have been removed)." % SANDBOX_EXEC
    if not os.access(SANDBOX_EXEC, os.X_OK):
        return False, "%s exists but is not executable." % SANDBOX_EXEC
    return True, ""


def profile(scratch):
    s = os.path.realpath(scratch).replace('"', '\\"')
    return "\n".join([
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        '(allow file-write* (subpath "%s") (literal "/dev/null") (literal "/dev/stdout")'
        ' (literal "/dev/stderr") (literal "/dev/tty") (literal "/dev/dtracehelper"))' % s,
    ]) + "\n"


def wrap(root, argv, profile_path):
    """argv, confined. Raises RuntimeError when confinement is unavailable."""
    ok, why = available()
    if not ok:
        raise RuntimeError("refusing to run product code unconfined: %s" % why)
    scratch = tempfile.mkdtemp(prefix="moadix-enum-")
    with open(profile_path, "w", encoding="utf-8") as fh:
        fh.write(profile(scratch))
    return [SANDBOX_EXEC, "-f", profile_path] + list(argv)
