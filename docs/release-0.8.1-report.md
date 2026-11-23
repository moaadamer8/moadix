# 0.8.1: the first product's phase 9 (MF-60, MF-62 to MF-65)

**Source.** The first product's phase 9 on 0.8.0 (task-tracker `docs/moadix-findings.md`, MF-60 and MF-62 to MF-65), MF-52 from phase 7, and the 0.8.0 real-engine run:

- **MF-63.** A findings log quoted a test fixture's password. gitleaks flags the quote in the history for good, and 0.8.0's allowlist accepts only paths under `tests/` or a fixtures directory.
- **MF-65.** check-security's own secret scan did not read the adopted allowlist, and its message asked for a v1 waiver (`rule: security`, `path`) that no operator command records.
- **MF-64.** check-surface-coverage ran the product's enumerator with the validator worker's PATH, which holds no node: `execvp() of 'node' failed`.
- **MF-60.** Schemathesis's ST201 refuses only 400, 401, 403, 404, 405, 406, 409, 415, 422, 428, 429 and 5xx. The app refuses an oversized body with 413, as its contract documents, so every form whose field limit equals the body limit failed.
- **MF-62.** The validator worker ran check-verifiers when it started. The critics, launched seconds earlier, wrote their evidence a minute later; the stored result said MISSING and nothing read the evidence again.
- **MF-52.** A gap critic's fix of more than 1,000 characters made the whole CRITIC.json fail the schema, so its BLOCKERs were not read.
- **Engine run.** The official postgres image declares `VOLUME /var/lib/postgresql/data`. Each live run left that anonymous volume: it carries no label, and the gate removed containers with `rm -f`.

## The fixes

**MF-63: a quote of a fixture's value** (`gate/v1/gitleaks_allow.py`).
- An entry may name `same-value-as: <fingerprint>` in place of `fixture: true`: `{fingerprint, path, reason, same-value-as}`, exactly those keys.
- The fingerprint it names must be a `fixture: true` entry of the same list, under `tests/`.
- Its own path may be any file except one under a `src/` directory or configuration: a configuration directory (`config/`, `conf/`, `settings/`, `deploy/`, `infra/`, ...), a dotfile or dot-directory (`.env`, `.github/`), or a configuration file (YAML, TOML, JSON, INI, `.env`, Dockerfile, compose, `*.config.*`, `env*`, ...). A glob, `.`, `..`, no fingerprint or a reason under four words is refused.
- ADOPT checks the entries; check-gitleaks checks them again and requires `product-tools.yaml` to be what ADOPT recorded.
- **Matching** (`check_scanners.secret_digests`): when the allowlist has such an entry, the gate runs gitleaks a second time, unredacted, into a private scratch directory, keeps only the sha256 of each finding's secret by fingerprint, and deletes the report at once. A quote is allowlisted only when its digest equals the named fixture finding's digest in the same scan. The value is never printed or kept; the SARIF evidence stays redacted.
- Otherwise the finding stays `[high]`, with the reason: `not the value of the fixture finding`, `was not found by this scan`, or `not an adopted test fixture under tests/`.
- Its ALLOWLISTED line says `the same value as the adopted test fixture <fingerprint>`.

**MF-65: one allowlist for both secret scans** (`gate/v1/check_security.py`).
- `gitleaks_allow.adopted_allowlist(root, reader)` is shared by check-gitleaks and check-security.
- A scan hit at `path:line` is covered by a tree entry for that path and line: a `fixture: true` entry under `tests/` or a fixtures directory, or a `same-value-as` entry when the value assigned on that line is one assigned at the fixture finding it names (read from the tree, or with `git show` for a history fingerprint).
- Each covered hit prints an ALLOWLISTED line (REVIEW collects it as for gitleaks). An allowlist that is not adopted is not applied, and the note says why.
- The SECRET DETECTED message now names the allowlist instead of a waiver.

**MF-64: the gate's Node for the enumerator** (`check_surface_coverage.enumerator_env`). The pinned Node's directory (`toolrun.node()`, the tools cache) goes first on the enumerator's PATH. Without a pinned Node the enumerator still runs, and its failure names the missing tool. The product names no machine path.

**MF-60: refusal statuses by ADOPT** (`gate/v1/st_refusal.py`, `gate/exec/st_config.py`).
- `product-tools.yaml`: `schemathesis: {refusal-statuses: [413]}`. Only 4xx statuses that Schemathesis does not already count, at most 4, no repeats, no other key. ADOPT refuses anything else; check-exec refuses it before any engine call.
- Inside the confined run, before Schemathesis, the gate's own `st_config.py` (mounted read-only at `/gx`) reads the contract with Schemathesis's own YAML and writes `/tmp/st.toml`: one `[[operations]]` block per operation whose `responses` document a listed status, selected by `include-name = "POST /path"`, with `checks.negative_data_rejection.expected-statuses` set to Schemathesis's own list plus that status. Schemathesis then runs with `--config-file /tmp/st.toml`. If the configuration cannot be written, the run fails (`run.rc` 97).
- Measured on the pinned 4.32.7: `include-path` and `include-method` together are OR'ed, so they would select every POST; `include-name` selects exactly one operation.
- Without the setting, the run is unchanged.

