# Amendment 3 (2026-11-12) — Phase coverage standards, gap critics and gate-run tools

Overrides earlier sections of DESIGN.md where they differ. Decided by the operator after a research review. Figma is out of scope.

**Rulings on increment 7 (2026-11-14), part of this amendment:**
1. Trace-ID prefixes keep MOADIX's built meanings: **T-** is a task (phase 7) and **SR-** a shared resource (phase 4). Threats are **TH-** and store-release items **STR-**. The amendment's TASK- is dropped in favour of T-. trace-lint checks upstream for all four.
2. Phase 12 (Retro) is a gated phase: APPROVE 12, its own path-map entry for `sdlc/12-*`, validators and a gap critic. APPROVE 11 still releases; phase 12 does not block the release. A new FEATURE on the same product is refused until phase 12 of the previous cycle is approved; STATUS shows it as pending.
3. MPL-2.0 is accepted for tools and product dependencies fetched unmodified from their registry and never vendored into this repository; each is recorded in THIRD-PARTY.md with its source. Any other non-permissive licence still stops and is reported.
4. Gate-run Node tools use a pinned Node 24 LTS fetched by the installer into the tools cache (checksum verified), never the system Node.
5. In-flight products start the contract at their current phase; already approved phases are not re-linted.

**Rulings on increment 7b (2026-11-14):** Docker is a hard requirement for the gates that execute product code (fail closed to UNKNOWN); no Testcontainers and no Docker socket for product code, ever; JSON-only configuration for LikeC4 and dependency-cruiser (`.dependency-cruiser.json`); the resource limits of docs/confinement-design.md section 3.5, raisable at most 2x through ADOPT; a package's install script runs only when listed in an adopted product-tools.yaml.

## 1. Cross-phase contract (every phase, Baseline and feature cycles)

| Element | Rule | Deterministic check (gate-run) |
|---|---|---|
| Coverage file | `sdlc/<phase>/COVERAGE.md` lists every topic ID of the phase with a section anchor or `N/A: <reason>` | `coverage-lint`: every ID present, no duplicates, anchors resolve, N/A reason non-empty and not boilerplate |
| Discovery | The phase skill asks the operator one question at a time, 2–4 options plus a recommendation; answers logged as `Q-n` | Log exists; every Q has a chosen option |
| Decision records | MADR-style `ADR-nnn`: context, ≥2 alternatives, criteria, decision, consequences, sources with URL and date | Schema check |
| Gap critic | Fresh-context verifier per phase (brief generated and enforced by the gate, as in increment 4) writes `CRITIC.json`: id, topic, severity, evidence quote, fix | JSON schema; any open BLOCKER refuses APPROVE; a MAJOR needs a WAIVE with reason |
| Trace IDs | B-, BR-, R-, P-/US-/AC-, H-/ADR-, TH-/SEC-, SR- (shared resource), L-, U-, V-, T- (task), TS-, SF-, LV-, RG-, CL-, RL-, STR-, RT-, BL-, FC- (ruling 1) | `trace-lint`: every downstream ID points to an existing upstream ID; no orphans; IDs never reused |

Critic severity: BLOCKER = required topic missing or hollow, contradiction with an upstream or frozen document, missing security/privacy control, or a claim that needs a citation and has none. MAJOR = answered but not testable or measurable. MINOR = clarity. A critic never passes a phase; it only writes findings.

Skill hygiene: strip every step that commits, pushes, deploys, sets phase status or says done/ready; record source URL, commit, licence and retrieval date; rename every vendored BMAD skill so no MOADIX name contains "BMad"/"BMAD" (trademark), keeping the MIT notice.

Own linters to build: `coverage-lint`, `trace-lint`, `ears-lint`, `cite-lint`, CRITIC.json schema check.

## 2. Size rule (depth by product size, set in B19)

