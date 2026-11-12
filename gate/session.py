"""SessionStart (increment 6, ruling 5): report plugin drift, and keep BMad core in place.

The managed policy force-enables exactly two plugins (moadix@moadix and
claude-security@claude-plugins-official) and force-disables every other plugin
of the official marketplace (managed/render_policy.py). So no other plugin should
ever be enabled. This check catches drift: a plugin the official marketplace added
after managed/official-plugins.txt was generated, a policy that is not the one in
effect, or a settings layer the policy does not reach.

It computes the effective enabledPlugins the way Claude Code layers them (user,
then project, then local settings, then the managed policy, which wins) and, when
any plugin other than the two is enabled, says so to the session twice: as a
systemMessage the operator sees, and as added context the agent relays. It never
blocks the session and changes nothing (it only reads settings files).

In a MOADIX product it also re-installs BMad core's scripts into _bmad/ when they
are missing or differ from the pinned copy (gate/bmadcore.py), so the vendored
BMAD skills find them.
"""
import json
import os

ALLOWED = ("moadix@moadix", "claude-security@claude-plugins-official")
GATE_DIR = os.path.dirname(os.path.realpath(__file__))
MOADIX_HOME = os.path.dirname(GATE_DIR)


def _enabled(path):
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    ep = doc.get("enabledPlugins") if isinstance(doc, dict) else None
    return {str(k): bool(v) for k, v in ep.items()} if isinstance(ep, dict) else {}


def _project_dirs(cwd):
    """cwd and its git top level (where Claude Code looks for .claude/settings*.json)."""
    out = []
    d = os.path.realpath(cwd or os.getcwd())
    out.append(d)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            if d not in out:
                out.append(d)
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return out


def policy_path():
    """The managed-settings file next to MOADIX's home (installed: /Library/Application
    Support/ClaudeCode/managed-settings.json; a fixture's stand-in otherwise)."""
    return os.path.join(os.path.dirname(MOADIX_HOME), "managed-settings.json")


def effective_plugins(cwd, home=None):
    """{plugin key: (enabled, the settings file that decided it)}."""
    home = home or os.path.expanduser("~")
    layers = [os.path.join(home, ".claude", "settings.json")]
    for d in reversed(_project_dirs(cwd)):
        layers += [os.path.join(d, ".claude", "settings.json"), os.path.join(d, ".claude", "settings.local.json")]
    layers.append(policy_path())
    eff = {}
    for p in layers:
        for k, v in _enabled(p).items():
            eff[k] = (v, p)
    return eff


def drift(cwd, home=None):
    """[(plugin, settings file)] enabled other than the two the policy allows."""
    return sorted((k, src) for k, (on, src) in effective_plugins(cwd, home).items() if on and k not in ALLOWED)


def handle(hook_input):
    cwd = hook_input.get("cwd") or os.getcwd()
    notes = []
    extra = drift(cwd)
    if extra:
        names = ", ".join("%s (enabled in %s)" % (k, src) for k, src in extra)
        notes.append("PLUGIN DRIFT: %s. Only moadix and claude-security should be enabled; the managed policy "
                     "should prevent this. Tell the operator before doing anything else." % names)
    try:
        from . import bmadcore, state
        root = state.find_root(cwd)
        if root:
            note = bmadcore.ensure(root)
            if note:
                notes.append(note)
    except Exception as e:  # never block a session from starting
        notes.append("BMad core could not be checked (%s)" % type(e).__name__)
    if not notes:
        return None
    text = "MOADIX: " + " ".join(notes)
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    if extra:
        out["systemMessage"] = text
    return out
