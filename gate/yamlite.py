"""Minimal YAML for gate-owned files (stdlib only; no PyYAML on stock macOS).

emit() writes block YAML for dicts, lists, str, int, bool and None.
parse_flat() reads `key: value` files such as product.yaml.
phase.yaml is never parsed: STATUS recomputes it from the ledger and
compares the emitted text byte for byte.
"""
import json
import re

_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def _scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if _PLAIN.match(s) and s not in ("null", "true", "false", "yes", "no", "on", "off"):
        return s
    return json.dumps(s)


def emit(obj, indent=0):
    pad = " " * indent
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append("%s%s:" % (pad, k))
                out.append(emit(v, indent + 2))
            elif isinstance(v, (dict, list)):
                out.append("%s%s: %s" % (pad, k, "{}" if isinstance(v, dict) else "[]"))
            else:
                out.append("%s%s: %s" % (pad, k, _scalar(v)))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item:
                body = emit(item, indent + 2).split("\n")
                out.append("%s- %s" % (pad, body[0].lstrip()))
                out.extend(body[1:])
            else:
                out.append("%s- %s" % (pad, _scalar(item)))
    return "\n".join(out)


def parse_flat(text):
    out = {}
    for line in text.splitlines():
        line = line.split(" #", 1)[0].rstrip()
        if not line or line.lstrip().startswith("#") or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith('"'):
            v = json.loads(v)
        elif v == "null":
            v = None
        elif re.match(r"^-?\d+$", v):
            v = int(v)
        out[k.strip()] = v
    return out
