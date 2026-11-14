#!/usr/bin/python3
"""managed/render_policy.py: the repo is its own marketplace, and the policy allows exactly it.

    /usr/bin/python3 tests/install/render.py

No sudo, no Keychain. Checks the rendered policy with and without --plugin, that
.claude-plugin/marketplace.json names the plugin the policy force-enables, and
that a template allowing a second marketplace is refused.
"""
import hashlib
import json
import os
import re
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


def render(repo, tpl=TPL, extra=()):
    return subprocess.run(["/usr/bin/python3", "-I", RENDER, tpl, "/cc", "/cc/moadix", PIN, repo] + list(extra),
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
    check("increment 5 network allowlist entries are present",
          all(h in net for h in added), "%d hosts" % len(net))
    # 0.5.2: nothing product-specific in the public template; product hosts come from the local overlay
    # the nine product hosts of the operator's change request, by sha256 only: their names are in no commit
    product = {"d54755c56acce1e90e5ba416b055729afb42c0fd35ac4bddf19d4bdb980b2091",
               "ad845a6da981f0bab6de66eb228d73ab0a888ac0e29a18066ad6a5d8ba08cd24",
               "d5262348a6d615eaf76a08b33739590455633e460f4036354caae3e20de00b31",
               "f2cc2568d6a2453d32de5e08653006c31f1162ddb14b3df7ce72c41be15f5e19",
               "4f101f892e0c383624859e286fb2fe1d8655408dcb4d85072f03ef309b91f15d",
               "bdf8e8a474fc15ffb91ec8fe0a1e3ae3805bae62a238224265dcb90ff8f8dcc4",
               "b2cec97c4ab2309797bf15de3b70179fdb4f4e1d51e1b3551a431cafa587fb4f",
               "85b8a1106aec59e06b2ba33a5d5eb87964264f39efab0cf984a5e3f5993b33d0",
               "5976c1f96d72b8322e98c72f292fd2363332b3a080cef34f878fc6877260ab4f"}
    raw = open(TPL).read()
    check("the public template carries no product host and no Firebase project id (they belong in the local overlay)",
          not [t for t in re.findall(r'"([^"]+)"', raw) if hashlib.sha256(t.encode()).hexdigest() in product] and not re.search(r"firebase\*[a-z0-9-]+-[a-z0-9]{4,}\*", raw)
          and len(net) == 12 + len(added) and len(set(net)) == len(net), "%d hosts" % len(net))
    check("no allowlist entry is a bare wildcard or a whole TLD (e.g. '*', '*.com', '*.googleapis.com')",
          not any(h == "*" or re.match(r"^\*\.[^.]+$", h) or h == "*.googleapis.com" for h in net), str(net))
    check("every allowlist entry is a plain host name string (no scheme, link or path)",
          all(isinstance(h, str) and re.match(r"^(\*\.)?[a-z0-9.-]+\.[a-z]{2,}$", h) for h in net), str(net))
    sb = pol.get("sandbox", {})
    check("excludedCommands are exactly docker, playwright (2 forms), gh, firebase",
          sb.get("excludedCommands") == ["docker *", "npx playwright *", "playwright *", "gh *", "firebase *"],
          json.dumps(sb.get("excludedCommands")))
    check("the sandbox still has no escape hatch (allowUnsandboxedCommands false, failIfUnavailable true)",
          sb.get("enabled") is True and sb.get("allowUnsandboxedCommands") is False and sb.get("failIfUnavailable") is True,
          "enabled=%r allowUnsandboxed=%r failIfUnavailable=%r" % (
              sb.get("enabled"), sb.get("allowUnsandboxedCommands"), sb.get("failIfUnavailable")))
    deny = (pol.get("permissions") or {}).get("deny") or []
    guards = ["Bash(git push*main*)", "Bash(git push*HEAD:main*)", "Bash(git push --all*)", "Bash(git push --mirror*)",
              "Bash(gh pr merge*)", "Bash(vercel promote*)", "Bash(vercel --prod*)", "Bash(vercel deploy --prod*)",
              # operator decisions 1 and 2: gh and firebase run unsandboxed, with these held back
              "Bash(gh auth token*)", "Bash(gh api*merge*)", "Bash(gh api*-X PUT*)", "Bash(gh api*--method PUT*)",
              "Bash(gh api*-X PATCH*refs*)", "Bash(gh api*--method PATCH*refs*)",
              "Bash(firebase*firestore:delete*)"]
    check("managed deny carries the project guards (main pushes, gh pr merge, vercel prod, gh token and merge "
          "API writes, the production Firebase project, firestore:delete) that "
          "allowManagedPermissionRulesOnly would otherwise drop", all(g in deny for g in guards),
          "missing %s" % [g for g in guards if g not in deny])
    earlier = ["CronCreate", "Bash(sudo *)", "Bash(claude *)", "Bash(security *)", "Read(~/.claude/projects/**)"]
    creds = ["Read(~/.config/gh/**)", "Read(~/.config/configstore/**)"]  # 0.5.2: the CLIs' stored credentials
    check("the agent cannot read gh's or firebase's stored credentials (Read tool and sandbox denyRead)",
          all(c in deny for c in creds) and {"~/.config/gh", "~/.config/configstore"} <=
          set(pol.get("sandbox", {}).get("filesystem", {}).get("denyRead") or []), str(creds))
    check("the earlier deny rules are all still there", all(g in deny for g in earlier) and
          len(deny) == 12 + len(guards) + len(creds),
          "%d rules" % len(deny))
    check("allowManagedHooksOnly and allowManagedPermissionRulesOnly are still on",
          pol.get("allowManagedHooksOnly") is True and pol.get("allowManagedPermissionRulesOnly") is True,
          "hooks=%r rules=%r" % (pol.get("allowManagedHooksOnly"), pol.get("allowManagedPermissionRulesOnly")))

    # the local overlay (0.5.2)
    d = tempfile.mkdtemp()
    ov, out = os.path.join(d, "overlay.json"), os.path.join(d, "overlay-out.json")
    with open(ov, "w") as f:
        json.dump({"version": 1, "protected_firebase_projects": ["prod-proj-1"],
                   "extra_network_hosts": ["api.example.com", "*.example.org"]}, f)
    r = render("someone/moadix", extra=["--overlay", ov, "--overlay-out", out])
    pol2 = json.loads(r.stdout) if r.returncode == 0 else {}
    net2 = pol2.get("sandbox", {}).get("network", {}).get("allowedDomains", [])
    deny2 = (pol2.get("permissions") or {}).get("deny") or []
    gout = json.load(open(out)) if os.path.exists(out) else {}
    check("a local overlay merges: its hosts join the allowlist, each protected project gets a deny rule, and the "
          "gate's copy lists the protected projects", r.returncode == 0 and "api.example.com" in net2 and
          "*.example.org" in net2 and "Bash(firebase*prod-proj-1*)" in deny2 and
          gout.get("protected_firebase_projects") == ["prod-proj-1"], r.stderr.strip() or str(gout))
    r = render("someone/moadix", extra=["--overlay", os.path.join(d, "absent.json"), "--overlay-out", out])
    check("no overlay file: the policy renders without one and the gate's copy protects nothing",
          r.returncode == 0 and json.load(open(out)).get("protected_firebase_projects") == [], r.stderr.strip())
    for bad, why in (({"version": 1, "extra_network_hosts": ["[api.example.com](http://api.example.com)"]}, "plain host"),
                     ({"version": 1, "extra_network_hosts": ["https://api.example.com"]}, "plain host"),
                     ({"version": 1, "extra_network_hosts": ["*.com"]}, "plain host"),
                     ({"version": 1, "extra_network_hosts": ["*.googleapis"]}, "plain host"),
                     ({"version": 1, "protected_firebase_projects": ["Prod Project"]}, "Firebase project ids"),
                     ({"version": 1, "allowUnsandboxedCommands": True}, "may not set"),
                     ({"extra_network_hosts": []}, "version")):
        with open(ov, "w") as f:
            json.dump(bad, f)
        r = render("someone/moadix", extra=["--overlay", ov, "--overlay-out", out])
        check("a malformed overlay is refused: %s" % json.dumps(bad)[:70], r.returncode != 0 and why in r.stderr,
              r.stderr.strip())

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
