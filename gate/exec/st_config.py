"""Gate-owned (0.8.1, task-tracker MF-60): run inside the Schemathesis container, before Schemathesis.

    python st_config.py <openapi file> <out.toml> <statuses as JSON, e.g. [413]>

Writes Schemathesis's configuration: for every operation whose OpenAPI `responses` document one of the operator's
adopted refusal statuses, ST201 (negative_data_rejection) accepts that status as well as Schemathesis's own list. An
operation is selected by its exact name ("POST /tasks/{taskId}"): include-path and include-method together would match
any operation that has either. Every other operation keeps Schemathesis's own list. Prints one line per operation.
"""
import json
import sys

import yaml

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def default_statuses():
    try:
        from schemathesis.config._checks import NegativeDataRejectionConfig
        return [str(s) for s in NegativeDataRejectionConfig._DEFAULT_EXPECTED_STATUSES]
    except Exception:  # noqa: BLE001 (the pinned 4.32.7's list)
        return ["400", "401", "403", "404", "405", "406", "409", "415", "422", "428", "429", "5xx"]


def operations(spec, statuses):
    """[(name, [status, ...])] for every operation that documents one of statuses."""
    out = []
    for path, item in sorted(((spec or {}).get("paths") or {}).items()):
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if str(method).lower() not in METHODS or not isinstance(op, dict):
                continue
            documented = {str(k) for k in (op.get("responses") or {})}
            add = [str(s) for s in statuses if str(s) in documented]
            if add:
                out.append(("%s %s" % (str(method).upper(), path), add))
    return out


def toml(ops, default):
    lines = ["# written by the gate (gate/exec/st_config.py): the refusal statuses each operation's contract documents"]
    for name, add in ops:
        lines += ["", "[[operations]]", "include-name = %s" % json.dumps(name),
                  "checks.negative_data_rejection.expected-statuses = %s" % json.dumps(default + add)]
    return "\n".join(lines) + "\n"


def main(argv):
    spec_path, out_path, statuses = argv[0], argv[1], json.loads(argv[2])
    with open(spec_path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    ops = operations(spec, statuses)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(toml(ops, default_statuses()))
    for name, add in ops:
        print("gate: ST201 also accepts %s for %s (its contract documents it)" % (", ".join(add), name))
    if not ops:
        print("gate: no operation documents %s; Schemathesis's own refusal statuses apply" % ", ".join(map(str, statuses)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
