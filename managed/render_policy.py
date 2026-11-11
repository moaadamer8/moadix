#!/usr/bin/python3
"""Render managed/managed-settings.json for one machine.

    render_policy.py <template> <cc_dir> <moadix_home> <pin> <owner/repo|none> > out.json

Placeholders: __CC_DIR__ (the managed-settings directory), __MOADIX_HOME__ (the
root-owned gate copy), __PIN__ (fingerprint of the Keychain secrets),
__MARKETPLACE_REPO__. With "none", the plugin keys are left out: the gate runs
entirely from managed settings, and strictKnownMarketplaces stays [] (no
plugin source allowed).
"""
import json
import re
import sys


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
    text = json.dumps(d, indent=2) + "\n"
    left = sorted(set(re.findall(r"__(?:CC_DIR|MOADIX_HOME|PIN|MARKETPLACE_REPO)__", text)))
    if left:
        sys.exit("unfilled placeholders: %s" % left)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
