# Increment 7: Amendment 3, the cross-phase contract, gap critics and new tools

2026-11-14. Built per docs/AMENDMENT-3.md, plus the operator's phase-7 rules and toy-notes findings F-1 and F-2. Plugin 0.5.0. Committed locally. Nothing was pushed, tagged or installed. The live gate still runs 0.4.0 until the operator reruns `managed/install.sh`. Nothing from docs/AMENDMENT-4.md was built.

**Read this first.** Two parts of Amendment 3 conflict with what is already built (section 5). I did not choose between them. They are built in the narrowest form that changes nothing already built, and each needs a ruling.

## 1. What was built

### 1.1 The cross-phase contract (Amendment 3 section 1)

| Item | What |
|---|---|
| Topic catalogue | `gate/config/coverage-topics.yaml`, generated once from the amendment's text. It holds:<br>• 18 phase entries: 0–11b, 12, B;<br>• 303 topics, each with its role and phase-specific BLOCKER rules;<br>• FC1–FC11, each assigned to a feature-cycle phase;<br>• the size rule. |
| Contract files | Per phase, in `sdlc/<label>/` (in a feature cycle, `sdlc/features/<id>/<label>/`):<br>• `COVERAGE.md`;<br>• `DISCOVERY.md` (Q-n log);<br>• `adr/ADR-nnn-*.md`.<br>The path map gives each phase its folder; phase 4 also owns `tm/` for pytm. |
| Linters | All in `gate/contract.py`. The gate runs them as `check-contract-<label>` (`gate/v1/check_contract.py`) in every gated phase and in B, in product and feature scope. The agent may run `gate/contract.py <lint> <root> <label>`, but only for feedback. |
| coverage-lint | Refuses:<br>• a missing, duplicated or foreign topic ID;<br>• an anchor that does not resolve, points outside `sdlc/` or is external;<br>• a hollow section;<br>• an empty, boilerplate or under-four-word N/A reason;<br>• the same reason copied onto three or more topics.<br>It also applies the size rule (1.3). |
| discovery-lint | `DISCOVERY.md` must exist. Each `## Q-n` needs:<br>• 2–4 options;<br>• a `Recommendation:` naming one of them;<br>• a `Chosen:` naming one of them.<br>No Q-n may be reused. A phase with no questions writes `No questions: <reason>`. |
| adr-lint | Checks the MADR shape:<br>• title `# ADR-nnn:`;<br>• Context, Alternatives (at least 2), Criteria, Decision, Consequences;<br>• Sources, each with a URL and a date.<br>A `Supersedes:` must name an ADR that exists, and an ADR number may not be reused. |
| trace-lint | • A definition must cite an existing ID of a lower trace level.<br>• A reference to an undefined ID is dangling (checked only for prefixes the documents use).<br>• An ID may not be defined twice.<br>• An ID that existed at an approved phase's commit may not disappear.<br>• A row in an `ID` table is a register entry: it counts as defined but needs no upstream.<br>• T- and SR- are not checked for upstream (conflict 5.1). |
| ears-lint | Runs in phase 2 and in phase B. Each AC must match an EARS template. It refuses:<br>• vague terms (fast, user-friendly, appropriate, etc., TBD, should, may…);<br>• more than one `shall`;<br>• a story without an `If …, then …` AC (P16);<br>• an NFR without a number and unit;<br>• a role × action matrix (P3) with a cell that is neither allow nor deny, or that denies nothing.<br>Phase B accepts `(as-is, not EARS: why)`. A gate run writes the gate-owned `AC.json` to `.sdlc/cache/contract/<scope>/AC.json`. |
| cite-lint | Runs in phase 1. It refuses:<br>• a URL without a date on its line;<br>• a future date;<br>• an unsourced claim in the R2–R8 and R11–R14 sections (an inline link with a date, or a dated `[^n]` footnote, counts as a source);<br>• a link that returns 404, 410 or 5xx.<br>Links are probed by the gate's run and cached for 30 days in `.sdlc/cache/links.json`. A link not yet checked is UNKNOWN (exit 2), never a pass. A feature's research additions are optional, as built in Amendment 2. |
| CRITIC.json schema | `gate/config/critic.schema.json`, checked by a small JSON Schema validator (stdlib only). There is no verdict field, and additional properties are refused. |

