#!/usr/bin/python3
"""Render managed/managed-settings.json for one machine.

    render_policy.py <template> <cc_dir> <moadix_home> <pin> <owner/repo|none>
                     [--overlay FILE --overlay-out FILE] > out.json

The local overlay (0.5.2) is the operator's own file outside the repository (default
~/.config/moadix/overlay.json, docs/INSTALL.md "Local overlay"): production Firebase projects
to protect and extra network hosts. Nothing product-specific is in the public template; the
overlay is validated, merged into the rendered policy (one deny rule per protected project,
the hosts appended to the sandbox allowlist), and written for the gate's main-branch guard
(--overlay-out, installed root-owned as <gate>/config/overlay.json).

Placeholders: __CC_DIR__ (the managed-settings directory), __MOADIX_HOME__ (the
root-owned gate copy), __PIN__ (fingerprint of the Keychain secrets),
__MARKETPLACE_REPO__ (owner/repo of this repo on GitHub, which serves as its own
marketplace: strictKnownMarketplaces then allows exactly that one plus Anthropic's
official marketplace, and enabledPlugins force-enables moadix@moadix and
claude-security@claude-plugins-official, and force-disables every other official
plugin). With "none", the plugin
keys are left out: the gate runs entirely from managed settings, and
strictKnownMarketplaces stays [] (no plugin source allowed).
"""
import json
import os
import re
import sys

OFFICIAL_NAME = "claude-plugins-official"
OFFICIAL = {"source": "github", "repo": "anthropics/claude-plugins-official"}
ENABLED = {"moadix@moadix": True, "claude-security@%s" % OFFICIAL_NAME: True}
OFFICIAL_LIST = os.path.join(os.path.dirname(os.path.realpath(__file__)), "official-plugins.txt")


def official_plugins():
    with open(OFFICIAL_LIST) as f:
        names = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if "claude-security" not in names or len(names) < 2:
        sys.exit("managed/official-plugins.txt does not look like the official marketplace's plugin list")
    return names


def sub(v, m):
    if isinstance(v, str):
        for k, x in m.items():
            v = v.replace(k, x)
        return v
    if isinstance(v, list):
        return [sub(i, m) for i in v]
    if isinstance(v, dict):
        return {k: sub(x, m) for k, x in v.items()}
    return v


HOST = re.compile(r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
OVERLAY_KEYS = {"version", "protected_firebase_projects", "extra_network_hosts"}


def load_overlay(path):
    """The validated overlay {projects, hosts}; exits with the reason on anything malformed."""
    try:
        with open(path) as f:
            doc = json.load(f)
    except ValueError as e:
        sys.exit("overlay %s is not JSON: %s" % (path, e))
    if not isinstance(doc, dict) or doc.get("version") != 1:
        sys.exit("overlay %s must be a JSON object with \"version\": 1" % path)
    extra = sorted(set(doc) - OVERLAY_KEYS)
    if extra:
        sys.exit("overlay %s has keys it may not set: %s (allowed: %s)" % (path, ", ".join(extra),
                                                                         ", ".join(sorted(OVERLAY_KEYS))))
    projects, hosts = doc.get("protected_firebase_projects") or [], doc.get("extra_network_hosts") or []
    if not isinstance(projects, list) or not all(isinstance(x, str) and PROJECT.match(x) for x in projects):
        sys.exit("overlay: protected_firebase_projects must be a list of Firebase project ids (plain strings)")
    for h in hosts:
        if not isinstance(h, str) or not HOST.match(h):
            sys.exit("overlay: extra_network_hosts entry %r is not a plain host name (no scheme, path, port or "
                     "Markdown link; a leading *. is allowed)" % (h,))
        if re.match(r"^\*\.[^.]+$", h) or h.count(".") < 1:
            sys.exit("overlay: %r would allow a whole top-level domain" % h)
    return {"projects": sorted(set(projects)), "hosts": list(dict.fromkeys(hosts))}


def main():
    args = sys.argv[1:]
    overlay = overlay_out = None
    if "--overlay" in args:
        k = args.index("--overlay")
        overlay = args[k + 1]
        del args[k:k + 2]
    if "--overlay-out" in args:
        k = args.index("--overlay-out")
        overlay_out = args[k + 1]
        del args[k:k + 2]
    tpl, cc_dir, home, pin, repo = args[0:5]
    if not re.match(r"^[0-9a-f]{32}$", pin):
        sys.exit("bad pin")
    if repo != "none" and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
        sys.exit("bad repo")
    d = json.load(open(tpl))
    if repo == "none":
        for k in ("extraKnownMarketplaces", "enabledPlugins"):
            d.pop(k, None)
        d["strictKnownMarketplaces"] = []
    d = sub(d, {"__CC_DIR__": cc_dir.rstrip("/"), "__MOADIX_HOME__": home.rstrip("/"), "__PIN__": pin,
                "__MARKETPLACE_REPO__": repo})
    if repo != "none":
        # The repo is its own public marketplace (.claude-plugin/marketplace.json, name "moadix").
        # Increment 5 adds Anthropic's official marketplace for ONE plugin, claude-security (the
        # phase-9 finding source). Allow exactly those two marketplaces, register both, and
        # force-enable exactly moadix@moadix and claude-security@claude-plugins-official.
        # Every other plugin the official marketplace lists (managed/official-plugins.txt) is
        # force-DISABLED, so none can be enabled from user, project or local settings.
        want = {"source": "github", "repo": repo}
        if d.get("strictKnownMarketplaces") != [want, OFFICIAL]:
            sys.exit("strictKnownMarketplaces must allow exactly %s and %s" % (repo, OFFICIAL["repo"]))
        if d.get("extraKnownMarketplaces") != {"moadix": {"source": want}, OFFICIAL_NAME: {"source": OFFICIAL}}:
            sys.exit("extraKnownMarketplaces must register exactly moadix -> %s and %s" % (repo, OFFICIAL_NAME))
        if d.get("enabledPlugins") != ENABLED:
            sys.exit("enabledPlugins must force-enable exactly %s" % ", ".join(sorted(ENABLED)))
        for name in official_plugins():
            key = "%s@%s" % (name, OFFICIAL_NAME)
            if key not in ENABLED:
                d["enabledPlugins"][key] = False
        on = sorted(k for k, v in d["enabledPlugins"].items() if v is True)
        if on != sorted(ENABLED):
            sys.exit("the rendered policy enables %s, not exactly %s" % (on, sorted(ENABLED)))
    ov = load_overlay(overlay) if overlay and os.path.exists(overlay) else {"projects": [], "hosts": []}
    deny = d["permissions"]["deny"]
    for pid in ov["projects"]:
        deny.append("Bash(firebase*%s*)" % pid)
    net = d["sandbox"]["network"]["allowedDomains"]
    for h in ov["hosts"]:
        if h not in net:
            net.append(h)
    if overlay_out:
        with open(overlay_out, "w") as f:
            json.dump({"version": 1, "protected_firebase_projects": ov["projects"],
                       "extra_network_hosts": ov["hosts"], "source": overlay if overlay and os.path.exists(overlay)
                       else None}, f, indent=1, sort_keys=True)
    text = json.dumps(d, indent=2) + "\n"
    left = sorted(set(re.findall(r"__(?:CC_DIR|MOADIX_HOME|PIN|MARKETPLACE_REPO)__", text)))
    if left:
        sys.exit("unfilled placeholders: %s" % left)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
