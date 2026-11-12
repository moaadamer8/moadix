# Increment 6: feature cycles, onboarding, the deferred BMAD items

2026-11-12. Built per DESIGN.md Amendment 2 and the rulings on increment 5. Plugin 0.4.0. Nothing was installed, pushed or tagged: the live gate still runs 0.3.0 until the operator reruns `managed/install.sh` (section 6).

## 1. Rulings on increment 5, as applied

| # | Ruling | What changed | Where |
|---|---|---|---|
| 1 | An unconfirmed Claude Security finding is not unwaivable | An unconfirmed finding keeps the plugin's severity, marked `confirmed: false`. It blocks phase 9 until one of two things happens:<br>• the new fresh-context verifier `moadix:sf-triager` assesses it as `confirmed` or `rejected`, citing `path:line` that resolves at HEAD;<br>• the operator waives it with a reason.<br>A rejected finding stops blocking. A confirmed one is judged by severity (the higher of the plugin's and the triager's). Confirmed critical, high and unknown stay unwaivable.<br>The triager is scheduled only in phase 9, only while the scan result for HEAD holds unconfirmed findings. Its brief lists them; its required paths are their files. | `gate/secscan.py` (`judge`), `gate/verify.py` (`when: unconfirmed`, `triage` evidence), `gate/v1/check_claude_security.py`, `gate/opcmd.py` (WAIVE), `agents/sf-triager.md`, `verifiers.yaml` |
| 2 | GitHub token deferred, read from the Keychain by the gate | `plugin.json` starts the `github` MCP server through `gate/ghmcp.py`. The launcher reads Keychain item `moadix-github-readonly` and passes the token to that one process only. Without a token it exits with "needed only once a product reaches phase 11".<br>check-release and the launcher share `toolrun.github_token()`.<br>INSTALL.md no longer asks for the token at install, and says never to `export` it. | `gate/ghmcp.py`, `gate/v1/toolrun.py`, `docs/INSTALL.md` |
| 3 | Live checks move into the toy run | No live claim is made here. Claude Security, the Playwright verifier and the phase-11 GitHub check are still stub-tested only (section 5). | — |
| 4 | Installer: Permission-denied flood; last line | The root-run tool fetch now writes only into `$rootwork`: created by root with `mktemp`, with TMPDIR and the npm cache inside it, and removed by root right after the fetch (and by the trap, `-n`, without prompting).<br>Cleanup runs silently before the final message. The last line is `MOADIX is updated.` (or `installed.`). | `managed/install.sh`; `tests/install/dryrun.py` now checks the last line and an empty stderr |
| 5 | SessionStart drift check | A managed `SessionStart` hook computes the effective `enabledPlugins` (user, then project, then local settings, then the managed policy, which wins). It reports any enabled plugin other than moadix and claude-security, as a `systemMessage` for the operator and as context for the agent. It never blocks a session. | `gate/session.py`, `hook.py session`, `managed/managed-settings.json` |

## 2. What was built (Amendment 2)

### A. Feature cycles

| Item | What |
|---|---|
| `FEATURE <id> <code>` | Starts a cycle when the product has an approved baseline: phase 11 approved (released) or, onboarded, B approved.<br>Refused when:<br>• a feature is active (one at a time);<br>• the id was used before;<br>• the baseline is not approved. |
| Ledger and replay | Every phase line during a feature carries `payload.feature`. The replay keeps the product's phases and each feature's 16 phases apart. `phases`/`current_phase` are the scope in force.<br>`.sdlc/features/<id>/phase.yaml` is derived from the ledger, drift-checked like `.sdlc/phase.yaml`. Render version 4: older files are re-derived. A feature closes when all its phases are done. |
| Path map | In a feature, each product document glob `sdlc/X` becomes `sdlc/features/<id>/X`; code globs are unchanged. The product's documents are denied with their own reason ("approved product document … frozen"), and so are other features' folders. |
| Validators | Registry components gain `scope`: `product` (default), `feature` or `both`.<br>• `both`: the code, tool and verifier checks (contracts, env, the four scanners, claude-security, verifiers 6/7/8/10a, live probe, Arazzo, load, release).<br>• `check-feature-<phase>` (16 entries) runs in feature scope only.<br>Validation results carry the scope in their key, so a feature's phase 3 never reuses the product's. |
| check-feature (`gate/feature.py`) | Cumulative up to the phase. It checks:<br>• each phase's addition document is present (Research and Store Release optional);<br>• no ID the product defines is reused: BG, US, NFR, **SEC**, TB, T, CON, SR;<br>• stories trace to a product or feature goal, with EARS acceptance criteria;<br>• a new SEC-ID names an existing trust boundary and a mitigation;<br>• the LLD mentions every feature story; every story has a task, and tasks cite real SEC-IDs; the test report covers every feature AC; the security report covers every feature SEC-ID;<br>• **contradictions**: an AC whose normalised EARS trigger and subject match an approved one while its response has the opposite polarity, or an addition that declares `Supersedes`/`Replaces`/`Removes`/`Overrides`/`Contradicts` of an approved requirement. |
| Merge at 11 | APPROVE 11 of a feature computes the merge plan before recording. The additions of phases 0–6b are appended to the product documents under `## Feature <id> (ledger seq n)`; LLD files are copied into `sdlc/05-lld/` (a name collision is refused).<br>The APPROVE line's payload carries `merge` (each target with before/after sha256). The gate then writes the files, checks them against the recorded hashes, and commits them as `MOADIX gate` (`--no-verify`, no signing).<br>Tasks, test and verification documents stay in the feature folder. A feature's 11 cannot be PROCEED-PAST. |
| Verifiers in a feature | The brief's range starts at the commit FEATURE was recorded on. Stories come from the feature's PRD only. |
| Guidance | `/moadix:feature` (commands/feature.md), templates in `templates/feature/`. |

