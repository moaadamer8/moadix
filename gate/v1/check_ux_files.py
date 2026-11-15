#!/usr/bin/env python3
"""check-ux-files -- phase 6 design checks run by the gate (increment 7b; Amendment 3 phase 6).

Reads committed files only (no tool, no product code):

  design/tokens.json         W3C Design Tokens (DTCG) format: groups and tokens ($value, $type
                             on the token or inherited from a group), known types, colour
                             and dimension values well formed, every alias {a.b} resolving,
                             no alias cycle (U12)
  design/contrast.csv        foreground,background,usage: each a token path (or a hex colour),
                             usage body | large | ui. The gate computes the WCAG 2 contrast
                             ratio itself: body text at least 4.5:1, large text and UI at
                             least 3:1, and at least one body pair (U6, U12)
  design/screen-states.csv   screen,state,status,reference: every screen the PRD lists (P5)
                             appears; each screen has default, loading, empty and error
                             (U15), each designed (a reference that exists at HEAD) or n/a
                             with a reason (U4). An optional `url` column (an app-relative path)
                             tells the axe gate where the screen is (increment 7d, ruling 4)
  design/component-states.csv  component,state,status,reference: the component x state
                             inventory (U13), same rules; phase 10a's LV-INVENTORY.csv must
                             cover every designed row of both files

Exit 0 pass, 1 fail, 2 UNKNOWN (state unreadable).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import readonly  # noqa: E402
import toolrun  # noqa: E402

TOKENS = "design/tokens.json"
CONTRAST = "design/contrast.csv"
SCREENS = "design/screen-states.csv"
COMPONENTS = "design/component-states.csv"
TYPES = {"color", "dimension", "fontFamily", "fontWeight", "duration", "cubicBezier", "number", "strokeStyle",
         "border", "transition", "shadow", "gradient", "typography"}
SYSTEM_STATES = ("default", "loading", "empty", "error")
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
DIM = re.compile(r"^-?\d+(?:\.\d+)?(?:px|rem)$")
ALIAS = re.compile(r"^\{([^{}]+)\}$")
MIN = {"body": 4.5, "large": 3.0, "ui": 3.0}


# ---------------------------------------------------------------- tokens
def walk_tokens(node, path, inherited, out, errs):
    if not isinstance(node, dict):
        errs.append("%s: a group or token must be a JSON object" % (".".join(path) or "(root)"))
        return
    typ = node.get("$type", inherited)
    if "$value" in node:
        out[".".join(path)] = {"type": typ, "value": node["$value"]}
        return
    for k, v in node.items():
        if k.startswith("$"):
            continue
        if any(c in k for c in "{}.") or not k:
            errs.append("%s: token or group name %r may not contain {, } or ." % (".".join(path) or "(root)", k))
            continue
        walk_tokens(v, path + [k], typ, out, errs)


def resolve(tokens, name, seen=()):
    t = tokens.get(name)
    if t is None:
        return None, "alias {%s} resolves to no token" % name
    if name in seen:
        return None, "alias cycle through {%s}" % name
    v = t["value"]
    m = ALIAS.match(v) if isinstance(v, str) else None
    if m:
        return resolve(tokens, m.group(1), seen + (name,))
    return t, None


def color_hex(v):
    if isinstance(v, str) and HEX.match(v):
        return v
    if isinstance(v, dict) and v.get("colorSpace") == "srgb" and isinstance(v.get("components"), list):
        try:
            return "#" + "".join("%02x" % round(float(c) * 255) for c in v["components"][:3])
        except (TypeError, ValueError):
            return None
    if isinstance(v, dict) and isinstance(v.get("hex"), str) and HEX.match(v["hex"]):
        return v["hex"]
    return None


def check_tokens(root, errs, notes):
    p = os.path.join(root, TOKENS)
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
    except OSError:
        errs.append("%s is missing (U12: tokens in W3C DTCG format)" % TOKENS)
        return {}
    except ValueError as e:
        errs.append("%s is not JSON: %s" % (TOKENS, e))
        return {}
    tokens, bad = {}, []
    walk_tokens(doc, [], None, tokens, bad)
    errs += ["%s: %s" % (TOKENS, b) for b in bad]
    if not tokens:
        errs.append("%s defines no token" % TOKENS)
    for name, t in sorted(tokens.items()):
        v = t["value"]
        if isinstance(v, str) and ALIAS.match(v):
            r, why = resolve(tokens, name)
            if why:
                errs.append("%s: %s: %s" % (TOKENS, name, why))
                continue
            if t["type"] is None:
                t["type"] = r["type"]
            continue
        if t["type"] not in TYPES:
            errs.append("%s: %s has no valid $type (got %r; one of %s)" % (TOKENS, name, t["type"], ", ".join(sorted(TYPES))))
        elif t["type"] == "color" and color_hex(v) is None:
            errs.append("%s: %s colour value %r is not #rgb/#rrggbb/#rrggbbaa or an sRGB object" % (TOKENS, name, v))
        elif t["type"] == "dimension" and not ((isinstance(v, str) and DIM.match(v)) or (
                isinstance(v, dict) and isinstance(v.get("value"), (int, float)) and v.get("unit") in ("px", "rem"))):
            errs.append("%s: %s dimension value %r is not a number with px or rem" % (TOKENS, name, v))
    notes.append("%s: %d token(s)" % (TOKENS, len(tokens)))
    return tokens


# ---------------------------------------------------------------- contrast
def luminance(hexv):
    h = hexv.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def colour_of(tokens, ref):
    ref = ref.strip()
    if HEX.match(ref):
        return ref, None
    m = ALIAS.match(ref)
    name = m.group(1) if m else ref
    t, why = resolve(tokens, name)
    if why:
        return None, why
    hx = color_hex(t["value"])
    return (hx, None) if hx else (None, "%s is not a colour token" % name)


def check_contrast(root, tokens, errs, notes):
    rows, probs = readonly.read_csv(os.path.join(root, CONTRAST), ["foreground", "background", "usage"])
    if rows is None:
        errs.append("%s is missing (the gate's contrast check needs the colour pairs the UI uses)" % CONTRAST)
        return
    errs += probs
    body = 0
    for r in rows:
        where = "%s line %d" % (CONTRAST, r["_line"])
        use = r["usage"].lower()
        if use not in MIN:
            errs.append("%s: usage %r is not body, large or ui" % (where, r["usage"]))
            continue
        fg, w1 = colour_of(tokens, r["foreground"])
        bg, w2 = colour_of(tokens, r["background"])
        if w1 or w2:
            errs.append("%s: %s" % (where, w1 or w2))
            continue
        q = ratio(fg, bg)
        body += use == "body"
        if q + 1e-9 < MIN[use]:
            errs.append("%s: %s on %s is %.2f:1, below %.1f:1 for %s text (WCAG 2.2 AA)" % (
                where, r["foreground"], r["background"], q, MIN[use], use))
        else:
            notes.append("%s: %s on %s %.2f:1 (%s)" % (where, r["foreground"], r["background"], q, use))
    if rows and not body:
        errs.append("%s has no body-text pair; body text must be checked at 4.5:1" % CONTRAST)


# ---------------------------------------------------------------- state inventories
def prd_screens(root):
    """Screen names the PRD lists for P5 (every screen state): the first column of the table (or the
    bold lead of each list item) in the section phase 2's COVERAGE.md anchors for P5."""
    sys.path.insert(0, os.path.dirname(toolrun.GATE))
    from gate import contract
    feature = os.environ.get("MOADIX_FEATURE") or None
    st = {"feature": feature, "current_phase": "2"}
    ents = contract.coverage_entries(root, st, "2") or {}
    e = ents.get("P5")
    if not e or e["na"] is not None or not e["sections"]:
        return None
    out = []
    for ln in e["sections"][0][1][3].splitlines():
        s = ln.strip()
        m = re.match(r"^\|\s*\**([^|*]+?)\**\s*\|", s)
        if m and not re.match(r"^\|[\s:|-]+\|?$", s):
            out.append(m.group(1).strip())
            continue
        m = re.match(r"^[-*]\s+\*\*([^*]+)\*\*", s)
        if m:
            out.append(m.group(1).strip().rstrip(":"))
    if out and out[0].lower() in ("screen", "screens", "name"):
        out = out[1:]
    return out


