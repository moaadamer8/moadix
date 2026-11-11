#!/usr/bin/python3
"""MOADIX hook entry point: `hook.py prompt` (UserPromptSubmit) or `hook.py pretool`.

Run by /usr/bin/python3 (SIP-protected), from MOADIX_HOME, the root-owned copy
the installer makes. Exit codes:
  0  normal; JSON on stdout when there is something to say
  1  internal failure -> with onFailure "block" Claude Code blocks the action
PreToolUse fails closed inside the script too (any exception -> deny).
UserPromptSubmit never blocks on purpose (Amendment 1 §2): an exception is
reported to the agent as added context, and nothing is recorded.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gate import opcmd, pretool  # noqa: E402


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
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
            try:
                opcmd._burn_all(data.get("prompt") or "")
            except Exception:
                pass
    else:
        sys.stderr.write("usage: hook.py prompt|pretool\n")
        return 1
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
