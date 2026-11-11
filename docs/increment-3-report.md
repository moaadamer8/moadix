# Increment 3: corpus fix, rulings on increment 2, skills, report

2026-11-11. Built per DESIGN.md §6 (per-phase skills), build increment 3, and the rulings on increment 2 (now recorded in DESIGN.md under Amendment 1). Nothing was installed: the live gate still runs increment 2 until the operator reruns `managed/install.sh`.

## 1. The corpus (fixed first)

**What was wrong.** Run from Terminal, `tests/corpus/run.py` got `ERR totp-secret-unreadable` on the Keychain-dependent checks. The leftovers of that run in `~/moadix-scratch/corpus` show:

- the test checker *did* read its own test keychain at first. Fixture A recorded `APPROVE 0` at 16:04:08, and fixture B's validator worker read B's keychain at 16:06:43;
- later calls failed.

Neither run is visible from inside Claude Code (the sandbox blocks the Keychain, and the live gate refuses `security` commands), so **the root cause is not established**. The corpus now names it on the next run instead of failing dozens of checks for one reason.

**What changed** (`tests/corpus/isolation.py`, `tests/corpus/run.py`, `tests/probes/kc-probe.c`):

| Layer | What it does |
|---|---|
| Static assertions, before any check | **Scratch dir:** not inside a real product, and never deletes a directory the corpus did not make. **Keychain:** each test keychain is under the scratch dir and is not the login keychain, the default keychain or anything under `~/Library/Keychains`. **Checker:** each one is this run's build, and the binary itself contains the scratch keychain path and scratch pin file, not the production pin file. **Gate copy:** its checker resolves to that build. **Products:** each one is under the scratch dir. |
| argv check on every command | No argument may name the installed home (`/Library/Application Support/ClaudeCode`) or a real keychain. `security` is limited to an allowlist of subcommands, each of which must name exactly one scratch keychain as its last argument. |
| Audit hook (`sys.addaudithook`) | Refuses any subprocess, exec or file write naming those resources, even when it bypasses `sh()`. |
| Gate processes | Each fixture gate copy now carries `tests/lib/_testguard.py`. Its log of any real-product read or write must be empty (a hygiene check). |
| Self-test | 18 cases, run first. 17 hand the guard a real resource (or a stand-in that trips the same rule) and must abort. 1 control must be accepted. The exec cases use stand-ins that would do nothing if the guard failed. |
| Health probe | `kc-probe status`: lock state and an attribute-only lookup, so no secret is read. Plus `checker state`. It runs after the build (**preflight**: the run stops there if a test checker cannot read its own keychain), between groups, and once at the first failing check. |

A guard hit aborts the run with exit 3. It is never reported as a failed check.

**Result.**

| Run | Where | Result |
|---|---|---|
| Guard self-test (`--guard-selftest`) | this session | **18/18 fired** (`docs/evidence/increment-3-corpus-guard-selftest.txt`) |
| Corpus driven with the stub checker, no Keychain (scratch adapter, not committed) | this session | **116/117**. The 1 is `checker init → already-initialised`, which only the real checker implements. The keychain group (11) was skipped. (`docs/evidence/increment-3-corpus-stub-precheck.txt`) |
| **The real corpus** | **not run: needs the Keychain, so Terminal only** | Expected `128 checks, 128 passed, 0 failed`; how to run it and what it prints is in `docs/INSTALL.md` → "Running the attack corpus" |

## 2. Rulings on increment 2

