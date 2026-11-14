# Increment 7b: rulings on increment 7, read-only tool gates, confinement design

2026-11-14. Plugin 0.5.1. Committed locally. Nothing was pushed, tagged or installed. Stopped for review after the confinement design, as instructed.

## A. The uncommitted main-branch guard work

- **Who asked and when.** The operator, in this session (2026-11-14), before increment 7, in two messages.
  - The first was the change request:
    - product hosts added to the sandbox allowlist (Firestore and the Google APIs, Sentry, the Vercel API);
    - `gh` and `firebase` running outside the sandbox;
    - managed deny rules for pushing to main, `gh pr merge` and Vercel production.
  - The second gave four decisions:
    - `gh` and `firebase` unsandboxed, with extra deny rules: `gh auth token`, `gh api` merge and ref writes, the production Firebase project `<production-project-id>`, `firestore:delete`;
    - the text patterns accepted as a coarse first layer;
    - option A: a guard in the gate that parses commands, applies to every repository and fails closed.
- **What it does.** `gate/mainguard.py`, called from `pretool.check_bash` on every Bash command in every repository, reads the command as shell words. It refuses:
  - any push whose target is main, including `-C`, refspecs, `HEAD`/`@` on main, bare pushes on or tracking main, `--all`, `--mirror`, aliases and nested shells;
  - every `gh pr merge`;
  - `gh api` merges and writes to main;
  - Vercel production deploys, promotes and rollbacks.

  Its only subprocesses are local git reads, under a time limit. An error or timeout is a refusal.