### B. Onboarding

| Item | What |
|---|---|
| INIT | On a repository whose HEAD tracks any non-documentation file, the INIT line records `mode: onboarding` and the file count. The product's only phase is **B**; its scope is `sdlc/00-*`, `02-*`, `03-*`, `04-*`, `sdlc/B-*`. The code itself is not writable in B.<br>**A new product must be INITialised before any code is committed** (a scaffolded `package.json` counts as code). |
| Templates | `templates/baseline/`: as-is BRD, PRD, architecture, threat model (each SEC-ID with `Current status`), test inventory, known-gaps register, accounts and services. They use the product's document names, so feature cycles validate against them unchanged. |
| check-baseline | Completeness (each document and section; no `{{` placeholder).<br>**Every `path:line` citation resolves at HEAD** (file exists, lines inside it), and a citation into `sdlc/` is refused. Each goal, story, AC, component, SEC-ID, suite and account must cite code.<br>EARS or `(as-is, not EARS: why)`.<br>Every SEC-ID not `mitigated` and every AC with no test must be in the gaps register.<br>No secret-looking value in the accounts document. The test environment must be loopback or a test host; a production-looking URL fails. |
| Baseline verifier | `moadix:baseline-verifier` (phase B, no skill, read-only Bash): checks every claim against the code; a high finding (a claim the code does not support) blocks APPROVE B through `check-verifiers-B`. |
| APPROVE B | As any APPROVE. Afterwards the baseline is frozen and every change is a feature cycle. |
| Guidance | `/moadix:baseline`. Manifest phase B, with bmad-prd, bmad-architecture and threat-model available `during: B`. |

### C. Deferred items