def check_states(root, rel, key, required, errs, notes):
    rows, probs = readonly.read_csv(os.path.join(root, rel), [key, "state", "status", "reference"])
    if rows is None:
        errs.append("%s is missing" % rel)
        return []
    errs += probs
    seen = {}
    for r in rows:
        where = "%s line %d" % (rel, r["_line"])
        name, stt, status, ref = r[key], r["state"].lower(), r["status"].lower(), r["reference"]
        if not name or not stt:
            errs.append("%s: %s and state are required" % (where, key))
            continue
        if (name.lower(), stt) in seen:
            errs.append("%s: %s / %s is listed twice" % (where, name, stt))
        seen[(name.lower(), stt)] = r
        if status == "designed":
            path = ref.split("#", 1)[0]
            if not path or not readonly.tracked_at_head(root, path):
                errs.append("%s: %s / %s is designed but its reference %r is not a file at HEAD" % (where, name, stt, ref))
        elif status == "n/a":
            if len(re.findall(r"[A-Za-z]{2,}", ref)) < 4:
                errs.append("%s: %s / %s is n/a without a reason in reference" % (where, name, stt))
        else:
            errs.append("%s: status %r is not designed or n/a" % (where, r["status"]))
    names = {n for n, _s in seen}
    for n in sorted(names):
        for s in required:
            if (n, s) not in seen:
                errs.append("%s: %s has no %s state (each needs %s, designed or n/a with a reason)" % (
                    rel, n, s, ", ".join(required)))
    notes.append("%s: %d row(s), %d %s(s)" % (rel, len(rows), len(names), key))
    return rows


def main():
    root = hlib.project_root()
    notes, errs, unknown = [], [], []
    try:
        tokens = check_tokens(root, errs, notes)
        check_contrast(root, tokens, errs, notes)
        rows = check_states(root, SCREENS, "screen", SYSTEM_STATES, errs, notes)
        check_states(root, COMPONENTS, "component", (), errs, notes)
        screens = prd_screens(root)
        if screens is None:
            notes.append("the PRD's P5 section is not anchored in sdlc/2/COVERAGE.md, so screens are not cross-checked")
        else:
            have = {r["screen"].lower() for r in rows}
            for s in screens:
                if s.lower() not in have:
                    errs.append("%s does not cover PRD screen %r (P5)" % (SCREENS, s))
            notes.append("PRD screens (P5): %d, all checked against %s" % (len(screens), SCREENS))
    except Exception as e:  # unknown, never a pass
        unknown.append("%s: %s" % (type(e).__name__, e))
    return toolrun.report("check-ux-files (phase 6: DTCG tokens, WCAG contrast, screen and component states)",
                          notes, [], errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