| Size | Profile | N/A by default (canned reason, operator may override) | Turned on |
|---|---|---|---|
| S | ≤ ~5 entities, no payments, one locale, low risk | B17 (100x), B24, H17, H22, H23, T19, L20, L22 formal proof, U17, V13, TS10, CL3 soak, CL6, RL3, RL7, RL8, all of 11b if no mobile | ASVS L1, ZAP baseline, restore drill |
| M | Multi-tenant or payments, RTL, public users | H23 if no mobile, T19 if no AI, formal proofs, RL3, RL8 | ASVS L2, pytm, Stryker ≥70% on critical modules, Schemathesis, soak, Lighthouse CI |
| L | Regulated data, high scale, native apps | none | ASVS L2/L3, PASTA, 1–2 formal invariants, Stryker ≥80%, fault injection, canary, SLSA provenance, full 11b |

## 3. Coverage topics per phase

### Phase 0 BRD — role: senior business analyst / product strategist
B1 problem and vision · B2 stakeholders and personas · B3 business model · B4 feature discovery (run a domain checklist; record every feature the operator did not name as accepted or rejected with a reason) · B5 feature necessity (MoSCoW + Kano class, with reason) · B6 entity lifecycles · B7 user journeys · B8 operations/back office · B9 notifications · B10 markets, language, RTL, currency · B11 legal and compliance (named regimes) · B12 data and retention · B13 competitors · B14 success metrics (baseline, target, data source, review date) · B15 constraints · B16 risks and assumptions · B17 growth path 10x/100x · B18 out of scope · B19 platform ruling and size · B20 jobs-to-be-done · B21 riskiest-assumption tests · B22 money flows (payments, refunds, chargebacks, payouts, VAT) · B23 business-rules catalogue (BR-n) · B24 tenancy model · B25 customer support and SLAs · B26 accessibility obligation per market · B27 top three ISO 25010 qualities from the business view.
Critic BLOCKER: missing money flow or legal regime; attacks generic personas, invented statistics, everything rated Must.

### Phase 1 Research — role: research analyst / technical due diligence
R1 open questions · R2 competitor teardown (3–5 real products) · R3 user expectations · R4 legal with dated authoritative sources · R5 technical options compared · R6 third-party providers · R7 cost model at launch/10x/100x · R8 prior art and reuse · R9 decision log (ADRs) · R10 BRD changes · R11 source quality (URL + retrieval date, primary over secondary) · R12 build vs buy, lock-in, exit cost · R13 licence compatibility · R14 provider SLAs, quotas, data residency · R15 feasibility spikes · R16 new risks fed back to B16.
Gate: `cite-lint` (every claim has URL and date; links resolve). Critic BLOCKER: uncited legal or cost claim.

### Phase 2 PRD — role: senior PM / requirements engineer
P1 stories traced to goals · P2 EARS acceptance criteria · P3 role × action matrix incl. who must not · P4 entity rules · P5 every screen state · P6 validation rules · P7 notifications · P8 admin and audit · P9 search/filter/sort/pagination · P10 measurable NFRs · P11 analytics events · P12 migration and seed data · P13 release slicing · P14 open questions · P15 traceability · P16 ≥1 unwanted-behaviour AC per story · P17 limits and quotas · P18 privacy ACs (consent, export, deletion) · P19 audit log · P20 accessibility ACs · P21 i18n/RTL ACs · P22 glossary · P23 story map with walking skeleton.
Gate: `ears-lint` (each AC matches an EARS template; no vague terms such as fast, user-friendly, appropriate, etc., TBD; no compound requirements; every NFR has number and unit; role × action matrix complete). Evidence: PRD, AC.json. Critic BLOCKER: untestable AC or missing authorization rule.