### 1.2 Gap critics (one per gated phase)

| Item | What |
|---|---|
| Role | `moadix:gap-critic` (`agents/gap-critic.md`). It reads, uses read-only Bash and writes its evidence only. It is listed in `verifiers.yaml` as `phase: "*"`, so it is scheduled in every gated phase with topics: product, B and feature cycles. |
| Brief and enforcement | Built and enforced by the gate, exactly like the increment-4 verifiers: prompt replacement, a one-time receipt, the stamp and HEAD. The brief has:<br>• the role;<br>• every topic, marked with its size default or operator ruling;<br>• the severity definitions and the phase's BLOCKER rules;<br>• the upstream/frozen documents to check for contradictions;<br>• the schema.<br>Required paths are **every** file of the phase's documents at HEAD, not only the changed ones. |
| Evidence check | `contract.critic_check` checks:<br>• the schema;<br>• that `topics_checked` covers every topic;<br>• that each finding's topic belongs to the phase;<br>• that the citation resolves at HEAD;<br>• that the **quote appears at the cited lines**. |
| Severity effects | • BLOCKER refuses APPROVE, and WAIVE of it is refused.<br>• MAJOR refuses APPROVE until `WAIVE gap-critic.<topic> … reason=…` is recorded.<br>• MINOR goes to the file only.<br>A critic can only block: there is no field through which it can pass a phase. |
| Every phase checks its verifiers | `check-verifiers-<label>` was added for the 12 phases that had none. The phase-9 triager stays consumed by check-claude-security (ruling 1); check-verifiers does not require it. |

### 1.3 Size rule (section 2)

- **Source.** Size and ruling are read from B19: the BRD's `- **Size:**` and `- **Target Platform Ruling:**`. In a feature cycle, the feature's own BRD comes first (FC11). The ruling uses check_profile's canonical names.
- **Defaults.** Each default has its canned reason. "If no mobile" means the ruling's profile marks phase 11b N/A (profiles.yaml). "If no AI" is assumed and can be turned on by the operator. `partial` defaults (B17 100x, L22 formal proof, CL3 soak, RL3 provenance at M) still need a section.
- **Turned on.** Each item the size turns on is checked: not N/A, a regex mention, or a minimum percentage. Examples: ASVS L1/L2 in T20, Stryker at least 70% or 80% in TS10, ZAP SV7 at S.
- **Pre-filled.** On every Stop, the gate writes `.sdlc/coverage/<scope>-<label>-COVERAGE.md` with the defaults and their canned reasons. Agents copy it into place.
- **Operator override.** `ADOPT` of `.sdlc-proposals/config/coverage-overrides.yaml` (`turn_on: [ID]`, `na: [{topic, reason}]`), validated at ADOPT. A turned-on topic can no longer be N/A. A ruled topic is written `N/A: operator`.

### 1.4 Coverage topics in the phase skills and validators (section 3)

- **The topics.** `/moadix:coverage` (`commands/coverage.md`) is in the always-available skill set for every phase. It is generated from the catalogue by `gate/contract.py doc`, and tests/inc7 checks that the file matches. It covers the discovery protocol, the three contract files, trace IDs, the EARS and cite rules, the critic, the size rule, and every phase's topics with its role and BLOCKERs.
- **Where they are enforced.** The validators enforce the topics through check-contract, and the critic's brief carries them per phase.

### 1.5 Tools (section 4)

See section 4 below. The new tools are pinned and fetched, and `tests/tools` checks each one's installed stamp. They are **not yet wired** as gate-run validators (section 6).

### 1.6 Skill hygiene

