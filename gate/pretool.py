"""PreToolUse: invariants 1, 3, 4 and 6 (DESIGN.md section 2).

 1. No write to .sdlc/ through the agent's tools (the sandbox covers the
    processes it runs; the signed ledger covers Docker/Playwright).
 3. The agent has no command that changes phase state: it cannot run the
    checker or the gate's entry points, or touch the Keychain.
 4. sudo, plugin install/enable/disable, `claude mcp add`, nested `claude`,
    scheduled tasks, cross-session messages, and edits to settings, plugin
    and managed paths are denied.
 6. Writes inside a product repo must fall in the current phase's path map.

Returns a deny dict or None (no opinion: normal permission flow continues).
Any internal error is a deny (fail closed).
"""
import os
import re

from . import bashcls, pathmap, state

TURN_TOOLS = {"CronCreate", "CronDelete", "ScheduleWakeup", "SendMessage", "ListAgents", "RemoteTrigger"}
WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
READ_TOOLS = {"Read": "file_path", "Grep": "path", "Glob": "path"}
GATE_NAMES = re.compile(r"moadix-checker|gate/hook\.py|gate\.(?:opcmd|state|pretool)|MOADIX_HOME|ClaudeCode/moadix")
PROTECTED_WORDS = re.compile(r"\.sdlc|\.claude|moadix|Keychains|ClaudeCode|settings(?:\.local)?\.json|\.mcp\.json")
SECURITY_SUBS = re.compile(r"^(add|delete|set|import|export|dump|unlock|lock|create|default|list-keychains|login-keychain|"
                           r"find-generic-password|find-internet-password|find-key|authorizationdb|execute-with-privileges)")
TRANSCRIPTS = os.path.join(pathmap.HOME, ".claude", "projects")


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "MOADIX: " + reason}}


def _phase_for(root, cache):
    if root not in cache:
        st, problems = state.current_state(root)
        cache[root] = (st["current_phase_id"], problems)
    return cache[root]


def check_path(path, cwd, cache):
    """None if writing `path` is allowed, else the reason."""
    ab = pathmap.resolve(path, cwd)
    probe = ab if os.path.isdir(ab) else os.path.dirname(ab)
    root = state.find_root(probe) or state.find_root(cwd)
    if root and not (ab == os.path.realpath(root) or ab.startswith(os.path.realpath(root) + os.sep)):
        root = state.find_root(probe)
    phase_id = 0
    if root:
        phase_id, problems = _phase_for(root, cache)
        if problems:
            return "gate state failed its integrity check, so writes in %s are refused until STATUS is clean (%s)" % (
                root, "; ".join(problems))
    d = pathmap.classify(ab, root, phase_id)
    return None if d.allow else d.reason


def _docker_mounts(toks):
    """Host paths in `docker run/create -v SRC:DST` and `--mount ...source=SRC`."""
    out = []
    for j, t in enumerate(toks):
        val = None
        if t in ("-v", "--volume", "--mount") and j + 1 < len(toks):
            val = toks[j + 1]
        elif t.startswith("--volume=") or t.startswith("--mount=") or (t.startswith("-v") and len(t) > 2):
            val = t.split("=", 1)[1] if "=" in t[:9] else t[2:]
        if not val:
            continue
        m = re.search(r"(?:^|,)(?:source|src)=([^,]+)", val)
        src = m.group(1) if m else val.split(":", 1)[0]
        src = re.sub(r"^(?:\$PWD|\$\{PWD\}|\$\(pwd\)|`pwd`)", ".", src)
        if src.startswith(("/", "~", ".")):
            out.append(src)
    return out


def check_bash(cmd, cwd, cache):
    a = bashcls.analyse(cmd)
    verbs = [v.rsplit("/", 1)[-1] for v in a["verbs"]]
    if {"sudo", "doas", "su"} & set(verbs) or re.search(r"(^|[\s;&|(])sudo\s", cmd):
        return "sudo is denied (invariant 4)"
    if "claude" in verbs or re.search(r"@anthropic-ai/claude-code|(^|[\s;&|(/])claude\s+(plugin|mcp|-p|--print|--resume|-c)\b", cmd):
        return "nested claude sessions and claude plugin/mcp commands are denied (invariant 4)"
    if GATE_NAMES.search(cmd):
        return "the agent has no command that changes gate state; operator commands are typed in chat (invariant 3)"
    if "security" in verbs:
        toks = a["words"]
        for j, t in enumerate(toks):
            if t.rsplit("/", 1)[-1] == "security" and j + 1 < len(toks) and SECURITY_SUBS.match(toks[j + 1]):
                return "Keychain commands are denied: the Keychain holds MOADIX's approval secrets (invariant 3)"
    if a["opaque"] and PROTECTED_WORDS.search(cmd):
        return "this command runs code the gate cannot see into and names a protected path; write it as plain commands"
    if "docker" in verbs or "podman" in verbs:
        for src in _docker_mounts(a["words"]):
            ab = pathmap.resolve(src, cwd)
            root = state.find_root(ab if os.path.isdir(ab) else os.path.dirname(ab)) or state.find_root(cwd)
            sensitive = [pathmap.HOME, "/", os.path.join(pathmap.HOME, ".claude")]
            if root:
                sensitive += [os.path.realpath(root), os.path.join(os.path.realpath(root), ".sdlc")]
            if ab in sensitive or os.path.basename(ab) in (".sdlc", ".claude") or \
                    any(s.startswith(ab.rstrip("/") + "/") for s in sensitive if s != "/") or ab == "/":
                return "docker mount of %s would expose gate state or settings to the container; mount a subdirectory" % src
    bases = [cwd] + [pathmap.resolve(c, cwd) for c in a["cd"]]
    for t in a["targets"]:
        for base in bases:
            why = check_path(t, base, cache)
            if why:
                return why
    return None


def decide(hook_input):
    tool = hook_input.get("tool_name") or ""
    ti = hook_input.get("tool_input") or {}
    cwd = hook_input.get("cwd") or os.getcwd()
    cache = {}
    if tool in TURN_TOOLS:
        return deny("%s is denied: the agent cannot schedule turns or message other sessions (invariant 4)" % tool)
    if tool in WRITE_TOOLS:
        p = ti.get(WRITE_TOOLS[tool])
        if not p:
            return deny("%s without a path" % tool)
        why = check_path(p, cwd, cache)
        return deny(why) if why else None
    if tool in READ_TOOLS:
        p = ti.get(READ_TOOLS[tool])
        if p and pathmap.resolve(p, cwd).startswith(TRANSCRIPTS):
            return deny("session transcripts are not readable by the agent")
        return None
    if tool == "Bash":
        why = check_bash(ti.get("command") or "", cwd, cache)
        return deny(why) if why else None
    return None
