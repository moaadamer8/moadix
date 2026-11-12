"""BMad core in a product (increment 6, item C).

The vendored BMAD skills call BMad core's shared scripts at
`{project-root}/_bmad/scripts/` (memlog.py, resolve_config.py,
resolve_customization.py, and config_utils.py, which the last two import). MOADIX
vendors those four files verbatim from BMAD-METHOD v6.12.4 (gate/bmad/scripts/,
upstream sha256 in gate/bmad/MOADIX-UPSTREAM.sha256) and the GATE installs them
into the product, with a MOADIX-written `_bmad/config.toml`:

  _bmad/scripts/*.py     verbatim copies (BMAD's "wrap, don't modify")
  _bmad/config.toml      [core] and [modules.bmm]: output folders under sdlc/, so
                         the skills write where the phase path map allows
  _bmad/MOADIX-BMAD.json what the gate installed: version, commit, sha256 per file
  _bmad/.gitignore       ignores everything above (a per-machine install, like
                         .sdlc/cache/), but not _bmad/custom/ (team overrides,
                         committed)

`_bmad/**` is protected (gate/pathmap.py): the agent cannot write it; only
`_bmad/custom/**` is excepted. The gate installs it at INIT and re-installs a
missing or changed file at session start and when the agent's turn ends.
check-seam's BMAD half (gate/v1/check_seam.py) verifies it.
"""
import hashlib
import json
import os

GATE_DIR = os.path.dirname(os.path.realpath(__file__))
SRC = os.path.join(GATE_DIR, "bmad")
VERSION = "6.12.4"
COMMIT = "bab9082c3e884e0d72c759bcd1a6d90bcc01be84"
SCRIPTS = ("memlog.py", "resolve_config.py", "resolve_customization.py", "config_utils.py")
MANIFEST = "MOADIX-BMAD.json"
GITIGNORE = "# MOADIX: BMad core is installed by the gate per machine; only custom/ is committed.\n*\n!custom/\n!custom/**\n"
CONFIG = """# MOADIX-managed BMad core configuration (gate/bmadcore.py). Written by the gate:
# agents cannot write _bmad/. Team overrides go in _bmad/custom/config.toml.
# Output folders point at sdlc/ paths the MOADIX phase path map owns:
#   phase 0 sdlc/00-forge/   1 sdlc/01-research/   2 sdlc/02-prd/   3 sdlc/03-architecture/
#   retro (during 11) sdlc/12-retro/
[core]
user_name = "operator"
project_name = "%(product)s"
communication_language = "English"
document_output_language = "English"
output_folder = "{project-root}/sdlc"

[modules.bmm]
user_skill_level = "intermediate"
planning_artifacts = "{project-root}/sdlc"
implementation_artifacts = "{project-root}/sdlc/12-retro"
project_knowledge = "{project-root}/docs"
"""


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def upstream():
    """{vendored path: upstream sha256} from gate/bmad/MOADIX-UPSTREAM.sha256."""
    out = {}
    with open(os.path.join(SRC, "MOADIX-UPSTREAM.sha256")) as f:
        for ln in f:
            if ln.startswith("#") or not ln.strip():
                continue
            uh, _stt, rel = ln.split("  ")[:3]
            out[rel] = uh
    return out


def expected(product_id):
    """{path under _bmad/: bytes} the gate installs."""
    files = {}
    for name in SCRIPTS:
        with open(os.path.join(SRC, "scripts", name), "rb") as f:
            files["scripts/" + name] = f.read()
    files["config.toml"] = (CONFIG % {"product": product_id}).encode()
    files[".gitignore"] = GITIGNORE.encode()
    man = {"bmad_version": VERSION, "commit": COMMIT, "installed_by": "MOADIX gate",
           "files": {k: sha256(v) for k, v in sorted(files.items())}}
    files[MANIFEST] = (json.dumps(man, indent=1, sort_keys=True) + "\n").encode()
    return files


def problems(root, product_id):
    """[(path, what)] where the product's _bmad/ differs from what the gate installs."""
    base = os.path.join(root, "_bmad")
    if os.path.islink(base):
        return [("_bmad", "is a symbolic link")]
    out = []
    for rel, want in sorted(expected(product_id).items()):
        p = os.path.join(base, rel)
        if os.path.islink(p):
            out.append(("_bmad/" + rel, "is a symbolic link"))
            continue
        try:
            with open(p, "rb") as f:
                got = f.read()
        except OSError:
            out.append(("_bmad/" + rel, "is missing"))
            continue
        if got != want:
            out.append(("_bmad/" + rel, "differs from the pinned copy"))
    return out


def install(root, product_id):
    """Write every file that is missing or differs. Returns the paths written."""
    base = os.path.join(root, "_bmad")
    if os.path.islink(base):
        raise OSError("_bmad is a symbolic link; refusing to write through it")
    written = []
    for rel, want in sorted(expected(product_id).items()):
        p = os.path.join(base, rel)
        try:
            with open(p, "rb") as f:
                if f.read() == want and not os.path.islink(p):
                    continue
        except OSError:
            pass
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.islink(p):
            os.unlink(p)
        tmp = p + ".moadix-tmp"
        with open(tmp, "wb") as f:
            f.write(want)
        os.replace(tmp, p)
        written.append("_bmad/" + rel)
    return written


def ensure(root):
    """Re-install BMad core when the product's copy is missing or changed. Returns a note
    for the session, or None when nothing had to change. Never raises."""
    try:
        from . import state
        pid = state.load_product(root)["product"]
        if not problems(root, pid):
            return None
        written = install(root, pid)
        return "BMad core %s (re)installed into _bmad/ by the gate: %s." % (VERSION, ", ".join(written[:6]))
    except Exception as e:
        return "BMad core could not be installed into _bmad/ (%s: %s)" % (type(e).__name__, e)
