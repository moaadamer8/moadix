# Increment 7c: Part 1 (guard restructure, 0.5.2) and Part 2 (confined runner, partly built, 0.5.3)

2026-11-14. Two local commits. Nothing was pushed, tagged or installed.

- **Part 1:** complete, committed on its own as **0.5.2** (`0b58e36`).
- **Part 2:** **stopped on a conflict** with ruling 2 (base-image licences, section B.1).
  - Built and committed as **0.5.3**: everything that does not need a base image.
  - Not built: the executing gates. **0.6.0** is held back until they exist.

## Part 1: main-branch guard restructured (0.5.2)

### 1. gh and firebase allowlists

`gate/mainguard.py` now holds allowlists that fail closed: a subcommand or flag not on the list is refused. Both tools may run **only when typed directly as the whole command**, because `excludedCommands` takes only a command that *starts with* `gh `/`firebase ` out of the sandbox. Every other form is refused, with a negative test for each (`tests/mainguard`):

- `sh -c`, `bash -lc`, `eval`;
- `env` and `VAR=` prefixes; `command`, `exec`, `time`;
- full and relative paths;
- `xargs`, `find -exec`, `npx`/`pnpm`/`yarn` runners;
- aliases;
- pipes in and out, `&&`/`;`, background `&`, subshells;
- `$(...)`, backticks, variables;
- every redirection and here-string;
- scripts that call them: `sh x.sh`, `./x.sh`, `source`, `node x.js`, `npm run`/`npm test` package scripts.

| Tool | Allowed | Refused (tested) |
|---|---|---|
| gh | `pr create/view/list/diff/checks/status/comment`, `run list/view/watch`, `issue list/view/create/comment`, `repo view`, `auth status` (no `-t`/`--show-token`), `api` with GET only, `--help`, `--version`.<br>`--body-file`/`-F`/`--template` only from files inside the repository. | `auth token/login/refresh/setup-git`, `auth status -t`, `config`, `secret`, `variable`, `ssh-key`, `gpg-key`, `repo delete/edit/rename/archive/create/sync`, `release`, `workflow run/enable/disable`, `ruleset`, `pr merge/checkout`, `alias`, `extension`, alias names.<br>`api` with POST/PUT/PATCH/DELETE, with fields but no `-X GET` (gh would POST), `graphql`, `--input`.<br>Body files outside the repository or from stdin. |
| firebase (my proposal) | `--version`, `help`; `projects:list`, `login:list`.<br>With an explicit `--project` that is neither protected nor a `.firebaserc` alias of a protected project: `deploy`, `hosting:channel:deploy` (no `--force`, no `predeploy`/`postdeploy` hooks in `firebase.json`, because firebase runs them as shell commands outside the sandbox), `hosting:channel:list`, `hosting:sites:list`, `apps:list`, `functions:list`, `functions:log`, `firestore:indexes`.<br>`emulators:start`/`serve` only with `--only` limited to auth, firestore, database, hosting, storage, pubsub, eventarc, ui. | `firestore:delete`, `database:remove/set/update/push`, `functions:delete`, `hosting:disable`, `auth:import`, `auth:export`, `functions:config:*`, `functions:secrets:*`, `login`, `login:ci`, `logout`, `use`, `init`, `emulators:exec`, `ext:*`, `--token`.<br>The functions emulator, which runs product code outside the sandbox.<br>Any project command with no explicit project (the `.firebaserc` default may be production).<br>Every project command when no overlay is installed. |

### 2. Nothing product-specific in the public repository; the local overlay

- **Removed from `managed/managed-settings.json`:** the production project deny rule and the nine product hosts. tests/install checks the template carries no product host or project id.
- **The overlay.** `~/.config/moadix/overlay.json` (or `$MOADIX_OVERLAY`), outside the repository.
  - **Format.** Documented in `docs/INSTALL.md` "Local overlay", with placeholders only.
  - **Validation.** `managed/render_policy.py --overlay` validates it: version 1, two keys, project ids, plain host names. It refuses a Markdown link, a scheme, a whole top-level domain and unknown keys, all tested.
  - **What it renders.** One deny rule per protected project, the hosts appended to the allowlist, and `--overlay-out`, the root-owned copy the guard reads (`<gate>/config/overlay.json`, gitignored).
  - **Installer.** `managed/install.sh` shows the overlay and asks before applying it.
  - **Write protection.** The overlay path is write-protected for the agent (sandbox `denyWrite`, path map).
- **The 7b report** quoted the production project id. It is redacted in the working copy (committed in 0.5.2). The id is still in the **local, unpushed** history of `3be1bb4`. I did not rewrite history. If you want it gone before you push, that is your call (an interactive rebase or a fresh squash of the unpushed commits).
- **Overlay values.** You asked for your actual overlay values in this report, which is committed to the public repository. That conflicts with "nothing product-specific in the public repository". I followed the second rule: the values are in my reply in chat, not in any committed file.