### Phase 3 HLD — role: staff architect
H1 quality attributes ranked with trade-offs · H2 C4 context and containers as LikeC4 source · H3 architecture style with alternatives · H4 module boundaries · H5 data architecture · H6 performance design and budgets · H7 scalability · H8 concurrency and integrity · H9 integrations and failure behaviour · H10 security architecture · H11 reliability, backups, RTO/RPO · H12 observability · H13 deployment and rollback · H14 cost · H15 technology choices as ADRs · H16 future-proofing · H17 multi-tenancy isolation · H18 privacy and data residency · H19 i18n/RTL architecture · H20 fitness functions as dependency-cruiser rules in `.dependency-cruiser.json` (JSON only) · H21 operability for a solo operator · H22 ATAM risks, sensitivity and trade-off points · H23 readiness for native clients.
Gate: LikeC4 build exits 0 (JSON configuration only); `.dependency-cruiser.json` rules name the H4 modules (JSON only: a JS or TS config is refused, ruling 4 on increment 7b); every container appears in H4/H13; every H1 attribute has a measurable scenario. Critic BLOCKER: no tenant-isolation design, or an unaddressed H1 trade-off.

### Phase 4 Threat Model — role: security architect
T1 assets · T2 data flows and trust boundaries · T3 STRIDE per element · T4 abuse cases · T5 authorization/IDOR · T6 authentication attacks · T7 injection and input · T8 privacy threats (LINDDUN categories) · T9 supply chain · T10 business-logic races · T11 controls mapped to OWASP ASVS 5.0.0 IDs (V1–V17) · T12 residual risk · T13 cross-tenant threats (queries, caches, files, jobs) · T14 feature abuse · T15 detection and alerting (Top 10:2025 A09) · T16 exceptional conditions and fail-open paths (A10) · T17 secrets and key management · T18 third-party trust (webhook signatures, SSRF, OAuth redirects) · T19 AI/LLM features or N/A · T20 ASVS level with reason.
Gate: pytm model (`tm/model.py`) runs and exits 0; every T-ID has a SEC-ID or accepted-risk record; SEC-CONTROLS.csv maps SEC-ID → T-ID → ASVS ID → verification method; ASVS IDs exist in 5.0.0. Critic BLOCKER: unmitigated high-impact authz or tenant threat.

### Phase 5 LLD — role: staff engineer / API designer
L1 OpenAPI contract · L2 error model (RFC 9457 problem details) · L3 API conventions · L4 schema, indexes, migrations · L5 state machines · L6 key sequences · L7 concurrency details · L8 module design · L9 background jobs · L10 configuration · L11 test strategy · L12 traceability · L13 idempotency and retries · L14 pagination/filter/sort contract · L15 endpoint authorization map (operation → permission → tenant rule) · L16 versioning and deprecation · L17 zero-downtime expand/contract migrations · L18 caching and ETags · L19 rate limits per endpoint · L20 events and webhooks · L21 tenant scoping in data access · L22 critical invariants and how each is proven.
Gate: Redocly exits 0; vacuum OWASP ruleset clean; oasdiff against the last released spec shows no ERR without an approving ADR; squawk clean on Postgres migrations (N/A for SQLite); every operation has security, operationId, problem+json errors and an L15 row. Critic BLOCKER: missing authz or tenant scope; unapproved breaking change.

### Phase 6 UX — role: design lead
U1 information architecture · U2 flows · U3 design system · U4 every screen, every state · U5 responsive · U6 accessibility WCAG 2.2 AA · U7 languages and RTL · U8 content and microcopy · U9 motion · U10 brand · U11 usability check · U12 tokens in W3C DTCG format with computed contrast · U13 component × state inventory · U14 forms and error recovery · U15 system states per screen · U16 LCP/INP/CLS budgets · U17 themes · U18 RTL rules (mirroring, non-mirrored icons, numerals, bidi) · U19 email and notification templates · U20 touch targets and gesture alternatives.
Gate: tokens.json schema; own contrast script (body text ≥ 4.5:1); screen × state matrix CSV complete and covering every PRD screen; stylelint logical-properties rule in the product. Critic BLOCKER: WCAG AA failure on a core journey or a missing state on a P1 screen.

