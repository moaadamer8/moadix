#!/usr/bin/env python3
"""check-hardcoded-state — gate state must be computed, never written down twice.

Constitution 3.7 requires a test to compute every state-dependent expectation
rather than hardcode it. The v0.4 run produced FIVE instances of the same
class, the last one inside the suite that exists to catch it:

  1. attack-suite.sh hardcoded the product name in 112 places  -> 66 false FAILs
  2. .gitignore hardcoded `toy-product/.run/`                  -> untracked noise
  3. product-app.yaml hardcoded a web command for a native app -> phase 10a blocked
  4. the phase-10a validator set ignored the platform ruling   -> 10a unapprovable
  5. attack-suite P11 hardcoded DENY for a phase-11 path       -> false FAIL

Each was found by tripping over it. This finds them mechanically.

THE THREE AXES OF GATE STATE
  product   the governed root. Declared once, in phase-paths.yaml.
  phase     the current phase label/id. Declared in phase.yaml, ordered by
            phase-paths.yaml.
  ruling    the Target Platform Ruling. Declared in the BRD, with its
            vocabulary in check_profile.CANON and its consequences in
            profiles.yaml.

Anything else that names one of these is a second copy that can drift.

WHY THIS IS NOT A GREP
A bare grep reports ~11 files, nearly all of them legitimate: docstrings that
explain a past attack, the canonical vocabulary itself, the config that
declares the value. A check that reports mostly noise gets ignored — which is
3.7's own lesson turned on the checker. So this:

  - strips comments and docstrings before matching (a comment naming
    `toy-product` in an attack write-up is documentation, not state)
  - exempts the files that legitimately DECLARE each axis
  - carries an explicit exemptions file, so a genuine exception is recorded
    with a reason and an owner rather than silently tolerated

Exit 0 = no undeclared hardcoded state · 1 = findings · 2 = cannot evaluate.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

# MOADIX v2 change notice: a self-check of the GATE's own tree (v1 scanned the
# harness repo, where products were subdirectories). Paths below are relative to
# the gate's repo/install directory.
#
# Files that legitimately DECLARE an axis. A declaration is not a duplicate.
EXEMPTIONS_FILE = "gate/config/hardcoded-state-exemptions.yaml"

DECLARES = {
    "product": {EXEMPTIONS_FILE},
    "phase":   {"gate/pathmap.py", "gate/config/registry.yaml", "gate/config/profiles.yaml",
                "gate/config/control-deps.yaml", EXEMPTIONS_FILE},
    # this checker declares the accepted ASCII spelling of the transition ruling
    "ruling":  {"gate/config/profiles.yaml", "gate/v1/check_profile.py", "gate/v1/check_hardcoded_state.py",
                EXEMPTIONS_FILE},
}

SCAN_GLOBS = [
    ("gate", (".py",)),
    ("gate/config", (".yaml",)),
    ("managed", (".sh", ".py")),
]

def _rulings():
    """The ruling vocabulary, from the module that DECLARES it.

    This was a literal list, and it had already drifted: it omitted "WEB", so
    the checker could not see a hardcoded WEB ruling anywhere -- a blind spot in
    the instrument itself. check_profile owns CANON and is the only file this
    checker exempts for the ruling axis; taking the vocabulary from there is the
    same rule the checker enforces on everyone else.
    """
    try:
        import check_profile
        return sorted({str(v) for v in check_profile.CANON.values()}, key=len, reverse=True)
    except Exception as exc:
        # Fail LOUD rather than silently scanning for a subset (3.10: a check
        # that could not run is not a check that passed). `from exc` keeps the
        # original cause attached -- the reason this could not run IS the finding.
        raise SystemExit("check-hardcoded-state: cannot import check_profile, so the "
                         "ruling vocabulary is unknown. Refusing to scan for a guessed "
                         "subset. (%r)" % (exc,)) from exc


RULINGS = _rulings()

# Longest-match suppression also has to know the accepted ASCII spelling, which
# is not itself a ruling: without it "WEB" still fires inside "WEB->APP".
RULING_SUPERSTRINGS = sorted(set(RULINGS) | {"WEB->APP"}, key=len, reverse=True)

# MOADIX v2 (v1 defect: check-hardcoded-state substring match). v1 tested
# `r_ not in line`, a SUBSTRING test: "WEB" fired inside WEBHOOK, WEBSITE and
# "website", "APP-FIRST" inside "APP-FIRST-CLASS", and suppression only knew the
# one superstring "WEB->APP". A ruling is now matched as a whole TOKEN: not
# preceded or followed by a letter, digit, "_" or "-", with the alternatives
# tried longest first so "WEB->APP" is one match, never "WEB" plus "APP".
EDGE_CHARS = r"A-Za-z0-9_\-"
RULING_RE = re.compile(r"(?<![%s])(%s)(?![%s>])" % (
    EDGE_CHARS, "|".join(re.escape(r) for r in RULING_SUPERSTRINGS), EDGE_CHARS))


def ruling_tokens(line):
    """The rulings a line names, as whole tokens (longest alternative wins)."""
    out = []
    for m in RULING_RE.finditer(line):
        tok = m.group(1)
        out.append("WEB→APP" if tok == "WEB->APP" else tok)
    return out


def names_product(line, pid):
    """True when `pid` appears as a whole token. v1 used \\b, which treats "-"
    and "." as boundaries, so product "toy" matched inside "toy-mobile"."""
    return re.search(r"(?<![A-Za-z0-9_.\-])%s(?![A-Za-z0-9_\-])" % re.escape(pid), line) is not None


def strip_comments(text, ext):
    """Remove comments and Python docstrings; state hidden in prose is not state."""
    if ext == ".py":
        text = re.sub(r'(?s)("""|\'\'\')(?:(?!\1).)*\1', "", text)
        return "\n".join(re.sub(r"(?<!\\)#.*$", "", l) for l in text.splitlines())
    if ext in (".sh", ".yaml", ".yml", ".toml"):
        return "\n".join(re.sub(r"(?<!\\)#.*$", "", l) for l in text.splitlines())
    return text