### 3. The hosts were plain strings

- **Before 0.5.2.** In the file as it stood, every host was a plain JSON string, for example `"<a product host>",`. The link you saw in your paste was chat rendering.
- **Now.** The template keeps no product hosts. tests/install checks every allowlist entry is a plain host-name string, and the overlay validator refuses a Markdown link.

### 4. `docs/mainguard.md`

It contains:

- your change request and your four decisions;
- what the guard refuses;
- both allowlists;
- the accepted risks, including that every allowed host can carry data out.

**One limit:** the agent cannot read Claude Code transcripts (read-denied by MOADIX's own policy), so the request is recorded from this session's notes, with your quoted phrases kept. It is not a verbatim copy.

### 5. The phase-11 GitHub token, and gh outside the sandbox

There is no conflict with the ruling:

- **Where the token lives.** The phase-11 token (Keychain item `moadix-github-readonly`) is read only by the gate (`gate/ghmcp.py`, `toolrun.github_token`) and is never in the agent's shell.
- **What gh uses.** gh outside the sandbox uses **its own** login, a separate credential you granted in decision 1. gh has no reason to read MOADIX's item, and no allowlisted subcommand can be made to read it: `config`, aliases and extensions are refused.
- **What I found and closed.** The sandbox did **not** read-deny the CLIs' own credential stores. The agent could have read `~/.config/gh/` and `~/.config/configstore/firebase-tools.json` (firebase keeps its refresh token there) from Bash or the Read tool. 0.5.2 adds both to sandbox `denyRead` and to managed `Read()` deny rules. gh and firebase themselves run outside the sandbox and still reach them. I did not open either file.
- **What stays.** Allowlisted gh commands act on GitHub as you (decision 1, accepted risk 2 in `docs/mainguard.md`).

### Part 1 tests

- mainguard: **281/281** (was 163). The new allowlist group has 125 checks: allowed forms, refused subcommands, every evasion, scripts, firebase with and without the overlay, aliases of production, deploy hooks.
- render: **29/29** (overlay merge, absent overlay, 7 malformed overlays, no product strings, credential read-deny).
- All other suites green.

## Part 2: increment 7c (0.5.3)

### B.1 Conflict: stopped

**Ruling 2: base-image licences.** Each image's licence was read inside the image (`/usr/share/doc/*/copyright`):

| Image | Licences found |
|---|---|
| `node:24-slim` (`sha256:dc26ae92…`) | bash GPL-3+, coreutils GPL-3+, glibc LGPL-2.1+ |
| `python:3.12-slim` (`sha256:5e2bdb1b…`) | the same Debian userland |
| ZAP (`sha256:030d3df5…`) | Debian with OpenJDK (GPL-2.0 with Classpath exception) |
| Playwright/Chromium (not pulled) | Ubuntu base |
| official Postgres | Debian base |

Ruling 2 allows only "permissive or MPL-2.0-unmodified", so **every proposed base image is stopped**.

- **Why no image can pass.** Any Linux userland that runs Node or Python carries GPL or LGPL components. distroless/static has none, but it has no runtime.
- **Consequence.** No executing gate can run, so none was built: pytm, LikeC4, dependency-cruiser, knip, ESLint, tsc, Stryker, Schemathesis, the test suites, ZAP, Lighthouse CI, axe.
- **How they fail closed.** The images are recorded in `gate/config/confinement.yaml` with `status: blocked` and the reason, so a gate that needs one would report UNKNOWN. The gates are not registered, so no phase is blocked by them yet.

**Your ruling is needed:** accept GPL/LGPL components in base images that are pulled unmodified by digest and never vendored (as ruling 3 did for MPL-2.0), or name another source.

**Also measured (not a conflict):**

- `docker` commands work only when the command *starts with* `docker` (`excludedCommands`). A sandboxed test process (`python3 tests/...`) cannot reach the Docker socket.
- So real-engine tests of the runner must run from Terminal, like the corpus.
- The gate itself runs outside the sandbox (hooks and worker) and is unaffected.

### B.2 What was built

| Item | What |
|---|---|
| Design gaps | `docs/confinement-design.md` §3.8 and §3.9 (B.4). |
| Confined runner | `gate/confined.py` and `gate/config/confinement.yaml`, the policy of the design, with section 3.5's tiers and limits. The engine-call path `run()` (volumes, `docker cp` with no host bind, run, copy-out, cleanup) is written but **untested against an engine**: images are blocked, and the sandboxed suite cannot reach Docker. |
| Limits | A product may raise them to at most 2× through ADOPT (`product-tools.yaml limits:`). Unknown keys are refused. |
| Install scripts | Ruling 6: only packages listed in the adopted product-tools.yaml `install_scripts`. |
| `docker run` argv | uid 10001, `--cap-drop ALL`, `no-new-privileges`, `--read-only`, size-capped tmpfs, `--network none` or the run's internal network, the limits, a read-only named `/src` volume and one `/out` volume. It refuses host paths, the Docker socket, non-gate volumes and other networks, and builds the environment from scratch (secret-looking names refused). |
| Compose | `compose_project`: the product's file is never run. Allowlisted keys go into a gate-generated, hardened project on an `internal` network. Refused: privileged, cap_add, devices, host network/PID/IPC, user, security_opt, extra_hosts, volumes_from, host-path and socket volumes, external volumes, non-loopback ports, top-level networks, undigested images, secret-looking env, non-test hosts. |
| Image build | `dockerfile_problems` and `build_argv`: FROM by digest or stage only; no secret or ssh mounts; no `ADD <url>`; `--network none` by default; `build.network: registry` through the egress network with the classic builder; secret-looking build args refused. |
| Output | `check_output` and `read_json_output`: no links, devices or oversize; a report must parse, never a "PASS" line. |
| Docker | Ruling 1: Docker missing or the engine unreachable gives UNKNOWN. |
| Amendment | Ruling 3: Testcontainers removed from the amendment's table and the pins (one-line reason); TS6 now names gate-started service containers. Ruling 4: H20 and the phase-3 gate name `.dependency-cruiser.json`, JSON only, and LikeC4 JSON-only, in the amendment, the catalogue and `/moadix:coverage`. |
| **Merged product-plus-feature validators** | `check-merged-<0,1,2,3,4,5,6b>` (feature scope) run the product's own document validators (check-handoff, check-profile, check-threat-model, check-lld, check-provisioning) on an export of HEAD with the feature's additions merged exactly as APPROVE 11 would. A collision fails, and so does any addition the full validator rejects. Onboarded products report N/A (question C.3). |

The merged view immediately found **a real bug**. `check_threat_model.py` used `zip(..., strict=False)`, which crashes on the system Python 3.9, so a product threat model with SEC-IDs never validated at all. It is fixed.

### B.3 Tests

| Suite | Result |
|---|---|
| **tests/inc7c (new)** | **75/75**. Hostile inputs for every threat in design section 2: T1 secrets (10), T2/T7 mounts and escalation (23), T3/T6 output and forged results (5), T4/T8 network and production (12), T5 resources and install scripts (8), fail closed (6), merged validators (6), rulings (3), guard (1). These test the runner's **decisions**. No container ran (B.1). |
| mainguard | 281/281 |
| gate2 | 299/299 |
| verifiers | 97/97 |
| inc6 | 70/70. Its released-product fixture had to become complete enough for the product validators: research log, threat-model verification methods, shared-resources section. |
| inc7 | 119/119 |
| inc7b | 58/58 |
| tools | 107/107, 2 skipped (loopback) |
| skills | 43/43 |
| release | 9/9 |
| render | 29/29 |
| corpus | guard self-test 18/18. Please rerun the full corpus in Terminal. |
| static | clean |

### B.4 Design gaps closed

- **Gap 7 (compose).** The gate **generates** the compose project from an allowlisted schema and refuses every other key (§3.8). Ports are never published. The gate's own service catalogue provides Postgres and others, with per-run credentials, on the internal network. No Docker socket, ever.
- **Gap 8 (image build).** Confined like this (§3.9):
  - the context is the export streamed as a tar;
  - FROM by digest only;
  - no secrets, no SSH, no host mounts;
  - `--network none` by default, or registry-only through the egress proxy when declared.

  Accepted risks: `RUN` steps run as root inside the builder container; with `build.network: registry`, the registries are a channel out.

## C. Open questions for the operator

1. **Base-image licences (blocking).** Accept GPL/LGPL components in base images that are pulled unmodified by digest and never vendored? If yes, I pin `node:24-slim`, `python:3.12-slim`, a Playwright image, Postgres and ZAP by digest and build the executing gates. If no, which images?
2. **0.6.0** is reserved for when the executing gates exist. Is 0.5.3 right for this partial step?
3. **Merged validators on onboarded products.** The baseline's documents follow the baseline shape, not the greenfield validators. Keep N/A, or run check-baseline's completeness rules on the merged view?
4. **History.** The production project id is in the unpushed commit `3be1bb4`. Do you want to rewrite the unpushed history before your first push?
5. **The firebase allowlist** above is my proposal. Confirm or adjust it.

## D. What the operator must do by hand

1. Create `~/.config/moadix/overlay.json` with your values (they are in my reply).
2. Close every Claude Code session. Then, in Terminal: `cd ~/moadix && managed/install.sh`, confirm the overlay, and expect `MOADIX is updated.`
3. In a new session, run the live check in `docs/INSTALL.md` (12 rows).
4. In Terminal: `/usr/bin/python3 tests/corpus/run.py` and `/usr/bin/python3 tests/install/dryrun.py`.
5. Rule on C.1 so the executing gates can be built.
