"""The gate runs the current phase's validators itself (ruling 2, increment 3).

Two triggers, both gate-side (the agent cannot start a worker or write the cache):
  Stop hook       `hook.py stop`: every time the agent's turn ends in a product,
                  if the current phase has no fresh result and the tree is clean.
  request-review  the agent's /moadix:request-review call (PreToolUse sees the
                  Skill / SlashCommand tool call and starts the run before it
                  is allowed through).

Neither ever blocks or answers: a missing result makes APPROVE refuse, which is
the fail-closed side. The worker (gate/validate.py) writes .sdlc/cache/, keyed
by commit; APPROVE reads it and records the digest of the file it relied on.
"""
import re

from . import state, validation

REQUEST_REVIEW = re.compile(r"^/?(?:moadix:)?request-review\b")


def trigger(cwd):
    """(started, detail) for the product holding cwd; (False, reason) otherwise. Never raises."""
    try:
        root = state.find_root(cwd)
        if not root:
            return False, "not in a MOADIX product"
        st, problems = state.current_state(root)
        if problems:
            return False, "gate state failed its integrity check"
        started, status, detail = validation.ensure(root, st)
        return started, "%s: %s" % (status, detail)
    except Exception as e:  # never block the agent's turn from ending
        return False, "error: %r" % (e,)


def on_stop(hook_input):
    trigger(hook_input.get("cwd"))


def on_request_review(cwd):
    """request-review: the validators (as on Stop) and, in phase 9 only, the Claude Security
    scan for HEAD (gate/secscan.py). Never on the Stop hook: a scan costs real time and
    tokens, so it starts only when the agent says the phase is ready. Never raises."""
    started, detail = trigger(cwd)
    try:
        root = state.find_root(cwd)
        if root:
            st, problems = state.current_state(root)
            if not problems and st.get("current_phase") == "9":
                from . import secscan
                detail += "; claude-security: " + secscan.schedule(root, st)
    except Exception as e:
        detail += "; claude-security: not started (%r)" % (e,)
    return started, detail


def is_request_review(tool, tool_input):
    if tool == "Skill":
        return bool(REQUEST_REVIEW.match(str((tool_input or {}).get("skill") or "")))
    if tool == "SlashCommand":
        return bool(REQUEST_REVIEW.match(str((tool_input or {}).get("command") or "")))
    return False