| # | Ruling | Built |
|---|---|---|
| 1 | Approved phases frozen until REOPEN | Accepted; recorded in DESIGN.md |
| 2 | Gate runs the validators; REVIEW optional | **Triggers:** a managed **Stop hook** (`hook.py stop`) and the agent's `/moadix:request-review` call (PreToolUse sees the `Skill`/`SlashCommand` call). Either starts the current phase's validators on a clean tree when the cached result is missing or stale (`gate/autoval.py`). **REVIEW** is read-only. **APPROVE** reads the cache, refuses with the findings when the result is missing, stale or failing, and records `validation.digest`, the sha256 of the exact cache file. REVIEW of an approved phase shows that digest. The Stop hook never answers or blocks: failing open there is safe, because APPROVE fails closed. |
| 3 | ADOPT `<code>` | `gate/adopt.py`. The agent writes `.sdlc-proposals/product.yaml` (keys `platform`, `size`, `app_run`, `test_targets`, `park` only) and `.sdlc-proposals/config/<name>.yaml` (the product config files). ADOPT validates them (names, plain files, size, YAML mapping, allowed keys, the `park:` argv rules, product id unchanged after the merge). It then records one line with each target's proposal and result sha256 (and the text when ≤ 6 KB), writes `.sdlc/` and removes the proposals. STATUS lists pending proposals and says whether they are adoptable. An adopted file edited outside ADOPT is an integrity failure. Pending proposals don't make the validator cache dirty. |
| 4 | Scorecard reads the ledger | `hlib.v1_phase_doc` takes `approval_sha`, `approval_dirty`, `approval_mode`, `approver` and `evidence` from the verified ledger. A gate APPROVE gives the commit the run was keyed to, interactive mode, a clean tree and its results. **Imported v1 lines** (`payload.imported`, for the onlineMarket migration) give the facts they carry; a missing fact stays unknown. `build_scorecard` answers "registered at approval?" from the APPROVE line instead of `git log` on `harness/registry.yaml`, treats `n/a-by-profile` as neither pass nor fail, and names the typed REOPEN/WAIVE commands. **Found on the way:** without this, every v2 approval had no `approval_mode`, so check-approvals and the HARD RULE would have read all of them as non-interactive. |
| 5 | Deferred items | DESIGN.md table:<br>• live probe → increment 5<br>• check-seam's BMAD half → increment 6<br>• size-profile collapse → increment 6<br>• WEB→APP → increment 7 |

## 3. Skills (increment 3)