**MF-62: stale, never missing** (`gate/verify.py`, `gate/v1/check_verifiers.py`, `gate/validate.py`).
- A verifier with a current brief and schedule but no evidence is `pending`: check-verifiers prints `STALE ... launched at <time> and has not written its evidence yet` and exits 3 when that is its only problem. A verifier never launched at the commit is still MISSING.
- At the end of its run, the validator worker runs check-verifiers again (unless it passed and no verifier evidence changed or is pending), after waiting up to `VERIFIER_WAIT` (1,200 s) for every pending verifier. The result's key takes the verifier evidence it read, so REVIEW finds it fresh.
- A verifier still not written by then leaves the row `stale` (REVIEW shows STALE; `validation.findings` lists it). PROCEED-PAST refuses a stale result ("send REVIEW again"), and APPROVE refuses it as before.
- Only a test fixture's gate copy may shorten the wait (`MOADIX_TEST_VERIFIER_WAIT`).

**MF-52: a long fix is cut** (`contract.truncate_fixes`). Before the schema check, a fix longer than the schema's `maxLength` (1,000) is cut so that, with the marker `[... cut by the gate: the fix ran <n> characters over the 1000-character limit]`, it fits. A MINOR note records the cut. The gap critic's brief now states the limit.

**Anonymous volumes** (`gate/confined.py`). Every container removal is `rm -f --volumes` (`_rm_own`, `_remove_label`; the long form of `-v`, which inc7d's host-mount guard would read as a bind mount), so an image's VOLUME goes with its container. Named volumes are still removed by label.

## Tests

- **`tests/rel081`: new, 44 checks here (45 in Terminal).** Controls run 0.8.0's files (`git show c39a878:...`). Run against an export of 0.8.0 with only the new tests, 26 of 34 fail: every fix check fails or crashes (the 8 that pass are refusals 0.8.0 already made, the engine suite's plan, and the guard). (The controls cannot run in that export: it has no 0.8.0 history to restore from.)
  - **gitleaks** (real pinned gitleaks): the 0.8.0 control; a quote entry in `docs/` or `README.md` accepted; 18 refused shapes; ADOPT refuses `src/`; without the entry the docs history hit is `[high]`; with it check-gitleaks passes, with the ALLOWLISTED line and no value printed; a quote of another value fails `[high]` in history and tree; an entry written past ADOPT is not applied.
  - **security:** the control; the fixture and its docs quote pass; the ALLOWLISTED lines; the same value in `src/` and another value in `docs/` are still found, and the message names the allowlist; an edited allowlist is not applied.
  - **surface:** the control (no node); the enumerator runs with the pinned Node; the PATH entry is the tools cache's Node; under real `sandbox-exec` (Terminal only; skipped inside Claude Code, where sandbox-exec cannot nest).
  - **st201** (real pinned Schemathesis, in-process through WSGI): the control (both operations fail ST201 on 413); st_config.py selects only the operation that documents 413; with its configuration only the operation whose contract lacks 413 still fails; 9 refused shapes; ADOPT refuses 200 and records 413; through the engine double, the 0.8.0 control, the confined script and `/gx` mount, a refused status stops the gate before any engine call, and no setting changes nothing.
  - **verifiers:** the control (MISSING); STALE with exit 3; the worker waits for a critic that writes 4 s later and passes, fresh for REVIEW; a critic that never writes leaves the row stale, never MISSING; the wait is bounded and only fixtures may shorten it.
  - **volumes** (engine double): the 0.8.0 control leaves one anonymous volume; 0.8.1 leaves none, and every `rm` has `--volumes`; named volumes are still removed.
  - **critic:** the control (schema error, no BLOCKER); the BLOCKER is read; the MINOR note; the kept text fits with the marker; the brief states the limit.
  - **engine:** the rel081 group, and the total of 73.
- **The engine double:** an image's VOLUME (postgres) gives a container an unlabelled anonymous volume, which `rm --volumes` (or `-v`) removes and `rm` leaves.
- **Fixtures:** smoke-076's app gains `POST /notes`: a body over 38 bytes (`title=` plus the 32-character field limit) is 413, a wrong content type 415, an invalid form 400, other methods 405. The new smoke-081 overlay's contract documents that route with 413.
- **`tests/confined-engine`:** new group rel081, 3 checks:
  - the control: a postgres container removed without `--volumes` leaves its volume, and one removed with it leaves none;
  - Schemathesis passes on smoke-081 with `refusal-statuses: [413]` and leaves no volume;
  - without the setting, the same run fails ST201 on `POST /notes`.
  The total is 73.
- **Earlier suites:** `inc7d` and `rel075` to `rel080` check the new total.

**Results here:** rel081 44 (1 skipped: real sandbox-exec), rel080 37, gate2 299, inc6 70, inc7 141, inc7b 58, inc7c 78, inc7d 150, inc8 72, verifiers 97, release 9, skills 43, tools 107 (2 skipped), rel071 61, rel072 176, rel073 75, rel074 32, rel075 28, rel076 54, rel077 29, rel078 20, rel079 22, mainguard 281, all passed; check-static clean (uv folders in the sandbox). Changed expectations: `verifiers` (a launched verifier with no evidence is STALE, exit 3, not MISSING), `inc7d` and `rel075`–`rel080` (total 73).

**Not run here.** The real-engine suite, because the sandbox cannot reach Docker. The enumerator under real `sandbox-exec`, because it cannot nest inside this sandbox.
