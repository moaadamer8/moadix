# Confinement design for gates that run product code

2026-11-14 · increment 7b, approved with rulings; gaps 7 and 8 (sections 3.8 and 3.9) added in increment 7c. What 7c built is in docs/increment-7c-report.md.

Amendment 3 asks the gate to run tools that execute or load product code or product configuration. A product's code is written by the agent the gate is supervising, so every such run must be treated as running untrusted code. This document says how those runs are confined, before any of them is built.

## 1. Which gates this covers

| Gate (phase) | What of the product it executes or loads | Needs a running app | Tier |
|---|---|---|---|
| pytm (4, B, FC) | `tm/model.py`: the threat model is a Python program | no | E |
| LikeC4 build (3, B) | `.c4` sources; a `likec4.config.ts`/`.js` would be executed | no | E (R if config is JSON only, see 4.4) |
| dependency-cruiser (3, 7, B) | `.dependency-cruiser.cjs` (JavaScript) and the bundler/tsconfig it points at | no | E |
| knip (7, B) | its plugins load the product's tool configs (vite, vitest, next, eslint…), which are code | no | E |
| ESLint (7) | `eslint.config.js` and every plugin it imports | no | E |
| tsc --noEmit (7) | `tsconfig.json` and installed type packages; no product code runs, but installed packages may have install scripts | no | E-lite (4.4) |
| Stryker (8, B) | the product's test suite, many times over | no | E (heavy) |
| Test suites (8, B, existing suite in onboarding) | the product's tests and code; Testcontainers needs a Docker API | sometimes | E, or L for integration |
| Schemathesis (8, 10b) | nothing of the product in the tool, but sends generated requests to the running app | yes | L |
| ZAP passive baseline (9) | the running app (passive scan) | yes | L |
| Lighthouse CI (10a) | the running app in Chrome; `lighthouserc.js` would be executed | yes | L |
| axe (6, 8, 10a) | the running app's pages in a browser | yes | L |

The tiers:

- **Tier R** (built in 7b) reads files only, with `sandbox-exec`.
- **Tier E** executes product code with no app running.
- **Tier L** runs a disposable instance of the app and a scanner against it.

## 2. What could go wrong (threats)