- **What it changes in `managed/managed-settings.json`.** These are the only changes in that file:
  - **Deny rules (16 added):**
    - `Bash(git push*main*)`, `Bash(git push*HEAD:main*)`, `Bash(git push --all*)`, `Bash(git push --mirror*)`
    - `Bash(gh pr merge*)`
    - `Bash(vercel promote*)`, `Bash(vercel --prod*)`, `Bash(vercel deploy --prod*)`
    - `Bash(gh auth token*)`, `Bash(gh api*merge*)`, `Bash(gh api*-X PUT*)`, `Bash(gh api*--method PUT*)`, `Bash(gh api*-X PATCH*refs*)`, `Bash(gh api*--method PATCH*refs*)`
    - `Bash(firebase*<production-project-id>*)`, `Bash(firebase*firestore:delete*)`
  - **Commands excluded from the sandbox:** `gh *` and `firebase *`.
  - **Hosts added to the network allowlist:** nine product hosts (the Firestore, Firebase and Google API endpoints, Sentry and the Vercel API; their names now live only in the operator's local overlay).

  The full diff was printed in the reply that started this increment. The other files in that work:
  - `gate/pretool.py`: 3 lines that call the guard, an import and a docstring note;
  - `tests/install/render.py`, `tests/mainguard/` and `tests/install/policy_live.sh`: tests;
  - `docs/INSTALL.md`: docs.

  None of it is committed or changed, pending your ruling. It is still excluded from the commit.

## B. Can PROCEED-PAST pass a gap-critic BLOCKER?

- **Before 7b.** Yes. A BLOCKER fails `check-verifiers-<phase>`, and PROCEED-PAST accepts any current, determinate failure. The ledger recorded only the failing validator IDs and the reason, not the finding. WAIVE already refused a BLOCKER.
- **Built now, as you described.**
  - WAIVE never passes a BLOCKER (unchanged).
  - PROCEED-PAST is the only way past one. Its ledger line now carries `passed_findings`: role, finding id, topic, severity, quote, citation, the evidence file's sha256 and the commit, for every open BLOCKER and unwaived MAJOR it passes.
  - The reply names them.
  - Tested in tests/inc7b (`proceed-past`, 3 checks).

## 1. Rulings applied

| # | Ruling | What changed |
|---|---|---|
| 1 | T- tasks, SR- shared resources, TH- threats, STR- store release, TASK- dropped | Amendment 3 (a "Rulings on increment 7" block, the trace-ID row, I1 and the phase-7 gate text), the catalogue, `/moadix:coverage` (regenerated) and trace-lint. Upstream checks are now on for all four: TB 4 < TH and SR 4.2 < SEC 4.5 < … < T 8 < … < STR 15. inc7 checks each one as an orphan. |
| 2 | Phase 12 gated | Phase 12 now has:<br>• its own path-map entry (`sdlc/12-*.md`, `sdlc/12-retro/**`, `sdlc/12/**`, removed from phase 11);<br>• APPROVE 12;<br>• `check-contract-12` and `check-verifiers-12` (gap critic), with the manifest's retro skills now in 12 (and after `done`);<br>• check-seam's retro artifact folder in 12;<br>• render version 5, so an existing `phase.yaml` is re-derived.<br>APPROVE 11 still releases. FEATURE is refused while the product cycle's 12 is pending, or while a feature's 12 is pending (the feature stays active until it is approved). STATUS prints `PENDING: phase 12 (Retro) …`. |
| 3 | MPL-2.0 accepted when fetched unmodified and never vendored | axe-core 4.14.0 and @axe-core/playwright 4.14.0 added to `product_dependencies`. `THIRD-PARTY.md` gains a table of every MPL-2.0 component with its source: lightningcss, axe-core via lhci, hypothesis, certifi, and the two axe packages. |
| 4 | code-simplifier skipped | Removed from the amendment's table, with a one-line reason. |
| 5 | Pinned Node 24 for gate-run Node tools | `node` 24.22.2 pinned in tools.yaml from nodejs.org, checked against SHASUMS256.txt (released 2026-10-27, the newest 24.x at least 14 days old; MIT). `toolrun.node()` uses only that pin, with no fallback to PATH or Homebrew. The pinned Playwright MCP server in plugin.json starts with it too. dependency-cruiser 18.7.0 runs on it (measured). |
| 6 | In-flight products start at their current phase | As built. Approved phases are not re-linted. |
| 7 | `_bmad/MOADIX-BMAD.json` keeps its name | Unchanged. |

## 2. Read-only tool gates

Each is a validator in the increment-5 style. It reads an export of HEAD with the product's tool config removed (`gate/v1/readonly.py`), runs pinned tools under `toolrun`'s `sandbox-exec` (no network, writes only to scratch), uses the gate's own configuration and records evidence. Each has product and feature scope.

| Validator | Phase | Checks |
|---|---|---|
| `check-api-tools-5` | 5 | **vacuum** 0.36.1, OWASP ruleset only (`gate/config/vacuum/owasp.yaml`): any error or warning fails.<br>**oasdiff** 1.35.0 `breaking`, from the spec at the commit the product's phase 11 was approved on, with external `$ref`s refused: each ERR needs an *accepted* ADR naming the path with a deprecation plan (FC5). No release yet: reported.<br>**squawk** 2.71.0 with the gate's config, on the migrations `product-tools.yaml` declares Postgres: any violation fails. SQLite: N/A. SQL committed with no dialect declared: fails. |
| `check-ux-files-6` | 6 | `design/tokens.json` in W3C DTCG format: types, colour and dimension values, aliases, cycles.<br>The gate's own WCAG 2 contrast computation over `design/contrast.csv`: body at least 4.5:1, large and UI at least 3:1, at least one body pair.<br>`design/screen-states.csv`: default, loading, empty and error per screen, each designed (with a reference at HEAD) or n/a with a reason; every PRD screen covered (P5's anchored section).<br>`design/component-states.csv` (U13). |
| `check-sec-controls-4` | 4 | `<scope>/4/SEC-CONTROLS.csv` `sec_id,th_id,asvs_id,verification`:<br>• every SEC-ID and TH- of the threat model mapped, or `accepted-risk` with its record;<br>• IDs defined;<br>• ASVS IDs shaped as 5.0.0 requirement IDs, V1–V17;<br>• no duplicates. |
| `check-sec-verification-9` | 9 | `<scope>/9/SEC-VERIFICATION.csv` `sec_id,method,evidence,result`:<br>• every phase-4 control has a row;<br>• result is verified, failed or accepted-risk; failed fails the phase;<br>• evidence paths exist at HEAD;<br>• accepted-risk names the residual-risk acceptance. |
| `check-lv-inventory-10a` | 10a | `<scope>/10a/LV-INVENTORY.csv` covers 100% of the designed rows of both state inventories. LV-IDs are unique; a pass needs an artifact, an n/a needs a reason, and a fail fails the phase. |
| `check-workflows-11` | 11 | **zizmor** 1.31.1 (`--no-config --no-online-audits`, no token): any low, medium or high finding fails.<br>**actionlint** 1.7.12 with the gate's empty config, shellcheck and pyflakes off: any error fails.<br>No workflow at all fails. |

