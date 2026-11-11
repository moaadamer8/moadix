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
    off = {"source": "github", "repo": "anthropics/claude-plugins-official"}
    check("--plugin: strictKnownMarketplaces allows exactly this repo and anthropics/claude-plugins-official",
          pol.get("strictKnownMarketplaces") == [want, off], json.dumps(pol.get("strictKnownMarketplaces")))
    check("--plugin: both marketplaces registered (moadix, claude-plugins-official)",
          pol.get("extraKnownMarketplaces") == {"moadix": {"source": want}, "claude-plugins-official": {"source": off}},
          json.dumps(pol.get("extraKnownMarketplaces")))
    ep = pol.get("enabledPlugins") or {}
    on = sorted(k for k, v in ep.items() if v is True)
    check("increment 5 policy test: the rendered policy enables EXACTLY moadix and claude-security",
          on == ["claude-security@claude-plugins-official", "moadix@moadix"], "enabled: %s" % on)
    names = [ln.strip() for ln in open(os.path.join(REPO, "managed", "official-plugins.txt"))
             if ln.strip() and not ln.startswith("#")]
    off_keys = sorted(k for k, v in ep.items() if v is False)
    want_off = sorted("%s@claude-plugins-official" % n for n in names if n != "claude-security")
    check("every other plugin of the official marketplace is force-DISABLED (%d plugins)" % len(want_off),
          off_keys == want_off and all(k.endswith("@claude-plugins-official") for k in off_keys),
          "%d false entries, e.g. %s" % (len(off_keys), off_keys[:3]))
    check("no plugin from any other marketplace appears in enabledPlugins",
          all(k.split("@", 1)[1] in ("moadix", "claude-plugins-official") for k in ep), "%d entries" % len(ep))
    net = pol.get("sandbox", {}).get("network", {}).get("allowedDomains", [])
    added = ["release-assets.githubusercontent.com", "api.osv.dev", "api.deps.dev",
             "osv-vulnerabilities.storage.googleapis.com", "mirror.gcr.io", "ghcr.io",
             "pkg-containers.githubusercontent.com", "api.github.com"]
    check("increment 5 network allowlist entries are present, and nothing else was added",
          all(h in net for h in added) and len(net) == 12 + len(added), "%d hosts" % len(net))

    tpl = json.load(open(TPL))
    tpl["enabledPlugins"]["security-guidance@claude-plugins-official"] = True
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(tpl, f)
    try:
        r2 = render("someone/moadix", f.name)
    finally:
        os.unlink(f.name)
    check("negative control: a template enabling a third plugin from the official marketplace is refused",
          r2.returncode != 0 and "exactly" in r2.stderr, r2.stderr.strip())

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