### Phase 6b Provisioning — role: platform engineer
V1 accounts · V2 secrets and keys · V3 environments · V4 domains and email · V5 quotas and costs · V6 test data · V7 readiness check · V8 least-privilege IAM and MFA · V9 spend caps · V10 account recovery / break-glass · V11 SPF, DKIM, DMARC · V12 environment parity, no production data elsewhere · V13 infrastructure record · V14 secret rotation · V15 sandbox vs live keys.
Gate: dotenvx check; .env.example lists every key the code reads; gitleaks clean; Trivy config scan. The agent never holds live credentials. Critic BLOCKER: a production credential reachable by the agent, or MFA missing.

### Phase 7 Implementation — role: tech lead
I1 task breakdown T- → AC · I2 definition of done per task · I3 slice order (walking skeleton, riskiest first) · I4 TypeScript strict, no unexplained any · I5 ESLint with type-aware rules · I6 dependency-cruiser rules pass · I7 knip clean · I8 complexity and file-size limits · I9 error handling and structured logging · I10 secure coding: validation, authz per handler, tenant scope · I11 no hard-coded user-facing strings · I12 squawk-clean migrations · I13 review findings resolved or waived · I14 ADR for every deviation from the LLD · I15 Conventional Commits.
Gate: `tsc --noEmit`, ESLint JSON, dependency-cruiser JSON (0 errors), knip JSON (0 or allow-listed with reason); every P1 AC has a T- task; every closed T- task links its tests. Critic BLOCKER: security or tenant defect; a test weakened or skipped to pass.

### Phase 8 Testing — role: SDET / QA lead
TS1 strategy incl. what is not tested and why · TS2 AC traceability (`@AC-id` tags) · TS3 partitions, boundaries, decision tables, state transitions · TS4 a test per unwanted-behaviour AC · TS5 authz matrix allow and deny incl. cross-tenant · TS6 real-database integration (service containers the gate starts; no Testcontainers) · TS7 HTTP doubles (MSW), no live third-party calls · TS8 contract tests (Schemathesis, ephemeral environment only) · TS9 property tests for L22 invariants (fast-check) · TS10 mutation score (Stryker) · TS11 line/branch coverage · TS12 test-data builders · TS13 zero retries in the gate, quarantine list with expiry · TS14 axe checks · TS15 i18n missing-key and pseudo-locale/RTL checks · TS16 defect register.
Gate: JUnit, coverage JSON, ac-trace.json (no AC without a passing test), Stryker mutation.json threshold by size, Schemathesis report, axe JSON, no skipped test without waiver. Critic BLOCKER: untested P1 AC, missing cross-tenant deny test, lowered threshold.

### Phase 9 Security Verification — role: AppSec engineer
SV1 scope and ASVS level · SV2 SAST · SV3 SCA · SV4 secrets in full history · SV5 container images · SV6 config/IaC · SV7 DAST passive baseline (ZAP) · SV8 API negative and fuzz tests · SV9 authz/IDOR evidence · SV10 authentication, sessions, tokens · SV11 CycloneDX SBOM (Trivy) · SV12 licence allow-list · SV13 headers, TLS, cookies · SV14 evidence for every SEC-ID · SV15 triage of SF-n findings · SV16 human residual-risk acceptance · SV17 MASVS or N/A.
Gate: SARIF from Semgrep, gitleaks, Trivy, ZAP, Claude Security; OSV JSON; sbom.cdx.json; SEC-VERIFICATION.csv; tool versions recorded; no open High/Critical without recorded acceptance. ZAP: passive baseline via Docker CLI against a disposable environment only. Critic BLOCKER: unresolved Critical/High; unverified authz or tenant control.