18 skills vendored under `skills/`, each with `LICENSE`, `MOADIX-CHANGES.md` (every removal and adaptation, with the original text) and `MOADIX-UPSTREAM.sha256` (each file's upstream hash and whether it is verbatim or modified). Policy: `skills/VENDORING.md`. Sources, pinned commits, licences and attribution: `skills/SOURCES.yaml`.

| Phase | Skills (SKILL.md bytes) | MCP | Gate-run (increment 5) |
|---|---|---|---|
| 0 BRD | bmad-forge-idea (10,380) | | |
| 1 Research | bmad-deep-recon (9,298) | context7 | |
| 2 PRD | bmad-prd (14,047; + cc-sdd EARS in its PRD template) | | |
| 3 HLD | bmad-architecture (13,869; + spec-kit Data Model / Contracts in its template) | | |
| 4 Threat Model | threat-model (7,750), threat-mitigation-mapping (3,346) | | |
| 5 LLD | – | | redocly-cli |
| 6 UX | ui-ux-pro-max (17,562), impeccable critique+audit (5,324), apple-design (23,036); template `templates/DESIGN.md` (Notion, from awesome-design-md) | | |
| 7 Implementation | code-review (7,209), diagnosing-bugs (8,815), test-driven-development (9,572), verification-before-completion (3,836), typescript-reviewer + ECC TypeScript rules (9,082) | | |
| 8 Testing | pr-test-analyzer (5,019), javascript-testing-expert = fast-check guidance (16,728) | | |
| 9 | – | | gitleaks, osv-scanner, trivy, semgrep |
| 10c | – | | k6 |
| 12 Retro (during 11 and after the last phase) | phase-retrospective (13,473), reflect-queue (9,587) | | |
| every phase | moadix:request-review | | |

**Licence obligations (Amendment 1).**

- BMAD retrospective renamed `phase-retrospective`, with no BMad mark in its name or description.
- Impeccable ships `NOTICE.md`.
- Change notices sit in every modified Apache-2.0 file (threat-model, Impeccable, pr-test-analyzer); the tests check this against the upstream hashes.
- pr-test-analyzer comes from claude-plugins-official, and the threat model from defending-code-reference-harness.
- The DESIGN.md template carries a not-affiliated line.

**Manifest and hook.** `gate/config/phase-manifest.yaml` is installed root-owned with the gate. In a product, PreToolUse (`gate/manifest.py`, invariant 5) denies any `Skill`/`SlashCommand` call or `mcp__*` call outside the current phase's manifest, naming the phase. Example: `skill 'moadix:bmad-forge-idea' is denied in phase 1 (Research): it is not in the manifest for phase 1 (Research). Allowed now: moadix:bmad-deep-recon, moadix:request-review`.

- Only `moadix:<name>` counts. A bare name or another plugin's same-named skill is refused, because only MOADIX's stripped copies are allowed.
- An integrity failure refuses every Skill and MCP call.
- STATUS shows the phase's skill set and its SKILL.md cost.

### Every self-approval step removed

- **bmad-forge-idea:**
  - mark-done: `memlog.py set --key status --value complete`
  - auto-advance: "offer the file as input to bmad-spec/bmad-prd/bmad-prfaq/bmad-build"
- **bmad-deep-recon:**
  - mark-done: `status: complete` in the synthesis frontmatter
  - auto-advance: "Invoke `bmad-help` to suggest the next step"
- **bmad-prd:**
  - mark-done: `status: final` plus the "PRD finalized" event
  - auto-advance: "Common next: bmad-ux, bmad-architecture, …; invoke bmad-help"
  - self-approve: headless "`complete` = stands on its own" now says the operator still reviews it
- **bmad-architecture:**
  - auto-advance: "invoke bmad-prd/… instead" at activation, "Offer to invoke bmad-spec", and the "lead with bmad-spec … bmad-help" routing
  - mark-done: `status: final` plus "spine finalized", and the template's `draft · final`
  - self-approve: headless "`complete` stands alone"
- **phase-retrospective:**
  - mark-done: every sprint-status write is gone, both `sprint_status.py update` (`--set-retro-done`, `--add-action`, `--set-action-status`) and the `update` subcommand itself; also "retro key stays done"
  - auto-advance: "orchestrator keys off verdict to hold the next epic"
  - self-approve: the retro verdict is now a recommendation that approves nothing
- **threat-model:**
  - commit: `allowed-tools: Bash(git:*)` (which pre-granted `git commit`/`git push`) narrowed to `git log/show/diff/blame/rev-parse`
- **pr-test-analyzer:**
  - mark-done: "before marking a PR ready" (twice)
  - self-approve: output is findings only, with no verdict
- **typescript-reviewer:**
  - self-approve / merge: the "Approval Criteria" block (Approve / Warning "can merge with caution" / Block) is now a findings summary with no verdict
- **impeccable:**
  - ship: score band "Minor polish only; ship it"
  - auto-advance: "You can ask me to run these… / Re-run after fixes", in critique, audit and audit.native
- **code-review:**
  - self-approve: findings only, no verdict; stop after step 5
  - auto-advance: "run `/setup-matt-pocock-skills`"
- **diagnosing-bugs:**
  - auto-advance: "Flag this for the next phase"
  - mark-done: "Required before declaring done"
  - commit: "stated in the commit / PR message"
- **test-driven-development:**
  - mark-done: "Before you call the change done" and "Before marking work complete"
  - auto-advance: the `superpowers:writing-skills` reference
  - ship: "Tests Ship With…" and "Ship the tests…"
- **verification-before-completion:**
  - commit: "before committing or creating PRs", "About to commit/push/PR", and "Committing, PR creation, task completion"
  - mark-done: added "a claim never closes a task or a phase"
- **reflect-queue:**
  - auto-advance: the "Remind users about /reflect" behaviour
  - mark-done: the "DONE: Applied" banner
  - commit: added "Do not commit anything"
  - self-approve: "Apply all (Recommended)" removed; the operator answers per item
- **threat-mitigation-mapping, javascript-testing-expert, ui-ux-pro-max, apple-design:** nothing to remove; ui-ux-pro-max was adapted only (plugin path, `--persist --output-dir design`, `--rtl=full`)

## 4. Tests

| Suite | Where | Result |
|---|---|---|
| Increment-3 suite `tests/skills/run.py` | this session, stub checker | **43/43** (`docs/evidence/increment-3-suite.txt`) |
| … enforce | | 27/27, including:<br>• a skill allowed in its phase<br>• the same skill denied in the next phase, with the phase named<br>• MCP outside the manifest denied (Gmail, chrome, playwright, a server named to look like context7)<br>• Context7 allowed only in phase 1<br>• bare and foreign names refused<br>• passive outside a product<br>• fail-closed on integrity failure |
| … manifest / sources / licence obligations | | 13/13 |
| … grep | | 2/2:<br>• 157 matches over 57 files, **0 not allowlisted**; each allowlist row has a reason (`docs/evidence/increment-3-selfapproval-grep.txt`)<br>• a negative control: planted "mark done / commit / approve / next phase / status: final / merge / ship / Common next" lines are all caught |
| … guard | | 1/1 |
| Increment-2 suite `tests/gate2/run.py` (with new groups) | this session | **290/290** (was 244):<br>• autoval 10<br>• adopt 21<br>• scorecard 12<br>• approve 19 (+3) |
| check-static (ruff + mypy + shellcheck), check-hardcoded-state | this session | clean |
| Corpus guard self-test | this session | 18/18 |
| Real corpus, install dry run | **not run** (Keychain; Terminal only) | see section 1 and the install steps |

## 5. Known gaps (stated plainly)

- **The skills are only reachable once the plugin is installed.** That needs this repo on GitHub and `managed/install.sh --plugin <owner>/moadix`. Until then, in a product the hook denies every Skill and MCP call except `moadix:*` ones, and none of those is installed, so the agent has no skills. Outside products nothing changes.
- **MCP is strict.** In a product session every MCP server not in the current phase's manifest is denied, including claude.ai connectors and Claude in Chrome. That is the ruling as written.
- **Skill output paths vs the path map.** Several skills write where the phase path map denies:
  - BMAD skills write run folders (`prd.md`, `.memlog.md`, …);
  - threat-model writes `<target>/THREAT_MODEL.md`;
  - Impeccable reports now go to `design/reviews/`, which is allowed;
  - ui-ux-pro-max persists to `design/`, which is allowed.

  The hook denies the others with a reason, and the agent must name the `sdlc/NN-*.md` path. Reconciling this is for increment 6 (toy run).
- **BMAD's shared scripts.** The BMAD skills call `{project-root}/_bmad/scripts/{memlog,resolve_config,resolve_customization}.py` (BMad core 6.12.4, not vendored). Increment 6.
- **Dropped helpers.** threat-model's bootstrap checkpoint helper (`.claude/skills/_lib/checkpoint.py`) is not vendored. Impeccable's launcher (it downloads a binary) was dropped, so the skill always takes its documented "launcher unavailable" path.
- **Stop-hook cost.** Validators now start at the end of any turn that left a new clean commit. A long validator run can overlap the next turn.
- **Unchanged from increment 2:** the validator cache is not signed (APPROVE now records its digest, so a swapped file shows in the ledger). PARK stops and measures before the code is checked.

## 6. Install steps (operator, in Terminal)

1. Close every Claude Code session.
2. `cd ~/moadix && git log --oneline -1` (note the commit).
3. `managed/install.sh`. It detects the existing install and asks for your password once. It re-copies the gate (new: `autoval.py`, `adopt.py`, `manifest.py`, `config/phase-manifest.yaml`), rewrites the policy (new: the **Stop** hook) and re-runs its checks. The checker binary is unchanged, so your key and ledgers are kept.
4. `/usr/bin/python3 tests/corpus/run.py`. Expect the 18 guard self-test lines, the preflight health lines, and finally `128 checks, 128 passed, 0 failed`. If it stops at the preflight or a check fails, send the whole output: `… 2>&1 | tee ~/moadix-scratch/corpus-run.txt`.
5. Optional: `/usr/bin/python3 tests/install/dryrun.py` (now also checks the Stop hook in the policy and that the Stop hook runs the validators).
6. Open a new session in `~/moadix-scratch/live-demo` and type `STATUS`. Expect `INTEGRITY OK` and a `Phase N manifest: skills …` line.
7. When this repo is on GitHub: `managed/install.sh --plugin <owner>/moadix` makes the vendored skills available.
