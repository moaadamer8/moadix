#!/usr/bin/python3
"""MOADIX hook entry point: `hook.py prompt` (UserPromptSubmit), `hook.py pretool`
or `hook.py stop` (Stop: starts the current phase's validators, never blocks).

Run by /usr/bin/python3 (SIP-protected), from MOADIX_HOME, the root-owned copy
the installer makes. Exit codes:
  0  normal; JSON on stdout when there is something to say
  1  internal failure -> with onFailure "block" Claude Code blocks the action
PreToolUse fails closed inside the script too (any exception -> deny).
UserPromptSubmit never blocks on purpose (Amendment 1 §2): an exception is
reported to the agent as added context, and nothing is recorded.
"""
import contextlib
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with contextlib.suppress(ImportError):  # only in test fixtures' gate copies (tests/lib/_testguard.py)
    importlib.import_module("gate._testguard")
from gate import autoval, opcmd, pretool  # noqa: E402


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "stop":
        # Never answers and never fails: a Stop hook that blocked would keep the agent running.
        # Fail-open is safe here because a missing validator result makes APPROVE refuse.
        with contextlib.suppress(Exception):
            autoval.on_stop(json.load(sys.stdin))
        return 0
    data = json.load(sys.stdin)
    if mode == "pretool":
        try:
            out = pretool.decide(data)
        except Exception as e:  # fail closed
            out = pretool.deny("gate error (%s); the action is refused until this is fixed" % type(e).__name__)
    elif mode == "prompt":
        try:
            out = opcmd.handle(data)
        except Exception as e:
            out = opcmd._ctx("gate error (%s: %s). Nothing was recorded." % (type(e).__name__, e))
            with contextlib.suppress(Exception):  # best effort: the reply above already says nothing was recorded
                opcmd._burn_all(data.get("prompt") or "")
    else:
        sys.stderr.write("usage: hook.py prompt|pretool\n")
        return 1
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