- **Renamed.** `bmad-forge-idea`, `bmad-deep-recon`, `bmad-prd` and `bmad-architecture` are now `forge-idea`, `deep-recon`, `prd` and `architecture`. Each keeps `LICENSE` (MIT and the BMad trademark notice). Each rename is recorded in its MOADIX-CHANGES.md, with SKILL.md marked `modified` in MOADIX-UPSTREAM.sha256 and `upstream_name` in SOURCES.yaml. The manifest, bmad-adapter, check-seam, THIRD-PARTY.md and the tests follow the new names.
- **Provenance.** Every SOURCES.yaml entry now carries `retrieved:` beside its source, commit and licence.
- **Self-approval grep.** It now also catches push-to-remote wording and done/ready wording.
  - One real hit was stripped: the prd `customize.toml` comment "the user has been told the PRD is ready".
  - Seven benign hits were allowlisted with reasons. All 165 matches now have a reason.

### 1.7 Operator experience (section 5)

- **Summaries.** APPROVE and REVIEW show only BLOCKER and MAJOR findings, plus a count of the MINORs and the file they are in (`.sdlc/cache/minor/<scope>-<label>.md`). The worker routes `MINOR` lines out of the summary.
- **Size defaults.** They are pre-filled with their canned reasons (1.3), and the operator can override any of them.
- **Monthly pin proposal.** `managed/propose_pins.py` asks npm, PyPI and GitHub for the newest release at least 14 days old and prints a proposal; it changes nothing. tools.yaml carries `reviewed: 2026-11-14`. SessionStart tells the operator when that date is more than 30 days old (no cron: the design bans scheduled tasks).

### 1.8 Phase-7 rules (operator instruction)

- **The rules.** They are added verbatim to the phase-7 implementation skill (`test-driven-development`), with a MOADIX change notice and a CHANGES entry:
  1. Smallest change that meets the requirement.
  2. Do not touch code the task does not need.
  3. Add nothing nobody asked for.
- **Enforcement.** The code reviewer's brief lists them as R7-1 to R7-3. A finding carrying `"rule": "R7-n"` is a MAJOR: check-verifiers-7 fails until the finding is fixed or the operator records `WAIVE code-reviewer.<id>` with a reason. An unknown rule id fails the evidence. A high or critical one stays unwaivable.

### 1.9 Toy-notes findings

- **F-1.** The INIT/session message now lists every installed `_bmad/` file and says how many there are (7).
- **F-2.** Nothing in the gate reads `active_phases`, so the gate already ran 6b and 10c for WEB. The profile simply declared otherwise. WEB and WEB→APP now declare 6b and 10c, which matches what the gate does and Amendment 3, which gives both phases topics. No behaviour changed.

## 2. Test counts