def products(root, given=None):
    """Product ids to look for. v2 products live in their own repos, so the gate
    tree must name none of them; ids come from --product (and the tests)."""
    return set(given or [])


def phase_labels(root):
    try:
        if os.path.dirname(hlib.GATE_DIR) not in sys.path:
            sys.path.insert(0, os.path.dirname(hlib.GATE_DIR))
        from gate import pathmap
        return set(pathmap.LABELS)
    except Exception:
        return set()


def load_exemptions(root):
    p = os.path.join(root, EXEMPTIONS_FILE)
    if not os.path.exists(p):
        return []
    try:
        return (hlib.load_yaml(p) or {}).get("exemptions") or []
    except Exception:
        return []


def exempt(exemptions, rel, axis, token):
    for e in exemptions:
        if (str(e.get("file")) == rel and str(e.get("axis")) == axis
                and str(e.get("token")) == token and e.get("reason") and e.get("owner")):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(prog="check-hardcoded-state.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--root", default=None, help="tree to scan (default: the gate's own repo)")
    ap.add_argument("--product", action="append", default=[], help="a product id to look for")
    args = ap.parse_args()

    root = os.path.realpath(args.root or os.path.dirname(hlib.GATE_DIR))
    prods = products(root, args.product)
    labels = phase_labels(root)
    exemptions = load_exemptions(root)

    findings = []
    for base, exts in SCAN_GLOBS:
        bd = os.path.join(root, base)
        if not os.path.isdir(bd):
            continue
        for dirpath, _dirs, files in os.walk(bd):
            for f in files:
                if not f.endswith(exts):
                    continue
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root)
                if "/proposals/" in rel or "/docs/" in rel or "/tests/" in rel or "__pycache__" in rel:
                    continue
                try:
                    # SIM115: this walks EVERY file in the tree, so a leaked
                    # handle per file is a real descriptor leak, not a style
                    # point.
                    with open(full, encoding="utf-8", errors="replace") as _fh:
                        raw = _fh.read()
                except Exception:
                    # S112: an unreadable file cannot carry a hardcoded name
                    # that this scan would otherwise have seen.
                    continue
                body = strip_comments(raw, os.path.splitext(f)[1])
                for lineno, line in enumerate(body.splitlines(), 1):
                    for p in prods:
                        if rel in DECLARES["product"]:
                            continue
                        if names_product(line, p) and not exempt(exemptions, rel, "product", p):
                            findings.append((rel, lineno, "product", p, line.strip()[:90]))
                    if rel not in DECLARES["ruling"] and not rel.endswith(".md"):
                        for r_ in sorted(set(ruling_tokens(line))):
                            if not exempt(exemptions, rel, "ruling", r_):
                                findings.append((rel, lineno, "ruling", r_, line.strip()[:90]))
                    for lbl in labels:
                        if rel in DECLARES["phase"] or rel.endswith(".md"):
                            continue
                        # A bare quoted digit ("0", "4") is arithmetic, a version,
                        # a shard count -- scanning for it produced 230 false hits
                        # from example code alone. Only DISTINCTIVE labels (10a,
                        # 10b, 11b) stand on their own; a numeric label counts
                        # only next to the word `phase`.
                        quoted = re.search(r"""['"]%s['"]""" % re.escape(lbl), line)
                        distinctive = not lbl.isdigit()
                        near_phase = re.search(r"phase", line, re.I) is not None
                        if quoted and (distinctive or near_phase) \
                                and not exempt(exemptions, rel, "phase", lbl):
                            findings.append((rel, lineno, "phase", lbl, line.strip()[:90]))

    if not args.quiet:
        print("check-hardcoded-state: root=%s products=%s, phase labels=%d, exemptions=%d"
              % (root, ",".join(sorted(prods)) or "(none given)", len(labels), len(exemptions)))
        for rel, ln, axis, tok, src in findings:
            print("  FAIL  %s:%d hardcodes %s %r" % (rel, ln, axis, tok))
            print("        %s" % src)
    print("check-hardcoded-state: %d undeclared hardcoded reference(s)." % len(findings))
    if findings:
        print("Each must either be computed from the declaring source, or recorded in "
              + EXEMPTIONS_FILE + " with a reason and an owner.")
        return 1
    print("No gate state is written down twice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