| Item | What |
|---|---|
| BMAD's own scripts | `memlog.py`, `resolve_config.py`, `resolve_customization.py`, `config_utils.py` vendored **verbatim** from BMAD-METHOD v6.12.4 (bab9082), with LICENSE, TRADEMARK.md and upstream sha256 in `gate/bmad/`.<br>The gate installs them into the product's `_bmad/scripts/` with a MOADIX-written `_bmad/config.toml`, at INIT and again at session start and on Stop when missing or changed. `_bmad/.gitignore` keeps the tree clean except `custom/`. |
| BMAD output paths | The four BMAD skills' `customize.toml` now point at `sdlc/00-forge`, `sdlc/01-research`, `sdlc/02-prd` and `sdlc/03-architecture`; the retro's implementation artifacts at `sdlc/12-retro`. Each folder is in its phase's path map. Recorded as `modified` in each skill's MOADIX-UPSTREAM.sha256 and MOADIX-CHANGES.md. |
| check-seam, BMAD half | Re-rooted (`gate/config/bmad-adapter.yaml`). It checks:<br>• the pin agrees between adapter and gate;<br>• the vendored scripts are byte-identical to upstream;<br>• the product's `_bmad/` holds exactly what the gate installs;<br>• each skill's output folder is writable in its phase;<br>• `_bmad/` is protected and `_bmad/custom/` excepted.<br>Registered at phase 0 and B. |
| Size-profile collapse | `COLLAPSE <phase> <code>` records the ruling: the size (from the BRD, the feature's own BRD in a cycle; it must agree with `.sdlc/product.yaml` when set), the reason and `checks_not_run` from profiles.yaml.<br>The phase becomes `COLLAPSED` (not APPROVED, not current). It is refused for a phase or size the profile does not collapse. |

## 3. Tests

| Suite | Result | Evidence |
|---|---|---|
| **Increment-6 `tests/inc6/run.py`** | **68/68** in 45 s | `docs/evidence/increment-6-suite.txt` |
| Increment-5 `tests/tools/run.py` (real pinned tools) | **95/95, 2 skipped** (loopback binding, Terminal only) | `…/increment-5-suite-after-increment-6.txt` |
| Increment-4 verifiers | **97/97** | `…/increment-4-suite-after-increment-6.txt` |
| Increment-3 skills | **43/43** | `…/increment-3-suite-after-increment-6.txt` |
| Increment-2 gate port | **299/299** | `…/increment-2-suite-after-increment-6.txt` |
| Policy render | **11/11** | `docs/evidence/increment-6-policy.txt` |
| Release check | **9/9** (0.3.0 → 0.4.0) | `docs/evidence/increment-6-release.txt` |
| ruff, mypy, shellcheck, hardcoded-state, guard self-test | clean; 0 undeclared; 18/18 | `docs/evidence/increment-6-static.txt` |
| Install dry run, attack corpus | **not run** (Keychain, Terminal only) | — |

The increment-6 suite, by group:

| Group | Checks | What it proves |
|---|---|---|
| feature | 18 | The full cycle, FEATURE through the merge at 11:<br>• FEATURE refused before release; recorded after, with the feature id in the ledger; its `phase.yaml` is derived.<br>• **A second FEATURE while F1 is active is refused.**<br>• Path map: product documents frozen, other features denied.<br>• Phases 0–4 through the gate's worker and real APPROVEs.<br>• **A contradicting AC is refused at APPROVE 2**, naming US-001/AC-1. A declared supersede is refused. A redefined SEC-001 is refused.<br>• **APPROVE 11** passes check-feature-11 and check-release (GitHub stub). The ledger records the merge; the product PRD holds US-002 under "Feature F1"; every sha256 matches the ledger; the approved text above is unchanged; the gate's commit leaves a clean tree.<br>• After 11b the feature is done, a second feature starts, the id cannot be reused, and a later feature reusing the merged IDs conflicts. |
| onboarding | 17 | • INIT with code → phase B, recorded; B cannot write code or later documents; templates as shipped fail.<br>• **A dead citation (`src/app.js:3-60` in a 9-line file) fails**, and so does a missing file.<br>• A missing gap, a production URL and a secret value each fail.<br>• **Real citations pass.**<br>• APPROVE B: refused without baseline-verifier evidence, and refused with a high finding; recorded with clean evidence. The baseline is then frozen.<br>• **A feature on the onboarded product**: FEATURE recorded, a contradiction of the baseline's US-001/AC-2 refused, then through to its merge at 11, recorded in the ledger. |
| bmad | 9 | • INIT installs the 4 scripts byte-identical to upstream; the tree stays clean; the agent cannot write them.<br>• `resolve_config.py` resolves the output folders to `sdlc/`, and `memlog.py` writes into `sdlc/00-forge/` (with the pinned CPython 3.12).<br>• Each skill's folder is writable in its phase and frozen after.<br>• check-seam passes, catches a tampered script, and session start re-installs it. |
| collapse | 3 | `COLLAPSE 1` on size S is recorded with its reason and `check-handoff-1`, and the current phase becomes 2. COLLAPSE 2 is refused; size M is refused. |
| triage | 8 | • Unconfirmed findings block; WAIVE of an unconfirmed (plugin HIGH) finding is recorded; WAIVE of a confirmed high one is refused.<br>• The triager is scheduled with the unconfirmed ones in its brief; a triage citing a non-existent line counts for nothing.<br>• Rejected-with-evidence stops blocking; confirmed-high blocks as high. |
| session | 4 | • Clean: silent.<br>• A user-settings plugin is reported (systemMessage and context); one the policy force-disables is not; a project-local one is reported.<br>• The policy runs the hook. |
| github | 4 | plugin.json uses the launcher with no env token; INSTALL.md has no export; no token → exit with reason; with the token, the stub server runs `--read-only` with the token. |
| installer | 4 | Static checks of install.sh: root's scratch folder, root removes it, last line; the dry run checks it. |
| guard | 1 | No test touched a real product, keychain or `~/.claude` (the session test uses a fixture HOME). |

## 4. Choices made without asking (say if any is wrong)

- **What counts as "a repo that already has code"**: any tracked file at HEAD other than README/LICENSE/CHANGELOG, CLAUDE.md, `.gitignore`/`.gitattributes`, `docs/`, `sdlc/`, `.sdlc-proposals/`. So a product meant to be greenfield must be INITialised before code (or a scaffold) is committed.
- **Which documents merge**: phases 0–6b (requirements, design, threats, UX, provisioning). Tasks, tests and verification stay in the feature folder as its record.
- **Who commits the merge**: the gate, as `MOADIX gate`, skipping the product's git hooks (they would run product code outside the sandbox) and signing.
- **When a feature ends**: when all 16 of its phases are done (11b too), not at the merge.
- **Contradiction detection** is mechanical (EARS trigger, subject and response with opposite polarity, or a declared supersede). Two requirements that conflict in different words are not caught by the gate; the phase-7 verifiers may catch them.
- **A triager-confirmed finding with no readable severity from either side is `unknown`** and stays unwaivable.
- **New command `COLLAPSE`** for the size-profile ruling (the alternative was a variant of APPROVE).

## 5. Known gaps (stated plainly)

- **Nothing live was run (ruling 3).** Claude Security's headless scan, the live verifier against a real page, and check-release against real GitHub are still stub-tested. The same holds for the two new agents: the suite wrote their evidence through the gate's real brief, receipt and evidence check, but no real Claude subagent was run. Prompt replacement itself was measured live in increment 4.
- **SessionStart is unmeasured live**: that Claude Code runs a managed SessionStart hook and shows its `systemMessage`. The effective-plugin computation is my model of the settings layering. It does not read `installed_plugins.json` or `--plugin-dir` (sideloading is disabled by the policy).
- **The existing test suite of an onboarded product is not run by the gate.** Amendment 2 B.3 asks for that, in a test environment. check-baseline checks only that the inventory declares a command and a non-production environment. Running product code from the gate needs the same confinement design as the scanners. Not built.
- **Product-document validators do not run on feature additions.** check-handoff, check-lld, check-threat-model, check-traceability, check-provisioning, the scorecard and check-approvals stay product-scoped. check-feature is a lighter, purpose-built check, and the merged product documents are not re-validated by them.
- In the feature-cycle test, **feature phases 5–10c were recorded by the stub checker**, not through their tools. Phases 0–4 and 11 went through the worker.
- **If the merge write or commit fails after the ledger recorded APPROVE 11**, the reply says so plainly, but nothing retries. The ledger holds the plan with every hash.
- **Verifier directories are per phase label, not per scope** (`.sdlc/cache/verify/<label>/`). A feature's evidence is kept apart from the product's by HEAD, brief and receipt, not by folder; plugin.json's Playwright output folder is fixed.
- **BMad core's scripts need Python 3.11+.** The skills call them through `uv run`; whether `uv` can fetch a Python inside the agent's sandbox was not measured. The suite used the pinned CPython 3.12. In a feature cycle the BMAD skills must be given an explicit `doc_workspace` under the feature (the default folders are frozen then). That is an instruction in `/moadix:feature`, not enforced beyond the path map.
- `.sdlc/untested.yaml` is not filled from the onboarding gaps register.

## 6. Install steps (operator, in Terminal)

The checker source is unchanged since v0.3.0, so this is an update (no new QR code).

1. Close every Claude Code session.
2. `cd ~/moadix && git push && git tag v0.4.0 && git push origin v0.4.0`
3. `managed/install.sh`: password once. Expect no "Permission denied" lines, and **`MOADIX is updated.` as the last line**.
4. In Claude Code: `/plugin marketplace update moadix`, then `/reload-plugins`. Expect moadix **0.4.0**, two more agents (`sf-triager`, `baseline-verifier`) and `/moadix:feature` and `/moadix:baseline`. `plugin:moadix:github` shows failed until a product reaches phase 11; that is expected.
5. Start a new session. It should show **no** `PLUGIN DRIFT` message; if one appears, send it to me.
6. Optional, in Terminal: `/usr/bin/python3 tests/inc6/run.py` (expect `68 checks, 68 passed, 0 failed`) and `/usr/bin/python3 tests/install/dryrun.py`.

No GitHub token now: store it only when a product reaches phase 11 (INSTALL.md, "GitHub token, at phase 11").
