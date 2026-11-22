"""The confined runner (increment 7c; docs/confinement-design.md sections 3.1-3.9, approved with rulings).

Every gate that executes or loads product code goes through here. This module is the policy:
it decides limits, images, the exact `docker` argv, the compose project the gate generates,
whether a Dockerfile may be built, and whether a run's output may be believed. It fails closed:
anything it cannot establish raises Unavailable (the gate reports UNKNOWN) or Refused (FAIL).

  limits(tier, product_tools)       section 3.5; a product may raise a limit to at most 2x
                                    (max_factor) through ADOPT of product-tools.yaml `limits:`
  install_scripts(product_tools)    ruling 6: packages whose install script may run, from the
                                    adopted product-tools.yaml only
  image(name)                       a digest-pinned image, or Unavailable (blocked or unpinned)
  run_argv(...)                     `docker run` as uid 65534 (nobody), --cap-drop ALL, no-new-privileges,
                                    --read-only, tmpfs /tmp, --network none (or the run's internal
                                    network), limits, a read-only /src volume and one /out volume,
                                    and never a host bind mount or the Docker socket
  compose_project(doc, run)         section 3.8: the product's compose file is never run as
                                    written; the allowlisted keys are taken into a project the
                                    gate generates and hardens; every other key is refused
  dockerfile_problems(text)         section 3.9: FROM by digest only; no secret or ssh mounts
  label_stages(text, run_id)        0.7.9: the run's labels set first in every stage, so every image a build
                                    makes (intermediate, untagged, earlier stages) carries them
  check_output(dir, max_bytes)      no links, devices or oversize output
  docker_available()                Docker is a hard requirement (ruling 1): UNKNOWN without it

The engine calls are in class Run (increment 7d): named volumes loaded with `docker cp` (no host
path), a gate-controlled helper that sets their owner, internal networks, the allowlisting egress
proxy for the install step, confined execution with OOM and wall-clock detection, end_step() (0.7.9:
every name is unique within the run, and what a step created goes when the step ends), and close(),
which removes everything carrying the run's label. Tested against a real engine by
tests/confined-engine (Terminal).
"""
import contextlib
import json
import os
import re
import stat
import subprocess
import time

GATE_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG = os.path.join(GATE_DIR, "config", "confinement.yaml")
DOCKER_DIRS = ("/usr/local/bin", "/opt/homebrew/bin", "/usr/bin")
DIGEST_REF = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}$")
LIMIT_KEYS = ("cpus", "memory_mb", "pids", "tmp_mb", "out_mb", "wall_s")
SECRETISH = re.compile(r"(?i)(secret|token|passw(or)?d|private[_-]?key|api[_-]?key|credential)")
PROD_HOST = re.compile(r"(?i)\b(prod|production|live)\b|\.(com|io|app|net|org)\b(?!\.invalid)")


class Unavailable(Exception):
    """Confinement cannot be set up: the gate reports UNKNOWN."""


class Refused(Exception):
    """The product asked for something the design forbids: the gate reports FAIL."""


def _yaml(path):
    import sys
    sys.path.insert(0, os.path.join(GATE_DIR, "v1"))
    import hlib
    return hlib.load_yaml(path) or {}


def config():
    return _yaml(CONFIG)


# ------------------------------------------------------------------ limits, install scripts
def limits(tier, product_tools=None):
    cfg = config()
    base = (cfg.get("tiers") or {}).get(tier)
    if not base:
        raise Unavailable("no limits are configured for tier %s" % tier)
    out = {k: base[k] for k in LIMIT_KEYS}
    want = ((product_tools or {}).get("limits") or {}).get(tier) or {}
    factor = float(cfg.get("max_factor") or 2)
    for k, v in want.items():
        if k not in LIMIT_KEYS:
            raise Refused("product-tools.yaml limits.%s.%s is not a limit (allowed: %s)" % (tier, k, ", ".join(LIMIT_KEYS)))
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise Refused("product-tools.yaml limits.%s.%s is not a number" % (tier, k)) from None
        if v <= 0 or v > base[k] * factor:
            raise Refused("product-tools.yaml limits.%s.%s = %s is above %s x the default %s" % (
                tier, k, v, factor, base[k]))
        out[k] = int(v) if k != "cpus" else v
    return out


def install_scripts(product_tools):
    """Packages whose install script may run (ruling 6). product_tools is the ADOPTED
    .sdlc/config/product-tools.yaml (only ADOPT writes it), never a proposal or a repo file."""
    names = (product_tools or {}).get("install_scripts") or []
    out = []
    for n in names:
        if not isinstance(n, str) or not re.match(r"^(@[a-z0-9._-]+/)?[a-z0-9._-]+$", n):
            raise Refused("product-tools.yaml install_scripts entry %r is not a package name" % (n,))
        out.append(n)
    return out


# ------------------------------------------------------------------ images, engine
def image(name):
    e = (config().get("images") or {}).get(name)
    if not e:
        raise Unavailable("no image %r is configured" % name)
    if str(e.get("status") or "") == "blocked":
        raise Unavailable("image %s is blocked: %s" % (name, e.get("reason")))
    ref = str(e.get("ref") or "")
    if not DIGEST_REF.match(ref):
        raise Unavailable("image %s is not pinned by digest" % name)
    return ref


