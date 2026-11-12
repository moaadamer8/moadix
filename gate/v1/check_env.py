#!/usr/bin/env python3
"""check-env -- phase 6b: every required key present, every value encrypted (dotenvx).

MOADIX-native (increment 5). The product keeps its configuration in dotenvx
files committed encrypted (`dotenvx encrypt`, pinned 2.38.2 in
gate/config/tools.yaml). This validator NEVER reads a value: each line is
matched by a pattern that captures only the key and whether what follows `=`
starts with `encrypted:`, and the value text is neither kept, compared,
printed nor written as evidence. Nothing is decrypted; the private keys
(.env.keys, DOTENV_PRIVATE_KEY*) are never touched.

  required keys   the keys of .env.example at HEAD (v1 check-provisioning's
                  contract), or `env.required` in .sdlc/config/product-tools.yaml
  files           `env.files` in product-tools.yaml (default: .env.production),
                  as committed at HEAD
  rules           each file is tracked; each required key appears in it; every
                  assignment except DOTENV_PUBLIC_KEY* is `encrypted:...`; the
                  file carries its DOTENV_PUBLIC_KEY*; .env.keys is not tracked
                  and no tracked file assigns DOTENV_PRIVATE_KEY*.

Exit 0 pass, 1 fail.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import toolrun  # noqa: E402

PHASE = "6b"
# key, then '=', then only a test of the value's first characters. The value is not captured.
ASSIGN = re.compile(r'^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(?P<enc>["\']?encrypted:)?')
KEY_ONLY = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=')


def show(root, rel):
    p = subprocess.run([toolrun.GIT, "-C", root, "show", "HEAD:" + rel], capture_output=True)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


def required_keys(root, cfg):
    req = (cfg.get("env") or {}).get("required")
    if isinstance(req, list) and req:
        return [str(k) for k in req], "product-tools.yaml env.required"
    text = show(root, ".env.example")
    if text is None:
        return None, ".env.example"
    keys = []
    for ln in text.splitlines():
        m = KEY_ONLY.match(ln)
        if m and not ln.lstrip().startswith("#") and m.group(1) not in keys:
            keys.append(m.group(1))
    return keys, ".env.example"


def scan(text):
    """{key: encrypted?} and whether a public key is declared. Values are never captured."""
    seen, public = {}, False
    for ln in text.splitlines():
        if ln.lstrip().startswith("#"):
            continue
        m = ASSIGN.match(ln)
        if not m:
            continue
        key = m.group("key")
        if key.startswith("DOTENV_PUBLIC_KEY"):
            public = True
            continue
        seen[key] = seen.get(key, True) and bool(m.group("enc"))
    return seen, public


def main():
    root = hlib.project_root()
    cfg = toolrun.product_tools(root)
    notes, errs = [], []
    files = [str(f) for f in ((cfg.get("env") or {}).get("files") or [".env.production"])]
    keys, src = required_keys(root, cfg)
    if keys is None:
        errs.append("no required-key list: commit .env.example (keys only) or declare env.required in "
                    ".sdlc/config/product-tools.yaml")
        keys = []
    elif not keys:
        errs.append("%s lists no keys; nothing would be checked" % src)
    tracked = set(toolrun.tracked(root))
    for leak in sorted(p for p in tracked if p.rsplit("/", 1)[-1] == ".env.keys"):
        errs.append("%s is committed: it holds the dotenvx PRIVATE keys. Remove it from history and rotate" % leak)
    summary = {"required_from": src, "required": keys, "files": {}}
    for rel in files:
        if rel not in tracked:
            errs.append("%s is not committed at HEAD (env.files)" % rel)
            continue
        text = show(root, rel) or ""
        seen, public = scan(text)
        del text  # nothing below sees the file's contents
        plain = sorted(k for k, enc in seen.items() if not enc)
        missing = [k for k in keys if k not in seen]
        private = sorted(k for k in seen if k.startswith("DOTENV_PRIVATE_KEY"))
        for k in missing:
            errs.append("%s: required key %s is missing" % (rel, k))
        for k in plain:
            errs.append("%s: %s is not encrypted (run `dotenvx encrypt -f %s`)" % (rel, k, rel))
        for k in private:
            errs.append("%s assigns %s: a private key is committed" % (rel, k))
        if not public:
            errs.append("%s has no DOTENV_PUBLIC_KEY* line, so it was not written by dotenvx encrypt" % rel)
        summary["files"][rel] = {"keys": sorted(seen), "unencrypted": plain, "missing": missing,
                                 "public_key_declared": public}
        notes.append("%s: %d key(s), %d encrypted, %d required missing" % (
            rel, len(seen), len(seen) - len(plain), len(missing)))
    notes.append("required keys from %s: %d" % (src, len(keys)))
    try:
        _p, pin = toolrun.tool("dotenvx")
        ver = str(pin["version"])
    except toolrun.ToolUnavailable:
        ver = "not-installed"  # the check itself needs no binary; it records the pin it enforces
    rel, digest = toolrun.record(root, PHASE, "dotenvx-check", ver, "env-check.json",
                                 json.dumps(summary, indent=1, sort_keys=True), "check-env")
    notes.append("evidence %s (sha256 %s; key names only, no values)" % (rel, digest[:12]))
    return toolrun.report("check-env (phase 6b, dotenvx encryption)", notes, [], errs, [])


if __name__ == "__main__":
    sys.exit(main())
