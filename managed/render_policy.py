#!/usr/bin/python3
"""Render managed/managed-settings.json for one machine.

    render_policy.py <template> <cc_dir> <moadix_home> <pin> <owner/repo|none> > out.json

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


def main():
    tpl, cc_dir, home, pin, repo = sys.argv[1:6]
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
    text = json.dumps(d, indent=2) + "\n"
    left = sorted(set(re.findall(r"__(?:CC_DIR|MOADIX_HOME|PIN|MARKETPLACE_REPO)__", text)))
    if left:
        sys.exit("unfilled placeholders: %s" % left)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