### Phase 10a Live Verification — role: QA lead / exploratory tester
LV1 element inventory from U13 · LV2 trace or video per P1 AC · LV3 every role incl. forbidden attempts by UI and URL · LV4 every state observed · LV5 every locale incl. RTL · LV6 all breakpoints + one mobile device or emulation · LV7 axe + keyboard pass · LV8 Lighthouse CI assertions · LV9 no console errors or failed requests · LV10 notifications received · LV11 sandbox payments (success, failure, refund) · LV12 browsers by size · LV13 defects with repro and trace.
Gate: LV-INVENTORY.csv covers 100% of U13; every P1 AC has a trace; LHCI JSON; axe JSON. Critic BLOCKER: unexercised P1 AC or element; "verified" by reading code.

### Phase 10b Regression — role: SDET
RG1 scope (all P1 ACs, critical journeys) · RG2 Playwright E2E tagged by AC · RG3 API regression (Schemathesis + oasdiff) · RG4 visual baselines LTR and RTL (Playwright toHaveScreenshot, baselines in repo) · RG5 Maestro mobile flows or N/A · RG6 flakiness check (repeat-each, zero retries) · RG7 runtime budget · RG8 data reset · RG9 ownership · RG10 runs on every PR.
Critic BLOCKER: uncovered critical journey; flaky gate test.

### Phase 10c Concurrency and Load — role: SRE / performance engineer
CL1 workload model · CL2 p95/p99 and error-rate thresholds from SLOs · CL3 load, stress, spike (+ soak for M/L) · CL4 race tests with SQL invariant checks · CL5 slow queries, EXPLAIN, locks, deadlocks · CL6 fault injection (M/L) · CL7 backpressure and rate limits · CL8 capacity headroom · CL9 results vs H6 budgets · CL10 stated differences from production.
Gate: k6 JUnit and summary; thresholds in the script equal CL2; invariant output shows 0 violations. k6 is AGPL: run the unmodified binary, never vendor or patch it. Critic BLOCKER: invariant violation; SLO miss without ADR; thresholds set after seeing results.

### Phase 11 Release — role: release manager / SRE
RL1 CI re-runs every gate tool at pinned versions · RL2 actions pinned by 40-char SHA, least-privilege permissions, zizmor and actionlint clean · RL3 SBOM attached (+ provenance for L) · RL4 production environment with required human reviewer · RL5 migration order and pre-deploy backup · RL6 rehearsed, timed rollback · RL7 kill switches · RL8 canary/blue-green (L) · RL9 smoke tests · RL10 logs, metrics, traces, error tracking · RL11 SLOs and alerts · RL12 uptime check · RL13 timed restore drill vs RTO/RPO · RL14 runbooks · RL15 changelog (release-please) · RL16 docs · RL17 privacy policy, terms, cookie consent, accessibility statement · RL18 human go/no-go record.
Critic BLOCKER: no rehearsed rollback or restore; unpinned or injectable workflow.

### Phase 11b Store Release — role: mobile release manager
SR1 human-owned store accounts · SR2 signing-key custody · SR3 versioning · SR4 privacy labels / data-safety form mapped from the SBOM and SDK list · SR5 review pre-check (demo account, in-app account deletion, purchase rules, UGC moderation) · SR6 localized metadata and screenshots incl. RTL · SR7 age rating · SR8 permission purpose strings · SR9 TestFlight/internal tracks · SR10 phased rollout and halt criteria · SR11 crash-free threshold · SR12 OTA policy or N/A · SR13 export compliance.
No automatic submission. Critic BLOCKER: privacy-label mismatch.

### Phase 12 Retro — role: engineering manager
RT1 timeline · RT2 metrics (DORA four keys, phase cycle times, critic findings by severity, escaped defects) computed from git and the ledger · RT3 blameless went-well/went-poorly · RT4 contributing factors · RT5 MOADIX process changes · RT6 lessons queue, applied only after operator approval · RT7 actions with owner and date · RT8 cost (time, tokens, money) · RT9 tech-debt register · RT10 CLAUDE.md updates as approved diffs.
Critic BLOCKER: a change to MOADIX rules without approval.

