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

Increment 2:
- APPROVE runs the current phase's validators: it reads their cached results
  (gate/validation.py) and refuses with their findings unless a FRESH result
  for the current commit passed. Missing, running, stale or dirty = refused.
- Increment 3 (ruling 2): REVIEW is no longer required before APPROVE. The gate
  starts the validators itself when the agent's turn ends (Stop hook) or the
  agent calls /moadix:request-review (gate/autoval.py). REVIEW <phase> is an
  optional, read-only view of the cache. Each APPROVE line records the digest
  of the exact validator result it relied on.
- INIT, WAIVE (owner, scope, expiry; high severity unwaivable), PROCEED-PAST
  (v1's progression waiver) and PARK (stop, measure, record, tag).
- ADOPT <code> (ruling 3, increment 3): adopts the product settings the agent
  proposed under .sdlc-proposals/ into .sdlc/ (gate/adopt.py).
"""
import base64
import contextlib
import datetime
import json
import os
import re
import shutil
import subprocess

from . import adopt, pathmap, state, validation

PH = r"(?P<phase>\d{1,2}[a-z]?)"
TEXT = r"[ !#-\[\]-~]{1,300}?"  # printable ASCII without " and \ (the checker's alphabet)
CODE = r" (?P<code>\d{6})"
PID = r"(?P<id>[A-Za-z0-9_.-]{1,64})"
COMMANDS = [
    ("APPROVE", re.compile(r"^APPROVE " + PH + CODE + r"$")),
    ("REOPEN", re.compile(r"^REOPEN " + PH + r" (?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("WAIVE", re.compile(r"^WAIVE " + PID + r" owner=(?P<owner>[A-Za-z0-9_.@-]{1,64}) "
                         r"scope=(?P<scope>[A-Za-z0-9_./:*@-]{1,128}) "
                         r"expiry=(?P<expiry>\d{4}-\d{2}-\d{2}) reason=(?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("UNWAIVE", re.compile(r"^UNWAIVE " + PID + CODE + r"$")),
    ("PROCEED-PAST", re.compile(r"^PROCEED-PAST " + PH + r" (?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("PARK", re.compile(r"^PARK" + CODE + r"$")),
    ("INIT", re.compile(r"^INIT " + PID + CODE + r"$")),
    ("ADOPT", re.compile(r"^ADOPT" + CODE + r"$")),
    ("REVIEW", re.compile(r"^REVIEW " + PH + r"$")),
    ("STATUS", re.compile(r"^STATUS$")),
]
VERBS = {name for name, _ in COMMANDS}
USAGE = {
    "APPROVE": "APPROVE <phase> <code>",
    "REOPEN": "REOPEN <phase> <reason> <code>",
    "WAIVE": "WAIVE <id> owner=<name> scope=<what it covers> expiry=YYYY-MM-DD reason=<text> <code>",
    "UNWAIVE": "UNWAIVE <id> <code>",
    "PROCEED-PAST": "PROCEED-PAST <phase> <reason> <code>",
    "PARK": "PARK <code>",
    "INIT": "INIT <product-id> <code>",
    "ADOPT": "ADOPT <code>",
    "REVIEW": "REVIEW <phase>",
    "STATUS": "STATUS",
}
CODE_TOKEN = re.compile(r"(?<!\d)\d{6}(?!\d)")
FINDING_ID = re.compile(r"^(?:SF|SEC)-\d+$")
PREFIX = "MOADIX gate: "
PARK_STOP_TIMEOUT = 45
PARK_COUNT_TIMEOUT = 10
PARK_VERBS = ("docker", "podman")


def _ctx(text):
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": PREFIX + text}}


def _burn_all(message, keep=None):
    for tok in CODE_TOKEN.findall(message)[:8]:
        if tok == keep:
            continue
        with contextlib.suppress(state.GateError, OSError, subprocess.SubprocessError):
            state.run_checker(["burn", "--code", tok])


def _git(root, *args, timeout=10):
    try:
        p = subprocess.run([state.GIT, "-C", root] + list(args), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


def _git_head(root):
    rc, out, _ = _git(root, "rev-parse", "--verify", "HEAD")
    return out if rc == 0 and out else None


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
    w = ", ".join("%s (owner %s, scope %s, expires %s)" % (x["id"], x.get("owner"), x.get("scope") or "-",
                                                           x.get("expiry")) for x in st["waivers"]) or "none"
    parked = ""
    if st.get("parked"):
        parked = "; PARKED at ledger seq %s (counts: %s)" % (st["parked"]["seq"], json.dumps(st["parked"].get("counts")))
    return "current phase %s; ledger seq %d; waivers: %s%s; phases: %s" % (
        st["current_phase"], st["ledger_seq"], w, parked, "; ".join(rows))


def _approval_digest(st, label):
    """The validator-result digest recorded by the APPROVE that approved `label`, if any."""
    for e in reversed(st.get("_entries") or []):
        if e["action"].split(" ", 1)[0] in ("APPROVE", "REOPEN"):
            pl = state.decode_payload(e)
            if pl.get("phase") == label:
                return (pl.get("validation") or {}).get("digest") if e["action"].startswith("APPROVE") else None
    return None


def _phase(st, label):
    return next((p for p in st["phases"] if p["label"] == label), None)


def _precheck(name, g, st):
    """Reason string if the action cannot apply to this state, else None."""
    ph = _phase(st, g.get("phase")) if "phase" in g else None
    if "phase" in g and ph is None:
        return "there is no phase %s (phases: %s)" % (g["phase"], ", ".join(pathmap.LABELS))
    if name in ("APPROVE", "PROCEED-PAST") and g["phase"] != st["current_phase"]:
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


def _paused():
    """Seconds left in a wrong-code pause, or 0."""
    try:
        rc, out = state.run_checker(["state"])
    except (state.GateError, OSError, subprocess.SubprocessError):
        return 0
    m = re.search(r"paused_for=(\d+)", out)
    return int(m.group(1)) if rc == 0 and m else 0


# ---------------------------------------------------------------- validators

def _validation_text(status, data, detail, label):
    if status == "fresh":
        head = "validators for phase %s: %s (%s; result %s)" % (label, data["verdict"].upper(), detail,
                                                                 data["_digest"][:19])
        return head + ". " + "; ".join(validation.summary(data))
    if status == "running":
        return "validators for phase %s are still running (%s); send REVIEW %s again in a minute" % (
            label, detail, label)
    if status in ("missing", "stale"):
        return ("validators for phase %s have no current result (%s); the gate runs them when the agent's turn "
                "ends or the agent calls /moadix:request-review" % (label, detail))
    if status == "dirty":
        return "validators for phase %s cannot run yet (%s)" % (label, detail)
    return "validators for phase %s cannot be judged (%s)" % (label, detail)


def _approve_gate(root, st, label):
    """(ok, reason, data). APPROVE passes only on a fresh, passing result."""
    status, data, detail = validation.read(root, label, st)
    if status != "fresh":
        hint = ("; the gate runs them when the agent's turn ends, so send APPROVE again in a minute (REVIEW %s "
                "shows when they are done)" % label) if status in ("missing", "stale", "running") else ""
        if status == "dirty":
            hint = "; the agent must commit the work first; the gate then runs them when its turn ends"
        return False, "the phase's validators have no fresh result for this commit (%s), and a stale or missing " \
                      "result counts as a failure%s" % (detail, hint), None
    if data["verdict"] != "pass":
        return False, "the phase %s validators did not pass (%s). Findings: %s" % (
            label, data["verdict"].upper(), " | ".join(validation.findings(data)) or "see REVIEW %s" % label), data
    return True, None, data


def _proceed_gate(root, st, label):
    """v1 progression_state: only a DETERMINATE, CURRENT failure may be proceeded past."""
    status, data, detail = validation.read(root, label, st)
    if status != "fresh":
        return False, "there is no fresh validator result for this commit (%s). A waiver is an exception to " \
                      "something known; send REVIEW %s first" % (detail, label), None
    unknown = [r["validator"] for r in data["results"] if r["result"] == "unknown"]
    if unknown:
        return False, "validator(s) %s could not reach their instrument (UNKNOWN), so the result says nothing " \
                      "about the product; UNKNOWN is not a basis for proceeding" % ", ".join(unknown), data
    failing = [r["validator"] for r in data["results"] if r["result"] == "fail"]
    if not failing:
        return False, "every validator passed, so there is nothing to proceed past; APPROVE %s instead" % label, data
    return True, failing, data


# ---------------------------------------------------------------- WAIVE

def _finding_severities(root):
    """{finding-id: severity|None} from sdlc/09-security-report.md (v1
    gate._finding_severities), or None when the report cannot be read."""
    try:
        with open(os.path.join(root, "sdlc", "09-security-report.md"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    out = {}
    for m in re.finditer(r"^\|\s*((?:SF|SEC)-\d+)\s*\|([^|]*)\|", text, re.M):
        out[m.group(1).upper()] = m.group(2).strip().lower() or None
    for m in re.finditer(r"^#{2,4}\s+((?:SF|SEC)-\d+)\b", text, re.M):
        out.setdefault(m.group(1).upper(), None)
    return out


def _waiver_policy():
    from .v1 import hlib
    out = {"require_expiry": True, "max_expiry_days": 180, "unwaivable_severities": ["high", "critical"]}
    try:
        cfg = hlib.load_yaml(os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "waivers.yaml"))
    except Exception:
        cfg = {}
    for k, v in out.items():
        if isinstance((cfg or {}).get(k), type(v)):
            out[k] = cfg[k]
    out["unwaivable_severities"] = [str(x).lower() for x in out["unwaivable_severities"]]
    return out


def _waive_gate(root, g):
    pol = _waiver_policy()
    try:
        exp = datetime.date(*(int(x) for x in g["expiry"].split("-")))
    except ValueError:
        return "expiry %s is not a real date" % g["expiry"]
    days = (exp - datetime.date.today()).days
    if days < 0:
        return "expiry %s is already in the past; that waiver would grant nothing" % g["expiry"]
    if days > pol["max_expiry_days"]:
        return "expiry %s is %d days out, beyond the %d-day maximum (gate/config/waivers.yaml)" % (
            g["expiry"], days, pol["max_expiry_days"])
    key = g["id"].split(":", 1)[0].strip().upper()
    sevs = _finding_severities(root)
    if FINDING_ID.match(key):
        if sevs is None:
            return ("%s names a security finding, but sdlc/09-security-report.md cannot be read, so whether it is "
                    "high severity is UNKNOWN; refusing rather than granting blind" % g["id"])
        if key in sevs and sevs[key] is None:
            return ("%s is a finding in the phase-9 report and its severity cannot be read (add a row "
                    "'| %s | <severity> | ... |'); refusing rather than granting blind" % (g["id"], key))
    sev = (sevs or {}).get(key)
    if sev and sev in pol["unwaivable_severities"]:
        return ("%s is a %s-severity finding and CANNOT be waived. Fix it, or downgrade it with evidence in the "
                "phase-9 report" % (g["id"], sev))
    return None


# ---------------------------------------------------------------- PARK

def _trusted_dirs():
    from .v1 import hlib
    p = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "trusted-bin.yaml")
    try:
        return [str(d) for d in (hlib.load_yaml(p) or {}).get("dirs") or []]
    except Exception:
        return []


def _park_spec(root):
    """(spec, reason). spec = {"stop": argv, "counts": {name: argv}} with argv[0] resolved."""
    from .v1 import hlib
    try:
        doc = hlib.load_yaml(state.paths(root)["product"]) or {}
    except Exception as e:
        return None, ".sdlc/product.yaml could not be parsed (%s)" % e
    park = doc.get("park")
    if not isinstance(park, dict):
        return None, (".sdlc/product.yaml declares no `park:` section (stop command and counts), so there is "
                      "nothing to run. The agent proposes it in .sdlc-proposals/product.yaml and the operator adopts it with "
                      "ADOPT <code>; agents cannot write .sdlc/")
    dirs = _trusted_dirs()

    def resolve(argv, what):
        if not isinstance(argv, list) or not argv or not all(isinstance(a, (str, int)) for a in argv):
            return None, "%s must be a non-empty argv list" % what
        argv = [str(a) for a in argv]
        if argv[0] not in PARK_VERBS:
            return None, ("%s starts with %r; PARK runs outside the sandbox with the operator's authority, so it "
                          "only runs %s (resolved from the gate's trusted directories)" % (
                              what, argv[0], " or ".join(PARK_VERBS)))
        for d in dirs:
            exe = os.path.join(d, argv[0])
            if os.access(exe, os.X_OK):
                return [exe] + argv[1:], None
        return None, "%s is not installed in any trusted directory (%s)" % (argv[0], ", ".join(dirs) or "none")

    stop, why = resolve(park.get("stop"), "park.stop")
    if why:
        return None, why
    counts = {}
    for name, argv in (park.get("counts") or {}).items():
        if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", str(name)):
            return None, "park.counts name %r is not a plain identifier" % name
        counts[str(name)], why = resolve(argv, "park.counts.%s" % name)
        if why:
            return None, why
    if not counts:
        return None, "park.counts is empty; PARK records the counts it measures, so declare at least one"
    return {"stop": stop, "counts": counts}, None


def _run(argv, root, timeout):
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:" + ":".join(_trusted_dirs()), "HOME": os.environ.get("HOME", "")}
    try:
        p = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ds" % timeout
    except OSError as e:
        return 127, "", str(e)


def _park_execute(root, spec):
    """Stop the stack, then measure. (counts, error)."""
    rc, out, err = _run(spec["stop"], root, PARK_STOP_TIMEOUT)
    if rc != 0:
        return None, "the stop command failed (exit %d: %s)" % (rc, (err or out).strip()[:200])
    counts = {}
    for name, argv in spec["counts"].items():
        rc, out, err = _run(argv, root, PARK_COUNT_TIMEOUT)
        val = out.strip()
        if rc != 0 or not re.match(r"^-?\d+$", val):
            return None, "measuring %s failed (exit %d, output %r%s)" % (
                name, rc, val[:60], (": " + err.strip()[:120]) if err.strip() else "")
        counts[name] = int(val)
    return counts, None


# ---------------------------------------------------------------- INIT

def _init(message, g, cwd):
    pid, code = g["id"], g["code"]
    if state.find_root(cwd):
        _burn_all(message)
        return _ctx("INIT NOT recorded: %s is already inside the MOADIX product at %s. Nothing changed; the code "
                    "is spent." % (cwd, state.find_root(cwd)))
    rc, top, _ = _git(cwd or ".", "rev-parse", "--show-toplevel")
    if rc != 0 or not top:
        _burn_all(message)
        return _ctx("INIT NOT recorded: %s is not inside a git repository; run `git init` there first. Nothing "
                    "changed; the code is spent." % cwd)
    root = os.path.realpath(top)
    try:
        rc, out = state.run_checker(["anchor", "--product", pid])
    except (state.GateError, OSError, subprocess.SubprocessError) as e:
        _burn_all(message)
        return _ctx("INIT NOT recorded: the checker is unavailable (%s). Nothing changed." % e)
    if out != "OK 0 GENESIS":
        _burn_all(message)
        return _ctx("INIT NOT recorded: the product id %s already has a ledger on this Mac (%s); every product "
                    "needs its own id. Nothing changed; the code is spent." % (pid, out))
    created = not os.path.exists(state.paths(root)["dir"])
    try:
        state.init_product(root, pid)
    except (state.GateError, OSError) as e:
        _burn_all(message)
        return _ctx("INIT NOT recorded: %s. Nothing changed; the code is spent." % e)
    payload = {"product": pid, "source_commit": _git_head(root)}
    rc, out = state.run_checker(["record", "--product", pid, "--action", "INIT %s" % pid, "--code", code,
                                 "--payload-b64", base64.b64encode(json.dumps(payload, sort_keys=True).encode()).decode()])
    if rc != 0:
        if created:
            shutil.rmtree(state.paths(root)["dir"], ignore_errors=True)
        _burn_all(message)
        return _ctx("INIT NOT recorded: %s. Nothing changed (.sdlc/ was not created)." % _refusal(out))
    _burn_all(message, keep=code)
    state.append_line(root, out)
    st, _ = state.current_state(root)
    state.write_phase(root, st)
    return _ctx("INIT %s recorded (ledger seq 1): %s/.sdlc created; the current phase is %s. Tell the operator it was "
                "recorded." % (pid, root, st["current_phase"]))


# ---------------------------------------------------------------- handle

def handle(hook_input):
    message = hook_input.get("prompt") or ""
    name, g = parse(message)
    cwd = hook_input.get("cwd")

    if name is None:
        _burn_all(message)
        return None
    if name == "INIT":
        return _init(message, g, cwd)
    if name == "MALFORMED":
        _burn_all(message)
        return _ctx("'%s' was not recognised as an exact operator command, so nothing was recorded and any code in it "
                    "is now spent. Tell the operator to send the command alone, as: %s" % (
                        g["verb"], USAGE.get(g["verb"], g["verb"])))
    root = state.find_root(cwd)
    if root is None:
        _burn_all(message)
        return _ctx("%s ignored: this repository has no .sdlc/ (MOADIX is passive here; INIT <product-id> <code> "
                    "creates it). Nothing recorded." % name)

    st, problems = state.current_state(root)
    if name == "STATUS":
        integrity = "INTEGRITY OK (ledger chain, signatures, Keychain anchor, phase.yaml)" if not problems else \
            "INTEGRITY FAILURE: " + "; ".join(problems)
        val = ""
        if not problems and st["current_phase"] != "done":
            val = " " + _validation_text(*validation.read(root, st["current_phase"], st), st["current_phase"]) + "."
        if not problems:
            try:
                from . import manifest
                val += " Phase %s manifest: %s." % (st["current_phase"], manifest.budget(st["current_phase"]))
            except Exception as e:  # STATUS still answers; the PreToolUse check fails closed on its own
                val += " Phase manifest unreadable (%s)." % type(e).__name__
        props = adopt.pending(root)
        if props:
            try:
                adopt.plan(root)
                verdict = "valid; ADOPT <code> adopts them"
            except (adopt.ProposalError, OSError) as e:
                verdict = "NOT adoptable as they stand: %s" % e
            val += " Pending proposals in %s/: %s (%s)." % (adopt.DIR, ", ".join(props[:10]), verdict)
        return _ctx("STATUS. %s. %s.%s Relay this to the operator verbatim." % (integrity, _summary(st), val))
    if name == "REVIEW":
        ph = _phase(st, g["phase"])
        if ph is None:
            return _ctx("REVIEW: there is no phase %s." % g["phase"])
        head = "REVIEW %s (%s): status %s; source commit %s; open waivers %d" % (
            ph["label"], ph["name"], ph["status"], _git_head(root) or "none", len(st["waivers"]))
        if problems:
            return _ctx("%s; gate state failed its integrity check (%s), so validators were not run. Relay this to "
                        "the operator verbatim." % (head, "; ".join(problems)))
        if ph["label"] == st["current_phase"]:
            # Read-only (ruling 2): REVIEW never starts a run; it shows what the gate's last run left.
            status, data, detail = validation.read(root, ph["label"], st)
            text = _validation_text(status, data, detail, ph["label"])
            if status == "fresh" and data["verdict"] != "pass":
                text += ". Findings: " + " | ".join(validation.findings(data))
        else:
            ev = ph.get("evidence") or []
            relied = _approval_digest(st, ph["label"])
            text = "not the current phase (%s); recorded validator evidence: %s%s" % (
                st["current_phase"], ", ".join("%s %s" % (e.get("validator"), e.get("result")) for e in ev) or "none",
                "; approved on validator result %s" % relied if relied else "")
        return _ctx("%s; %s. Relay this to the operator verbatim." % (head, text))

    code = g.pop("code")
    if problems:
        _burn_all(message)
        return _ctx("%s NOT recorded: gate state failed its integrity check (%s). Nothing changed; the code is spent. "
                    "Tell the operator to run STATUS." % (name, "; ".join(problems)))
    why = _precheck(name, g, st)
    payload = dict(g, source_commit=_git_head(root))
    if not why and name == "APPROVE":
        ok, why, data = _approve_gate(root, st, g["phase"])
        if ok:
            payload["validation"] = {"commit": data["key"]["commit"], "verdict": data["verdict"],
                                     "finished_at": data.get("finished_at"), "digest": data["_digest"],
                                     "results": [{"validator": r["validator"], "result": r["result"],
                                                  "exit_code": r["exit_code"]} for r in data["results"]]}
    if not why and name == "PROCEED-PAST":
        ok, res, data = _proceed_gate(root, st, g["phase"])
        if ok:
            payload["failing"] = res
        else:
            why = res
    if not why and name == "WAIVE":
        why = _waive_gate(root, g)
    adoption = None
    if not why and name == "ADOPT":
        try:
            adoption = adopt.plan(root)
            payload.update(adopt.payload(root, adoption))
        except (adopt.ProposalError, OSError) as e:
            why = "the proposal was refused: %s" % e
    park = None
    if not why and name == "PARK":
        spec, why = _park_spec(root)
        if not why and _paused():
            why = "approvals are PAUSED after repeated wrong codes, so nothing was stopped or measured"
        if not why:
            counts, err = _park_execute(root, spec)
            if err:
                _burn_all(message)
                stopped = "" if err.startswith("the stop command") else " The stack WAS stopped."
                return _ctx("PARK NOT recorded: %s.%s Nothing was recorded or tagged, and the code is spent." % (
                    err, stopped))
            park = {"counts": counts}
            payload.update(counts=counts, stop=spec["stop"][1:], tag="moadix-parked-%d" % (st["ledger_seq"] + 1))
    if why:
        _burn_all(message)
        return _ctx("%s NOT recorded: %s. Nothing changed; the code is spent." % (name, why))

    action = message.strip()[: -len(code) - 1]  # the command without its code
    prod = state.load_product(root)
    rc, out = state.run_checker(["record", "--product", prod["product"], "--action", action, "--code", code,
                                 "--payload-b64", base64.b64encode(json.dumps(payload, sort_keys=True).encode()).decode()])
    if rc != 0:
        _burn_all(message)  # including this code: a refused valid code (e.g. during a pause) must not stay live
        tail = " The stack WAS stopped and measured (%s), but nothing was recorded or tagged." % json.dumps(
            park["counts"]) if park else ""
        return _ctx("%s NOT recorded: %s. Nothing changed.%s" % (name, _refusal(out), tail))
    _burn_all(message, keep=code)
    state.append_line(root, out)
    if adoption:
        adopt.apply(root, adoption)
    st2, problems2 = state.current_state(root)
    if not problems2 or all("phase.yaml differs" in p for p in problems2):
        state.write_phase(root, st2)
    seq = json.loads(json.loads(out)["body"])["seq"]
    nxt = ""
    if name == "APPROVE":
        nxt = " It rests on validator result %s." % payload["validation"]["digest"][:19]
    if name in ("APPROVE", "PROCEED-PAST"):
        nxt += " Proceed to phase %s." % st2["current_phase"] if st2["current_phase"] != "done" else \
            " All phases are done."
    if name == "REOPEN":
        nxt = " Phase %s is open again; continue from there." % g["phase"]
    if name == "ADOPT":
        nxt = " Adopted into .sdlc/: %s; the proposals were removed. Validator results computed before this are now " \
              "stale." % ", ".join("%s (sha256 %s)" % (f["target"], f["result_sha256"][:12]) for f in payload["files"])
    if name == "PARK":
        tag = payload["tag"]
        rc, _o, err = _git(root, "tag", "-a", tag, "-m", "MOADIX PARK (ledger seq %d) counts %s" % (
            seq, json.dumps(park["counts"], sort_keys=True)))
        nxt = " Stack stopped; counts %s; tagged %s." % (json.dumps(park["counts"], sort_keys=True), tag) if rc == 0 \
            else " Stack stopped; counts %s; the tag %s could NOT be created (%s)." % (
                json.dumps(park["counts"], sort_keys=True), tag, err[:120])
    return _ctx("%s recorded (ledger seq %d).%s Tell the operator it was recorded." % (action, seq, nxt))
