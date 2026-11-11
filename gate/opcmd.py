"""UserPromptSubmit: operator commands typed in chat (Amendment 1).

- The WHOLE message (surrounding whitespace trimmed) must match one command.
  Anything else (a quote, a pasted report, a longer message) records nothing.
- State-changing commands end with a 6-digit authenticator code. The checker
  alone verifies it (single use, cooldown after 3 wrong codes) and alone signs
  the ledger line.
- Never blocks: the outcome goes to the agent as added context, and the
  agent relays it. The ledger is the truth.
- Every 6-digit token in any message that did not become a recorded action is
  burned, so a valid code that lands in the agent's context is already spent.
"""
import base64
import json
import re
import subprocess

from . import pathmap, state

PH = r"(?P<phase>\d{1,2}[a-z]?)"
TEXT = r"[ !#-\[\]-~]{1,300}?"  # printable ASCII without " and \ (the checker's alphabet)
CODE = r" (?P<code>\d{6})"
COMMANDS = [
    ("APPROVE", re.compile(r"^APPROVE " + PH + CODE + r"$")),
    ("REOPEN", re.compile(r"^REOPEN " + PH + r" (?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("WAIVE", re.compile(r"^WAIVE (?P<id>[A-Za-z0-9_.-]{1,64}) owner=(?P<owner>[A-Za-z0-9_.@-]{1,64}) "
                         r"expiry=(?P<expiry>\d{4}-\d{2}-\d{2}) reason=(?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("UNWAIVE", re.compile(r"^UNWAIVE (?P<id>[A-Za-z0-9_.-]{1,64})" + CODE + r"$")),
    ("PROCEED-PAST", re.compile(r"^PROCEED-PAST " + PH + r" (?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("PARK", re.compile(r"^PARK" + CODE + r"$")),
    ("REVIEW", re.compile(r"^REVIEW " + PH + r"$")),
    ("STATUS", re.compile(r"^STATUS$")),
]
VERBS = {name for name, _ in COMMANDS}
CODE_TOKEN = re.compile(r"(?<!\d)\d{6}(?!\d)")
PREFIX = "MOADIX gate: "


def _ctx(text):
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": PREFIX + text}}


def _burn_all(message, keep=None):
    for tok in CODE_TOKEN.findall(message)[:8]:
        if tok == keep:
            continue
        try:
            state.run_checker(["burn", "--code", tok])
        except (state.GateError, OSError, subprocess.SubprocessError):
            pass


def _git_head(root):
    try:
        p = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def parse(message):
    msg = message.strip()
    for name, rx in COMMANDS:
        m = rx.match(msg)
        if m:
            return name, m.groupdict()
    first = msg.split(" ", 1)[0] if msg else ""
    if first in VERBS and "\n" not in msg:
        return "MALFORMED", {"verb": first}
    return None, None


def _summary(st):
    rows = ["%s %s: %s" % (p["label"], p["name"], p["status"]) for p in st["phases"]]
    w = ", ".join("%s (owner %s, expires %s)" % (x["id"], x["owner"], x["expiry"]) for x in st["waivers"]) or "none"
    return "current phase %s; ledger seq %d; waivers: %s; phases: %s" % (
        st["current_phase"], st["ledger_seq"], w, "; ".join(rows))


def _precheck(name, g, st):
    """Reason string if the action cannot apply to this state, else None."""
    ph = next((p for p in st["phases"] if p["label"] == g.get("phase")), None) if "phase" in g else None
    if "phase" in g and ph is None:
        return "there is no phase %s (phases: %s)" % (g["phase"], ", ".join(pathmap.LABELS))
    if name == "APPROVE":
        if g["phase"] != st["current_phase"]:
            return "phase %s is not the current phase (current: %s)" % (g["phase"], st["current_phase"])
    if name == "PROCEED-PAST" and g["phase"] != st["current_phase"]:
        return "phase %s is not the current phase (current: %s)" % (g["phase"], st["current_phase"])
    if name == "REOPEN" and ph["status"] not in ("APPROVED", "PROCEED-PAST"):
        return "phase %s is not approved, so there is nothing to reopen" % g["phase"]
    if name == "WAIVE" and any(w["id"] == g["id"] for w in st["waivers"]):
        return "waiver %s already exists" % g["id"]
    if name == "UNWAIVE" and not any(w["id"] == g["id"] for w in st["waivers"]):
        return "there is no active waiver %s" % g["id"]
    if name == "PARK" and st["parked"]:
        return "the product is already parked"
    return None


def _minutes(seconds):
    m = max(1, (int(seconds) + 59) // 60)
    return "%d minute%s" % (m, "" if m == 1 else "s") if m < 120 else "%d hours" % ((m + 59) // 60)


def _refusal(out):
    """Operator-facing text for a checker refusal."""
    parts = out.split()
    if out == "ERR wrong-code":
        return "the code is wrong"
    if len(parts) == 3 and parts[1] == "wrong-code-paused" and parts[2].isdigit():
        return ("the code is wrong; after repeated wrong codes, approvals are PAUSED for %s. "
                "A valid code after the pause works normally" % _minutes(parts[2]))
    if len(parts) == 3 and parts[1] == "paused" and parts[2].isdigit():
        return ("approvals are PAUSED for another %s after repeated wrong codes (this attempt was not "
                "evaluated and does not extend the pause)" % _minutes(parts[2]))
    if out == "ERR code-already-used":
        return "that code was already used; wait for the next one"
    return out


def handle(hook_input):
    message = hook_input.get("prompt") or ""
    name, g = parse(message)
    root = state.find_root(hook_input.get("cwd"))

    if name is None:
        _burn_all(message)
        return None
    if root is None:
        _burn_all(message)
        return _ctx("%s ignored: this repository has no .sdlc/ (MOADIX is passive here). Nothing recorded." % name)
    if name == "MALFORMED":
        _burn_all(message)
        return _ctx("'%s' was not recognised as an exact operator command, so nothing was recorded and any code in it "
                    "is now spent. Tell the operator to send the command alone, e.g. 'APPROVE 1 123456'." % g["verb"])

    st, problems = state.current_state(root)
    if name == "STATUS":
        integrity = "INTEGRITY OK (ledger chain, signatures, Keychain anchor, phase.yaml)" if not problems else \
            "INTEGRITY FAILURE: " + "; ".join(problems)
        return _ctx("STATUS. %s. %s. Relay this to the operator verbatim." % (integrity, _summary(st)))
    if name == "REVIEW":
        ph = next((p for p in st["phases"] if p["label"] == g["phase"]), None)
        if ph is None:
            return _ctx("REVIEW: there is no phase %s." % g["phase"])
        return _ctx("REVIEW %s (%s): status %s; source commit %s; open waivers %d; validators: not yet ported "
                    "(increment 2). Relay this to the operator verbatim." % (
                        ph["label"], ph["name"], ph["status"], _git_head(root) or "unknown", len(st["waivers"])))

    code = g.pop("code")
    if problems:
        _burn_all(message)
        return _ctx("%s NOT recorded: gate state failed its integrity check (%s). Nothing changed; the code is spent. "
                    "Tell the operator to run STATUS." % (name, "; ".join(problems)))
    why = _precheck(name, g, st)
    if why:
        _burn_all(message)
        return _ctx("%s NOT recorded: %s. Nothing changed; the code is spent." % (name, why))

    payload = dict(g, source_commit=_git_head(root))
    action = message.strip()[: -len(code) - 1]  # the command without its code
    prod = state.load_product(root)
    rc, out = state.run_checker(["record", "--product", prod["product"], "--action", action, "--code", code,
                                 "--payload-b64", base64.b64encode(json.dumps(payload, sort_keys=True).encode()).decode()])
    if rc != 0:
        _burn_all(message)  # including this code: a refused valid code (e.g. during a pause) must not stay live
        reason = _refusal(out)
        return _ctx("%s NOT recorded: %s. Nothing changed." % (name, reason))
    _burn_all(message, keep=code)
    state.append_line(root, out)
    st2, problems2 = state.current_state(root)
    if not problems2 or all("phase.yaml differs" in p for p in problems2):
        state.write_phase(root, st2)
    seq = json.loads(json.loads(out)["body"])["seq"]
    nxt = ""
    if name in ("APPROVE", "PROCEED-PAST"):
        nxt = " Proceed to phase %s." % st2["current_phase"] if st2["current_phase"] != "done" else " All phases are done."
    if name == "REOPEN":
        nxt = " Phase %s is open again; continue from there." % g["phase"]
    return _ctx("%s recorded (ledger seq %d).%s Tell the operator it was recorded." % (action, seq, nxt))
