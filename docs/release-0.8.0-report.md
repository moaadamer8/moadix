# 0.8.0: the first product's phase 9 (MF-56 to MF-59)

**Source.** The first product's phase 9 on 0.7.9 (task-tracker `docs/moadix-findings.md`, MF-56 to MF-59):

- **MF-57.** The app never listened in any live gate, because the database never started. `confined.Run.execute` replaced every container's PATH with `/usr/local/bin:/usr/bin:/bin`. The official postgres image keeps `initdb` and `postgres` in `/usr/lib/postgresql/17/bin`, which only its own PATH names, so its entrypoint exited 127 (`initdb: command not found`).
- **MF-56.** The evidence showed none of this. When the gate's wait loop gave up (exit 3), `run_logs` kept only the tool container's files, which held the one wait line.
- **MF-58.** `check-security` requires a `### SEC-nnn` heading in `09-security-report.md` for each SEC-ID. trace-lint counted each such heading as a second definition, so no report could pass both checks.
- **MF-59.** gitleaks rated the test-fixture passwords high, both in the tree and in the history. A high finding cannot be waived, and rewriting the history would break the ledger's approvals by commit.

The two 0.7.9 fixes (an unlabelled-image fix and a duplicate-network fix) are kept as built.

## The fixes

**MF-57: each image keeps its own PATH.**
- `confined.run_path(image_path, first=None)` builds the run's PATH in this order:
  1. a gate service's own directories (`confinement.yaml services.<name>.path`);
  2. the image's own PATH, in its order;
  3. the gate's entries (`RUN_PATH`) that are not already there.
- An image PATH that is not a list of absolute directories is never used, and the gate's entries alone apply. That covers an empty PATH, a relative entry, `.`, `..`, a variable or a space.
- `Run.image_path(img)` reads the PATH from the engine (`image inspect --format '{{json .Config.Env}}'`), once per image. It pulls an image the engine does not have yet first, as `docker run` would.
- This applies to every container: product services, the gate's own services and tool images (ZAP keeps `/zap/`).

**MF-56: a failed wait keeps the stack's own output.**
- When a live gate's script wrote `wait.log`, the gate calls `Run.service_output()` before its cleanup. For each `moadix-<id>-svc-<name>` container, that gives:
  - its state and exit code;
  - the last 400 lines of its stdout and stderr.
- `run_logs` adds a `--- service <name> (<state>; ...)` section for each one, bounded and redacted like the tool's own logs.
- The one-line failure names the services, stopped ones first, with their first error. For example: `services: app exited 1 (DATABASE_URL is not set), db running`.
- A run whose app listens adds nothing.

**MF-58: a SEC heading in the security report is a reference.**
- `contract.REFERENCE_HEADS = {"09-security-report.md": ("SEC",)}`. In that report, whether the product's or a feature cycle's, a `### SEC-nnn` heading is not a definition. trace-lint's reference scan still counts it, so a SEC-ID that the threat model does not define is reported as dangling.
- A SEC heading in any other document is still a second definition.
- `check-security` is unchanged.

**MF-59: an operator-reviewed gitleaks allowlist for test fixtures.**
- The allowlist lives in `product-tools.yaml` under `gitleaks: allow:`. Each entry has exactly these four keys:
  - `fingerprint`: gitleaks' own form, `<40-hex commit>:<path>:<rule>:<line>` for a history finding or `<path>:<rule>:<line>` for a tree finding;
  - `path`: it must equal the fingerprint's path;
  - `reason`: at least four words;
  - `fixture: true`.
- The path must be a file under `tests/` or under a `fixtures`/`__fixtures__` directory. A path with a `src` directory, a glob, `.` or `..` is refused.
- An entry with no fingerprint is refused, which also refuses a whole rule or a whole path. A repeated fingerprint is refused too. All of this lives in `gate/v1/gitleaks_allow.py`.
- **ADOPT** checks the entries (`adopt._validate_tools`) and refuses the proposal if any entry fails.
- **check-gitleaks** checks them again when it scans, and also requires `product-tools.yaml` to be exactly what ADOPT recorded (`adopt.adopted`). If either check fails, nothing is allowlisted, and each reason is reported as a high finding.
- **Matching:**
  - a finding is allowlisted only when its own fingerprint and path match an entry;
  - an edited fixture (another line) is a new finding;
  - every high finding now prints its fingerprint;
  - the SARIF evidence is unchanged.
