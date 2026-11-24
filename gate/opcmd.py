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

PH = r"(?P<phase>\d{1,2}[a-z]?|B)"
TEXT = r"[ !#-\[\]-~]{1,300}?"  # printable ASCII without " and \ (the checker's alphabet)
CODE = r" (?P<code>\d{6})"
PID = r"(?P<id>[A-Za-z0-9_.-]{1,64})"
# 0.6.4 (F-5): one WAIVE may name up to WAIVE_MAX findings, comma-separated, under one code;
# each becomes its own waiver (state.replay), each checked as if waived alone.
WAIVE_MAX = 20
PIDS = r"(?P<id>[A-Za-z0-9_.-]{1,64}(?:,[A-Za-z0-9_.-]{1,64}){0,%d})" % (WAIVE_MAX - 1)
COMMANDS = [
    ("APPROVE", re.compile(r"^APPROVE " + PH + r"(?P<ww> WITH-WAIVERS)?" + CODE + r"$")),
    ("REOPEN", re.compile(r"^REOPEN " + PH + r" (?P<reason>" + TEXT + r")" + CODE + r"$")),
    # 0.7.3 (item 5): owner, scope and expiry are optional; they default to `operator`, the finding's document and
    # 30 days (waiver_defaults). The order stays fixed.
    ("WAIVE", re.compile(r"^WAIVE " + PIDS + r"(?: owner=(?P<owner>[A-Za-z0-9_.@-]{1,64}))?"
                         r"(?: scope=(?P<scope>[A-Za-z0-9_./:*@-]{1,128}))?"
                         r"(?: expiry=(?P<expiry>\d{4}-\d{2}-\d{2}))? reason=(?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("UNWAIVE", re.compile(r"^UNWAIVE " + PID + CODE + r"$")),
    ("UNCARRY", re.compile(r"^UNCARRY (?P<id>(?:GC|CARRY)-[A-Za-z0-9_.-]{1,64})" + CODE + r"$")),
    ("PROCEED-PAST", re.compile(r"^PROCEED-PAST " + PH + r" (?P<reason>" + TEXT + r")" + CODE + r"$")),
    ("PARK", re.compile(r"^PARK" + CODE + r"$")),
    ("INIT", re.compile(r"^INIT " + PID + CODE + r"$")),
    ("FEATURE", re.compile(r"^FEATURE " + PID + CODE + r"$")),
    ("COLLAPSE", re.compile(r"^COLLAPSE " + PH + CODE + r"$")),
    ("ADOPT", re.compile(r"^ADOPT" + CODE + r"$")),
    ("REVIEW", re.compile(r"^REVIEW " + PH + r"$")),
    ("STATUS", re.compile(r"^STATUS$")),
]
VERBS = {name for name, _ in COMMANDS}
USAGE = {
    "APPROVE": "APPROVE <phase> [WITH-WAIVERS] <code>",
    "REOPEN": "REOPEN <phase> <reason> <code>",
    "WAIVE": "WAIVE <id>[,<id>...] [owner=<name>] [scope=<what it covers>] [expiry=YYYY-MM-DD] reason=<text> <code>",
    "UNWAIVE": "UNWAIVE <id> <code>",
    "UNCARRY": "UNCARRY <GC id or CARRY id> <code>",
    "PROCEED-PAST": "PROCEED-PAST <phase> <reason> <code>",
    "PARK": "PARK <code>",
    "INIT": "INIT <product-id> <code>",
    "FEATURE": "FEATURE <feature-id> <code>",
    "COLLAPSE": "COLLAPSE <phase> <code>",
    "ADOPT": "ADOPT <code>",
    "REVIEW": "REVIEW <phase>",
    "STATUS": "STATUS",
}
# 0.7.1 (task-tracker MF-4): what each command does, for the README's table, which
# command_table() generates from USAGE and this map (tests/rel071 checks they agree).
HELP = {
    "INIT": "Starts a product: creates `.sdlc/` at the repo root and the first ledger line.",
    "STATUS": "Shows the gate's state. It starts with `INTEGRITY OK` when the ledger and state verify.",
    "REVIEW": "Read-only. Shows the latest validator result for a phase and its digest.",
    "APPROVE": "Approves a phase. Refused, with the findings, unless the phase's validators passed on the current "
               "commit. With WITH-WAIVERS it also records, under the same code, exactly the waivers the agent proposed "
               "in `.sdlc-proposals/waivers.yaml` (REVIEW shows them); refused if one names a BLOCKER or an unknown id.",
    "REOPEN": "Reopens an approved (frozen) phase.",
    "WAIVE": "Waives findings for at most 180 days; owner defaults to operator, scope to the finding's document "
             "and expiry to 30 days. A gap-critic finding is named `gap-critic.<GC id>`, a carry `CARRY-<phase>-<n>`. BLOCKERs, high or critical security findings, and security, privacy or "
             "tenant-isolation carries can't be waived.",
    "UNWAIVE": "Withdraws a waiver.",
    "UNCARRY": "Pulls a carried finding back into the current phase (a GC id counts as a MAJOR; a CARRY id is "
               "readdressed to this phase).",
    "PROCEED-PAST": "Moves past a phase whose validators definitely failed on the current commit; the findings it "
                    "passes are recorded.",
    "COLLAPSE": "Collapses the current phase when the size profile (S: phases 1, 6b, 10c) or the platform ruling "
                "declares it not applicable (see /moadix:coverage) allows it, recording the reason and the checks that will "
                "not run.",
    "FEATURE": "Starts a feature cycle on a released (or onboarded) product.",
    "ADOPT": "Adopts what the agent proposed in `.sdlc-proposals/` (product settings, coverage overrides, standing "
             "instructions).",
    "PARK": "Stops the product's declared stack, records the counts and tags the repo.",
}
TABLE_ORDER = ("INIT", "STATUS", "REVIEW", "APPROVE", "REOPEN", "WAIVE", "UNWAIVE", "UNCARRY", "PROCEED-PAST",
               "COLLAPSE", "FEATURE", "ADOPT", "PARK")


def command_table():
    """The README's operator-command table, generated from USAGE and HELP."""
    rows = ["| Command | What it does |", "|---|---|"]
    rows += ["| `%s` | %s |" % (USAGE[v], HELP[v]) for v in TABLE_ORDER]
    return "\n".join(rows)


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
    scope = "product (%s)" % st.get("mode", "greenfield")
    if st.get("feature"):
        f = next((x for x in st.get("features") or [] if x["id"] == st["feature"]), {})
        scope = "feature %s (started at ledger seq %s; the product's documents are frozen)" % (
            st["feature"], f.get("seq"))
    done = [x for x in st.get("features") or [] if x["status"] == "done"]
    if done:
        scope += "; finished features: %s" % ", ".join("%s (merged at seq %s)" % (x["id"], x.get("merged_seq"))
                                                       for x in done)
    w = ", ".join("%s (owner %s, scope %s, expires %s)" % (x["id"], x.get("owner"), x.get("scope") or "-",
                                                           x.get("expiry")) for x in st["waivers"]) or "none"
    parked = ""
    if st.get("parked"):
        parked = "; PARKED at ledger seq %s (counts: %s)" % (st["parked"]["seq"], json.dumps(st["parked"].get("counts")))
    pend = retro_pending(st)
    if st.get("feature") and st["current_phase"] == pathmap.RETRO:
        pend = "phase %s (Retro) of feature %s is pending (no new FEATURE until it is approved)" % (
            pathmap.RETRO, st["feature"])
    if pend:
        parked += "; PENDING: %s" % pend
    return "scope %s; current phase %s; ledger seq %d; waivers: %s%s; phases: %s" % (
        scope, st["current_phase"], st["ledger_seq"], w, parked, "; ".join(rows))


def proceeded_phases(st):
    """0.7.0 (Addition 2): [(label, reason, [still-open passed findings])] for every phase of the
    scope closed by PROCEED-PAST. A passed finding is still open unless a waiver now covers it
    (gap-critic.<GC id>, or a pre-0.7.0 topic waiver)."""
    from . import verify
    aw = verify.active_waivers(st)
    out = []
    for p in st.get("phases") or []:
        if p.get("status") != "PROCEED-PAST":
            continue
        pl = {}
        for e in reversed(st.get("_entries") or []):
            if e["action"].split(" ", 1)[0] == "PROCEED-PAST":
                x = state.decode_payload(e)
                if x.get("phase") == p["label"] and x.get("feature") == st.get("feature"):
                    pl = x
                    break
        still = [f for f in pl.get("passed_findings") or []
                 if not ((f.get("gc") and "gap-critic.%s" % f["gc"] in aw) or
                         (not f.get("gc") and "gap-critic.%s" % f.get("topic") in aw and f.get("severity") == "MAJOR"))]
        out.append((p["label"], p.get("note") or pl.get("reason") or "", still))
    return out


def proceeded_summary(st):
    from . import critic, verify
    rows = proceeded_phases(st)
    over = critic.overdue_carries(st, verify.active_waivers(st))
    if not rows and not over:
        return ""
    t = ""
    if rows:
        t += " Phases closed by PROCEED-PAST (reported, not blocking): %s." % "; ".join(
            "phase %s (%s)%s" % (lab, why[:160], ": still-open findings it passed: %s" % ", ".join(
                "%s %s%s (%s)" % (f.get("severity"), f.get("id"), " [%s]" % f["gc"] if f.get("gc") else "",
                                  f.get("topic")) for f in still[:8]) if still else ", no finding it passed is open")
            for lab, why, still in rows)
    if over:
        t += " Open carried items whose target phase is closed (release blockers until settled or WAIVEd): %s." % (
            ", ".join("%s (to phase %s, %s)" % (cid, c.get("to"), c.get("class")) for cid, c in over[:12]))
    return t


def carry_text(st2, payload, name, label):
    from . import critic, verify
    t = ""
    if payload.get("carries"):
        t += " Carried to later phases (recorded in this ledger line): %s." % ", ".join(
            "%s -> phase %s (%s, %s)" % (c["id"], c["to"], c["rule"], c["class"]) for c in payload["carries"][:12])
    if payload.get("carries_closed"):
        t += " Settled here and closed: %s." % ", ".join(payload["carries_closed"])
    if name == "PROCEED-PAST":
        left = [cid for cid, c in critic.overdue_carries(st2, verify.active_waivers(st2)) if str(c.get("to")) == label]
        if left:
            t += (" Carried items addressed to phase %s stay OPEN and block the release until settled (REOPEN) or "
                  "closed by WAIVE <carry id>: %s." % (label, ", ".join(left)))
    return t


def contract_status(root, st):
    """0.7.0: STATUS lines for the critic's runs, carries, lapsed waivers and standing instructions."""
    from . import critic, verify
    aw = verify.active_waivers(st)
    t = ""
    label = st.get("current_phase")
    if label and label != "done":
        _run, reg = critic.latest_run(root, st, label)
        if reg["runs"]:
            t += (" Gap critic on phase %s: %d run(s); findings per run %s; late findings %d; regressions %d; "
                  "frozen-text findings %d." % (
                      label, len(reg["runs"]),
                      ", ".join(str(sum((r.get("counts") or {}).values())) for r in reg["runs"]),
                      sum(len(r.get("late") or []) for r in reg["runs"]),
                      sum(len(r.get("regressions") or []) for r in reg["runs"]),
                      sum(len(r.get("frozen") or {}) for r in reg["runs"])))
        cin = critic.carries_in(st, label, aw)
        if cin:
            t += " Carried into phase %s: %s." % (label, ", ".join(c for c, _x in cin))
    allc = critic.carries(st)
    if allc:
        n_open = len(critic.open_carries(st, aw))
        over = critic.overdue_carries(st, aw)
        t += " Carries: %d recorded, %d open%s." % (len(allc), n_open, "; release blockers: %s" % ", ".join(
            c for c, _x in over) if over else "")
    hd = _git_head(root)
    lapsed = critic.lapsed_waivers(root, st, hd, aw) if hd else []
    if lapsed:
        t += " Lapsed waivers (the cited text changed; the finding is judged afresh): %s." % ", ".join(
            "%s (%s)" % (w, p) for w, p in lapsed)
    si = adopt.standing_status(root, st)
    if si:
        t += " %s." % si
    return t


def _approval_digest(st, label):
    """The validator-result digest recorded by the APPROVE that approved `label`, if any."""
    for e in reversed(st.get("_entries") or []):
        if e["action"].split(" ", 1)[0] in ("APPROVE", "REOPEN"):
            pl = state.decode_payload(e)
            if pl.get("phase") == label:
                return (pl.get("validation") or {}).get("digest") if e["action"].startswith("APPROVE") else None
    return None


def waive_ids(text):
    """The finding ids one WAIVE names (0.6.4, F-5), in the order typed."""
    return [x for x in str(text or "").split(",") if x]


def _phase(st, label):
    return next((p for p in st["phases"] if p["label"] == label), None)


def _precheck(name, g, st):
    """Reason string if the action cannot apply to this state, else None."""
    ph = _phase(st, g.get("phase")) if "phase" in g else None
    if "phase" in g and ph is None:
        return "there is no phase %s in this scope (phases: %s)" % (
            g["phase"], ", ".join(p["label"] for p in st["phases"]))
    if name in ("APPROVE", "PROCEED-PAST", "COLLAPSE") and g["phase"] != st["current_phase"]:
        return "phase %s is not the current phase (current: %s%s)" % (
            g["phase"], st["current_phase"], ", in feature %s" % st["feature"] if st.get("feature") else "")
    if name == "FEATURE":
        return _feature_precheck(g["id"], st)
    if name == "REOPEN" and ph["status"] not in ("APPROVED", "PROCEED-PAST"):
        return "phase %s is not approved, so there is nothing to reopen" % g["phase"]
    if name == "WAIVE":
        ids = waive_ids(g["id"])
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            return "the WAIVE names %s more than once" % ", ".join(dup)
        if len("WAIVE %s owner=%s scope=%s expiry=%s reason=%s" % (
                g["id"], g["owner"], g["scope"], g["expiry"], g["reason"])) > 512:
            return "the WAIVE is longer than the ledger's 512-character action limit; split it in two"
        have = [i for i in ids if any(w["id"] == i for w in st["waivers"])]
        if have:
            return "waiver %s already exist%s" % (", ".join(have), "s" if len(have) == 1 else "")
    if name == "UNCARRY":
        return _uncarry_precheck(g["id"], st)
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
    if data["verdict"] != "pass" and unfixed_approvable(data):
        return True, None, data  # 0.8.2: this APPROVE is the operator's acceptance of the unfixed set REVIEW listed
    if data["verdict"] != "pass":
        fz = validation.frozen_text(data)  # 0.7.2 (ruling A1)
        return False, "the phase %s validators did not pass (%s). Findings: %s%s" % (
            label, data["verdict"].upper(), " | ".join(validation.findings(data)) or "see REVIEW %s" % label,
            ". " + fz if fz else ""), data
    return True, None, data


def unfixed_approvable(data, also=()):
    """0.8.2: True when every failing validator failed only on unfixed image findings the last APPROVE did not accept
    (it printed UNFIXED-ONLY; validate.py lists it in unfixed_only), or is one of `also`. Those findings have no fix
    to apply: the operator accepts them by approving, and the ledger line records the set."""
    only = set((data or {}).get("unfixed_only") or [])
    failing = [r for r in (data or {}).get("results") or [] if r.get("result") not in ("pass", "n/a-by-profile")]
    return bool(only) and bool(failing) and all(
        (r["validator"] in only and r.get("result") == "fail") or r["validator"] in also for r in failing)


def unfixed_payload(data):
    """0.8.2: what APPROVE records about the unfixed set: its sha256 and each finding (CVE, package, installed version,
    image digest, and for a built image its Dockerfile: validation.unfixed_key says what the acceptance binds)."""
    un = (data or {}).get("unfixed") or []
    if not un:
        return None
    keep = ("cve", "severity", "package", "installed", "image", "digest", "dockerfile", "scan_date")
    return {"sha256": validation.unfixed_digest(un),
            "findings": [{k: u.get(k) for k in keep if k != "dockerfile" or u.get(k)} for u in un]}


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
    stale = [r["validator"] for r in data["results"] if r["result"] == "stale"]
    if stale:  # 0.8.1 (task-tracker MF-62): a verifier had not written its evidence yet; that is not a known failure
        return False, "validator(s) %s read verifier evidence that was still being written (STALE); send REVIEW %s " \
                      "again once every launched verifier has finished" % (", ".join(stale), label), data
    failing = [r["validator"] for r in data["results"] if r["result"] == "fail"]
    if not failing:
        return False, "every validator passed, so there is nothing to proceed past; APPROVE %s instead" % label, data
    return True, failing, data


# ---------------------------------------------------------------- FEATURE, COLLAPSE (increment 6)

def baseline_approved(st):
    """Amendment 2: a product has an approved baseline when it was released (phase 11
    approved or proceeded past) or, onboarded, when its phase B was approved."""
    want = pathmap.BASELINE[0][1] if st.get("mode") == "onboarding" else pathmap.RELEASE
    ph = next((p for p in st.get("product_phases") or [] if p["label"] == want), None)
    return bool(ph and ph["status"] in ("APPROVED", "PROCEED-PAST")), want


def retro_pending(st):
    """Ruling 2 on increment 7: a product released through its own cycle must have approved that
    cycle's phase 12 (Retro) before a FEATURE starts. A sentence when it is pending, else None.
    (An onboarded product's baseline has no retro; a feature's retro keeps the feature active.)"""
    if st.get("feature") or st.get("mode") == "onboarding":
        return None
    ph = next((p for p in st.get("product_phases") or [] if p["label"] == pathmap.RETRO), None)
    rel = next((p for p in st.get("product_phases") or [] if p["label"] == pathmap.RELEASE), None)
    if ph and rel and rel["status"] in ("APPROVED", "PROCEED-PAST") and \
            ph["status"] not in ("APPROVED", "PROCEED-PAST", "COLLAPSED"):
        return ("phase %s (Retro) of the product's cycle is pending: the release is done, but a new FEATURE waits "
                "until the retro is approved (APPROVE %s)" % (pathmap.RETRO, pathmap.RETRO))
    return None


def _feature_precheck(fid, st):
    if not pathmap.FEATURE_ID.match(fid) or ".." in fid:
        return "%r is not a usable feature id (letters, digits, '.', '_' and '-', starting with a letter or digit)" % fid
    ok, want = baseline_approved(st)
    if not ok:
        return ("the product has no approved baseline yet: a feature cycle starts once the product's phase %s is "
                "approved (%s)" % (want, "onboarding: APPROVE B" if want == "B" else "released at phase 11"))
    if st.get("feature"):
        if st["current_phase"] == pathmap.RETRO:
            return ("phase %s (Retro) of feature %s is pending: its release is done, but a new FEATURE waits until the "
                    "previous cycle's retro is approved (APPROVE %s)" % (pathmap.RETRO, st["feature"], pathmap.RETRO))
        return ("feature %s is active (its current phase is %s). One feature at a time: finish it (approving its "
                "phase 11 merges it) before starting %s" % (st["feature"], st["current_phase"], fid))
    pending = retro_pending(st)
    if pending:
        return pending
    if any(f["id"] == fid for f in st.get("features") or []):
        return "feature id %s was already used (ledger seq %s); every feature needs its own id" % (
            fid, next(f["seq"] for f in st["features"] if f["id"] == fid))
    return None


def _collapse_gate(root, st, label):
    """(payload extras, reason). Increment 6 (item C): a phase the declared size profile
    collapses is skipped only through a RECORDED ruling: the size (S) is read from the
    approved BRD (the feature's own BRD in a feature cycle) and must agree with
    .sdlc/product.yaml's size when that is set; profiles.yaml names the reason and the
    checks that will not run, and the ledger line carries both."""
    from .v1 import hlib
    brd = None
    if st.get("feature"):
        from . import feature
        brd = feature.feature_doc(root, st["feature"], "0")
        if not brd:
            return None, "the feature has no BRD additions (%s/00-*.md) declaring its size" % feature.folder(st["feature"])
        brd = os.path.join(root, brd)
    ruled = _ruling_collapse(root, st, label)
    if ruled:
        return ruled, None
    stt, val = hlib.collapsed_phases(root, brd)
    if stt != "ok":
        return None, "whether phase %s may collapse is unknown: %s" % (label, val)
    if label not in val:
        return None, ("the size profile does not collapse phase %s (it collapses %s); do the phase, or PROCEED-PAST it "
                      "with a reason" % (label, ", ".join(sorted(val)) or "nothing at this size"))
    size = str(state.load_product(root).get("size") or "")
    if size and size not in ("null", "None") and size.upper() != val[label]["size"]:
        return None, ("the BRD declares size %s but .sdlc/product.yaml says %s; they must agree before anything is "
                      "collapsed" % (val[label]["size"], size))
    return {"size": val[label]["size"], "reason": val[label]["reason"],
            "checks_not_run": val[label]["checks_not_run"]}, None


def _ruling_collapse(root, st, label):
    """0.7.1 (task-tracker MF-3): a phase the Target Platform Ruling's profile retires (left out of
    `active_phases` AND declared not_applicable with a reason: 11b under WEB) collapses at any size.
    The reason and the checks that will not run come from the profile's `not_applicable`
    entries for that phase. None when the ruling does not retire the phase (or is undeclared)."""
    from . import contract
    _size, ruling = contract.size_and_ruling(root, st)
    if not ruling:
        return None
    prof = (contract._yaml(os.path.join(contract.GATE_DIR, "config", "profiles.yaml")).get("profiles") or {}).get(
        ruling) or {}
    if not contract.ruling_retires(prof, label):
        return None
    nas = [na for na in prof.get("not_applicable") or [] if str(na.get("phase")) == label]
    reason = " ".join(" ".join(str(na.get("reason") or "").split()) for na in nas).strip()
    return {"size": None, "ruling": ruling, "reason": reason,
            "checks_not_run": [str(na["validator"]) for na in nas if na.get("validator")]}


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


VERIFIER_FINDING = re.compile(r"^(?P<role>[a-z][a-z0-9-]*)\.(?P<fid>[A-Za-z0-9_.-]{1,64})$")


def _verifier_finding(root, wid, extra=None):
    """Increment 5: a verifier finding id is `<role>.<finding id>` (code-reviewer.S2,
    live-verifier.F1), and Claude Security's are SF-n from the gate's register.
    Returns None when wid is neither; else (severity or None, where/why). The severity
    is the one in the gate-checked evidence at HEAD, never one the report claims."""
    from . import secscan, verify
    m = VERIFIER_FINDING.match(wid)
    if m and m.group("role") in verify.roles() and verify.roles()[m.group("role")].get("critic"):
        return _critic_finding(root, m.group("role"), m.group("fid"), extra)
    if m and m.group("role") in verify.roles():
        role = verify.roles()[m.group("role")]
        ef = verify.evidence_file(root, str(role["phase"]), m.group("role"))
        try:
            with open(ef) as f:
                ev = json.load(f)
        except (OSError, ValueError):
            return None, "%s has no evidence at %s" % (m.group("role"), os.path.relpath(ef, root))
        for fd in ev.get("findings") or []:
            if isinstance(fd, dict) and str(fd.get("id")) == m.group("fid"):
                sev = str(fd.get("severity") or "")
                return (sev if sev in verify.SEVERITIES else "unknown"), "phase %s evidence of %s" % (
                    role["phase"], m.group("role"))
        return None, "%s's evidence has no finding %s" % (m.group("role"), m.group("fid"))
    if re.match(r"^SF-\d+$", wid, re.I):
        try:
            with open(secscan.result_file(root)) as f:
                res = json.load(f)
        except (OSError, ValueError):
            return None  # no Claude Security result: the phase-9 report's table decides (v1)
        for fd in res.get("findings") or []:
            if str(fd.get("id")).upper() == wid.upper():
                where = "Claude Security, commit %s" % str(res.get("head"))[:12]
                tri = {}
                if not fd.get("confirmed"):
                    with contextlib.suppress(Exception):
                        st, problems = state.current_state(root)
                        tri = {} if problems else verify.triage_of(root, st)
                stt, sev = secscan.judge(fd, tri.get(wid.upper()))
                if stt != "confirmed":
                    # Increment 6 (ruling 1): an unconfirmed (or triager-rejected) finding is waivable
                    # with a reason; only a CONFIRMED critical/high/unknown one is not.
                    return stt, where
                return sev, where + ("" if fd.get("confirmed") else ", confirmed by moadix:sf-triager")
        return None
    return None


def _critic_finding(root, role, fid, extra=None):
    """0.7.0: a gap-critic waiver binds ONE finding, `gap-critic.<GC id>` (the stable id the gate
    gave it, shown in REVIEW and the brief). It may waive a MAJOR in the current phase's current
    evidence; a BLOCKER is never waivable and a CARRY is not waived (it carries, or the operator
    UNCARRYs it). The finding's fingerprint (topic, path, section, sha256 of the cited text) goes
    in the ledger line through `extra`, so the waiver lapses when that text changes. A topic id
    (`gap-critic.B9`, the pre-0.7.0 form) is refused for new waivers. Returns (severity or None, where)."""
    from . import critic, verify
    st, problems = state.current_state(root)
    if problems:
        return None, "gate state failed its integrity check"
    label = st["current_phase"]
    if not critic.GC_ID.match(fid):
        return None, ("since 0.7.0 a gap-critic waiver binds one finding: name it by its id, gap-critic.GC-<phase>-<n> "
                      "(REVIEW %s lists them), not by topic" % label)
    ev, run, _sch = verify.current_critic(root, st, label)
    if not ev:
        return None, "%s has no current evidence for phase %s (launch it again)" % (role, label)
    inv = {g: c for c, g in (run or {}).get("map", {}).items()}
    cid = inv.get(fid)
    fd = next((x for x in ev.get("findings") or [] if isinstance(x, dict) and str(x.get("id")) == cid), None)
    where = "phase %s evidence of %s" % (label, role)
    if fd is None:
        return None, "%s's current evidence has no finding %s" % (role, fid)
    sev = str(fd.get("severity"))
    if sev == "BLOCKER":
        return "blocker", where
    if sev == "CARRY" and fid not in (st.get("_uncarried") or []):
        return None, ("%s is a CARRY, which is not waived: it carries to phase %s, or the operator pulls it back with "
                      "UNCARRY %s <code>" % (fid, fd.get("to"), fid))
    fp = (run.get("prints") or {}).get(fid) or {}
    if extra is not None:
        extra.setdefault("fingerprints", {})["%s.%s" % (role, fid)] = {
            "gc": fid, "topic": str(fd.get("topic")), "path": fp.get("path"), "section": fp.get("section"),
            "text": fp.get("text"), "text_sha": fp.get("text_sha"), "commit": run.get("commit"), "phase": label}
    return ("major" if sev in ("MAJOR", "CARRY") else "minor"), where


def _uncarry_precheck(fid, st):
    return None  # judged with the evidence in _uncarry_gate


def _uncarry_gate(root, st, fid):
    """Ruling Q2: the operator pulls a carry back to the current phase. A GC id: a CARRY finding of
    the current phase's current evidence then counts as a MAJOR. A CARRY id: an open carry in the
    register is readdressed to the current phase, whose COVERAGE.md must then settle it. Reason or None."""
    from . import critic, verify
    label = st["current_phase"]
    if critic.GC_ID.match(fid):
        if fid in (st.get("_uncarried") or []):
            return "%s was already uncarried" % fid
        ev, run, _sch = verify.current_critic(root, st, label)
        if not ev:
            return "the gap critic has no current evidence for phase %s" % label
        cid = {g: c for c, g in (run or {}).get("map", {}).items()}.get(fid)
        fd = next((x for x in ev.get("findings") or [] if isinstance(x, dict) and str(x.get("id")) == cid), None)
        if not fd or fd.get("severity") != "CARRY":
            return "%s is not a CARRY finding in phase %s's current evidence" % (fid, label)
        return None
    c = critic.carries(st).get(fid)
    if not c or c.get("status") != "open":
        return "%s is not an open carried item" % fid
    if str(c.get("to")) == str(label) and c.get("scope") == (st.get("feature") or "product"):
        return "%s is already addressed to the current phase %s" % (fid, label)
    return None


def _carry_waive(root, cid, extra):
    """Ruling Q5: an open carry whose target phase is already closed (approved, proceeded past or
    collapsed) may be closed with WAIVE and a reason, one item at a time; the ledger line carries the
    carry's text. A security, privacy or tenant-isolation carry cannot be waived. Reason or None."""
    from . import critic, verify
    st, problems = state.current_state(root)
    if problems:
        return "gate state failed its integrity check"
    c = critic.carries(st).get(cid)
    if c is None or c.get("status") != "open":
        return "%s is not an open carried item" % cid
    if cid not in {x for x, _c in critic.overdue_carries(st, verify.active_waivers(st))}:
        return ("%s is addressed to phase %s, which is still to come or still open: settle it there. A WAIVE closes "
                "only a carry whose target phase was closed without settling it" % (cid, c.get("to")))
    if c.get("class") in critic.rules()["protected"]:
        return "%s is a %s carry and CANNOT be waived; settle it (REOPEN its target phase)" % (cid, c.get("class"))
    extra.setdefault("carries_waived", {})[cid] = {k: c.get(k) for k in (
        "from", "to", "rule", "class", "topic", "quote", "citation", "fix", "commit", "gc")}
    return None


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


def _waive_gate(root, g, extra=None):
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
    from . import critic
    if critic.CARRY_ID.match(g["id"]):
        return _carry_waive(root, g["id"], extra if extra is not None else {})
    vf = _verifier_finding(root, g["id"], extra)
    if vf is not None:
        sev, where = vf
        if sev is None:
            return "%s names a verifier finding, but %s; refusing rather than granting blind" % (g["id"], where)
        if sev in ("unconfirmed", "rejected"):
            return None  # ruling 1: waivable with the reason the command carries
        if sev == "blocker":
            return ("%s names an open BLOCKER of the gap critic (%s); a BLOCKER cannot be waived. Fix the document "
                    "and run the critic again" % (g["id"], where))
        if sev in ("major", "minor"):
            return None  # Amendment 3: a MAJOR needs a WAIVE with a reason, which the command carries
        if sev in pol["unwaivable_severities"] or sev == "unknown":
            return ("%s is a confirmed %s-severity finding (%s) and CANNOT be waived. Fix it and verify again" % (
                g["id"], sev, where))
        return None
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
    if sev and (sev in pol["unwaivable_severities"] or sev == "unknown"):
        return ("%s is a %s-severity finding and CANNOT be waived. Fix it, or downgrade it with evidence in the "
                "phase-9 report" % (g["id"], sev))
    return None


# ---------------------------------------------------------------- 0.7.3: waiver defaults and proposals (item 5)
WAIVE_DEFAULT_OWNER = "operator"
WAIVE_DEFAULT_DAYS = 30
PROPOSED_WAIVERS = ".sdlc-proposals/waivers.yaml"
SCOPE_CHARS = re.compile(r"[^A-Za-z0-9_./:*@-]")


def finding_doc(root, st, wid):
    """The repository document a finding cites, as a waiver's default scope; `phase-<label>` when unknown."""
    from . import critic, secscan, verify
    label = (st or {}).get("current_phase") or "?"
    path = None
    m = VERIFIER_FINDING.match(wid)
    if m and m.group("role") in verify.roles() and verify.roles()[m.group("role")].get("critic"):
        _r, reg = critic.latest_run(root, st, label)
        path = (reg["findings"].get(m.group("fid")) or {}).get("path")
    elif m and m.group("role") in verify.roles():
        role = verify.roles()[m.group("role")]
        try:
            with open(verify.evidence_file(root, str(role["phase"]), m.group("role"))) as f:
                ev = json.load(f)
            fd = next((x for x in ev.get("findings") or [] if isinstance(x, dict) and str(x.get("id")) == m.group("fid")),
                      {})
            cit = (fd.get("citations") or [fd.get("citation")])[0]
            path = str(cit).split(":", 1)[0] if cit else None
        except (OSError, ValueError):
            path = None
    elif critic.CARRY_ID.match(wid):
        path = str((critic.carries(st).get(wid) or {}).get("citation") or "").split(":", 1)[0] or None
    elif re.match(r"^SF-\d+$", wid, re.I):
        try:
            with open(secscan.result_file(root)) as f:
                res = json.load(f)
            fd = next((x for x in res.get("findings") or [] if str(x.get("id")).upper() == wid.upper()), {})
            path = fd.get("path") or fd.get("file")
        except (OSError, ValueError):
            path = None
    out = SCOPE_CHARS.sub("-", str(path))[:128] if path else "phase-%s" % label
    return out or "phase-%s" % label


def waiver_defaults(root, st, g):
    """Fill a WAIVE's omitted owner and expiry (0.7.3). The scope is per finding: {id: scope}."""
    g = dict(g)
    g["owner"] = g.get("owner") or WAIVE_DEFAULT_OWNER
    g["expiry"] = g.get("expiry") or (datetime.date.today() + datetime.timedelta(days=WAIVE_DEFAULT_DAYS)).isoformat()
    scopes = {i: (g.get("scope") or finding_doc(root, st, i)) for i in waive_ids(g["id"])}
    g["scope"] = g.get("scope") or (list(scopes.values())[0] if len(set(scopes.values())) == 1 else "per-finding")
    return g, scopes


def known_finding(root, wid):
    """True when `wid` names a finding the gate can judge (a verifier's, Claude Security's, the phase-9 report's or
    a carry); a WITH-WAIVERS proposal naming anything else is an unknown id."""
    from . import critic
    if critic.CARRY_ID.match(wid) or VERIFIER_FINDING.match(wid):
        return True
    key = wid.split(":", 1)[0].strip().upper()
    if not FINDING_ID.match(key):
        return False
    vf = _verifier_finding(root, key)  # SF-n in Claude Security's result
    return bool(vf and vf[0] is not None) or key in (_finding_severities(root) or {})


def proposed_waivers(root, st):
    """(items, sha256 of the file, problems). Each item: {id, reason, owner, scope, expiry}; the file is
    .sdlc-proposals/waivers.yaml, written by the agent:

        waivers:
          - id: gap-critic.GC-1-4
            reason: the operator accepts this for the first release
            owner: operator        # optional
            expiry: 2026-12-31     # optional
            scope: sdlc/01-research.md   # optional

    Nothing is judged here except the shape; the gate judges each id with _waive_gate."""
    import hashlib
    from .v1 import hlib
    p = os.path.join(root, PROPOSED_WAIVERS)
    if not os.path.isfile(p) or os.path.islink(p):
        return [], None, ["there is no %s (the agent proposes waivers there)" % PROPOSED_WAIVERS]
    with open(p, "rb") as fh:
        raw = fh.read()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        doc = hlib.load_yaml(p) or {}
    except Exception as e:
        return [], digest, ["%s is not readable YAML (%s)" % (PROPOSED_WAIVERS, e)]
    items, probs = [], []
    rows = doc.get("waivers") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        return [], digest, ["%s lists no `waivers:`" % PROPOSED_WAIVERS]
    text = re.compile(r"^" + TEXT + r"$")
    for n, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            probs.append("entry %d is not a mapping" % n)
            continue
        wid, reason = str(r.get("id") or "").strip(), str(r.get("reason") or "").strip()
        if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", wid):
            probs.append("entry %d: id %r is not a finding id" % (n, wid))
            continue
        if not reason or not text.match(reason):
            probs.append("%s: a reason is required (printable ASCII, no quotes or backslashes, at most 300)" % wid)
            continue
        owner = str(r.get("owner") or WAIVE_DEFAULT_OWNER)
        expiry = str(r.get("expiry") or (datetime.date.today() + datetime.timedelta(days=WAIVE_DEFAULT_DAYS)).isoformat())
        scope = str(r.get("scope") or finding_doc(root, st, wid))
        if not re.match(r"^[A-Za-z0-9_.@-]{1,64}$", owner) or not re.match(r"^\d{4}-\d{2}-\d{2}$", expiry) or \
                SCOPE_CHARS.search(scope) or not scope:
            probs.append("%s: owner, expiry or scope is malformed" % wid)
            continue
        items.append({"id": wid, "reason": reason, "owner": owner, "scope": scope[:128], "expiry": expiry})
    ids = [i["id"] for i in items]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        probs.append("%s proposed more than once" % ", ".join(dup))
    return items, digest, probs


def judge_proposals(root, st, items, extra):
    """[(id, refusal or None)] for each proposed waiver, judged exactly as WAIVE judges it, plus: an unknown id
    is refused, and so is an id already waived."""
    out = []
    for it in items:
        if not known_finding(root, it["id"]):
            out.append((it["id"], "%s is not a finding id the gate knows (a verifier finding <role>.<id>, "
                                  "gap-critic.GC-..., SF-n, SEC-n or CARRY-...)" % it["id"]))
        elif any(w["id"] == it["id"] for w in st["waivers"]):
            out.append((it["id"], "waiver %s already exists" % it["id"]))
        else:
            out.append((it["id"], _waive_gate(root, it, extra)))
    return out


def _with_waivers_gate(root, st, label, data, items, extra):
    """(ok, reason). APPROVE WITH-WAIVERS on a result that did not pass: every failing validator must be one that
    judges verifier evidence (check-verifiers-*), and with the proposed waivers in force that evidence must pass."""
    from . import verify
    if data is None:
        return False, "there is no fresh validator result"
    failing = [r["validator"] for r in data["results"] if r["result"] not in ("pass", "n/a-by-profile")]
    other = [v for v in failing if not v.startswith("check-verifiers-") and
             v not in (data.get("unfixed_only") or [])]  # 0.8.2: accepted by this APPROVE
    if other:
        return False, ("validator(s) %s failed, and a waiver covers a finding, not a failing check: fix them first"
                       % ", ".join(other))
    st2 = dict(st)
    st2["waivers"] = list(st["waivers"]) + [dict(it, seq=None, at=None, feature=st.get("feature")) for it in items]
    wp = dict(st.get("_waiver_payload") or {})
    for it in items:
        wp[it["id"]] = {"fingerprints": {k: v for k, v in (extra.get("fingerprints") or {}).items() if k == it["id"]},
                        "phase_at": label, "source_commit": _git_head(root)}
    st2["_waiver_payload"] = wp
    still = [(name, probs) for name, status, probs, _i in verify.check_phase(root, st2, label) if status != "ok"]
    if still:
        return False, "with the proposed waivers the verifier evidence still fails: %s" % "; ".join(
            "%s: %s" % (n, "; ".join(p[:3])) for n, p in still)
    return True, None


def proposals_text(root, st):
    """REVIEW's lines for the proposed waivers, each judged now, or ""."""
    items, digest, probs = proposed_waivers(root, st)
    if digest is None:
        return ""
    judged = judge_proposals(root, st, items, {})
    rows = ["%s (%s; owner %s, scope %s, expiry %s)%s" % (it["id"], it["reason"], it["owner"], it["scope"],
                                                        it["expiry"], " REFUSED: %s" % why if why else "")
            for it, (_i, why) in zip(items, judged)]
    ok = not probs and not any(w for _i, w in judged)
    return " Proposed waivers (%s, sha256 %s): %s%s. %s" % (
        PROPOSED_WAIVERS, digest[:12], " | ".join(rows) or "none", "; problems: %s" % "; ".join(probs) if probs else "",
        "APPROVE %s WITH-WAIVERS <code> records exactly these with the approval." % st["current_phase"] if ok else
        "APPROVE %s WITH-WAIVERS would be refused until every proposal is valid." % st["current_phase"])


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
    mode, code_files = onboarding_mode(root)
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
    if mode == "onboarding":
        payload.update(mode="onboarding", code_files=code_files)
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
    with contextlib.suppress(OSError):
        validation.exclude_os_metadata(root)  # 0.6.4 (F-2): .DS_Store and kin never block a verifier
    from . import bmadcore
    bm = bmadcore.ensure(root) or ""
    if mode == "onboarding":
        return _ctx("INIT %s recorded (ledger seq 1): %s/.sdlc created. The repository already has code (%d tracked "
                    "file(s)), so the product starts in ONBOARDING mode at phase B (Baseline): document what exists, "
                    "citing the code (path:line), from the templates of /moadix:baseline. APPROVE B <code> approves the "
                    "baseline; from then on every change is a feature cycle (FEATURE <id> <code>). %s Tell the "
                    "operator it was recorded." % (pid, root, code_files, bm))
    return _ctx("INIT %s recorded (ledger seq 1): %s/.sdlc created; the current phase is %s. %s Tell the operator it "
                "was recorded." % (pid, root, st["current_phase"], bm))


NOT_CODE = re.compile(r"^(?:README[^/]*|LICENSE[^/]*|CHANGELOG[^/]*|CLAUDE\.md|\.gitignore|\.gitattributes|"
                      r"docs/.*|sdlc/.*|\.sdlc-proposals/.*|\.github/[^/]*\.md)$", re.I)


def onboarding_mode(root):
    """('onboarding', n) when the repository already has code at HEAD (Amendment 2: INIT on
    a repo with code starts at phase B), else ('greenfield', n). Code = any tracked file
    other than documentation (README, LICENSE, docs/, sdlc/, ...)."""
    rc, out, _ = _git(root, "ls-files", "-z")
    files = [f for f in out.split("\0") if f] if rc == 0 else []
    code = [f for f in files if not NOT_CODE.match(f)]
    return ("onboarding" if code else "greenfield"), len(code)


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
        if not problems:
            with contextlib.suppress(Exception):  # STATUS always answers
                val += contract_status(root, st)
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
            text += proposals_text(root, st)
        else:
            ev = ph.get("evidence") or []
            relied = _approval_digest(st, ph["label"])
            text = "not the current phase (%s); recorded validator evidence: %s%s" % (
                st["current_phase"], ", ".join("%s %s" % (e.get("validator"), e.get("result")) for e in ev) or "none",
                "; approved on validator result %s" % relied if relied else "")
        return _ctx("%s; %s. Relay this to the operator verbatim." % (head, text))

    code = g.pop("code")
    ww = bool(g.pop("ww", None))
    scopes = {}
    if name == "WAIVE" and not problems:
        g, scopes = waiver_defaults(root, st, g)
    if problems:
        _burn_all(message)
        return _ctx("%s NOT recorded: gate state failed its integrity check (%s). Nothing changed; the code is spent. "
                    "Tell the operator to run STATUS." % (name, "; ".join(problems)))
    why = _precheck(name, g, st)
    payload = dict(g, source_commit=_git_head(root))
    if name == "FEATURE":
        payload["feature"] = g["id"]
    elif st.get("feature") and name in ("APPROVE", "REOPEN", "PROCEED-PAST", "COLLAPSE", "WAIVE", "UNWAIVE",
                                         "UNCARRY"):
        payload["feature"] = st["feature"]  # Amendment 2 §6: ledger lines carry the feature id
    if not why and name == "COLLAPSE":
        extra, why = _collapse_gate(root, st, g["phase"])
        if extra:
            payload.update(extra)
    if not why and name == "APPROVE" and ww:
        # 0.7.3 (item 5): one code approves the phase and records exactly the proposed waivers
        items, digest, probs = proposed_waivers(root, st)
        wextra = {}
        judged = judge_proposals(root, st, items, wextra)
        refused = ["%s: %s" % (i, w) for i, w in judged if w]
        if probs or refused or not items:
            why = "the proposed waivers were refused (%s); nothing was recorded" % "; ".join(probs + refused)
        else:
            ok, why0, data = _approve_gate(root, st, g["phase"])
            if not ok and data is not None and data.get("verdict") == "fail":
                ok, why0 = _with_waivers_gate(root, st, g["phase"], data, items, wextra)
            why = why0
            if ok:
                payload.update(waivers=items, waivers_file=PROPOSED_WAIVERS, waivers_file_sha256=digest,
                               fingerprints=wextra.get("fingerprints") or {}, with_waivers=True)
                if unfixed_payload(data):  # 0.8.2: the operator's acceptance of the unfixed set
                    payload["unfixed_accepted"] = unfixed_payload(data)
                payload["validation"] = {"commit": data["key"]["commit"], "verdict": data["verdict"],
                                         "finished_at": data.get("finished_at"), "digest": data["_digest"],
                                         "passed_with_waivers": data["verdict"] != "pass",
                                         "results": [{"validator": r["validator"], "result": r["result"],
                                                      "exit_code": r["exit_code"]} for r in data["results"]]}
    if not why and name == "APPROVE" and not ww:
        ok, why, data = _approve_gate(root, st, g["phase"])
        if ok and unfixed_payload(data):  # 0.8.2: the operator's acceptance of the unfixed set REVIEW listed
            payload["unfixed_accepted"] = unfixed_payload(data)
        if ok:
            payload["validation"] = {"commit": data["key"]["commit"], "verdict": data["verdict"],
                                     "finished_at": data.get("finished_at"), "digest": data["_digest"],
                                     "results": [{"validator": r["validator"], "result": r["result"],
                                                  "exit_code": r["exit_code"]} for r in data["results"]]}
            if data["verdict"] != "pass":  # 0.8.2: failing only on the unfixed set this APPROVE accepts
                payload["validation"]["passed_with_unfixed_accepted"] = True
    merge = None
    if not why and name == "APPROVE" and st.get("feature") and g["phase"] == pathmap.RELEASE:
        from . import feature
        try:
            merge = feature.merge_plan(root, st["feature"], st["ledger_seq"] + 1)
            payload["merge"] = {"feature": st["feature"], "commit_before": payload["source_commit"],
                                "files": merge["files"]}
        except (feature.FeatureError, OSError) as e:
            why = "the feature's additions cannot be merged into the product documents: %s" % e
    if not why and name == "PROCEED-PAST":
        ok, res, data = _proceed_gate(root, st, g["phase"])
        if ok:
            payload["failing"] = res
            from . import verify
            passed = verify.passed_findings(root, st, g["phase"])
            if passed:  # increment 7b: the gap-critic findings this PROCEED-PAST passes, on the record
                payload["passed_findings"] = passed
        else:
            why = res
    if not why and name == "WAIVE":
        ids = waive_ids(g["id"])
        if len(ids) > 1:
            payload["ids"] = ids
        # Each id is judged as if waived alone; one refusal refuses the whole message (nothing is recorded).
        if len(set(scopes.values())) > 1:
            payload["scopes"] = scopes
        for i in ids:
            why = _waive_gate(root, dict(g, id=i), payload)
            if why:
                if len(ids) > 1:
                    why = "%s (no id of this WAIVE was recorded)" % why
                break
    if not why and name == "UNCARRY":
        why = _uncarry_gate(root, st, g["id"])
        payload["phase"] = st["current_phase"]  # the phase the carry is pulled back to
    if not why and name in ("APPROVE", "PROCEED-PAST"):
        # 0.7.0: the phase's carries go in the ledger line (the register is the ledger), and an APPROVE
        # closes the carries addressed to this phase that the critic raised nothing on.
        from . import critic, verify
        aw = verify.active_waivers(st)
        ev, run, _sch = verify.current_critic(root, st, g["phase"])
        out = critic.carries_out(root, st, g["phase"], run, ev, aw)
        if out:
            payload["carries"] = out
        if name == "APPROVE" and ev:
            closing = critic.carries_closing(st, g["phase"], ev, aw)
            if closing:
                payload["carries_closed"] = closing
    if not why and name == "PROCEED-PAST" and st.get("feature") and g["phase"] == pathmap.RELEASE:
        why = ("a feature's phase 11 merges its additions into the product documents, so it can only be APPROVED "
               "(on passing validators), never proceeded past")
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
        tail = proceeded_summary(st) if name == "APPROVE" and g.get("phase") == pathmap.RELEASE else ""
        return _ctx("%s NOT recorded: %s. Nothing changed; the code is spent.%s" % (name, why, tail))

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
    merged = ""
    if merge:
        from . import feature
        seq0 = json.loads(json.loads(out)["body"])["seq"]
        try:
            commit, files = feature.apply_merge(root, st["feature"], payload["merge"], seq0)
            merged = " Feature %s merged into the product documents (%s), committed by the gate as %s." % (
                st["feature"], ", ".join(f["target"] for f in files), commit[:12])
        except Exception as e:  # recorded: the ledger holds the plan; say plainly that the write failed
            merged = " The merge was RECORDED (ledger) but writing it failed: %s. Tell the operator." % e
    st2, problems2 = state.current_state(root)
    if not problems2 or all("phase.yaml differs" in p for p in problems2):
        state.write_phase(root, st2)
    seq = json.loads(json.loads(out)["body"])["seq"]
    nxt = ""
    if name == "APPROVE":
        nxt = " It rests on validator result %s." % payload["validation"]["digest"][:19]
        if payload.get("unfixed_accepted"):  # 0.8.2
            ua = payload["unfixed_accepted"]
            nxt += " It accepts %d unfixed High/Critical image finding(s) as residual risk (set sha256 %s): %s." % (
                len(ua["findings"]), ua["sha256"][:12], ", ".join("%s %s (%s)" % (
                    u["cve"], u["package"], u["digest"]) for u in ua["findings"]))
        fz = validation.frozen_text(data)  # 0.7.2 (ruling A1): shown, never blocking
        if fz:
            nxt += " %s." % fz
    if name in ("APPROVE", "PROCEED-PAST", "COLLAPSE"):
        nxt += merged
        if st.get("feature") and st2.get("feature") != st["feature"]:
            nxt += " Feature %s is complete; the product's documents now include it. FEATURE <id> <code> starts " \
                   "the next one." % st["feature"]
        elif st2["current_phase"] != "done":
            nxt += " Proceed to %sphase %s." % ("feature %s " % st2["feature"] if st2.get("feature") else "",
                                                 st2["current_phase"])
        elif st.get("mode") == "onboarding" or (st2.get("product_phases") and not st2.get("feature")):
            nxt += " All phases are done. From here every change is a feature cycle (FEATURE <id> <code>)."
        else:
            nxt += " All phases are done."
    if name == "PROCEED-PAST" and payload.get("passed_findings"):
        nxt = " It passes these open gap-critic findings, recorded in the ledger: %s.%s" % (
            "; ".join("%s %s%s (%s) at %s" % (f["severity"], f["id"], " [%s]" % f["gc"] if f.get("gc") else "",
                                               f["topic"], f["citation"])
                      for f in payload["passed_findings"][:8]), nxt)
    if name in ("APPROVE", "PROCEED-PAST"):
        nxt += carry_text(st2, payload, name, g["phase"])
        if g["phase"] == pathmap.RELEASE:
            nxt += proceeded_summary(st2)
    if name == "UNCARRY":
        from . import critic
        nxt = (" %s now counts as a MAJOR of phase %s: fix it, or WAIVE gap-critic.%s with a reason." % (
            g["id"], st["current_phase"], g["id"]) if critic.GC_ID.match(g["id"]) else
            " %s is now addressed to phase %s: its COVERAGE.md must settle it." % (g["id"], st["current_phase"]))
    if name == "APPROVE" and payload.get("waivers"):
        nxt += " Under the same code it recorded %d waiver(s) from %s (sha256 %s): %s." % (
            len(payload["waivers"]), PROPOSED_WAIVERS, payload["waivers_file_sha256"][:12],
            "; ".join("%s (%s, until %s)" % (w["id"], w["reason"], w["expiry"]) for w in payload["waivers"]))
        with contextlib.suppress(OSError):  # the proposals are used up, as ADOPT removes what it adopted
            os.unlink(os.path.join(root, PROPOSED_WAIVERS))
    if name == "COLLAPSE":
        nxt = " Phase %s collapsed by the %s (recorded ruling; checks not run: %s).%s" % (
            g["phase"], "%s platform ruling" % payload["ruling"] if payload.get("ruling") else
            "size-%s profile" % payload["size"], ", ".join(payload["checks_not_run"]) or "none", nxt)
    if name == "FEATURE":
        nxt = (" Feature %s started at phase %s; its documents go in sdlc/features/%s/ (see /moadix:feature); the "
               "product's approved documents are frozen until the feature's phase 11 merges the additions." % (
                   g["id"], st2["current_phase"], g["id"]))
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