def docker_path():
    for d in DOCKER_DIRS:
        p = os.path.join(d, "docker")
        if os.access(p, os.X_OK):
            return p
    return None


def docker_available(timeout=15):
    """(True, version) or (False, why). Ruling 1: without Docker every executing gate is UNKNOWN."""
    d = docker_path()
    if not d:
        return False, "Docker is not installed (it is a hard requirement for the gates that run product code)"
    try:
        p = subprocess.run([d, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, "docker version failed: %r" % (e,)
    if p.returncode != 0 or not p.stdout.strip():
        return False, "the Docker engine is not reachable: %s" % (p.stderr or "").strip()[:200]
    return True, p.stdout.strip()


# ------------------------------------------------------------------ docker run
KILLED = 137  # 128 + SIGKILL: what `docker run` returns when the kernel (or the engine) kills the run


def _refuse_host_mounts(options):
    """The engine options of a run (everything before the image) may not mount a host path or the Docker
    socket. Only the options are checked: the command runs inside the container, where naming a path that
    is not mounted reaches nothing, and checking it would refuse ordinary commands such as `node -v`."""
    joined = " ".join(options)
    if "docker.sock" in joined or "type=bind" in joined or re.search(r"(^| )(-v|--volume)( |=)", joined):
        raise Refused("a confined run may not mount a host path or the Docker socket")


RUN_PATH = "/usr/local/bin:/usr/bin:/bin"
RUN_PATH_RE = re.compile(r"^/[\w./-]+(:/[\w./-]+)*$")
# The runner's fixed environment: these names and nothing else, plus the image's own variables (which the
# engine keeps unless one of these replaces it) and what the gate passes for one run (never a secret).
RUN_ENV_NAMES = ("PATH", "HOME", "LANG", "CI", "TZ")


def run_argv(run_id, img, argv, lim, src_volume, out_volume, network="none", env=None, deps_volume=None):
    """The exact `docker run` argv (section 3.2). Volumes are named volumes the gate created for this
    run; a host path is refused, and so is anything naming the Docker socket."""
    for v in (src_volume, out_volume, deps_volume):
        if v is not None and (not re.match(r"^moadix-[a-z0-9-]+$", v) or "/" in v):
            raise Refused("volume %r is not a gate-created named volume" % (v,))
    if network != "none" and not re.match(r"^moadix-[a-z0-9-]+$", network):
        raise Refused("network %r is not the run's internal network" % (network,))
    uid = int(config().get("uid") or 65534)
    e = {"PATH": RUN_PATH, "HOME": "/tmp",  # noqa: S108 (inside the container: a tmpfs)
         "LANG": "C.UTF-8", "CI": "1", "NODE_ENV": "test", "TZ": "UTC"}
    for k, val in (env or {}).items():
        if SECRETISH.search(k) or not re.match(r"^[A-Z][A-Z0-9_]*$", k):
            raise Refused("environment variable %s may not be passed into a confined run" % k)
        e[k] = str(val)
    out = ["run", "--rm", "--name", "moadix-%s" % run_id, "--label", "moadix.run=%s" % run_id,
           "--user", "%d:%d" % (uid, uid), "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=%dm" % lim["tmp_mb"],  # noqa: S108 (the container's tmpfs)
           "--network", network, "--cpus", str(lim["cpus"]), "--memory", "%dm" % lim["memory_mb"],
           "--memory-swap", "%dm" % lim["memory_mb"], "--pids-limit", str(lim["pids"]),
           "--ulimit", "nofile=4096:4096", "--mount", "type=volume,src=%s,dst=/src,readonly" % src_volume,
           "--mount", "type=volume,src=%s,dst=/out" % out_volume, "--workdir", "/src"]
    if deps_volume:
        out += ["--mount", "type=volume,src=%s,dst=/deps,readonly" % deps_volume]
    for k in sorted(e):
        out += ["--env", "%s=%s" % (k, e[k])]
    _refuse_host_mounts(out)
    return out + [img] + list(argv)


# ------------------------------------------------------------------ compose (section 3.8)
SERVICE_KEYS = {"image", "build", "command", "entrypoint", "working_dir", "environment", "depends_on", "healthcheck",
                "expose", "ports", "volumes"}
TOP_KEYS = {"services", "volumes", "name", "version"}


def compose_project(doc, run_id, lim, internal_network=None):
    """(generated compose dict, notes). Raises Refused naming every key the design forbids."""
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict) or not doc["services"]:
        raise Refused("the compose file has no services mapping")
    probs, notes = [], []
    for k in doc:
        if k not in TOP_KEYS:
            probs.append("top-level `%s` is not allowed (only services and named volumes)" % k)
    for vname, v in (doc.get("volumes") or {}).items():
        if isinstance(v, dict) and (v.get("external") or v.get("driver_opts") or v.get("driver")):
            probs.append("volume %s: external volumes, drivers and driver_opts are refused" % vname)
    net = internal_network or "moadix-%s" % run_id
    out = {"name": "moadix-%s" % run_id, "services": {}, "networks": {net: {"internal": True,
                                                                            "labels": {"moadix.run": run_id}}},
           "volumes": {}}
    uid = int(config().get("uid") or 65534)
    for sname, svc in doc["services"].items():
        if not isinstance(svc, dict):
            probs.append("service %s is not a mapping" % sname)
            continue
        for k in svc:
            if k not in SERVICE_KEYS:
                probs.append("service %s: `%s` is refused (privileged, cap_add, devices, network_mode, pid, ipc, "
                             "extra_hosts, user, security_opt and every other key outside the allowlist)" % (sname, k))
        g = {"user": "%d:%d" % (uid, uid), "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
             "read_only": True, "tmpfs": ["/tmp:size=%dm" % lim["tmp_mb"]],  # noqa: S108 (the container's tmpfs) "networks": [net],
             "labels": {"moadix.run": run_id}, "mem_limit": "%dm" % lim["memory_mb"],
             "memswap_limit": "%dm" % lim["memory_mb"], "cpus": lim["cpus"], "pids_limit": lim["pids"]}
        if "image" in svc:
            if not DIGEST_REF.match(str(svc["image"])):
                probs.append("service %s: image %r is not pinned by digest" % (sname, svc["image"]))
            g["image"] = svc["image"]
        if "build" in svc:
            b = svc["build"]
            b = {"context": b} if isinstance(b, str) else (b or {})
            for k in b:
                if k not in ("context", "dockerfile"):
                    probs.append("service %s: build.%s is refused (no args from the environment, secrets, ssh, "
                                 "network or caches)" % (sname, k))
            ctx = str(b.get("context") or ".")
            if ctx.startswith("/") or ".." in ctx.split("/") or "://" in ctx:
                probs.append("service %s: build context %s is outside the export" % (sname, ctx))
            g["image"] = "moadix/%s-%s:%s" % (run_id, sname, run_id)  # built by the gate itself (section 3.9)
            notes.append("service %s is built by the gate from %s" % (sname, ctx))
        for k in ("command", "entrypoint", "working_dir", "depends_on", "healthcheck", "expose"):
            if k in svc:
                g[k] = svc[k]
        envd = svc.get("environment") or {}
        if isinstance(envd, list):
            envd = dict(x.split("=", 1) if "=" in x else (x, "") for x in envd)
        for k, v in envd.items():
            if SECRETISH.search(str(k)) and str(v):
                probs.append("service %s: environment %s looks like a secret; services get no secrets" % (sname, k))
            if v is not None and PROD_HOST.search(str(v)) and "://" in str(v):
                probs.append("service %s: environment %s names a non-test host (%s)" % (sname, k, v))
        if envd:
            g["environment"] = {str(k): str(v) for k, v in envd.items()}
        for p in svc.get("ports") or []:
            ps = json.dumps(p) if isinstance(p, dict) else str(p)
            ip = (p.get("host_ip") if isinstance(p, dict) else (ps.split(":")[0] if ps.count(":") >= 2 else None))
            if ip and ip not in ("127.0.0.1", "::1", "localhost"):
                probs.append("service %s: port %s is bound outside loopback" % (sname, ps))
        if svc.get("ports"):
            notes.append("service %s: ports are not published (scanners use the internal network)" % sname)
        vols = []
        for v in svc.get("volumes") or []:
            src = (v.get("source") if isinstance(v, dict) else str(v).split(":", 1)[0]) or ""
            typ = v.get("type") if isinstance(v, dict) else None
            if typ == "tmpfs":
                vols.append(v)
                continue
            if typ == "bind" or src.startswith(("/", ".", "~")) or "docker.sock" in str(v) or ".." in src:
                probs.append("service %s: volume %s is a host path (or the Docker socket); refused" % (sname, v))
                continue
            if not re.match(r"^[A-Za-z0-9_-]+$", src):
                probs.append("service %s: volume %s is not a named volume" % (sname, v))
                continue
            name = "moadix-%s-%s" % (run_id, src)
            out["volumes"][name] = {"labels": {"moadix.run": run_id}}
            dst = v.get("target") if isinstance(v, dict) else str(v).split(":", 2)[1]
            vols.append("%s:%s" % (name, dst))
        if vols:
            g["volumes"] = vols
        out["services"][sname] = g
    if probs:
        raise Refused("; ".join(probs))
    return out, notes


# ------------------------------------------------------------------ image build (section 3.9)
FROM = re.compile(r"(?im)^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?")


def dockerfile_problems(text, product_tools=None):
    probs, stages = [], set()
    for m in FROM.finditer(text or ""):
        ref, alias = m.group(1), m.group(2)
        if ref.lower() not in stages and not DIGEST_REF.match(ref):
            probs.append("FROM %s is not pinned by @sha256: digest (or an earlier stage)" % ref)
        if alias:
            stages.add(alias.lower())
    if not FROM.search(text or ""):
        probs.append("the Dockerfile has no FROM")
    if re.search(r"(?im)--mount=[^\s]*type=(secret|ssh)", text or ""):
        probs.append("RUN --mount=type=secret|ssh: builds get no secrets and no SSH agent")
    if re.search(r"(?im)^\s*ADD\s+https?://", text or ""):
        probs.append("ADD <url> downloads during the build; builds have no network unless build.network: registry")
    return probs


def build_network(product_tools=None):
    """none (the default) or registry (section 3.9)."""
    net = ((product_tools or {}).get("build") or {}).get("network") or "none"
    if net not in ("none", "registry"):
        raise Refused("build.network %r is not none or registry" % net)
    return net


def build_argv(run_id, tag, dockerfile, lim, product_tools=None, network=None):
    """`docker build -` reading the export as a tar on stdin (section 3.9). With build.network: registry,
    `network` is the run's internal build network, joined to the allowlisting egress proxy, and the build
    reaches the registries only through it (0.7.4: the name used to be one no step created)."""
    net = build_network(product_tools)
    args = (((product_tools or {}).get("build") or {}).get("args") or {})
    out = ["build", "-", "-f", dockerfile, "-t", tag, "--label", "moadix.run=%s" % run_id, "--pull=false",
           "--memory", "%dm" % lim["memory_mb"]]
    for k, v in sorted(args.items()):
        if SECRETISH.search(str(k)) or SECRETISH.search(str(v)):
            raise Refused("build arg %s looks like a secret; builds get no secrets" % k)
        if str(k).lower() in ("http_proxy", "https_proxy", "no_proxy", "all_proxy"):
            raise Refused("build arg %s is set by the gate, never by the product" % k)
        out += ["--build-arg", "%s=%s" % (k, v)]
    if net == "registry":
        if not network or not re.match(r"^moadix-[a-z0-9-]+$", network):
            raise Refused("a registry build needs the run's internal build network")
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            out += ["--build-arg", "%s=http://moadix-proxy:3128" % k]
        # 0.7.9: the classic builder's step containers sit on the build network; they go when the build ends, even
        # when it fails, so the network can be removed with its step
        out += ["--network", network, "--rm", "--force-rm"]
    else:
        out += ["--network", "none"]
    return out, ({"DOCKER_BUILDKIT": "0"} if net == "registry" else {"DOCKER_BUILDKIT": "1"})


def image_labels(run_id):
    """0.7.9: the labels every image a gate build makes carries (the build's --label reaches only the last image)."""
    if not re.match(r"^[a-z0-9][a-z0-9-]{3,40}$", run_id):
        raise Refused("run id %r is not a plain lower-case id" % run_id)
    return {"moadix.run": run_id, "moadix.owner": OWNER}


def label_stages(text, run_id):
    """0.7.9 (the 0.7.8 engine run left two unlabelled <none> images): the Dockerfile the gate builds, with a LABEL
    instruction right after every FROM. The classic builder (build.network: registry) keeps an image for every step
    and every earlier stage, untagged, and `docker build --label` labels only the final one; with the run's labels
    set first in each stage, every image the build makes inherits them, so the cleanup check recognises it.
    Parser directives (escape) and line continuations are kept; nothing else in the file changes."""
    labels = image_labels(run_id)
    line = "LABEL " + " ".join("%s=%s" % (k, labels[k]) for k in sorted(labels))
    esc = "\\"
    for ln in (text or "").split("\n"):
        m = re.match(r"^\s*#\s*([A-Za-z]+)\s*=\s*(\S+)\s*$", ln)
        if not m:
            break  # directives end at the first line that is not one
        if m.group(1).lower() == "escape" and m.group(2) in ("\\", "`"):
            esc = m.group(2)
    out, cont, is_from, n = [], False, False, 0
    for ln in (text or "").split("\n"):
        out.append(ln)
        s = ln.strip()
        if not s or s.startswith("#"):
            continue  # blank and comment lines never start or end an instruction
        if not cont:
            is_from = re.match(r"(?i)^FROM\s", s) is not None
        cont = s.endswith(esc)
        if is_from and not cont:
            out.append(line)
            is_from, n = False, n + 1
    if not n:
        raise Refused("the Dockerfile has no FROM")
    return "\n".join(out)


TAR_PLAIN_TYPES = b"0\x0012345677"


def stdin_context_problem(path):
    """None when the tar at `path` can be streamed to `docker build -` as its context, else the reason.
    0.7.4 (the 0.7.3 engine run): the engine tells a tar context from a Dockerfile on stdin by its first
    512 bytes alone; a first entry that needs a second header block (a PAX `x` or `g` header, a GNU long
    name `L`/`K`) does not parse there, so the engine read the tar as a Dockerfile and, with -f also given,
    refused the build as "ambiguous Dockerfile source". The first header must be a plain ustar header with
    a valid checksum."""
    try:
        with open(path, "rb") as f:
            h = f.read(512)
    except OSError as e:
        return "the build context cannot be read (%s)" % e
    if len(h) < 512 or not h.strip(b"\0"):
        return "the build context is empty"
    if h[257:262] != b"ustar":
        return "the build context's first entry is not a ustar header"
    if h[156:157] not in [bytes([c]) for c in TAR_PLAIN_TYPES]:
        return ("the build context's first entry is a %r header, which the engine cannot recognise as a tar from "
                "its first 512 bytes" % h[156:157].decode("latin-1"))
    try:
        want = int(h[148:156].split(b"\0", 1)[0].strip() or b"0", 8)
    except ValueError:
        return "the build context's first header has no valid checksum"
    if want != sum(h[:148]) + 8 * 32 + sum(h[156:]):
        return "the build context's first header checksum is wrong"
    return None


# ------------------------------------------------------------------ output (section 3.6)
def check_output(d, max_bytes):
    total, probs = 0, []
    for a, dirs, fs in os.walk(d):
        for n in dirs + fs:
            p = os.path.join(a, n)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                probs.append("%s is a symbolic link" % os.path.relpath(p, d))
            elif not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                probs.append("%s is not a regular file" % os.path.relpath(p, d))
            elif stat.S_ISREG(st.st_mode):
                total += st.st_size
    if total > max_bytes:
        probs.append("the output is %d bytes, above the %d-byte cap" % (total, max_bytes))
    return probs


def read_json_output(d, name, max_bytes=20 << 20):
    p = os.path.join(d, name)
    if not os.path.isfile(p) or os.path.islink(p):
        raise Refused("the run wrote no %s" % name)
    if os.path.getsize(p) > max_bytes:
        raise Refused("%s is larger than %d bytes" % (name, max_bytes))
    with open(p, encoding="utf-8", errors="replace") as f:
        try:
            return json.load(f)
        except ValueError as e:
            raise Refused("%s is not JSON: %s" % (name, e)) from None


# ------------------------------------------------------------------ the engine (increment 7d)
REGISTRIES = ("registry.npmjs.org", "pypi.org", "files.pythonhosted.org")
PROXY_ALIAS = "moadix-proxy"
SUT_ALIAS = "sut.moadix.test"  # never a bare name: Chromium force-upgrades http://app (.app is HSTS-preloaded)
# 0.7.7 (the 0.7.6 engine run, MF-50): the browser gates (axe, lhci) open the app as http://sut.localhost:<port>,
# and Chromium maps that name to the app's alias on the run's network. Measured on the real engine with the
# pinned Chromium 1.64.1: over http on sut.moadix.test the __Host- Secure session cookie is refused
# (blockedReasons InvalidPrefix), with or without --unsafely-treat-insecure-origin-as-secure (that flag made a
# secure context in full Chromium and none in the headless shell, and the cookie was refused in both). Under
# .localhost, which Chromium treats as a secure context over http, the cookie is kept. A bare sut.localhost alias
# is never asked of DNS (Chromium resolves *.localhost to loopback itself), hence the resolver rule.
# 0.7.8: the app's origin is one gate-owned value, http://APP_HOST:<live.port>, which every live gate uses for its URL,
# its Host header and (where it sends one) its Origin header: Schemathesis, ZAP, Lighthouse CI and axe. A product
# sets APP_ORIGIN in its gate test stack to exactly that value (/moadix:coverage, "Live gates: the app's origin").
# The app's service gets APP_HOST as a network alias, which Docker's DNS answers for Python, Java and bash; Chromium
# alone resolves *.localhost to loopback itself, so it maps APP_HOST to the service's second alias, SUT_ALIAS.
APP_HOST = "sut.localhost"
BROWSER_ALIAS = APP_HOST  # 0.7.7 name, kept for readers of that release
BROWSER_RULE = "MAP %s %s" % (APP_HOST, SUT_ALIAS)


def app_origin(port):
    """The one origin every live gate uses for the app: http://sut.localhost:<port>."""
    return "http://%s:%d" % (APP_HOST, int(port))


def fixture_engine():
    """In a test fixture's gate copy only (tests/lib/_testguard.py present, never installed), the suites may
    point the runner at the engine double through MOADIX_TEST_ENGINE. The installed gate ignores it."""
    if os.path.exists(os.path.join(GATE_DIR, "_testguard.py")):
        p = os.environ.get("MOADIX_TEST_ENGINE")
        if p and os.access(p, os.X_OK):
            return p
    return None


def engine():
    return fixture_engine() or docker_path()


# 0.7.6: what an earlier gate run left (its process killed before close(), task-tracker phase 8) is removed when
# the next run starts. A run is the gate's when its objects carry moadix.owner=gate (0.7.6 on) or a gate run id
# (x + 10 hex digits, the only form check_exec uses; runs before 0.7.6 had no owner label). It is stale when the
# process named by moadix.pid is gone, when it started more than STALE_AGE_S ago (no gate run lasts that long:
# the longest tier's wall clock is an hour), or when it is a pre-0.7.6 run. Nothing else is ever touched: the
# engine suite's own runs (es<hex>, no owner label), compose projects and unlabelled objects stay.
OWNER = "gate"
GATE_RUN_ID = re.compile(r"^x[0-9a-f]{10}$")
STALE_AGE_S = 6 * 3600


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # EPERM: it exists, owned by someone else
        return True
    return True


def is_stale(run_id, owner, pid, started, now=None):
    if owner == OWNER:
        if pid.isdigit() and not pid_alive(int(pid)):
            return True
        return started.isdigit() and (now or time.time()) - int(started) > STALE_AGE_S
    return not owner and not pid and bool(GATE_RUN_ID.match(run_id))


class Run(object):
    """One confined run: everything it creates carries the label moadix.run=<id> (and, from 0.7.6, the gate's owner
    label, its pid and its start time) and is removed by close()."""

    def __init__(self, run_id, product_tools=None):
        if not re.match(r"^[a-z0-9][a-z0-9-]{3,40}$", run_id):
            raise Refused("run id %r is not a plain lower-case id" % run_id)
        d = engine()
        if not d:
            raise Unavailable("Docker is not installed (it is a hard requirement for the gates that run product code)")
        self.d, self.id, self.pt = d, run_id, product_tools or {}
        self.label = "moadix.run=%s" % run_id
        self.labels = ["--label", self.label, "--label", "moadix.owner=%s" % OWNER, "--label",
                       "moadix.pid=%d" % os.getpid(), "--label", "moadix.started=%d" % int(time.time())]
        ok, why = self._version()
        if not ok:
            raise Unavailable(why)
        self.volumes, self.networks, self.containers = [], [], []
        self._used = set()  # 0.7.9: every name this run gave an object, so no step ever reuses one
        self.uid = int(config().get("uid") or 65534)
        self._users_ok = set()

    def check_user(self, img, user):
        """0.7.3 (task-tracker MF-27): the run's uid must have a passwd entry in the image, or a tool that asks
        for its user (Node's os.userInfo) crashes before doing anything. Checked once per image and user, in
        a helper with no network and no capabilities; an image without the entry is UNKNOWN, never a FAIL."""
        uid = str(user).split(":")[0]
        if (img, uid) in self._users_ok:
            return
        p = self._d(["run", "--rm"] + self.labels + ["--network", "none", "--user", "%s:%s" % (uid, uid),
                     "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                     "--entrypoint", "getent", img, "passwd", uid], check=False, timeout=120)
        if p.returncode != 0:
            raise Unavailable("image %s has no passwd entry for uid %s, so tools that look up their user crash; "
                              "the runner's uid (confinement.yaml) must exist in every pinned image" % (img, uid))
        self._users_ok.add((img, uid))

    def _version(self):
        try:
            p = subprocess.run([self.d, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True,
                               timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            return False, "docker version failed: %r" % (e,)
        if p.returncode != 0 or not p.stdout.strip():
            return False, "the Docker engine is not reachable: %s" % (p.stderr or "").strip()[:200]
        return True, p.stdout.strip()

    def _d(self, args, timeout=120, stdin=None, check=True):
        try:
            p = subprocess.run([self.d] + list(args), capture_output=True, timeout=timeout, stdin=stdin)
        except subprocess.TimeoutExpired:
            raise Unavailable("docker %s timed out" % args[0]) from None
        if check and p.returncode != 0:
            raise Unavailable("docker %s failed: %s" % (" ".join(args[:2]), p.stderr.decode(errors="replace")[:300]))
        return p

    # ---- resources
    def unique(self, base):
        """0.7.9 (the 0.7.8 product run: "network with name moadix-<id>-build already exists", a compose file with two
        built services): a name no earlier step of this run used. The first use keeps `base`; a later one gets -2, -3.
        Every network, volume and container the run creates is named through here."""
        if not re.match(r"^moadix-[A-Za-z0-9_.-]+$", base):
            raise Refused("name %r is not one of the run's" % (base,))
        name, i = base, 1
        while name in self._used:
            i += 1
            name = "%s-%d" % (base, i)
        self._used.add(name)
        return name

    def volume(self, name):
        v = self.unique("moadix-%s-%s" % (self.id, name))
        self._d(["volume", "create"] + self.labels + [v])
        self.volumes.append(v)
        return v

    def network(self, name, internal=True):
        n = self.unique("moadix-%s-%s" % (self.id, name))
        self._d(["network", "create"] + self.labels + (["--internal"] if internal else []) + [n])
        self.networks.append(n)
        return n

    def end_step(self, containers=(), networks=(), volumes=()):
        """0.7.9: what one step created goes when the step ends (containers first, then the networks they were on,
        then volumes); only names this run created are removed. A removal the engine refuses is left to close(),
        which removes everything carrying the run's label."""
        for c in containers:
            if c:
                self.remove(c)
        for n in networks:
            if n in self.networks:
                with contextlib.suppress(Unavailable):
                    if self._d(["network", "rm", n], check=False).returncode == 0:
                        self.networks.remove(n)
        for v in volumes:
            if v in self.volumes:
                with contextlib.suppress(Unavailable):
                    if self._d(["volume", "rm", "-f", v], check=False).returncode == 0:
                        self.volumes.remove(v)

    def _helper(self, img, mounts, argv, user="0"):
        """A gate-controlled helper (never product code): no network, no capabilities beyond chown."""
        args = ["run", "--rm"] + self.labels + ["--network", "none", "--user", user, "--cap-drop", "ALL"]
        if user == "0":
            args += ["--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER"]
        for src, dst, ro in mounts:
            args += ["--mount", "type=volume,src=%s,dst=%s%s" % (src, dst, ",readonly" if ro else "")]
        return self._d(args + ["--entrypoint", argv[0], img] + list(argv[1:]), timeout=300)

    def load(self, vol, tar_path, img):
        """Copy a tar (the git archive export, or gate files) into a volume, then hand it to the run's uid,
        read-only for everyone else. No host path is mounted: `docker cp` streams the tar."""
        c = self.unique("moadix-%s-load-%s" % (self.id, self._short(vol)))
        self._d(["create", "--name", c] + self.labels + ["--network", "none", "--mount",
                 "type=volume,src=%s,dst=/v" % vol, "--entrypoint", "true", img])
        try:
            with open(tar_path, "rb") as f:
                self._d(["cp", "-", "%s:/v" % c], stdin=f, timeout=600)
        finally:
            self._rm_own(c)
        self._helper(img, [(vol, "/v", False)], ["chown", "-R", "%d:%d" % (self.uid, self.uid), "/v"])

    def _short(self, vol):
        pre = "moadix-%s-" % self.id
        return vol[len(pre):] if vol.startswith(pre) else vol.rsplit("-", 1)[-1]

    def _own_ids(self, name):
        """Ids of this run's container called name: only an object carrying this run's label is ever removed."""
        p = self._d(["ps", "-aq", "--no-trunc", "--filter", "label=%s" % self.label, "--filter", "name=^/%s$" % name],
                    check=False)
        return p.stdout.decode().split()

    def _rm_own(self, name):
        ids = self._own_ids(name)
        if ids:
            self._d(["rm", "-f"] + ids, check=False)

    def own(self, vol, img, uid=None):
        self._helper(img, [(vol, "/v", False)], ["chown", "%d:%d" % (uid or self.uid, uid or self.uid), "/v"])

    def copy_out(self, vol, dest, img):
        c = self.unique("moadix-%s-unload-%s" % (self.id, self._short(vol)))
        self._d(["create", "--name", c] + self.labels + ["--network", "none", "--mount",
                 "type=volume,src=%s,dst=/v,readonly" % vol, "--entrypoint", "true", img])
        try:
            os.makedirs(dest, exist_ok=True)
            self._d(["cp", "%s:/v/." % c, dest], timeout=600)
        finally:
            self._rm_own(c)

    # ---- the egress proxy and the install step (3.4)
    def proxy(self, install_net, egress_net, proxy_src_vol, purpose="install"):
        """Start the allowlisting egress proxy for one step (`purpose`: install, build). 0.7.6 (task-tracker MF-54):
        each proxy has its own name; a live gate with build.network: registry starts two, and the second used to
        get the first one's name, which the engine refuses (the gate ended UNKNOWN). The caller removes it with
        remove() when its step ends; close() removes it on every other exit path."""
        if not re.match(r"^[a-z]{1,20}$", purpose):
            raise Refused("proxy purpose %r is not a plain word" % (purpose,))
        img = image("python")
        name = self.unique("moadix-%s-proxy-%s" % (self.id, purpose))
        self._d(["run", "-d", "--name", name] + self.labels + ["--network", egress_net,
                 "--user", "%d:%d" % (self.uid, self.uid), "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                 "--read-only", "--memory", "256m", "--pids-limit", "128", "--mount",
                 "type=volume,src=%s,dst=/p,readonly" % proxy_src_vol, img, "python3", "/p/egress_proxy.py", "3128"]
                + list(REGISTRIES))
        self.containers.append(name)
        self._d(["network", "connect", "--alias", PROXY_ALIAS, install_net, name])
        return name

    def remove(self, name):
        """Remove one of this run's containers (looked up by its name and this run's label) when its step ends."""
        with contextlib.suppress(Unavailable):
            self._rm_own(name)

    def execute(self, img, argv, tier, mounts, network="none", env=None, user=None, aliases=(), name=None,
                detach=False, tmpfs=(), path=None):
        """Run argv confined (3.2). mounts: [(volume, path, readonly)]; /out is the only writable one."""
        # 0.7.5: a gate-owned service (confinement.yaml services.<name>.path) may name the image's own tool
        # directory; the PATH is never taken from the product or the host, and is checked before the engine is called
        if path is not None and not RUN_PATH_RE.match(path):
            raise Refused("PATH %r is not a list of absolute directories" % (path,))
        lim = limits(tier, self.pt)
        self.check_user(img, user or "%d:%d" % (self.uid, self.uid))
        name = self.unique(name or "moadix-%s-%s" % (self.id, re.sub(r"[^a-z0-9-]", "-", argv[0].rsplit("/", 1)[-1].lower())))
        # 0.7.4 (the 0.7.3 engine run): HOME is the run's own tmpfs /tmp, which exists and is writable by any uid
        # (mode 1777). It was /tmp/home, which nothing created, so a tool writing to $HOME (zap-baseline.py's
        # zap.yaml) failed before it started.
        e = {"PATH": RUN_PATH, "HOME": "/tmp", "LANG": "C.UTF-8", "CI": "1", "TZ": "UTC"}  # noqa: S108
        if path is not None:
            e["PATH"] = path
        for k, v in (env or {}).items():
            if SECRETISH.search(k) or not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", k):
                raise Refused("environment variable %s may not be passed into a confined run" % k)
            e[k] = str(v)
        args = ["run", "--name", name] + self.labels + ["--user", user or "%d:%d" % (self.uid, self.uid),
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=%dm,uid=%d,gid=%d" % (lim["tmp_mb"], self.uid, self.uid),  # noqa: S108
                "--network", network, "--cpus", str(lim["cpus"]), "--memory", "%dm" % lim["memory_mb"],
                "--memory-swap", "%dm" % lim["memory_mb"], "--pids-limit", str(lim["pids"]),
                "--ulimit", "nofile=4096:4096", "--ulimit", "fsize=%d" % (lim["out_mb"] << 20)]
        for a in aliases:
            args += ["--network-alias", a]
        for t in tmpfs:
            if not re.match(r"^/[\w./-]+$", t) or t in ("/", "/proc", "/sys", "/dev"):
                raise Refused("tmpfs %r is not allowed" % t)
            args += ["--tmpfs", "%s:rw,nosuid,nodev,size=64m" % t]
        for src, dst, ro in mounts:
            if not re.match(r"^moadix-[a-z0-9-]+$", src):
                raise Refused("volume %r is not a gate-created named volume" % src)
            args += ["--mount", "type=volume,src=%s,dst=%s%s" % (src, dst, ",readonly" if ro else "")]
        for k in sorted(e):
            args += ["--env", "%s=%s" % (k, e[k])]
        args += ["-d"] if detach else []
        _refuse_host_mounts(args)
        args += [img] + list(argv)
        self.containers.append(name)
        if detach:
            self._d(args, timeout=120)
            return 0, "", ""
        try:
            p = subprocess.run([self.d] + args, capture_output=True, text=True, timeout=lim["wall_s"] + 30)
        except subprocess.TimeoutExpired:
            self._rm_own(name)
            raise Refused("the run exceeded its wall clock (%ss)" % lim["wall_s"]) from None
        ids = self._own_ids(name)
        state = self._d(["inspect", "--format", "{{.State.OOMKilled}}"] + ids[:1], check=False).stdout.decode().strip() \
            if ids else ""
        self._rm_own(name)
        # An OOM kill is never a result. The engine's OOMKilled flag is one signal; the exit status is the
        # other, and it does not depend on inspect succeeding or on the engine setting the flag: a run killed
        # by SIGKILL that was not the wall clock (handled above) is reported as past its memory limit.
        if state == "true" or p.returncode in (KILLED, -9):
            raise Refused("the run exceeded its memory limit (%d MiB) and was killed (exit %s%s)"
                          % (lim["memory_mb"], p.returncode, ", OOMKilled" if state == "true" else ""))
        return p.returncode, p.stdout[-20000:], p.stderr[-20000:]

    def _remove_label(self, label):
        """Remove every container, then network, then volume carrying `label`. 0.7.6: one engine call that times
        out no longer stops the rest (each step is attempted)."""
        with contextlib.suppress(Unavailable):
            out = self._d(["ps", "-aq", "--filter", "label=%s" % label], check=False).stdout.decode().split()
            if out:
                self._d(["rm", "-f"] + out, check=False, timeout=300)
        with contextlib.suppress(Unavailable):
            for n in self._d(["network", "ls", "-q", "--filter", "label=%s" % label], check=False).stdout.decode().split():
                with contextlib.suppress(Unavailable):
                    self._d(["network", "rm", n], check=False)
        with contextlib.suppress(Unavailable):
            vols = self._d(["volume", "ls", "-q", "--filter", "label=%s" % label], check=False).stdout.decode().split()
            if vols:
                self._d(["volume", "rm", "-f"] + vols, check=False, timeout=300)

    def close(self):
        """Remove everything this run created, by label (containers, then networks, then volumes)."""
        self._remove_label(self.label)

    def sweep_stale(self):
        """0.7.6: remove what earlier gate runs left (see is_stale). Returns the run ids removed."""
        fmt = '{{.Label "moadix.run"}}\t{{.Label "moadix.owner"}}\t{{.Label "moadix.pid"}}\t{{.Label "moadix.started"}}'
        seen = {}
        for kind in (["ps", "-a"], ["network", "ls"], ["volume", "ls"]):
            p = self._d(kind + ["--filter", "label=moadix.run", "--format", fmt], check=False)
            for ln in p.stdout.decode(errors="replace").splitlines():
                f = (ln.split("\t") + ["", "", "", ""])[:4]
                if f[0] and f[0] != self.id and re.match(r"^[a-z0-9][a-z0-9-]{3,40}$", f[0]):
                    seen.setdefault(f[0], f[1:])
        now = time.time()
        stale = sorted(rid for rid, (owner, pid, started) in seen.items() if is_stale(rid, owner, pid, started, now))
        for rid in stale:
            self._remove_label("moadix.run=%s" % rid)
        return stale

    def leftovers(self):
        found = []
        for kind in (["ps", "-aq"], ["network", "ls", "-q"], ["volume", "ls", "-q"]):
            found += self._d(kind + ["--filter", "label=%s" % self.label], check=False).stdout.decode().split()
        return found
