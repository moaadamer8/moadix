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

from . import autoval, bashcls, pathmap, state

TURN_TOOLS = {"CronCreate", "CronDelete", "ScheduleWakeup", "SendMessage", "ListAgents", "RemoteTrigger"}
WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
READ_TOOLS = {"Read": "file_path", "Grep": "path", "Glob": "path"}
GATE_NAMES = re.compile(r"moadix-checker|gate/hook\.py|gate\.(?:opcmd|state|pretool)|MOADIX_HOME|ClaudeCode/moadix")
# Protected words for commands the gate cannot see into, each with its class
# (v1 defect: one reason text for every class). The repo name "moadix" is no
# longer one of them: it matched this repository's own path, and the gate's
# home is covered by "ClaudeCode" and the plugin cache by ".claude".
PROTECTED_WORDS = [
    (re.compile(r"\.sdlc"), "MOADIX gate state (.sdlc/)"),
    (re.compile(r"\.claude|settings(?:\.local)?\.json|\.mcp\.json"), "Claude Code configuration"),
    (re.compile(r"Keychains"), "the Keychain databases"),
    (re.compile(r"ClaudeCode"), "the managed policy and MOADIX's root-owned home"),
]
# A link whose source is one of these is a second path to protected bytes.
LINK_PROTECTED = {"gate-state", "cc-config", "managed", "keychain", "shell-rc", "secret", "bmad"}
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
    """None if writing `path` is allowed, else the reason.

    The phase path map (invariant 6) is applied to the SESSION's product (the
    product holding the hook's cwd). In a different product, typically a
    scratch `git clone` of this one, which carries the tracked .sdlc/ and cannot
    be told apart from the original, only .sdlc/ and the protected classes are
    enforced, as v1 enforced nothing outside its one governed root. When the
    session is in no product, every product gets its full path map."""
    ab = pathmap.resolve(path, cwd)
    probe = ab if os.path.isdir(ab) else os.path.dirname(ab)
    root = state.find_root(probe) or state.find_root(cwd)
    if root and not (ab == os.path.realpath(root) or ab.startswith(os.path.realpath(root) + os.sep)):
        root = state.find_root(probe)
    session = cache.get("_session")
    foreign = bool(root and session and os.path.realpath(root) != os.path.realpath(session))
    phase_id = None
    if root and not foreign:
        phase_id, problems = _phase_for(root, cache)
        if problems:
            return "gate state failed its integrity check, so writes in %s are refused until STATUS is clean (%s)" % (
                root, "; ".join(problems))
    d = pathmap.classify(ab, root, phase_id, foreign=foreign)
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


def _link_reason(src_abs, session_root):
    """Reason if a link (symbolic or hard) to src_abs must be refused."""
    probe = src_abs if os.path.isdir(src_abs) else os.path.dirname(src_abs)
    d = pathmap.classify(src_abs, state.find_root(probe) or session_root, 0)
    if d.klass in LINK_PROTECTED:
        return "a link to %s would be a second path to protected bytes: %s" % (src_abs, d.reason)
    for prot in pathmap.protected_anchors(session_root):
        if prot == src_abs or prot.startswith(src_abs.rstrip("/") + "/"):
            return "a link to %s would be a second path into %s" % (src_abs, prot)
    return None


def check_bash(cmd, cwd, cache):
    a = bashcls.analyse(cmd, os.path.realpath(cwd) if cwd else None)
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
    if a["opaque"]:
        for rx, what in PROTECTED_WORDS:
            if rx.search(cmd):
                return "this command runs code the gate cannot see into (%s) and names %s; write it as plain " \
                       "commands" % (a["opaque_why"], what)
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
    session_root = state.find_root(cwd)
    if a["computed"] and session_root:
        return "%s, so the gate cannot tell which path it writes; name the path literally" % a["computed_why"]
    # Links: refuse a link whose source is protected, and follow links created
    # earlier in this same command (the increment-1 one-liner gap).
    made = []
    for src, link, lcwd, symbolic in a["links"]:
        if bashcls.COMPUTED.search(src) or (lcwd is None and not os.path.isabs(os.path.expanduser(src))):
            if session_root:
                return "the link source %r is only known at run time; name it literally" % src
            continue
        link_abs = pathmap.resolve(link, lcwd)
        base = os.path.dirname(link_abs) if symbolic else (lcwd or "/")
        src_abs = os.path.realpath(os.path.normpath(os.path.join(base, os.path.expanduser(src))))
        why = _link_reason(src_abs, session_root)
        if why:
            return why
        made.append((link_abs, src_abs))
    for t, wcwd in a["writes"]:
        why = check_path(t, wcwd, cache)
        if why:
            return why
        ab = pathmap.resolve(t, wcwd)
        for link_abs, src_abs in made:
            if ab == link_abs or ab.startswith(link_abs + "/"):
                why = check_path(src_abs + ab[len(link_abs):], wcwd, cache)
                if why:
                    return why
    for repo, _gcwd, sub in a["git"]:
        if repo is None:
            if session_root:
                return "git %s acts on a repository that is only known at run time" % sub
            continue
        prod = state.find_root(repo)
        if prod and session_root and os.path.realpath(prod) == os.path.realpath(session_root):
            return ("git %s rewrites tracked files across this product's work tree, including .sdlc/ (MOADIX gate "
                    "state, which only the gate's hooks write); name the paths (git checkout -- <path>) or use a "
                    "scratch copy" % sub)
    return None


def decide(hook_input):
    tool = hook_input.get("tool_name") or ""
    ti = hook_input.get("tool_input") or {}
    cwd = hook_input.get("cwd") or os.getcwd()
    cache = {"_session": state.find_root(cwd)}
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
    if autoval.is_request_review(tool, ti):
        autoval.trigger(cwd)  # ruling 2: the gate runs the phase's validators; the call itself changes no state
    return None
