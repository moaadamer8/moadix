#!/usr/bin/env python3
"""check-regression — Phase 10b validator: the committed regression suite.

Phase 10a proves a story worked once, in a browser someone was watching. Phase
10b is what stops it silently breaking next month. The gate therefore asks two
questions a document cannot answer for itself:

  1. **Does every story that PASSED 10a have a committed spec?** Coverage is
     computed from the 10a report, not claimed. A story verified live and then
     left without a regression test is exactly the case that regresses.
  2. **Is every quarantined spec actually tracked?** Quarantine is the sanctioned
     alternative to skipping a flaky test; without a tracking id, an owner and a
     reason it is just a skip with better manners.

It also lints locator quality, because a spec built on brittle selectors is a
spec that will be quarantined next week: `page.mouse.click(x, y)`, `nth-child`
chains and long descendant CSS are flagged; `getByRole` / `getByTestId` /
`getByLabel` are what the skill asks for.

Exit 0 = pass, non-zero = fail.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

SPEC_EXT = (".spec.ts", ".spec.js", ".spec.mjs", ".test.ts")

BRITTLE = [
    ("absolute-coordinates", re.compile(r"\bmouse\.(click|move|dblclick)\s*\(\s*\d+\s*,\s*\d+")),
    ("click_at-coordinates", re.compile(r"\bclick_at\b")),
    ("nth-child selector", re.compile(r":nth-child\(")),
    ("deep descendant CSS", re.compile(r"""locator\(\s*['"][^'"]*(?:\s>\s|\s){3,}[^'"]*['"]""")),
    ("xpath", re.compile(r"""locator\(\s*['"]//""")),
]
STABLE = re.compile(r"getBy(Role|TestId|Label|Placeholder|Text|Title|AltText)\b")


def strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def live_verdicts(path):
    """{story_id: verdict} from the 10a report."""
    text = read(path)
    if text is None:
        return None
    text = strip_comments(text)
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+((?:US|NFR)-\d+)\b", line.strip())
        if m:
            cur = m.group(1)
            continue
        if cur:
            v = re.match(r"^\s*[-*]\s*\*\*Verdict:?\*\*\s*(\S+)", line, re.I)
            if v:
                out[cur] = v.group(1).strip().upper()
                cur = None
    return out


def collect_specs(e2e_dir):
    out = {}
    if not os.path.isdir(e2e_dir):
        return out
    for dirpath, dirnames, filenames in os.walk(e2e_dir):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git")]
        for fn in sorted(filenames):
            if fn.endswith(SPEC_EXT):
                p = os.path.join(dirpath, fn)
                out[p] = read(p) or ""
    return out


def main():
    ap = argparse.ArgumentParser(prog="check-regression.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--e2e", default=None, help="e2e directory (default <governed_root>/e2e)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    d = args.dir or os.path.join(root, groot, "sdlc")
    e2e = args.e2e or os.path.join(root, groot, "e2e")

    errs, warns, notes = [], [], []

    # ---- 1. every 10a-PASSED story has a committed spec ------------------
    verdicts = live_verdicts(os.path.join(d, "10a-live-verification.md"))
    if verdicts is None:
        errs.append("no 10a report at %s/10a-live-verification.md; cannot know which stories "
                    "passed live verification." % d)
        verdicts = {}
    passed = sorted(s for s, v in verdicts.items() if v == "PASS")
    notes.append("10a verdicts: %d (%d PASS)" % (len(verdicts), len(passed)))

    specs = collect_specs(e2e)
    if not specs:
        errs.append("no Playwright specs found under %s. Phase 10b commits the regression suite; "
                    "an empty e2e/ directory is not one." % e2e)
    else:
        notes.append("specs: %d file(s)" % len(specs))

    covered = {}
    for path, body in specs.items():
        for sid in set(re.findall(r"\b((?:US|NFR)[-_]\d+)\b", body)):
            covered.setdefault(sid.upper().replace("_", "-"), []).append(path)

    for sid in passed:
        if sid not in covered:
            errs.append("story %s PASSED live verification but has no committed spec naming it. "
                        "A story verified once and never regression-tested is the case that "
                        "regresses." % sid)
    for sid, v in sorted(verdicts.items()):
        if v != "PASS" and sid in covered:
            warns.append("%s is %s in 10a but has a spec; make sure it is quarantined or "
                         "expected-to-fail." % (sid, v))

    # ---- 2. quarantine tracking ------------------------------------------
    qpath = os.path.join(e2e, "quarantine.yaml")
    tracked = {}
    if os.path.exists(qpath):
        try:
            qdoc = hlib.load_yaml(qpath) or {}
        except Exception as exc:
            errs.append("e2e/quarantine.yaml does not parse (%r)" % (exc,))
            qdoc = {}
        for item in (qdoc.get("quarantined") or []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("test") or item.get("spec") or "")
            missing = [f for f in ("tracking_id", "reason", "owner")
                       if not str(item.get(f) or "").strip()]
            if missing:
                errs.append("quarantine entry %r is missing %s. Quarantine without a tracking id, "
                            "a reason and an owner is a skip with better manners."
                            % (key or "(unnamed)", ", ".join(missing)))
            if key:
                tracked[key] = item

    # every @quarantine tag in a spec must have a tracking entry
    q_in_specs = 0
    for path, body in specs.items():
        for m in re.finditer(r"^.*@quarantine.*$", body, re.M):
            line = m.group(0)
            q_in_specs += 1
            title = None
            t = re.search(r"""['"`]([^'"`]*@quarantine[^'"`]*)['"`]""", line)
            if t:
                title = t.group(1)
            rel = os.path.relpath(path, root)
            hit = False
            for key, _item in tracked.items():
                if (title and key in title) or key == rel or (title and title in key):
                    hit = True
                    break
            if not hit:
                errs.append("%s tags a spec @quarantine but no matching entry exists in "
                            "e2e/quarantine.yaml: %s" % (rel, (title or line.strip())[:70]))
    if tracked or q_in_specs:
        notes.append("quarantine: %d tagged in specs, %d tracked" % (q_in_specs, len(tracked)))

    # a tracked entry whose spec no longer tags @quarantine is stale
    for key, _item in tracked.items():
        found = any("@quarantine" in body and (key in body or key in os.path.relpath(p, root))
                    for p, body in specs.items())
        if not found:
            warns.append("quarantine entry %r has no matching @quarantine tag in any spec "
                         "(stale?)." % key)

    # ---- 3. locator quality ----------------------------------------------
    for path, body in specs.items():
        rel = os.path.relpath(path, root)
        for name, rx in BRITTLE:
            for m in rx.finditer(body):
                ln = body[:m.start()].count("\n") + 1
                errs.append("%s:%d uses a brittle locator (%s). Phase 10b requires stable "
                            "locators: getByRole / getByTestId / getByLabel." % (rel, ln, name))
        if not STABLE.search(body):
            warns.append("%s uses no getBy* locator at all; check it is not selector-based." % rel)

    if not args.quiet:
        print("check-regression: %s" % e2e)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  all %d live-verified story/stories have a committed spec; "
                  "quarantine fully tracked; locators stable." % len(passed))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
