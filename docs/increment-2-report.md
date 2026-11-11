# Increment 2: gate port, report

2026-11-11 · built per DESIGN.md section 7 ("From v1"), build increment 2, and Amendment 1. Nothing was installed. The live gate still runs increment 1 until the operator reruns `managed/install.sh`.

## What was built

| Piece | Where | Notes |
|---|---|---|
| v1 validators, ported | `gate/v1/` (24 modules), `gate/config/` | All 21 validators v1 registered for a phase, plus their helpers. Re-rooted in `hlib`: the product root is the nearest `.sdlc/product.yaml`, and `governed_root` is `""`. The phase doc is derived from the verified ledger. Product config lives in `.sdlc/config/`, harness config in `gate/config/`. The exit-code contract (0 pass / 2 unknown / else fail) and the two-axis scorecard are unchanged. |
| Validator cache | `gate/validation.py`, `gate/validate.py` | REVIEW starts a detached worker. Results go to `.sdlc/cache/validation-<phase>.json`, keyed by commit, clean tree, gate version, `.sdlc` config digest and ledger head. Missing, running, stale or dirty never counts as a pass. |
| APPROVE / REVIEW | `gate/opcmd.py` | APPROVE reads only the cache and refuses with the validators' findings. The signed line carries the results it rests on. REVIEW prints the same results. |
| INIT | `gate/opcmd.py` | `INIT <id> <code>` creates `.sdlc/` at the session's git root and records ledger line 1. Refused inside a product, outside git, or for an id that already has a Keychain anchor. On a refused code, `.sdlc/` is removed again. |
| WAIVE | `gate/opcmd.py` | `owner=`, `scope=` and `expiry=` are required. The expiry may not be in the past or beyond the policy maximum (180 days). A high or critical finding is unwaivable, and a finding whose severity can't be read is refused. |
| PROCEED-PAST | `gate/opcmd.py` | v1's progression rule: requires a fresh, determinate failure. Refused when the validators pass ("APPROVE instead"), are UNKNOWN, or are stale. |
| PARK | `gate/opcmd.py`, `gate/config/trusted-bin.yaml` | Runs only the `docker`/`podman` argv declared under `park:` in `.sdlc/product.yaml`, resolved from root-owned trusted directories, never from PATH. Order: stop, measure, record (counts in the signed line), tag. Refused during a wrong-code pause. |
| Classifier rewrite | `gate/bashcls.py`, `gate/pretool.py` | See below. |
| Path map | `gate/pathmap.py` | v1's frozen phases and most-specific owner restored; shared globs; a distinct reason per class. |
| Hardening found on the way | `managed/managed-settings.json`, `gate/state.py` | Hooks run `python3 -I`. The prompt-hook timeout is 90 s (PARK). Git is `/usr/bin/git`. A hard link to a gate file is an integrity failure. `phase.yaml` render version 3 is re-derived from an older render instead of being reported as drift. |
| Tests | `tests/gate2/`, `tests/lib/`, `tests/fixtures/` | 244 checks; see below. |

## Test counts

| Suite | Where it ran | Result |
|---|---|---|
| Increment-2 suite `tests/gate2/run.py` | this session (sandboxed), stub checker, docker shim | **244/244** in 50 s. Full output: `docs/evidence/increment-2-suite.txt` |
| … guard | | 5/5 (self-tests: a read of an outside product, a non-fixture compose project and a real `docker` exec are each caught; any other violation fails the suite) |
| … classifier corpus | | 62/62 (39 read-only commands from the six v1 false-positive classes get no objection; 23 write-side neighbours are denied) |
| … symlinks / hard links | | 18/18 |
| … denial reasons per class | | 17/17 |
| … increment-1 tool-call cases (stub) | | 48/48 (one expectation changed, below) |
| … port / APPROVE+REVIEW / INIT / WAIVE / PROCEED-PAST / PARK | | 7/7 · 16/16 · 9/9 · 12/12 · 10/10 · 11/11 |
| … v1 defects / upgrade | | 27/27 · 2/2 |
| Increment-1 corpus `tests/corpus/run.py` (real checker, test keychains) | **not run here**: the sandbox blocks Keychain access, and the probe to check was refused | Must run in Terminal. As a pre-check, its operator, invariant, visibility and cooldown groups were driven against the stub (scratch adapter, not committed): **95/96**. The 1 is `checker init → already-initialised`, which only the real checker implements. |
| Install dry run `tests/install/dryrun.py` | not run here (writes `~/moadix-scratch`, keychain) | Updated for `-I` and REVIEW-before-APPROVE; run in Terminal. |
| check-static (ruff + mypy + shellcheck over `gate/`, `managed/`, `checker/`) | this session | clean (part of the suite) |

Measured: APPROVE answers in 0.26–0.33 s and never starts a validator. REVIEW of phase 0 or 1 returns results within its 8 s wait.

## The classifier, against the six v1 false-positive classes

| Class | v1 / increment-1 behaviour | Now |
|---|---|---|
| `git stash list` | (v1) denied as a stash | read-only stash/apply/reset/clean forms allowed; `git stash`, `pop`, `reset --hard`, `clean -fd` denied |
| `*.pem` in a read-only find | pattern read as a path; `-exec` always opaque | `-exec`/`xargs` with a read-only command allowed; `-exec rm`, `-delete`, `xargs rm` denied |
| bare `.` | `cp x .` meant "write the repo root, which contains `.sdlc/`" | writes into a directory are `dir/basename`; `touch .`, `rm -rf .`, `cp evil .` still denied |
| `tar -C` | `-C` always a write target | `-C` is a write only when extracting; `tar -xzf a.tgz` in the root and `-C .sdlc` denied |
| `git checkout` in a scratch copy | every checkout = write to `.sdlc` | refused only for the session's own product; explicit pathspecs judged per path |
| `cd` sweeps | every target checked against every `cd` | `cd` tracked in order (subshells, `pushd`/`popd`, `cd -`); a write under `cd "$d"` is refused as "only known at run time" |

