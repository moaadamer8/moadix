#!/usr/bin/python3
"""Fetch MOADIX's pinned gate-run tools (gate/config/tools.yaml) into a directory.

    fetch_tools.py <dest> [--only name,name] [--platform darwin-arm64]

Used by managed/install.sh (dest = a work dir, then copied root-owned to
<MOADIX_HOME>/tools) and by the tests (dest = ~/.cache/moadix-tools). Each tool
lands in <dest>/<name>-<version>/ with a .moadix-tool.json stamp. A download
whose sha256 differs from the pin is refused and nothing of that tool is kept.

  binary/archive  curl the asset, check sha256 against tools.yaml, extract `bin`
  npm             npm ci --ignore-scripts from tools/npm/<name>/package-lock.json
                  (every package carries an integrity hash; ci refuses a mismatch)
  pypi            uv venv with a uv-managed CPython (installed under <dest>/python),
                  then uv pip install --require-hashes from the hash-locked requirements

Idempotent: a tool whose stamp matches its pin is left alone. Each tool is built
in its final directory (a venv cannot be moved), so install.sh runs this as root
straight into <MOADIX_HOME>/tools; npm runs with --ignore-scripts and uv installs
wheels only, so no package code runs during the install.
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(REPO, "gate", "v1"))
import hlib  # noqa: E402

TOOLS_YAML = os.path.join(REPO, "gate", "config", "tools.yaml")
TRUSTED = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")


def plat():
    s = platform.system().lower()
    m = platform.machine().lower()
    arch = "arm64" if m in ("arm64", "aarch64") else "x64" if m in ("x86_64", "amd64") else m
    return "%s-%s" % ("darwin" if s == "darwin" else s, arch)


def which(name):
    for d in TRUSTED:
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    return None


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load():
    doc = hlib.load_yaml(TOOLS_YAML) or {}
    return {str(t["name"]): t for t in doc.get("tools") or []}


def stamp_path(d):
    return os.path.join(d, ".moadix-tool.json")


def current(d, t):
    try:
        with open(stamp_path(d)) as f:
            s = json.load(f)
        return s.get("version") == str(t["version"]) and os.path.exists(os.path.join(d, str(t["bin"])))
    except (OSError, ValueError):
        return False


def run(argv, **kw):
    p = subprocess.run(argv, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError("%s failed (%d): %s" % (" ".join(argv[:3]), p.returncode, (p.stderr or p.stdout)[-800:]))
    return p.stdout


def fetch_asset(t, pf, d, work):
    a = (t.get("assets") or {}).get(pf)
    if not a:
        raise RuntimeError("%s %s has no asset for %s" % (t["name"], t["version"], pf))
    url, want = str(a["url"]), str(a["sha256"])
    fn = os.path.join(work, url.rsplit("/", 1)[-1])
    run(["/usr/bin/curl", "-fsSL", "--proto", "=https", "--retry", "2", "-o", fn, url])
    got = sha256_file(fn)
    if got != want:
        raise RuntimeError("%s: sha256 %s does not match the pin %s; refusing" % (url, got, want))
    binname = str(t["bin"])
    out = os.path.join(d, binname)
    if t["kind"] == "binary":
        shutil.copy(fn, out)
    elif fn.endswith(".zip"):
        with zipfile.ZipFile(fn) as z:
            m = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == binname]
            if len(m) != 1:
                raise RuntimeError("%s: expected one %s in the archive, found %r" % (url, binname, m))
            with z.open(m[0]) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(fn) as tf:
            m = [x for x in tf.getmembers() if x.isfile() and x.name.rsplit("/", 1)[-1] == binname]
            if len(m) != 1:
                raise RuntimeError("%s: expected one %s in the archive, found %r" % (url, binname, [x.name for x in m]))
            src = tf.extractfile(m[0])
            with open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    os.chmod(out, 0o755)
    return {"url": url, "sha256": want, "bin_sha256": sha256_file(out)}


def fetch_npm(t, d):
    npm = which("npm")
    if not npm:
        raise RuntimeError("npm is required for %s" % t["name"])
    src = os.path.join(REPO, os.path.dirname(str(t["lock"])))
    for f in ("package.json", "package-lock.json"):
        shutil.copy(os.path.join(src, f), os.path.join(d, f))
    env = dict(os.environ, npm_config_update_notifier="false", npm_config_fund="false", npm_config_audit="false")
    run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--omit=dev"], cwd=d, env=env)
    with open(os.path.join(d, "node_modules", *str(t["package"]).split("/"), "package.json")) as f:
        got = json.load(f).get("version")
    if got != str(t["version"]):
        raise RuntimeError("%s: installed %s, pinned %s" % (t["name"], got, t["version"]))
    return {"lock_sha256": sha256_file(os.path.join(d, "package-lock.json"))}


def fetch_pypi(t, d, dest):
    uv = which("uv")
    if not uv:
        raise RuntimeError("uv is required for %s" % t["name"])
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=os.path.join(dest, "python"),
               UV_CACHE_DIR=os.path.join(tempfile.gettempdir(), "moadix-uv-cache"), UV_NO_CONFIG="1")
    venv = os.path.join(d, "venv")
    run([uv, "venv", "--quiet", "--python", str(t["python"]), "--managed-python", venv], env=env)
    lock = os.path.join(REPO, str(t["lock"]))
    shutil.copy(lock, os.path.join(d, "requirements.txt"))
    run([uv, "pip", "install", "--quiet", "--require-hashes", "--only-binary", ":all:", "--python", os.path.join(venv, "bin", "python"),
         "-r", lock], env=env)
    os.symlink(os.path.join("venv", "bin", str(t["bin"])), os.path.join(d, str(t["bin"])))
    return {"lock_sha256": sha256_file(lock)}


def main():
    args = sys.argv[1:]
    if not args:
        sys.stderr.write(__doc__)
        return 2
    dest = os.path.realpath(args[0])
    only = None
    pf = plat()
    i = 1
    while i < len(args):
        if args[i] == "--only":
            only = set(args[i + 1].split(","))
            i += 2
        elif args[i] == "--platform":
            pf = args[i + 1]
            i += 2
        else:
            sys.stderr.write("unknown argument %r\n" % args[i])
            return 2
    os.makedirs(dest, exist_ok=True)
    tools = load()
    failed = []
    for name, t in tools.items():
        if only and name not in only:
            continue
        d = os.path.join(dest, "%s-%s" % (name, t["version"]))
        if current(d, t):
            print("ok    %s %s (already present)" % (name, t["version"]))
            continue
        # Built in place: a venv's scripts carry absolute paths, so it cannot be moved.
        # The stamp is written last, so a half-built directory is never "current".
        tmp = d
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        try:
            with tempfile.TemporaryDirectory(prefix="moadix-fetch-") as work:
                if t["kind"] in ("binary", "archive"):
                    info = fetch_asset(t, pf, tmp, work)
                elif t["kind"] == "npm":
                    info = fetch_npm(t, tmp)
                elif t["kind"] == "pypi":
                    info = fetch_pypi(t, tmp, dest)
                else:
                    raise RuntimeError("unknown kind %r" % t["kind"])
            info.update({"name": name, "version": str(t["version"]), "kind": t["kind"], "platform": pf})
            with open(stamp_path(tmp), "w") as f:
                json.dump(info, f, indent=1, sort_keys=True)
            print("got   %s %s" % (name, t["version"]))
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            failed.append(name)
            print("FAIL  %s %s: %s" % (name, t["version"], e))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