1. **Secret theft.** Product code reads tokens from the environment or from the operator's home: `~/.ssh`, `~/.config/gh`, `~/.npmrc`, `~/.aws`, the Keychain via `security`, shell history. It then sends them out.
2. **Gate-state tampering.** Product code writes `.sdlc/` (ledger, cache, evidence), the ledger anchor, the gate copy or the tools cache, or plants files that a later gate run trusts.
3. **Persistence on the host.** It writes `~/.zshrc`, LaunchAgents, git hooks, or `node_modules` that the operator later runs.
4. **Exfiltration and outward actions.** Any network egress: posting data, calling production, pushing to GitHub.
5. **Resource exhaustion.** A fork bomb, a memory or disk fill, an endless loop that holds the validator worker.
6. **Forged results.** Code that prints PASS, writes a fake JUnit or `mutation.json`, or rewrites the report the gate parses.
7. **Escalation.** Through the Docker socket, privileged containers, setuid binaries, or host bind mounts.
8. **Reaching production.** A live gate pointed at a real deployment (v1's `test_sandbox` incident).

## 3. Design

### 3.1 One confined runner, owned by the gate

Every executing gate calls one gate function, `confined.run(tier, image, argv, inputs, limits)`.

- It builds the container argv **itself** from fixed parts. A product setting can choose a size or a URL from an allowlist, never a flag.
- The agent cannot call it. The agent's own Docker commands stay governed by the existing pretool docker guard.
- On any failure to set up confinement (no Docker, an image digest mismatch, a limit it cannot apply), the gate reports **UNKNOWN**. It never runs the gate less confined.

### 3.2 Isolation boundary: a disposable container, never the operator's user account

| Property | Rule |
|---|---|
| Engine | Docker (or Podman), already required for phases 7–10. On macOS that is a Linux VM. **No fallback to running on the host**: `sandbox-exec` keeps the operator's uid and HOME, and Tier E code is too broad to confine with a deny-list (Tier R stays on `sandbox-exec`, as built). |
| Images | Pinned by digest in `gate/config/tools.yaml` (`images:`): one Node 24 LTS base and one Python 3.12 base for E, ZAP for L, and a Chromium image for Lighthouse CI and axe. The licence of every image is read before pinning, under the 7b rule. |
| Gate tools | Mounted read-only from a Linux tools cache that the installer fetches beside the macOS one (tools.yaml already has linux-x64 and linux-arm64 assets with checksums). |
| User | Non-root (uid/gid 10001), `--user 10001:10001`. The image contains no setuid binaries; `--security-opt no-new-privileges`. |
| Privileges | `--cap-drop ALL`, the default seccomp profile, no `--privileged`, no host PID, IPC or network namespace, no devices. |
| Filesystem | `--read-only` root filesystem and a `tmpfs` `/tmp` (size-capped). |
| Repository | `git archive HEAD`: the commit the gate judges, not the working tree. It goes into a fresh volume with `docker cp`, mounted **read-only at `/src`**. It has no `.git`, no `.sdlc/`, no `.sdlc-proposals/`, and no `.env*` except `.env.example`. **No bind mount of any host path**, so the VM's file sharing of `/Users` is never handed to the container. |
| Output | **One** writable volume at `/out`, size-capped. The gate copies it out after exit and checks it: no symlinks or devices, a total size cap, and each expected file parsed (JSON, XML, SARIF) with a size limit before anything is believed. Nothing else leaves the container. |
| Work space | Tools that must write next to the code (Stryker's sandbox, a build cache) copy `/src` into `/tmp/work`, inside the container's tmpfs. |
| Lifetime | `--rm`. The volumes are removed after the copy-out. Containers, volumes and networks carry a gate label (`moadix.run=<id>`), and a stale one is removed at the next run. |

### 3.3 No secrets in the environment

- **Environment.** Built from scratch, never inherited: `PATH`, `HOME=/tmp/home`, `LANG`, `CI=1`, `NODE_ENV=test`, `TZ=UTC`, plus the tool's own fixed variables (for example telemetry off). No proxy variables, no `GH_TOKEN`, no `DOTENV_PRIVATE_KEY*`, no `NPM_TOKEN`.
- **The machine's secrets.** No SSH agent socket, no Docker socket, no Keychain: a Linux container cannot reach the macOS Keychain, and nothing bridges it. No host HOME mount.
- **The product's secrets.** dotenvx-encrypted files stay encrypted because no private key is given. A test that needs a value uses the fixture values committed for tests (V6, V15). The gate refuses to start a Tier L app whose declared environment names a production host or a live key (V15), using the same production-URL rule as check-baseline.

### 3.4 Network egress

| Step | Network |
|---|---|
| Executing product code (E) | `--network none`. No DNS, no loopback to the host. |
| Installing dependencies (before E) | A separate, earlier container step:<br>• `npm ci --ignore-scripts` from the product's lockfile, or `uv pip install --require-hashes`;<br>• egress only to the package registries, through a gate-run allowlisting proxy (registry.npmjs.org, pypi.org, files.pythonhosted.org);<br>• output: a read-only `node_modules` volume for the execution step.<br>Install scripts stay off. A package that needs one (esbuild, sharp) is listed in product-tools.yaml and its script runs in the same no-secret container (accepted risk 5.3). |
| Live (L) | The app runs as a disposable compose project the gate names (`moadix-<product>-<run>`) on a `docker network create --internal` network: **no egress at all**. Only the scanner container (ZAP, Schemathesis, Chromium for Lighthouse CI and axe) joins it. The base URL is the app's service name on that network, never a host address, so a production URL cannot be reached even when it is configured. |
| Testcontainers | A Testcontainers suite asks for the Docker API, and giving the host socket to product code is host compromise. Proposed: the integration tier runs in its own rootless Docker-in-Docker (or sysbox) runtime with no host mounts, on the internal network. **Open question for the operator** (6.3). |

### 3.5 Resource limits

| Tier | CPU | Memory | Processes | Disk (`/tmp`, `/out`) | Wall clock |
|---|---|---|---|---|---|
| E (lint, types, pytm, LikeC4) | 2 | 2 GiB | 256 | 512 MiB, 50 MiB | 5 min |
| E (test suites) | 2 | 4 GiB | 512 | 1 GiB, 200 MiB | 15 min |
| E (Stryker) | 4 | 8 GiB | 1024 | 2 GiB, 200 MiB | 60 min |
| L (app + scanner) | 2 + 2 | 2 GiB + 2 GiB | 512 each | 1 GiB, 200 MiB | 30 min |

- **How they apply.** Through `--cpus`, `--memory` (with `--memory-swap` equal to it), `--pids-limit`, `--ulimit nofile=4096` and the tmpfs and volume size caps. The wall clock is enforced by the gate, which kills and removes the container.
- **Exceeding a limit** is a FAIL with the limit named, not UNKNOWN: the product exceeded its budget.
- **Changes.** The limits live in `gate/config/confinement.yaml` (root-owned). A product may ask for at most 2× through ADOPT of product-tools.yaml.
- **The worker.** Validator timeouts in the registry rise to cover the wall clock. The worker already runs detached, so the Stop hook never waits.

### 3.6 Results the gate can believe

- **The gate's own configuration.** The tool runs with the gate's config wherever the tool allows. The product's `lighthouserc.js`, `stryker.conf.js`, `knip.ts` and `.dependency-cruiser.cjs` are removed from the export, as Tier R does. Where the tool *must* read product config to work at all (ESLint's flat config, the dependency-cruiser rules that name H4 modules), that config is executed only inside the container, and only its output is believed.
- **Where results go.** Reports are written by the tool to fixed names in `/out`. The gate re-derives the verdict from raw data (mutation score from `mutation.json`, failures from JUnit) and never from a tool's or the product's summary line.
- **Thresholds.** They come from gate configuration and the size rule (TS10 at 70%/80%), never from the product's config.
- **Limit.** Code that runs in the same process as the runner (tests) can still forge that runner's report. See accepted risk 5.2.

### 3.7 How each gate maps onto the runner

| Gate | Steps |
|---|---|
| pytm | E/Python: `python /src/tm/model.py --json /out/tm.json` with the pinned pytm on a read-only path. The gate parses the JSON and maps threats to TH-/SEC- (SEC-CONTROLS.csv, built in 7b). |
| LikeC4 | E/Node: `likec4 build`; `/out` gets the model JSON. |
| dependency-cruiser, knip, ESLint, tsc | Install step, then E/Node, each emitting JSON to `/out`. The 0-error and allow-list rules are applied by the gate. |
| Stryker | Install step, then E/Node heavy. `mutation.json` goes to `/out`; the threshold comes from the size rule. |
| Test suites | Install step, then E (unit) or L (integration). JUnit and coverage JSON go to `/out`. Zero retries are enforced by gate flags where the runner allows. |
| Schemathesis | L. The OpenAPI file is from the export; the base URL is the app's service name. JUnit goes to `/out`. |
| ZAP | L. `zap-baseline.py` (passive) with the gate's rules file; SARIF and JSON go to `/out`. |
| Lighthouse CI | L. Chromium image with the gate's lhci config; budgets from U16 and H6. |
| axe | L. A gate-owned Playwright script plus axe-core (MPL-2.0, fetched unmodified, ruling 3) visits the URLs from LV-INVENTORY.csv and screen-states.csv. JSON goes to `/out`. |

### 3.8 The product's compose file is never run as written (gap 7, increment 7c)

The product's `docker-compose.yml` is written by the agent, so it is product-controlled. The gate **generates** its own compose project from an allowlisted schema. It reads only the keys below from the product's file and refuses the run (FAIL, naming the key) on anything else. It writes a new file in the gate's scratch folder, adds its own hardening, and runs `docker compose -p moadix-<product>-<run> -f <that file>`. The product's file is never passed to Docker.

| Product key (per service) | Taken as | Refused |
|---|---|---|
| `image` | only `name@sha256:<digest>` | a tag without a digest |
| `build` | `context` (a subfolder of the export) and `dockerfile` (a path inside it); the gate builds the image itself (3.9) | `args` from the environment, `secrets`, `ssh`, `network`, `cache_from`/`cache_to` outside the gate, `additional_contexts` |
| `command`, `entrypoint`, `working_dir` | literal strings or lists | |
| `environment` | literal key/values. The gate refuses a value that looks like a secret (the check-baseline secret rule) or names a production host (V15). | `env_file` |
| `depends_on`, `healthcheck` | as written (`healthcheck.test` runs inside the container) | |
| `expose` | as written (internal network only) | |
| `ports` | **dropped**: nothing is published. Scanners reach services by name on the internal network. A port bound to an address other than loopback is refused, so a product cannot expect it. | a non-loopback `host_ip` |
| `volumes` | `tmpfs` entries, and named volumes the gate creates per run (`moadix-<run>-<name>`) | host-path (bind) volumes, `external` volumes, the Docker socket, any absolute or `..` source |
| anything else | | `privileged`, `cap_add`, `devices`, `network_mode`, `pid`, `ipc`, `userns_mode`, `security_opt`, `extra_hosts`, `dns`, `sysctls`, `ulimits`, `user` (the gate sets it), `volumes_from`, `links`, `profiles`, `configs`, `secrets`, top-level `networks`, `include`, `extends`, YAML anchors and merge keys the gate's parser does not read |

**What the gate adds to every service:**

- `user: "10001:10001"`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `read_only: true` with a size-capped tmpfs `/tmp`;
- the run's CPU, memory and pids limits (3.5);
- one network `moadix-<run>`, created with `internal: true`;
- labels `moadix.run=<id>`.

Service containers that the tests need (for example Postgres, ruling 3 on increment 7b) are not taken from the product's compose file. They come from the gate's own catalogue:

- a digest-pinned image with its licence read;
- fixed credentials generated per run (not secrets: they exist only inside the internal network for the run);
- the tests get the address by environment (`DATABASE_URL=postgres://moadix:<run-password>@postgres:5432/test`).

No container receives a Docker socket, ever.

### 3.9 Building the app image (gap 8, increment 7c)

`docker build` runs the Dockerfile's `RUN` steps, which is product code. The build is confined like this:

- **Context.** The `git archive HEAD` export only, streamed to `docker build -` as a tar, so there is no host path. `.dockerignore` comes from the export. No `.git`, no `.sdlc/` and no `.env*` are in it.
- **Base images.** Every `FROM` must name an image by `@sha256:` digest, or a stage of the same file. Anything else is refused before the build starts.
- **No secrets.** No `--secret`, no `--ssh` (BuildKit then fails any `RUN --mount=type=secret|ssh`), no SSH agent forwarding, and no build args from the environment. Only literal `build.args` from the adopted product-tools.yaml are passed, each checked by the secret rule.
- **No host mounts.** `RUN --mount=type=bind` can only bind from the build context. The gate passes no `--build-context` and no `--output` to a host path. The image is loaded into the Docker engine and tagged `moadix/<product>:<run>`.
- **Network.**
  - `--network none` by default: a Dockerfile that downloads during the build fails. The product installs dependencies in the gate's install step (3.4), whose read-only output is added to the context.
  - A product may declare `build.network: registry` in an adopted product-tools.yaml. The build then uses the classic builder on the gate's egress network, reaching the registry hosts only, through the allowlisting proxy.
  - BuildKit cannot attach to a custom network, so the classic builder is used for those builds.
- **Limits and lifetime.** The 3.5 limits apply to the build: a wall clock of 15 min. The image, its build cache and the run's containers are removed after the run.

**Accepted risks of the build:**

- `RUN` steps execute as **root inside the build container**. A non-root build is not possible for arbitrary Dockerfiles, so the builder's isolation (BuildKit/runc inside the Docker VM) is trusted, as in 5.1.
- With `build.network: registry`, a `RUN` step can talk to the registry hosts. Any upload a registry accepts is a channel out. It carries no secrets, because none are present.
- The resulting image runs only under 3.2's restrictions, as uid 10001, whatever its `USER` says.

## 4. Decisions inside the design

1. **Containers, not `sandbox-exec`, for E and L.** A Seatbelt profile cannot change the uid, and the operator's home is readable unless it is listed path by path.
2. **No host bind mounts.** Copy in, copy out. Docker Desktop shares `/Users` into its VM, so a bind mount would hand the container a path into the host.
3. **Fail closed.** No Docker, a wrong image digest, or limits that cannot be applied means UNKNOWN for that gate. A phase that needs it cannot be approved until it runs, or until the operator records PROCEED-PAST with a reason.
4. **Reduce what runs.** LikeC4 and dependency-cruiser could accept JSON-only configuration. The gate could refuse JS or TS configs, which would move those two gates down to Tier R or E-lite. Proposed as the default for LikeC4. For dependency-cruiser it conflicts with the amendment's `.dependency-cruiser.cjs` (H20), so it is a question (6.4).

## 5. Accepted risks (what stays)

1. **The container runtime is trusted.** A kernel or runtime escape reaches the Docker VM, and from there the VM's file sharing of the operator's home. This is the residual risk Amendment 1 already accepted for Docker. It is reduced by no bind mounts, non-root, no capabilities and seccomp, but not removed.
2. **Self-reported test results.** A test suite runs in the same process as its runner, so malicious tests can forge their own pass. Mitigated by:
   - the fresh-context AC-coverage critic and code reviewer;
   - mutation testing, whose score the gate computes;
   - the live verifier in 10a, which does not trust the suite.

   It is not prevented.
3. **Install scripts.** Where a dependency needs its install script, that script runs with registry egress during the install step, without secrets.
4. **Resource and timing side effects.** Heavy runs slow the operator's machine. The limits bound this; they do not remove it.
5. **Registry trust.** Dependencies come from public registries as the product's lockfile pins them. Integrity hashes protect against tampering in transit, not against a malicious published version. The phase-9 scanners (OSV, Trivy) are the control.
6. **Live-tier blindness to production.** The internal network prevents reaching production, so problems that only exist in production are not seen. That is intended; phase 11's smoke tests and uptime checks cover it.

## 6. Questions for the operator

1. Is Docker (or Podman) a hard requirement for every executing gate, failing closed without it? Or is a Linux-VM-only mode acceptable?
2. Which base images? Proposed: official `node:24-slim` and `python:3.12-slim` by digest, `ghcr.io/zaproxy/zaproxy` (pinned in 7b), and a Playwright/Chromium image by digest. Each needs its licence read.
3. Testcontainers: rootless Docker-in-Docker (or sysbox) for the integration tier, or refuse Testcontainers-based gates and require compose-defined services?
4. JS and TS configurations: refuse them for LikeC4 (JSON only)? And for dependency-cruiser, keep `.dependency-cruiser.cjs` (executed in the container) or require JSON?
5. Are the default resource limits in 3.5 acceptable, and may a product raise them (at most 2×) through ADOPT?

## 7. Not built (by instruction)

None of the executing gates, the confined runner, the Linux tools cache or the image pins is built in 7b. The merged product-plus-feature validators are also not built. Both are listed as remaining work in docs/increment-7b-report.md.
