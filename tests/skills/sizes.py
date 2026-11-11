#!/usr/bin/python3
"""Refresh the skill sizes in gate/config/phase-manifest.yaml from the files.

    /usr/bin/python3 tests/skills/sizes.py          print the sizes
    /usr/bin/python3 tests/skills/sizes.py --write  rewrite skill_md_bytes / total_bytes in place

tests/skills/run.py fails when the manifest's sizes and the files disagree.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
MANIFEST = os.path.join(REPO, "gate", "config", "phase-manifest.yaml")


def sizes(name):
    d = os.path.join(REPO, "skills", name)
    total = sum(os.path.getsize(os.path.join(a, f)) for a, _x, fs in os.walk(d) for f in fs)
    return os.path.getsize(os.path.join(d, "SKILL.md")), total


def main():
    text = open(MANIFEST).read()

    def fix(m):
        md, tot = sizes(m.group(1))
        print("%-32s SKILL.md %7d B   directory %9d B" % (m.group(1), md, tot))
        return "  - name: %s\n    skill_md_bytes: %d\n    total_bytes: %d" % (m.group(1), md, tot)

    new = re.sub(r"  - name: (\S+)\n    skill_md_bytes: \d+\n    total_bytes: \d+", fix, text)
    if "--write" in sys.argv and new != text:
        with open(MANIFEST, "w") as f:
            f.write(new)
        print("phase-manifest.yaml updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
