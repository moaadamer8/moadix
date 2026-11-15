"""Static check (ruling 3 on increment 7d): the confined runner, the executing gates and the engine suite
never carry a command that removes objects they did not create: no pruning of any kind (system, container,
volume, network, image, builder) and no compose "down" with volume removal. Removal is only ever by the
run's own label (gate/confined.py Run.close, Run._rm_own; the suite's own-label cleanup).

The patterns are assembled here so that this file, which is not one of the scanned files, names them.
"""
import os
import re

PRUNE = re.compile(r"\b" + "pru" + r"ne\b", re.I)
DOWN_V = re.compile(r"\b" + "do" + r"wn\b[^\n]{0,80}?(?:\s-[a-zA-Z]*v[a-zA-Z]*\b|--vol" + r"umes\b)", re.I)
RMI_ALL = re.compile(r"\brm" + r"i\b|\bimage\s+rm\b|\bvolume\s+rm\b[^\n]*\$\(|\bps\s+-a?q\b[^\n]*\|\s*xargs", re.I)

SCANNED = ("gate/confined.py", "gate/v1/check_exec.py", "gate/egress_proxy.py", "tests/confined-engine/run.py",
           "tests/lib/engine_double.py")


def scan(repo, files=SCANNED):
    """[(file, line no, text)] for every forbidden command; empty when clean."""
    hits = []
    for rel in files:
        with open(os.path.join(repo, rel), encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                for rx in (PRUNE, DOWN_V, RMI_ALL):
                    if rx.search(line):
                        hits.append((rel, n, line.strip()[:160]))
                        break
    return hits