**Symlink gap (increment 1), closed.** `ln -s .sdlc s && echo x > s/ledger.jsonl` is now denied for the link itself: `a link to …/.sdlc would be a second path to protected bytes`. The same goes for hard links (`ln`, `cp -l`, `cp -al`), links to the repo root, `~`, or `~/.claude`, and links with a run-time source. Links made earlier in the same command are followed. An existing hard link to the ledger turns STATUS into INTEGRITY FAILURE, and writes are refused until it's removed.

## Changed from increment 1 (on purpose)

1. **Approved phases are frozen again (v1's rule, which increment 1 dropped).** Writing `sdlc/00-brd.md` after APPROVE 0 is denied until REOPEN 0.
   - This flips one increment-1 corpus expectation (`tests/corpus/run.py`, marked `CHANGED in increment 2`).
   - The rest of that corpus keeps its attacks and expectations. Its fixture gained passing phase 0–2 documents and sends REVIEW before each APPROVE, and WAIVE gained `scope=`.
2. **A glob may belong to several phases** (`tests/**`: 7 and 8; `.github/workflows/**`: 7 and 10b). It is writable in each. The most specific glob decides (`release/assets/**` is 11b, not 11).
3. **Phase maps of other products are not applied from this session.** A scratch `git clone` carries the tracked `.sdlc/` and cannot be told apart from the original. Their `.sdlc/` and every protected class stay denied.
4. **The repo name "moadix" is no longer a protected word** for opaque commands: it matched this repo's own path. The managed home is covered by `ClaudeCode`, and the plugin cache by `.claude`.

## What from v1 did not port cleanly

1. **check-surface-coverage's live probe is off in gate runs.**
   - It asked v1's `run-product-app.sh` whether the app was running, then sent HTTP requests to it. v2 has no such front door yet, and a gate run must not touch the live product.
   - Its enumerator (product code) runs under a deny-all-writes, no-network `sandbox-exec` profile, and fails closed without one.
   - That profile is **unmeasured**: `sandbox-exec` refuses to nest inside this session's sandbox. It will apply in the real hook, which runs outside the sandbox.
2. **check-seam's BMAD-adapter half** waits for increment 3 (BMAD isn't vendored yet). Only the path-map half runs.
3. **build-scorecard (phase 11)** is ported and runs, but parts read v1-only history:
   - `git log -S` on `harness/registry.yaml`, and v1's `approval_sha`/`approval_dirty` fields. In a v2 product repo those come back UNKNOWN, so phase 11 will fail closed until they are re-pointed at the ledger.
   - No phase-11 fixture exists yet.
4. **Size-profile collapse** (`hlib.collapsed_phases`) is not in the ledger replay. A phase the BRD's size collapses is still a phase to approve or proceed past.
5. **Transition mode** (`check_transition`, the WEB→APP workspace) and v1's harness self-checks were not ported, because they check v1's own repo layout. These are `exec-surface`, `control-coverage`, `coherence`, `proposal-declares`, `patch-applied`, `retro`, `constitution-size` and `registry-shipped-status`.
6. **WAIVE without a phase-9 report.** v1 refused *every* waiver when `09-security-report.md` couldn't be read, which made waivers impossible before phase 9. v2 refuses only finding-shaped ids (`SEC-n`/`SF-n`), following v1's own P50 scoping.
7. **check-lld** still provisions PyYAML and openapi-spec-validator with `uv` at validation time, as v1 did. The first REVIEW 5 downloads them.
8. **Product config has no typed command.**
   - `.sdlc/config/*.yaml` (surface, tests, concurrency, mobile, exemptions) and the `park:` section of `.sdlc/product.yaml` are gate-owned.
   - Only the operator can write them, in Terminal.
   - Proposal for a later increment: an `ADOPT <file> <code>` command.

## Residual risks, stated plainly

- **The validator cache is not signed.** Something that can write `.sdlc/` (a Docker mount outside the hook's checks) could plant a "pass" with a matching key. APPROVE would still need the operator's code, and REVIEW prints what it rests on.
- **PARK stops and measures before the code is checked.** The counts must be in the signed line, so measuring has to come first. A wrong code therefore leaves the stack stopped with nothing recorded (it says so). PARK is refused during a wrong-code pause.
- **PARK runs `.sdlc/product.yaml` commands outside the sandbox.** They are limited to docker/podman from root-owned directories. `product.yaml` itself is unsigned: the hook, the sandbox's `.sdlc` rule and the hard-link check protect it.
- **gitignored files are not part of the cache key.** For example, test results a validator reads.

## Updating the live gate (operator, in Terminal)

1. Close every Claude Code session.
2. `cd ~/moadix && git log --oneline -1` (note the commit).
3. `managed/install.sh`. It detects the existing install, asks for your password once, re-copies the gate (now including `gate/v1/` and `gate/config/`), rewrites the policy (`python3 -I`, 90 s prompt timeout) and re-runs its checks. The checker binary did not change, so your key and ledgers are kept.
4. `/usr/bin/python3 tests/corpus/run.py`. This is the increment-1 corpus against the real checker and test keychains (writes under `~/moadix-scratch/corpus`).
5. Optional: `/usr/bin/python3 tests/install/dryrun.py`.
6. Open a new session in `~/moadix-scratch/live-demo` and type `STATUS`. Expect `INTEGRITY OK`; the first STATUS re-derives `phase.yaml` (render version 3).
