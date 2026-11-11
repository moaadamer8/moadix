#!/usr/bin/env python3
"""check-lld — Phase 5 validator: OpenAPI-first low-level design.

Runs under `uv run --with pyyaml --with openapi-spec-validator`, so the OpenAPI
document is checked by the real spec validator rather than by a hand-rolled
approximation. If those dependencies cannot be provisioned the script FAILS —
a validator that silently degrades to "looks fine" is worse than none.

Checks:
  1. sdlc/05-lld/openapi.yaml exists, parses as YAML, and is OpenAPI-schema-valid
  2. every local $ref resolves
  3. at least one path with at least one operation (an empty contract is not a contract)
  4. every PRD story ID (US-n / NFR-n) is covered by >= 1 module doc
  5. every SEC-ID whose Owner phase is 5 is addressed by >= 1 module doc
  6. every module doc carries 'Consumed by', 'Depends on', 'Covers stories'
     and 'Satisfies SEC-IDs' headers

Exit 0 = pass, non-zero = fail.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402


class DuplicateKeyError(ValueError):
    """A mapping repeats a key. YAML 1.2 requires unique keys; PyYAML silently keeps the last,
    which is how a contract with two '429' responses and two OpeningHours schemas passed this
    check while the product's parser refused it (AM-005, Increment 13 run 2)."""


def load_yaml_file(path):
    import yaml

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        seen = {}
        for key_node, _value in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise DuplicateKeyError(
                    "duplicate key %r at line %d (first at line %d)"
                    % (key, key_node.start_mark.line + 1, seen[key]))
            seen[key] = key_node.start_mark.line + 1
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    # MOADIX v2 (v1 defect: check-static S506 false positive). v1 called
    # `yaml.load(fh, Loader=UniqueKeyLoader)`. The loader IS safe (a SafeLoader
    # subclass), but ruff's S506 cannot see through the subclass and flagged it,
    # so the self-check failed on correct code. This is yaml.load's own body,
    # spelled out: same loader, same behaviour, and nothing for S506 to match.
    # No suppression was added.
    with open(path, "r", encoding="utf-8") as fh:
        loader = UniqueKeyLoader(fh)
        try:
            return loader.get_single_data()
        finally:
            loader.dispose()