**Product config never read** (tested): `.squawk.toml`, `zizmor.yml`, and also `actionlint.yaml` and vacuum/Spectral configs. Their evidence goes to `.sdlc/evidence/<phase>/` with the tool versions. The manifest's `gate_run` lists the five tools.

**Shape, not existence, for ASVS.** Checking that an ASVS ID exists needs the ASVS 5.0.0 data, which is CC BY-SA 4.0. That is a non-permissive licence, so the data is not vendored. The check is the shape and the V1–V17 chapter range, as instructed.

## 3. Confinement design

`docs/confinement-design.md`, for review. It covers:

- **Tiers.** Each executing gate is placed in a tier: R (read-only), E (executes code) or L (needs a running app).
- **Threats.**
- **The runner.** One gate-owned confined runner: a disposable container, never the operator's account. Fail closed when it is unavailable.
- **Non-root.** uid 10001, all capabilities dropped, `no-new-privileges`, read-only root filesystem.
- **Repository and output.** The repository goes in by `git archive HEAD`, copied into a read-only `/src`, with **no host bind mounts**. There is one checked `/out`.
- **No secrets.** The environment is built from scratch; no sockets, no Keychain, and dotenvx keys are withheld.
- **Network.** None while product code runs. Registry-only egress through a proxy for the install step. An internal Docker network with no egress for live gates.
- **Resource limits** per tier.
- **Results integrity.** The gate re-derives every verdict from raw data.
- **A per-gate mapping.**
- **Accepted risks:** runtime escape, self-reported tests, install scripts, side effects, registry trust.
- **Five questions** for the operator.

## 4. Tests

| Suite | Result | Evidence |
|---|---|---|
| **tests/inc7b (new)** | **58/58** | `docs/evidence/increment-7b-suite-inc7b.txt` |
| tests/inc7 | 119/119 (was 115: four orphan checks for TH-, SR-, T-, STR- and a control; the phase-12, axe and version checks were updated) | `…-suite-inc7.txt` |
| tests/gate2 | 299/299 | `…-suite-gate2.txt` |
| tests/verifiers | 97/97 | `…-suite-verifiers.txt` |
| tests/inc6 | 70/70 (was 68: plus FEATURE refused while the product's retro is pending, and while F1's retro is pending) | `…-suite-inc6.txt` |
| tests/tools | 107/107, 2 skipped (loopback bind, Terminal only); the Node pin's stamp is checked | `…-suite-tools.txt` |
| tests/skills | 43/43 | `…-suite-skills.txt` |
| tests/release | 9/9 (0.5.0 → 0.5.1) | `…-suite-release.txt` |
| tests/corpus | guard self-test 18/18. The full corpus needs the Keychain; please rerun it in Terminal (it was 128/128 on 0.5.0). | `…-corpus-guard-selftest.txt` |
| Static: ruff, mypy, shellcheck, hardcoded-state, self-approval grep | clean; 0 undeclared (5 exemptions added); 165/165 | `…-static.txt` |

**inc7b groups.** Every gate has a clean control and planted defects, run with the real pinned tools:

| Group | Checks | Planted defects |
|---|---|---|
| api-tools | 11 | a missing 429 response (vacuum); serial ids and a blocking index (squawk); a product `.squawk.toml` switching rules off; SQLite N/A; SQL with no dialect declared; a breaking path removal without an ADR, with an accepted ADR, and with a proposed ADR (oasdiff); no spec at all |
| ux-files | 12 | an unknown type; a bad colour; a dangling alias; an alias cycle; no tokens file; body text at 2.7:1; no body pair; a missing loading state; an n/a without a reason; an uncommitted reference; an uncovered PRD screen |
| workflows | 6 | a tag-pinned action; template injection; an invalid key; a product `zizmor.yml`; no workflow |
| sec-csv | 10 | 9 planted defects across phases 4 and 9 |
| lv-inventory | 5 | 4 planted defects |
| rulings | 10 | registry and scope; pinned Node used by Redocly; plugin.json; the amendment text; the phase-12 path map, APPROVE 12 and FEATURE gating |
| proceed-past | 3 | (B above) |
| guard | 1 | |

**Fixture changes in the earlier suites.** inc6's feature fixture gained a TH- threat and `4/SEC-CONTROLS.csv`, its release workflow gained explicit least-privilege permissions (zizmor and actionlint clean), and product approvals now include 11b and 12. gate2's registry count includes 7b's validators. The skills suite's retro check now expects phase 12. No assertion was weakened.

## 5. Choices made without asking (say if any is wrong)

- **"vacuum OWASP ruleset clean"** means no error and no warning; info and hints are reported.
- **zizmor "clean"** means no low, medium or high finding; informational ones are reported.
- **An approving ADR for an oasdiff ERR** is an ADR with `Status: accepted` that names the changed path and contains "breaking" and "deprecat…".
- **File locations:**
  - `design/tokens.json`, `design/contrast.csv`, `design/screen-states.csv`, `design/component-states.csv`;
  - `<scope>/4/SEC-CONTROLS.csv`, `<scope>/9/SEC-VERIFICATION.csv`, `<scope>/10a/LV-INVENTORY.csv` (in the contract folders);
  - Postgres migrations declared in `product-tools.yaml` under `migrations: {dialect, paths}`.
- **PRD screens** come from the section phase 2's COVERAGE.md anchors for P5: the first column of its table, or the bold lead of each list item. When P5 is not anchored, the screens are not cross-checked, and that is reported.
- **LV-INVENTORY.csv** covers the designed rows of both state inventories (U4 and U13).
- **SEC-CONTROLS.csv:** a threat with no control is acceptable only as an `accepted-risk` row naming its record.
- **A retro is pending** for the product cycle (greenfield product after APPROVE 11) and for a feature after its 11b. An onboarded product's baseline has no retro.
- **The pinned Playwright MCP server now starts with the pinned Node.** That takes effect only after the installer has fetched Node into the tools folder.

## 6. Remaining (not built in 7b, by instruction)

1. **The gates that execute product code:** pytm, LikeC4, dependency-cruiser, knip, ESLint, tsc, Stryker, Schemathesis, the product's test suites (including the existing suite in phase B), ZAP, Lighthouse CI and axe. They wait on the confinement design's review and its questions.
2. **The merged product-plus-feature validators:** the v1 product-document validators running on the merged view of the product's documents and a feature's additions (FC: "the full product-document validators, not a lighter check").
3. **Conflicts found:** none that block 7b. Two items that touch the amendment are raised as questions in the confinement design:
   - **dependency-cruiser config:** the amendment names a JavaScript config, `.dependency-cruiser.cjs` (H20). It can be executed safely only inside the container, or it could be replaced by a JSON config (question 6.4).
   - **ASVS existence:** it cannot be checked without CC BY-SA data (section 2).

## 7. Install (operator, in Terminal, when you choose)

Unchanged from 0.5.0 (an update, no new QR code). `managed/install.sh` now also fetches Node 24.22.2 (nodejs.org) into the tools folder. Expect moadix **0.5.1**. The main-branch guard work stays uncommitted and is not part of this commit.
