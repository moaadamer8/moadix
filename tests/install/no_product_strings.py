#!/usr/bin/python3
"""Before a push: no product-specific string in the commits about to be pushed. Terminal, from ~/moadix:

    /usr/bin/python3 tests/install/no_product_strings.py [<range>]

<range> defaults to origin/master..HEAD (what `git push origin master` would send). It reads the strings that
belong to your machine and products, never to this repository:
  * every protected Firebase project id and extra network host in the local overlay
    (~/.config/moadix/overlay.json, or $MOADIX_OVERLAY);
  * your home folder's absolute path and your user name in a path (/Users/<you>/);
  * each word in $MOADIX_PRIVATE_STRINGS (comma-separated), for anything else you keep private.

It scans the lines the range adds (`git log -p`), and also its commit messages. Last line:
  `no product-specific string in <range> (<n> commits, <m> strings checked)`   exit 0
or one line per hit and `<k> product-specific string(s) found in <range>`      exit 1
The overlay itself is read only by you, in Terminal; nothing is sent anywhere.
"""
import json
import os
import subprocess
import sys


def strings():
    out = set()
    path = os.environ.get("MOADIX_OVERLAY") or os.path.expanduser("~/.config/moadix/overlay.json")
    try:
        with open(path) as f:
            ov = json.load(f)
        out |= {str(x) for x in ov.get("protected_firebase_projects") or []}
        out |= {str(h)[2:] if str(h).startswith("*.") else str(h) for h in ov.get("extra_network_hosts") or []}
    except (OSError, ValueError):
        pass
    home = os.path.expanduser("~")
    out.add(home + "/")
    out |= {s.strip() for s in (os.environ.get("MOADIX_PRIVATE_STRINGS") or "").split(",") if s.strip()}
    return sorted(s for s in out if len(s) >= 4)


def main(argv):
    rng = argv[0] if argv else "origin/master..HEAD"
    p = subprocess.run(["/usr/bin/git", "log", "-p", "--no-color", "--format=commit %H%n%B", rng],
                       capture_output=True, text=True)
    if p.returncode != 0:
        print("could not read %s: %s" % (rng, p.stderr.strip()[:300]))
        return 2
    n = subprocess.run(["/usr/bin/git", "rev-list", "--count", rng], capture_output=True, text=True).stdout.strip()
    words = strings()
    hits, commit = [], "?"
    for line in p.stdout.splitlines():
        if line.startswith("commit "):
            commit = line[7:19]
        added = line.startswith("+") and not line.startswith("+++")
        message = not line.startswith(("+", "-", " ", "@@", "diff ", "index ", "---", "new file", "deleted file",
                                       "similarity", "rename", "Binary"))
        if not (added or message):
            continue
        for w in words:
            if w in line:
                hits.append("%s: %r in %s" % (commit, w, line.strip()[:160]))
    for h in hits:
        print("FOUND  %s" % h)
    if hits:
        print("%d product-specific string(s) found in %s" % (len(hits), rng))
        return 1
    print("no product-specific string in %s (%s commits, %d strings checked)" % (rng, n or "0", len(words)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
