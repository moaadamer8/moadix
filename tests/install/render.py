#!/usr/bin/python3
"""managed/render_policy.py: the repo is its own marketplace, and the policy allows exactly it.

    /usr/bin/python3 tests/install/render.py

No sudo, no Keychain. Checks the rendered policy with and without --plugin, that
.claude-plugin/marketplace.json names the plugin the policy force-enables, and
that a template allowing a second marketplace is refused.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TPL = os.path.join(REPO, "managed", "managed-settings.json")
RENDER = os.path.join(REPO, "managed", "render_policy.py")
PIN = "0123456789abcdef0123456789abcdef"
RESULTS = []


def check(name, ok, evidence):
    RESULTS.append(ok)
    print("%s  %s\n      %s" % ("PASS" if ok else "FAIL", name, evidence))


def render(repo, tpl=TPL):
    return subprocess.run(["/usr/bin/python3", "-I", RENDER, tpl, "/cc", "/cc/moadix", PIN, repo],
                          capture_output=True, text=True)


def main():
    r = render("someone/moadix")
    pol = json.loads(r.stdout) if r.returncode == 0 else {}
    want = {"source": "github", "repo": "someone/moadix"}
    check("--plugin: strictKnownMarketplaces allows exactly that one marketplace",
          pol.get("strictKnownMarketplaces") == [want], json.dumps(pol.get("strictKnownMarketplaces")))
    check("--plugin: the marketplace is registered as 'moadix' and moadix@moadix is force-enabled",
          pol.get("extraKnownMarketplaces") == {"moadix": {"source": want}} and pol.get("enabledPlugins") == {"moadix@moadix": True},
          "%s / %s" % (json.dumps(pol.get("extraKnownMarketplaces")), json.dumps(pol.get("enabledPlugins"))))

    r = render("none")
    pol = json.loads(r.stdout) if r.returncode == 0 else {}
    check("no --plugin: no marketplace allowed, no plugin keys",
          pol.get("strictKnownMarketplaces") == [] and "enabledPlugins" not in pol and "extraKnownMarketplaces" not in pol,
          "strictKnownMarketplaces=%r" % pol.get("strictKnownMarketplaces"))

    mk = json.load(open(os.path.join(REPO, ".claude-plugin", "marketplace.json")))
    pj = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))
    names = [p.get("name") for p in mk.get("plugins", [])]
    check("marketplace.json is named 'moadix' and lists exactly the plugin 'moadix' from this repo",
          mk.get("name") == "moadix" and names == ["moadix"] and mk["plugins"][0].get("source") == "./" and pj.get("name") == "moadix",
          "marketplace=%s plugins=%s" % (mk.get("name"), names))

    tpl = json.load(open(TPL))
    tpl["strictKnownMarketplaces"].append({"source": "github", "repo": "other/market"})
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(tpl, f)
    try:
        r = render("someone/moadix", f.name)
    finally:
        os.unlink(f.name)
    check("negative control: a template allowing a second marketplace is refused",
          r.returncode != 0 and "exactly" in r.stderr, r.stderr.strip())

    r = render("bad repo;rm")
    check("a malformed owner/repo is refused", r.returncode != 0 and "bad repo" in r.stderr, r.stderr.strip())

    print("\n%d checks, %d passed, %d failed" % (len(RESULTS), sum(RESULTS), len(RESULTS) - sum(RESULTS)))
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