### Phase B Baseline (extends Amendment 2)
BL1 system inventory · BL2 as-is C4 (LikeC4) · BL3 dependency graph and cycles · BL4 dead code · BL5 as-is schema · BL6 API inventory and drift · BL7 as-is BRD/PRD, each item tagged observed / inferred / unknown · BL8 test inventory (+ mutation on hotspots) · BL9 hotspots (churn × complexity from `git log --numstat`) · BL10 security baseline (phase 9 scanners) · BL11 as-is threat model (pytm) · BL12 ops baseline · BL13 known gaps and risks · BL14 characterization tests for top hotspots · BL15 frozen baseline tag. Also: the gate runs the product's existing test suite in the declared non-production environment.
Critic BLOCKER: inferred behaviour presented as fact.

### Feature cycles (extends Amendment 2)
FC1 feature brief vs frozen BRD · FC2 impacted documents · FC3 new AC IDs, never reused · FC4 superseding ADRs for conflicts · FC5 oasdiff result (breaking change needs ADR + deprecation plan) · FC6 expand/contract migration · FC7 threat-model delta · FC8 regression impact · FC9 flag and rollout · FC10 merge-back after release · FC11 feature size class. Feature additions get the full product-document validators, not a lighter check.
Critic BLOCKER: frozen-document change without a superseding ADR.

## 4. Tools

Keep everything already in MOADIX. Add (pin exact versions, verify each LICENSE file before vendoring or redistributing; stop and report any that is not permissive):

| Tool | Phase | Purpose |
|---|---|---|
| oasdiff | 5, 10b, 11, FC | API breaking-change detection |
| squawk | 5, 7, FC | Postgres migration safety |
| vacuum (OWASP ruleset only) | 5 | OWASP API rules on the OpenAPI contract |
| LikeC4 | 3, B | C4 diagrams as code, build-checked |
| dependency-cruiser | 3, 7, B | Module-boundary rules, cycles |
| knip | 7, B | Dead code and unused dependencies |
| OWASP pytm | 4, B, FC | Threat model as code |
| Stryker JS | 8, B | Mutation score |
| MSW | 8 | HTTP doubles |
| Schemathesis | 8, 10b | Contract and fuzz tests from OpenAPI |
| axe-core | 6, 8, 10a | Accessibility checks |
| ZAP (passive baseline) | 9 | DAST |
| Trivy CycloneDX output | 9, 11 | SBOM (reuse existing Trivy) |
| Lighthouse CI | 10a | Performance and web-vitals assertions |
| zizmor, actionlint | 11 | CI workflow security and lint |
| Playwright toHaveScreenshot | 10b | Visual regression LTR and RTL |

Testcontainers was removed from this table (ruling 3 on increment 7b): it needs the Docker API, and product code never gets a Docker socket; the gate starts service containers (for example Postgres) itself on the internal network and passes the tests their address.

Anthropic code-simplifier was removed from this table (ruling 4 on increment 7): it is a plugin agent, not a skill, and the operator chose to skip it.

Licences: MPL-2.0 is accepted for tools and product dependencies fetched unmodified from their registry and never vendored (ruling 3); axe-core and @axe-core/playwright are added on that basis.

Rejected (do not add): Spectral, Atlas migrate lint, Threagile, Threat Dragon, STRIDE GPT, Syft/Grype, trufflehog, CodeQL, Snyk, Pact, Chromatic/Argos/Lost Pixel, Artillery/Locust, changesets, ralph-loop, commit-commands, Anthropic frontend-design, Figma plugin, Infracost/Doppler/Infisical/SOPS, Appium MCP.

MCP servers stay phase-scoped: Playwright, DevTools, mobile-mcp only in 10a/10b; Context7 only in 1, 3, 5, 7; GitHub only in 11.

## 5. Operator experience

- The APPROVE/REVIEW summary shows only BLOCKER and MAJOR findings; MINOR findings go to a file.
- N/A defaults by size are pre-filled with their canned reason; the operator can override any of them.
- A monthly proposal bumps tool pins for operator review.
