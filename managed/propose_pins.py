#!/usr/bin/python3
"""Propose tool-pin bumps for operator review (increment 7; Amendment 3 section 5).

    /usr/bin/python3 managed/propose_pins.py [--today YYYY-MM-DD] > proposal.md

Reads gate/config/tools.yaml and, for each pinned tool, asks its registry (npm, PyPI or
GitHub releases) for the newest release at least 14 days old. Prints a Markdown proposal:
current pin, candidate, release date. It changes nothing: a bump is a proposal the operator
reviews (DESIGN.md section 6), and the new checksums and lockfiles are produced when the
operator accepts it. The SessionStart hook reminds the operator when the pins' `reviewed`
date is more than 30 days old.
"""
import datetime
import json
import os
import re
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(REPO, "gate", "v1"))
import hlib  # noqa: E402

MIN_AGE_DAYS = 14
UA = {"User-Agent": "moadix-propose-pins/1", "Accept": "application/json"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 (fixed https registry URLs)
        return json.load(r)


def _date(s):
    return datetime.date.fromisoformat(str(s)[:10])


def npm(pkg, cutoff):
    doc = get("https://registry.npmjs.org/%s" % pkg.replace("/", "%2F"))
    times = doc.get("time") or {}
    ok = [(v, _date(t)) for v, t in times.items() if re.match(r"^\d+\.\d+\.\d+$", v) and _date(t) <= cutoff]
    return max(ok, key=lambda x: [int(p) for p in x[0].split(".")]) if ok else None


def pypi(pkg, cutoff):
    doc = get("https://pypi.org/pypi/%s/json" % pkg)
    ok = []
    for v, files in (doc.get("releases") or {}).items():
        if re.match(r"^\d+(\.\d+)*$", v) and files:
            d = min(_date(f["upload_time"]) for f in files)
            if d <= cutoff:
                ok.append((v, d))
    return max(ok, key=lambda x: [int(p) for p in x[0].split(".")]) if ok else None


def github(repo, cutoff):
    rel = get("https://api.github.com/repos/%s/releases?per_page=30" % repo)
    ok = [(r["tag_name"].lstrip("v"), _date(r["published_at"])) for r in rel
          if not r.get("prerelease") and not r.get("draft") and _date(r["published_at"]) <= cutoff]
    return max(ok, key=lambda x: x[1]) if ok else None


def candidate(t, cutoff):
    kind = t.get("kind")
    if kind == "npm":
        return npm(str(t.get("package") or t["name"]), cutoff)
    if kind == "pypi":
        lock = os.path.join(REPO, str(t.get("lock")).replace("requirements.txt", "requirements.in"))
        pkg = str(t.get("package") or t["name"])
        if os.path.exists(lock):
            m = re.search(r"^([A-Za-z0-9_.-]+)==", open(lock).read(), re.M)
            pkg = m.group(1) if m else pkg
        return pypi(pkg, cutoff)
    url = str(((t.get("assets") or {}).get("linux-x64") or {}).get("url") or "")
    m = re.match(r"^https://github\.com/([^/]+/[^/]+)/releases/", url)
    return github(m.group(1), cutoff) if m else None


def main(argv):
    today = datetime.date.today()
    if len(argv) == 2 and argv[0] == "--today":
        today = datetime.date.fromisoformat(argv[1])
    cutoff = today - datetime.timedelta(days=MIN_AGE_DAYS)
    doc = hlib.load_yaml(os.path.join(REPO, "gate", "config", "tools.yaml")) or {}
    rows = []
    for t in doc.get("tools") or []:
        try:
            c = candidate(t, cutoff)
        except Exception as e:  # report, never guess
            rows.append((t["name"], str(t["version"]), "?", "could not ask the registry: %s" % type(e).__name__))
            continue
        if not c:
            rows.append((t["name"], str(t["version"]), "-", "no release older than %d days found" % MIN_AGE_DAYS))
        elif c[0] != str(t["version"]):
            rows.append((t["name"], str(t["version"]), c[0], "released %s: proposed" % c[1].isoformat()))
        else:
            rows.append((t["name"], str(t["version"]), c[0], "current"))
    print("# Tool pin proposal, %s\n" % today.isoformat())
    print("Pins last reviewed: %s. Candidates are the newest releases on or before %s (at least %d days old). "
          "Nothing changes until the operator accepts; the checksums, lockfiles and licence check are redone "
          "then.\n" % (doc.get("reviewed"), cutoff.isoformat(), MIN_AGE_DAYS))
    print("| Tool | Pinned | Candidate | Note |\n|---|---|---|---|")
    for r in rows:
        print("| %s | %s | %s | %s |" % r)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
