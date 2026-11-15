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
  run_argv(...)                     `docker run` with uid 10001, --cap-drop ALL, no-new-privileges,
                                    --read-only, tmpfs /tmp, --network none (or the run's internal
                                    network), limits, a read-only /src volume and one /out volume,
                                    and never a host bind mount or the Docker socket
  compose_project(doc, run)         section 3.8: the product's compose file is never run as
                                    written; the allowlisted keys are taken into a project the
                                    gate generates and hardens; every other key is refused
  dockerfile_problems(text)         section 3.9: FROM by digest only; no secret or ssh mounts
  check_output(dir, max_bytes)      no links, devices or oversize output
  docker_available()                Docker is a hard requirement (ruling 1): UNKNOWN without it

The engine calls are in class Run (increment 7d): named volumes loaded with `docker cp` (no host
path), a gate-controlled helper that sets their owner, internal networks, the allowlisting egress
proxy for the install step, confined execution with OOM and wall-clock detection, and close(),
which removes everything carrying the run's label. Tested against a real engine by
tests/confined-engine (Terminal).
"""
import json
import os
import re
import stat
import subprocess

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
def run_argv(run_id, img, argv, lim, src_volume, out_volume, network="none", env=None, deps_volume=None):
    """The exact `docker run` argv (section 3.2). Volumes are named volumes the gate created for this
    run; a host path is refused, and so is anything naming the Docker socket."""
    for v in (src_volume, out_volume, deps_volume):
        if v is not None and (not re.match(r"^moadix-[a-z0-9-]+$", v) or "/" in v):
            raise Refused("volume %r is not a gate-created named volume" % (v,))
    if network != "none" and not re.match(r"^moadix-[a-z0-9-]+$", network):
        raise Refused("network %r is not the run's internal network" % (network,))
    uid = int(config().get("uid") or 10001)
    e = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp/home",  # noqa: S108 (inside the container: a tmpfs)
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
    out += [img] + list(argv)
    joined = " ".join(out)
    if "docker.sock" in joined or re.search(r"(^| )(-v|--volume)( |=)", joined) or "type=bind" in joined:
        raise Refused("a confined run may not mount a host path or the Docker socket")
    return out


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
    uid = int(config().get("uid") or 10001)
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


def build_argv(run_id, tag, dockerfile, lim, product_tools=None):
    """`docker build -` reading the export as a tar on stdin (section 3.9)."""
    net = ((product_tools or {}).get("build") or {}).get("network") or "none"
    if net not in ("none", "registry"):
        raise Refused("build.network %r is not none or registry" % net)
    args = (((product_tools or {}).get("build") or {}).get("args") or {})
    out = ["build", "-", "-f", dockerfile, "-t", tag, "--label", "moadix.run=%s" % run_id, "--pull=false",
           "--memory", "%dm" % lim["memory_mb"]]
    for k, v in sorted(args.items()):
        if SECRETISH.search(str(k)) or SECRETISH.search(str(v)):
            raise Refused("build arg %s looks like a secret; builds get no secrets" % k)
        out += ["--build-arg", "%s=%s" % (k, v)]
    out += ["--network", "none" if net == "none" else "moadix-egress-%s" % run_id]
    return out, ({"DOCKER_BUILDKIT": "0"} if net == "registry" else {"DOCKER_BUILDKIT": "1"})


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


class Run(object):
    """One confined run: everything it creates carries the label moadix.run=<id> and is removed by close()."""

    def __init__(self, run_id, product_tools=None):
        if not re.match(r"^[a-z0-9][a-z0-9-]{3,40}$", run_id):
            raise Refused("run id %r is not a plain lower-case id" % run_id)
        d = engine()
        if not d:
            raise Unavailable("Docker is not installed (it is a hard requirement for the gates that run product code)")
        self.d, self.id, self.pt = d, run_id, product_tools or {}
        self.label = "moadix.run=%s" % run_id
        ok, why = self._version()
        if not ok:
            raise Unavailable(why)
        self.volumes, self.networks, self.containers = [], [], []
        self.uid = int(config().get("uid") or 10001)

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
    def volume(self, name):
        v = "moadix-%s-%s" % (self.id, name)
        self._d(["volume", "create", "--label", self.label, v])
        self.volumes.append(v)
        return v

    def network(self, name, internal=True):
        n = "moadix-%s-%s" % (self.id, name)
        self._d(["network", "create", "--label", self.label] + (["--internal"] if internal else []) + [n])
        self.networks.append(n)
        return n

    def _helper(self, img, mounts, argv, user="0"):
        """A gate-controlled helper (never product code): no network, no capabilities beyond chown."""
        args = ["run", "--rm", "--label", self.label, "--network", "none", "--user", user, "--cap-drop", "ALL"]
        if user == "0":
            args += ["--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER"]
        for src, dst, ro in mounts:
            args += ["--mount", "type=volume,src=%s,dst=%s%s" % (src, dst, ",readonly" if ro else "")]
        return self._d(args + ["--entrypoint", argv[0], img] + list(argv[1:]), timeout=300)

    def load(self, vol, tar_path, img):
        """Copy a tar (the git archive export, or gate files) into a volume, then hand it to the run's uid,
        read-only for everyone else. No host path is mounted: `docker cp` streams the tar."""
        c = "moadix-%s-load-%s" % (self.id, vol.rsplit("-", 1)[-1])
        self._d(["create", "--name", c, "--label", self.label, "--network", "none", "--mount",
                 "type=volume,src=%s,dst=/v" % vol, "--entrypoint", "true", img])
        try:
            with open(tar_path, "rb") as f:
                self._d(["cp", "-", "%s:/v" % c], stdin=f, timeout=600)
        finally:
            self._rm_own(c)
        self._helper(img, [(vol, "/v", False)], ["chown", "-R", "%d:%d" % (self.uid, self.uid), "/v"])

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
        c = "moadix-%s-unload-%s" % (self.id, vol.rsplit("-", 1)[-1])
        self._d(["create", "--name", c, "--label", self.label, "--network", "none", "--mount",
                 "type=volume,src=%s,dst=/v,readonly" % vol, "--entrypoint", "true", img])
        try:
            os.makedirs(dest, exist_ok=True)
            self._d(["cp", "%s:/v/." % c, dest], timeout=600)
        finally:
            self._rm_own(c)

    # ---- the egress proxy and the install step (3.4)
    def proxy(self, install_net, egress_net, proxy_src_vol):
        img = image("python")
        name = "moadix-%s-proxy" % self.id
        self._d(["run", "-d", "--name", name, "--label", self.label, "--network", egress_net,
                 "--user", "%d:%d" % (self.uid, self.uid), "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                 "--read-only", "--memory", "256m", "--pids-limit", "128", "--mount",
                 "type=volume,src=%s,dst=/p,readonly" % proxy_src_vol, img, "python3", "/p/egress_proxy.py", "3128"]
                + list(REGISTRIES))
        self.containers.append(name)
        self._d(["network", "connect", "--alias", PROXY_ALIAS, install_net, name])
        return name

    def execute(self, img, argv, tier, mounts, network="none", env=None, user=None, aliases=(), name=None,
                detach=False, tmpfs=()):
        """Run argv confined (3.2). mounts: [(volume, path, readonly)]; /out is the only writable one."""
        lim = limits(tier, self.pt)
        name = name or "moadix-%s-%s" % (self.id, re.sub(r"[^a-z0-9-]", "-", argv[0].rsplit("/", 1)[-1].lower()))
        e = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp/home", "LANG": "C.UTF-8", "CI": "1", "TZ": "UTC"}  # noqa: S108
        for k, v in (env or {}).items():
            if SECRETISH.search(k) or not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", k):
                raise Refused("environment variable %s may not be passed into a confined run" % k)
            e[k] = str(v)
        args = ["run", "--name", name, "--label", self.label, "--user", user or "%d:%d" % (self.uid, self.uid),
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
        args += [img] + list(argv)
        joined = " ".join(args)
        if "docker.sock" in joined or "type=bind" in joined or re.search(r"(^| )(-v|--volume)( |=)", joined):
            raise Refused("a confined run may not mount a host path or the Docker socket")
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
        if state == "true":
            raise Refused("the run exceeded its memory limit (%d MiB) and was killed" % lim["memory_mb"])
        return p.returncode, p.stdout[-20000:], p.stderr[-20000:]

    def close(self):
        """Remove everything this run created, by label (containers, then networks, then volumes)."""
        out = self._d(["ps", "-aq", "--filter", "label=%s" % self.label], check=False).stdout.decode().split()
        if out:
            self._d(["rm", "-f"] + out, check=False, timeout=300)
        for n in self._d(["network", "ls", "-q", "--filter", "label=%s" % self.label], check=False).stdout.decode().split():
            self._d(["network", "rm", n], check=False)
        vols = self._d(["volume", "ls", "-q", "--filter", "label=%s" % self.label], check=False).stdout.decode().split()
        if vols:
            self._d(["volume", "rm", "-f"] + vols, check=False, timeout=300)

    def leftovers(self):
        found = []
        for kind in (["ps", "-aq"], ["network", "ls", "-q"], ["volume", "ls", "-q"]):
            found += self._d(kind + ["--filter", "label=%s" % self.label], check=False).stdout.decode().split()
        return found