| Suite | Result | Evidence |
|---|---|---|
| **tests/inc7 (new)** | **115/115** | `docs/evidence/increment-7-suite-inc7.txt` |
| tests/gate2 (increment 2) | 299/299 (static checks included) | `…-suite-gate2.txt` |
| tests/verifiers (increment 4) | 97/97 | `…-suite-verifiers.txt` |
| tests/tools (increment 5, real pinned tools) | 106/106, 2 skipped (loopback bind, Terminal only); was 95, plus 11 new pin checks | `…-suite-tools.txt` |
| tests/inc6 (increment 6) | 68/68 | `…-suite-inc6.txt` |
| tests/skills (increment 3) | 43/43 | `…-suite-skills.txt` |
| tests/release | 9/9 (0.4.0 → 0.5.0) | `…-suite-release.txt` |
| tests/corpus (attack corpus) | **not run**: it needs the Keychain (Terminal). Its guard self-test passes 18/18. Its `review()` now prepares the contract like the other suites. | `…-suite-corpus-guard-selftest.txt` |
| Static: ruff, mypy, shellcheck, hardcoded-state, self-approval grep | clean; 0 undeclared (11 exemptions added for the catalogue's phase labels); 165/165 allowlisted | `…-static.txt` |
| tests/install/dryrun.py | not run (Terminal and Keychain) | — |

**inc7 groups** (passing controls plus planted defects for each):

| Group | Checks |
|---|---|
| coverage-lint | 15 |
| size rule | 11 |
| discovery-lint | 10 |
| adr-lint | 7 |
| trace-lint | 6 |
| ears-lint | 10 |
| cite-lint | 9 |
| critic, through the real hooks and APPROVE | 19 |
| overrides through ADOPT, and the skeleton | 7 |
| phase-7 rules | 5 |
| hygiene 4, tools 6, fixes 2, operator experience 3, guard 1 | 16 |

Two critic checks in detail:

- **BLOCKER and MAJOR:**
  - A BLOCKER refuses APPROVE, and its WAIVE is refused.
  - A MAJOR refuses APPROVE until a waiver is recorded; after the waiver, APPROVE is recorded.
  - A MINOR stays out of the summary and lands in the file.
- **Seven planted CRITIC.json defects:**
  - a verdict field;
  - a missing topic;
  - a quote that is not at the citation;
  - a dead citation;
  - a foreign topic;
  - a bad severity;
  - no fix.

**How the earlier suites follow increment 7.** `tests/lib/contract_fixture.py` gives each phase what an agent would write: every topic N/A with its own reason, the size defaults, real sections for the topics the size turns on, `No questions`, and clean critic evidence through the gate's real brief and receipt. `fixtures.Env.review_until_fresh` calls it. Fixture documents were changed only where the new linters require it: the fixture PRD gained an unwanted-behaviour AC and a role matrix, the research URL gained a date, and inc6's feature PRD gained the same. Assertions were changed where increment 7 adds a result: the registry count, PROCEED-PAST's failing list, and the no-Skill agents list. No existing assertion was weakened.

## 3. Choices made without asking (say if any is wrong)

- **Contract folder.** `sdlc/<label>/` (the amendment's `sdlc/<phase>/`), with ADRs in each phase's `adr/`. The older `sdlc/adr/` and `sdlc/decisions/` stay writable.
- **FC topics.** Each is assigned to the feature phase whose COVERAGE.md lists it:
  - FC1, FC2, FC11 → 0;
  - FC3 → 2;
  - FC4 → 3;
  - FC7 → 4;
  - FC5, FC6 → 5;
  - FC8 → 10b;
  - FC9, FC10 → 11.
- **Critic waiver id.** `gap-critic.<topic>`, which is stable across critic runs (finding ids are not). One waiver covers that topic's MAJOR findings in the current phase.
- **Code-reviewer MAJOR.** Severity stays `medium`, with `"rule": "R7-n"`. The verifier severity scale (critical…info) is unchanged.
- **A register-table row is not a definition.** Otherwise every security report and gaps register would fail trace-lint. A SEC-ID cites its trust boundary (TB, level 4 < SEC 4.5), as the built threat models do.
- **"If no AI".** Assumed by default; the operator turns T19 on.
- **The critic is required in every gated phase.** Missing evidence fails closed.
- **Links.** Resolution needs the network in the gate's worker. When it is offline, phase 1 is UNKNOWN and cannot be approved or proceeded past until the links are checked.

## 4. Tools (pinned, licences read)

Pins are the newest releases at least 14 days old on 2026-11-14 (cut-off 2026-10-31). Each LICENSE was read in full and hashed. The full table, with URLs, hashes and lockfile notes, is in `docs/evidence/increment-7-licences.md`. All gate-run tools are fetched into `~/.cache/moadix-tools` with their sha256 checked, and each runs.

| Tool | Version | Licence | Kind and pin | Phase (Amendment 3) |
|---|---|---|---|---|
| oasdiff | 1.35.0 | Apache-2.0 | archive, upstream checksums.txt | 5, 10b, 11, FC |
| squawk | 2.71.0 | Apache-2.0 OR MIT | PyPI `squawk-cli` wheels, hash-locked (no GitHub checksum file) | 5, 7, FC |
| vacuum | 0.36.1 | MIT | archive, checksums.txt | 5 |
| LikeC4 | 1.60.0 | MIT | npm lockfile | 3, B |
| dependency-cruiser | 18.7.0 | MIT | npm lockfile | 3, 7, B |
| knip | 6.44.1 | ISC | npm lockfile | 7, B |
| OWASP pytm | 1.4.0 | MIT, plus MITRE CAPEC terms (royalty-free, attribution) | PyPI, hash-locked | 4, B, FC |
| Schemathesis | 4.32.7 | MIT | PyPI, hash-locked | 8, 10b |
| Lighthouse CI | 0.15.1 | Apache-2.0 | npm lockfile | 10a |
| zizmor | 1.31.1 | MIT | PyPI wheels, hash-locked | 11 |
| actionlint | 1.7.12 | MIT | archive, checksums file | 11 |
| ZAP (passive baseline) | 2.17.0, image `20261026-stable` | Apache-2.0 | `images:` in tools.yaml, OCI digest sha256:030d3df5… (not fetched) | 9 |
| Trivy CycloneDX | 0.76.1 (already pinned) | Apache-2.0 | `--format cyclonedx` confirmed in the 0.76.1 source | 9, 11 |
| Stryker JS | 10.1.1 | Apache-2.0 | product dependency (version pinned, not fetched) | 8, B |
| Testcontainers (Node) | 12.2.1 | MIT | product dependency | 8 |
| MSW | 3.0.3 | MIT | product dependency | 8 |
| Playwright toHaveScreenshot (`@playwright/test`) | 1.64.1 | Apache-2.0 | product dependency | 10b |
| Anthropic code-simplifier | commit aecd4c85 | Apache-2.0 | **not vendored** (see 6) | 7 |

Nothing from the rejected list was added; tests/inc7 checks this.

**Stopped and reported (not permissive).** axe-core 4.14.0 and @axe-core/playwright 4.14.0 are **MPL-2.0**, read from their LICENSE files. They are not added. The phase 6/8/10a axe checks therefore have no pinned tool.

**Flagged.** These tools are permissive themselves but pull in MPL-2.0 dependencies, fetched unmodified from their registries. They are added; question 7.3.

| Tool | MPL-2.0 dependencies |
|---|---|
| likec4 | lightningcss |
| lhci | axe-core |
| Schemathesis | hypothesis, certifi |

**Caveats measured:**

- **dependency-cruiser 18.7.0** refuses this Mac's Node 25.2.0; it supports ^22, ^24 and >=26.
- **pytm** has no CLI. Its `python` symlink loses the venv, so it must run as `<tool>/venv/bin/python`.
- **lhci** 0.15.1 dates from June 2025 (0.16 is under 14 days old) and needs a Chrome binary.
- **actionlint** moves slowly: its last release was 2026-03-30 and its last push 2026-07-16. It is not archived.
- **ZAP:** the `stable` tag points at a build only 11 days old, so the dated build is pinned instead. The image contents (Debian, OpenJDK, firefox-esr) were not licence-scanned.

## 5. Conflicts: stopped, awaiting a ruling

1. **Trace-ID prefixes T- and SR-.** Amendment 3 uses T- for threats (phase 4) and SR- for store-release items. The built system already uses:
   - **T-nnn for tasks** (phase 7: v1 check-traceability, the feature task template);
   - **SR-n for shared resources** (phase 4: v1 check-threat-model, concurrency).

   trace-lint therefore checks T- and SR- only for duplicates and dangling references, never for upstream. Ruling needed: rename the built prefixes (a migration of every validator and template), or change the amendment's.
2. **Phase 12 (Retro).** Amendment 3 gives it coverage topics and a critic BLOCKER that "refuses APPROVE". In MOADIX, phase 12 is not gated: there is no APPROVE 12, its skills run during 11 and after `done`, and `sdlc/12-*.md` lives in phase 11's path map. The RT topics are in the catalogue and in `/moadix:coverage`, but no validator or critic is scheduled for 12. Ruling needed: make 12 a gated phase, or check RT coverage at APPROVE 11.

## 6. Not built, or skipped, and why

- **Phase-specific gates from section 3, beyond the four linters, are not built.** The tools are pinned and fetched, but none is wired as a gate-run validator. That leaves:
  - the LikeC4 build and the dependency-cruiser rules naming H4 modules (3);
  - the pytm run and SEC-CONTROLS.csv with ASVS 5.0.0 IDs (4);
  - vacuum, oasdiff and squawk (5);
  - the tokens.json schema, the contrast script, the screen × state CSV and stylelint (6);
  - tsc, ESLint, depcruise and knip JSON (7);
  - JUnit, ac-trace.json, Stryker, Schemathesis and axe (8);
  - ZAP, sbom.cdx.json and SEC-VERIFICATION.csv (9);
  - LV-INVENTORY.csv and LHCI (10a);
  - zizmor and actionlint (11);
  - the existing test suite run in phase B.

  Each needs its own validator in the style of increment 5, fixtures and real-tool tests. Several also run product code (pytm, LikeC4 config, Stryker, Schemathesis), which needs the confinement design increment 6 already noted as missing. This is the bulk of the remaining work.
- **"Feature additions get the full product-document validators, not a lighter check" (FC).** The new linters do run on feature additions with the full rules. The v1 product validators (check-handoff, check-lld, check-threat-model, check-traceability…) still do not; increment 6 listed this gap. Doing it means validating a merged view of the product and the feature.
- **code-simplifier is not vendored.** It is a plugin **agent**, not a skill: `plugins/code-simplifier/agents/code-simplifier.md` in anthropics/claude-plugins-official at commit aecd4c85, Apache-2.0. A second copy sits in pr-review-toolkit. Making it phase-7 authoring guidance with its verdict text stripped is an adaptation, so it is a question (7.4).
- **Discovery "one question at a time"** is an instruction in `/moadix:coverage`. The gate can check the log, not the conversation.
- **ZAP** is pinned in `images:`. The installer does not pull images, and no validator runs it yet.
- **Not run here:** the attack corpus and the install dry run (Terminal and Keychain), and any live check.

## 7. Open questions for the operator

1. **Conflict 5.1:** how should the T- and SR- prefixes be resolved?
2. **Conflict 5.2:** should phase 12 be gated, or should its RT coverage be checked at APPROVE 11?
3. **MPL-2.0 transitive dependencies:** are they acceptable when fetched unmodified (likec4/lightningcss, lhci/axe-core, Schemathesis/hypothesis and certifi)? And with axe-core refused, what is the accessibility check for 6, 8 and 10a? Options: accept MPL-2.0 for an unmodified product dependency, or name another tool.
4. **code-simplifier:** vendor its agent text as a phase-7 skill (verdict text stripped), or skip it?
5. **dependency-cruiser and Node:** install Node 24 LTS for it, or pin an older dependency-cruiser?
6. **Products already in progress (toy-notes):** after the update, every remaining phase needs COVERAGE.md, DISCOVERY.md and gap-critic evidence, and its documents must pass the new linters (for example ears-lint at phase 2). Should in-flight products start the contract at their current phase (as built), or be exempt until their next feature?
7. **Naming:** `_bmad/MOADIX-BMAD.json`, the manifest the gate writes into products, still has BMAD in its file name. The trademark rule as written covers skill names. Should this file be renamed too?
8. **Which tool gates in section 6 should come first?**

## 8. Install steps (operator, in Terminal)

The checker is unchanged, so this is an update (no new QR code).

1. Close every Claude Code session.
2. When you choose to publish: `cd ~/moadix && git push && git tag v0.5.0 && git push origin v0.5.0`.
3. `managed/install.sh`. Expect `MOADIX is updated.` as the last line. The installer fetches the 11 new tools.
4. In Claude Code: `/plugin marketplace update moadix`, then `/reload-plugins`. Expect moadix **0.5.0**, the agent `gap-critic`, `/moadix:coverage`, and the renamed skills `forge-idea`, `deep-recon`, `prd` and `architecture`.
5. Optional, in Terminal: `/usr/bin/python3 tests/corpus/run.py` and `/usr/bin/python3 tests/install/dryrun.py`.

**Separate from this commit.** The main-branch guard and policy change from earlier in this session are still uncommitted in the working tree: `gate/mainguard.py`, `gate/pretool.py`, `managed/managed-settings.json`, `tests/install/render.py`, `tests/install/policy_live.sh`, `tests/mainguard/` and `docs/INSTALL.md`. `docs/AMENDMENT-4.md` is also untracked. All of these were deliberately left out of the increment-7 commit. In the working tree, the mainguard suite passes 163/163 and render passes 18/18. If you install from the working tree, it includes them.