- History findings now name their commit. gitleaks puts the commit in `partialFingerprints`, so before this fix they said `HEAD`.
- **REVIEW:**
  - the validator prints an `ALLOWLISTED <fingerprint> <where>: ... (<reason>)` line for each allowlisted finding;
  - `gate/validate.py` collects them from the whole output, and they are never taken as the first line;
  - `validation.summary` shows them under "Allowlisted test-fixture findings, by the operator's adopted allowlist (not blocking)".
- `/moadix:coverage` gets a new generated paragraph, "Phase 9: SEC headings and test-fixture secrets", which explains both rules.

## Tests

- **`tests/rel080`: new, 37 checks.** It uses the real pinned gitleaks for the gitleaks group. With 0.7.9's files restored, each control fails the way the product run did, and the fix checks fail or crash on 0.7.9.
  - **path:**
    - the control: 0.7.9 gives the database the gate's PATH only, and Schemathesis fails;
    - `run_path` order, its refusals, and a service's own directories coming first;
    - the database keeps `/usr/lib/postgresql/17/bin`, and Schemathesis passes;
    - ZAP keeps `/zap/`;
    - the PATH is read with `image inspect`.
  - **logs:**
    - the control;
    - service state and output in the evidence: 3000 lines bounded to the last 400, and a URL password and `password=` redacted;
    - the failure line names the stopped service;
    - no service output when the app listens;
    - lhci behaves the same way.
  - **trace:**
    - the control: "defined 2 times";
    - trace-lint passes, and check-security still finds every block;
    - a dangling SEC heading;
    - a SEC heading in another document is still a second definition;
    - a feature cycle's report.
  - **gitleaks:**
    - the control: two `[high]` findings on 0.7.9;
    - fingerprints;
    - 13 refused entry shapes;
    - ADOPT refuses `src/`;
    - an adopted history and tree entry passes;
    - ALLOWLISTED lines, and the REVIEW summary;
    - an edited fixture fails again;
    - negative cases with a real-looking AWS-format key in `src/`: ADOPT refuses it; written into the file past ADOPT, it is refused at scan time and the allowlist is not applied ("not adopted"); and an adopted `tests/` entry with the same rule and line never covers `src/`.
  - **engine:** the rel080 group is present, and the total is 70.
- **The engine double:**
  - a detached service starts, and a command its PATH cannot find stops it with 127 and the message;
  - `MOADIX_DOUBLE_SVC` stops a service with a given exit and output;
  - a live tool run on a network with a stopped service gives up its wait (`wait.log`, exit 3);
  - it answers `logs --tail`, `inspect` State, and `image inspect` (Config.Env PATH);
  - a built image takes its base image's PATH.
- **`tests/fixtures/smoke-080`** is an overlay on smoke-076. Its database is built FROM the gate's pinned official `postgres:17-bookworm` image, with a read-only root, `PGDATA=/tmp/pgdata` and the socket directory pointing at `/tmp`. The app waits for `db:5432` before it listens, and exits 1 with "DATABASE_URL is not set" without it.
- **`tests/confined-engine`:**
  - new group rel080, 3 checks:
    - the control: the official image, confined with 0.7.9's PATH, exits 127 with `initdb: command not found`;
    - Schemathesis passes on smoke-080 with nothing left;
    - with no `DATABASE_URL`, the evidence holds the app's exit and message and the database's state;
  - `postgres` is pulled with the other images;
  - the secrets check expects the node image's PATH with the gate's entries appended;
  - the total is 70.
- **Earlier suites:** `inc7d`, `rel075` to `rel079` check the new total. `rel075`'s ZAP check expects the image's PATH with the gate's entries, and its services checks read the double's container state: the 0.7.4 postgres run is `exited 127` with the message, and the configured PATH gives `running`.

**Results here:** rel080 37, gate2 299, inc6 70, inc7 141, inc7b 58, inc7c 78, inc7d 150, inc8 72, verifiers 97, release 9, skills 43, tools 107 (2 skipped), rel071 61, rel072 176, rel073 75, rel074 32, rel075 28, rel076 54, rel077 29, rel078 20, rel079 22, mainguard 281, all passed. check-static is clean when uv's tool and cache folders are pointed into the sandbox (`UV_TOOL_DIR`, `UV_CACHE_DIR`); with the defaults the sandbox refuses uv's temporary files.

**Not run here.** The real-engine suite, because the sandbox cannot reach Docker.