def collect_refs(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                out.append(v)
            else:
                collect_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_refs(v, out)


def resolve_local_ref(doc, ref):
    if not ref.startswith("#/"):
        return True  # external refs are out of scope for this check
    node = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return True


def prd_story_ids(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        text = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    return sorted(set(re.findall(r"^#{2,4}\s+((?:US|NFR)-\d+)\b", text, re.M)))


def phase5_sec_ids(path):
    """SEC-IDs in the threat model whose Owner phase is 5."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s+(SEC-\d{3})\b", line.strip())
        if m:
            cur = m.group(1)
            continue
        if cur:
            m2 = re.match(r"^\s*[-*]\s*\*\*Owner phase:?\*\*\s*(\S+)", line, re.I)
            if m2 and m2.group(1).strip().rstrip(".") == "5":
                out.append(cur)
    return sorted(set(out))


def field(block, name):
    m = re.search(r"^\s*[-*]\s*\*\*%s:?\*\*\s*(.+?)\s*$" % re.escape(name), block, re.I | re.M)
    return m.group(1).strip() if m else None


def main():
    ap = argparse.ArgumentParser(prog="check-lld.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    d = args.dir
    if not d:
        try:
            groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
        except Exception:
            groot = ""
        d = os.path.join(root, groot, "sdlc")

    lld = os.path.join(d, "05-lld")
    errs, warns, notes = [], [], []

    # ---- 1-3. the OpenAPI contract ---------------------------------------
    spec_path = os.path.join(lld, "openapi.yaml")
    if not os.path.exists(spec_path):
        spec_path = os.path.join(lld, "openapi.json")
    doc = None
    if not os.path.exists(spec_path):
        errs.append("no OpenAPI contract at %s/openapi.yaml. Phase 5 is OpenAPI-FIRST: the contract "
                    "is authored before implementation, not derived from it." % lld)
    else:
        try:
            doc = load_yaml_file(spec_path)
        except Exception as exc:
            errs.append("OpenAPI document does not parse: %r" % (exc,))
        if doc is not None and not isinstance(doc, dict):
            errs.append("OpenAPI document is not a mapping at the top level.")
            doc = None
        if doc is not None:
            try:
                from openapi_spec_validator import validate as oas_validate
                oas_validate(doc)
                notes.append("OpenAPI %s is schema-valid (openapi-spec-validator)"
                             % doc.get("openapi", "?"))
            except ImportError:
                errs.append("openapi-spec-validator is unavailable; refusing to pass an unvalidated "
                            "contract. Run via harness/bin/check-lld.sh, which provisions it with uv.")
            except Exception as exc:
                first = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
                errs.append("OpenAPI schema validation FAILED: %s" % first[:300])

            paths = doc.get("paths") or {}
            ops = 0
            for _p, item in (paths.items() if isinstance(paths, dict) else []):
                if isinstance(item, dict):
                    ops += sum(1 for k in item
                               if k.lower() in ("get", "put", "post", "delete", "patch",
                                                "head", "options", "trace"))
            if ops == 0:
                errs.append("the OpenAPI contract declares no operations. An empty contract is not a "
                            "design.")
            else:
                notes.append("%d path(s), %d operation(s)" % (len(paths), ops))

            refs = []
            collect_refs(doc, refs)
            bad = sorted({r for r in refs if not resolve_local_ref(doc, r)})
            for r in bad:
                errs.append("unresolved $ref in the OpenAPI contract: %s" % r)

    # ---- module docs ------------------------------------------------------
    mod_dir = os.path.join(lld, "modules")
    mods = {}
    if os.path.isdir(mod_dir):
        for fn in sorted(os.listdir(mod_dir)):
            if fn.endswith(".md"):
                with open(os.path.join(mod_dir, fn), "r", encoding="utf-8") as fh:
                    mods[fn] = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    if not mods:
        errs.append("no module design docs found in %s. Expected one .md per module." % mod_dir)

    covered_stories, addressed_secs = set(), set()
    for fn, body in mods.items():
        for hdr in ("Consumed by", "Depends on", "Covers stories", "Satisfies SEC-IDs"):
            if field(body, hdr) is None:
                errs.append("%s: missing required header '**%s:**'." % (fn, hdr))
        cs = field(body, "Covers stories") or ""
        covered_stories.update(re.findall(r"\b(?:US|NFR)-\d+\b", cs))
        ss = field(body, "Satisfies SEC-IDs") or ""
        addressed_secs.update(re.findall(r"\bSEC-\d{3}\b", ss))

    # ---- 4. story coverage ------------------------------------------------
    stories = prd_story_ids(os.path.join(d, "02-prd.md"))
    if stories is None:
        errs.append("PRD not found at %s/02-prd.md; cannot verify story coverage." % d)
    elif not stories:
        warns.append("PRD contains no US-/NFR- story IDs; story coverage is vacuous.")
    else:
        missing = [s for s in stories if s not in covered_stories]
        for s in missing:
            errs.append("PRD story %s is not covered by any module design doc "
                        "('**Covers stories:**')." % s)
        notes.append("story coverage %d/%d" % (len(stories) - len(missing), len(stories)))

    # ---- 5. phase-5 SEC-IDs ----------------------------------------------
    secs = phase5_sec_ids(os.path.join(d, "04-threat-model.md"))
    if secs is None:
        errs.append("threat model not found at %s/04-threat-model.md; cannot verify SEC coverage." % d)
    else:
        missing = [s for s in secs if s not in addressed_secs]
        for s in missing:
            errs.append("%s is owned by phase 5 but no module doc lists it under "
                        "'**Satisfies SEC-IDs:**'." % s)
        notes.append("phase-5 SEC coverage %d/%d" % (len(secs) - len(missing), len(secs)))
        extra = sorted(addressed_secs - set(secs))
        if extra:
            warns.append("module docs claim SEC-IDs not owned by phase 5: %s (harmless, but check "
                         "the owner phase is right)" % extra)

    if not args.quiet:
        print("check-lld: %s" % lld)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  OpenAPI contract valid; %d module doc(s); all stories and phase-5 SEC-IDs "
                  "covered." % len(mods))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
