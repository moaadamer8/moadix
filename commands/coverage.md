---
description: How the MOADIX cross-phase contract works in every phase (COVERAGE.md, DISCOVERY.md, ADRs, the gap critic, the size rule) and the coverage topics of each phase. Changes no gate state.
---
<!-- Generated from gate/config/coverage-topics.yaml by gate/contract.py coverage_doc(). Do not edit. -->
Every phase (Baseline and feature cycles too) leaves three things beside its documents, in `sdlc/<label>/` (`sdlc/features/<id>/<label>/` in a feature cycle). The gate checks them. For feedback before you commit, run a linter from the product root: `python3 -I "${CLAUDE_PLUGIN_ROOT}/gate/contract.py" <lint> . <phase>` (`${CLAUDE_PLUGIN_ROOT}` is the moadix plugin directory; <lint> is coverage, discovery, adr, trace, ears or cite). It prints FAIL and MINOR lines; only the gate's own run counts.

1. **Discovery, in rounds.** Ask the operator in rounds, not one question per message:
   - A round holds only questions that do not depend on each other. A question whose options depend on another answer waits for the next round.
   - Each question has 2-4 lettered options (A-D) and your recommendation with one line of why. A question of fact (the operator's tax status, where they deliver) has options but no recommendation: say so.
   - The operator answers the whole round in one line, for example `Q-4 B, Q-5 A, Q-6 C`.
   - Ask as many rounds as the phase needs. Never guess an answer to avoid asking; an assumption the operator did not confirm is a question for the next round.

   Log each answer in `DISCOVERY.md` (the format is the same whatever the round):

   ```
   ## Q-1: <the question>
   - A: <option>
   - B: <option>
   Recommendation: B, <why>
   Chosen: B
   ```

   For a question of fact, the recommendation line is `Recommendation: none (question of fact)`. If the phase raises no question, write `No questions: <why>`. Q-n IDs are never reused.
2. **Coverage.** `COVERAGE.md` lists every topic ID of the phase (below), each as `- <ID>: [title](../NN-doc.md#section)` pointing at the section that covers it, or `- <ID>: N/A: <reason>`. coverage-lint refuses a missing or duplicated ID, an anchor that does not resolve, a hollow section, and an empty, boilerplate or copied reason. The gate keeps a pre-filled skeleton at `.sdlc/coverage/<scope>-<label>-COVERAGE.md`: copy it and fill it in.
3. **Decision records.** Each decision is `adr/ADR-nnn-<slug>.md` (MADR): `# ADR-nnn: <decision>`, then `## Context`, `## Alternatives` (at least two), `## Criteria`, `## Decision`, `## Consequences`, `## Sources` (each with a URL and a date, YYYY-MM-DD). A superseding record says `Supersedes: ADR-nnn`.

**Trace IDs.** Every downstream ID cites an existing upstream ID in its own section or item (trace-lint): B-/BR-/BG- -> R- -> P-/US-(/AC-) -> H-/ADR- -> TH-/SR- -> SEC- -> L- -> U- -> V- -> T- (task) -> TS- -> LV-/RG-/CL- -> RL- -> STR- -> RT-. An ID is defined once (a heading or a bold list item; a row of a table whose first column is `ID` is a register entry), never reused, and never deleted once a phase was approved: mark it withdrawn.

**Phase 2** (ears-lint): each acceptance criterion is EARS (`The <system> shall ...`, `When <trigger>, the <system> shall ...`, `While <state>, ...`, `If <condition>, then the <system> shall ...`, `Where <feature>, ...`), one `shall`, no vague words (fast, user-friendly, appropriate, etc., TBD, should, ...); every story has an `If ..., then ...` AC; every NFR has a number and a unit; the role x action matrix (P3) marks every cell allow or deny and denies something. **Phase 1** (cite-lint): every URL carries a retrieval date on its line, every research claim has a source, and every link resolves.

**The gap critic.** When the phase is committed, launch `moadix:gap-critic` (the gate writes its brief). Its findings are BLOCKER (refuses APPROVE, cannot be waived), MAJOR (refuses APPROVE until fixed or waived by the operator), MINOR (a file for the operator) or CARRY (below the phase's depth: recorded for the later phase its defers rule names; never blocks this phase). The operator's waiver line is exactly `WAIVE <id>[,<id>...] [owner=<name>] [scope=<what it covers>] [expiry=YYYY-MM-DD] reason=<text> <code>`, with `gap-critic.<GC id>` as the id; one WAIVE may name several, comma-separated; owner, scope and expiry default to operator, the finding's document and 30 days. To keep a phase to one code, write the waivers you propose to `.sdlc-proposals/waivers.yaml` (`waivers:` entries with `id` and `reason`, optionally `owner`, `scope`, `expiry`): REVIEW shows them, and `APPROVE <phase> WITH-WAIVERS <code>` approves the phase and records exactly those waivers under that one code (a proposal naming a BLOCKER or an unknown id refuses the whole command). The gate gives every finding a stable id, `GC-<phase>-<n>`: the brief says which ids the run's new findings will get, and the critic's final message lists `C<k> = GC-...`, so a WAIVE can be typed before REVIEW. The next brief lists earlier findings with what happened to each (waived, carried, ruled, fixed?, open), so findings converge. A waiver binds one finding and lapses when the cited text changes. To rule on a finding in the log, write `Rules: GC-<phase>-<n>` in the Q-n or ADR that decides it. Fix the documents, commit, and launch it again. It never passes a phase. Runs 1 and 2 of a phase are full reviews; from run 3 a run reviews only the earlier findings and the sections changed since the previous run, and a new finding on a section unchanged since run n-2 counts only as a security, privacy, tenant-isolation or upstream-contradiction BLOCKER (otherwise it goes to the MINOR file, tagged frozen). An uncited claim is a BLOCKER only when it is a legal, cost, security or feasibility claim a decision depends on; cite the source's sentence for such a claim, because the critic has no network and judges support only from quoted text. Its result is tied to the documents it read: a fix commit to them needs a new run before APPROVE, so plan on at least two runs for a phase with a BLOCKER. A verifier's result stays current while its document set is byte-identical to the commit it reviewed: committing other files does not make it stale.

**Depth and carries.** Each phase below lists what it decides and what it defers (to which phase). A gap that matches no defers rule is judged at the current phase exactly as before; decides wins every overlap; nothing about security, privacy or tenant isolation is carried past phase 9. On APPROVE or PROCEED-PAST the gate records the phase's carries in the ledger as `CARRY-<phase>-<n>`. The target phase's COVERAGE.md lists each one addressed to it (`- CARRY-0-3: [section](../NN-doc.md#anchor)` or `N/A: <reason>`; the gate's skeleton pre-lists them). A carry left open after its target phase closes blocks the release; the operator may close it with `WAIVE CARRY-<phase>-<n> ...` and a reason (never a security, privacy or tenant-isolation one) or pull a carry back with `UNCARRY <GC id or CARRY id> <code>`.

**The size rule.** The size and platform ruling come from B19 (the BRD's `- **Size:**` and `- **Target Platform Ruling:**`). Topics N/A by default at that size may stay `N/A: size-default` (the skeleton fills in the canned reason); `partial` defaults still need a section. The operator can turn a default back on or rule a topic N/A through `ADOPT` of `.sdlc-proposals/config/coverage-overrides.yaml` (`turn_on: [ID]`, `na: [{topic: ID, reason: ...}]`); then write `N/A: operator`.

**Collapsing a phase.** At size S the operator may instead collapse phases 1, 6b, 10c (`COLLAPSE <phase> <code>`), recorded with the reason and the checks that will not run; a collapsed phase needs no COVERAGE.md and no critic run. When such a phase is not collapsed, its topics follow the size rule below. A phase the platform ruling leaves out (11b under WEB) collapses the same way at any size.

**Docker runs outside the sandbox only as the whole command.** The policy lets a command that starts with `docker` reach the Docker engine only when it is the entire command: no `cd`, `&&`, `;`, pipe, environment prefix or script around it (in any other form the socket is refused: `connect: operation not permitted`). Use docker's own flags instead of `cd`: `docker compose --project-directory app -f app/compose.yaml up -d`, `docker build -f app/Dockerfile app`, `docker run --rm -w /work <image> <command>`, `docker exec -w /app <container> <command>`, and `--env-file <file>` instead of an environment prefix. One docker command per Bash call.

**Live gates: the app's origin.** Every gate that talks to the running app (Schemathesis, ZAP, Lighthouse CI, axe) reaches it at one origin the gate owns, `http://sut.localhost:<port>` (product-tools.yaml `live.port`), and uses it for its URL, its Host header and, where it sends one, its Origin header. In the gate test stack (`live.compose`), set `APP_ORIGIN` (or the product's own allowed-origin setting) to exactly that value, for example `APP_ORIGIN: http://sut.localhost:3000` for port 3000, and allow no other host. `.localhost` is a secure context over plain http, so `Secure` and `__Host-` cookies work there unchanged.

**Claude Code memory is off in a product.** The gate refuses writes to `~/.claude/projects/*/memory/`: a note there would reach later sessions without the operator. A lasting instruction goes in `.sdlc-proposals/standing.md` for the operator to ADOPT.

- **S** (at most about five entities, no payments, one locale, low risk). N/A by default: B17 (the 100x growth path only), B24, H17, H22, H23, T19, L20, L22 (the formal proof of each invariant only), U17, V13, TS10, CL3 (the soak test only), CL6, RL3, RL7, RL8, all of phase 11b if no mobile. Turned on: ASVS L1 (T20), ZAP passive baseline (SV7), timed restore drill (RL13). Bars relaxed (quantities only): R2 2 to 3 real products; B13 at least 2 competitors.
- **M** (multi-tenant or payments, RTL, public users). N/A by default: H23 if no mobile, T19 if no ai, L22 (the formal proof of each invariant only), RL3 (the provenance attestation only), RL8. Turned on: ASVS L2 (T20), pytm threat model as code (T3), Stryker mutation score of at least 70% on critical modules (TS10), Schemathesis contract tests (TS8), soak test (CL3), Lighthouse CI assertions (LV8).
- **L** (regulated data, high scale, native apps). N/A by default: none. Turned on: ASVS L2 or L3 (T20), PASTA threat analysis (T3), one or two formal invariants (L22), Stryker mutation score of at least 80% (TS10), fault injection (CL6), canary or blue-green release (RL8), SLSA provenance (RL3), full phase 11b (SR1).

## Topics per phase

### Phase 0 BRD (role: senior business analyst / product strategist)

B1 problem and vision · B2 stakeholders and personas · B3 business model · B4 feature discovery (run a domain checklist; record every feature the operator did not name as accepted or rejected with a reason) · B5 feature necessity (MoSCoW + Kano class, with reason) · B6 entity lifecycles · B7 user journeys · B8 operations/back office · B9 notifications · B10 markets, language, RTL, currency · B11 legal and compliance (named regimes) · B12 data and retention · B13 competitors · B14 success metrics (baseline, target, data source, review date) · B15 constraints · B16 risks and assumptions · B17 growth path 10x/100x · B18 out of scope · B19 platform ruling and size · B20 jobs-to-be-done · B21 riskiest-assumption tests · B22 money flows (payments, refunds, chargebacks, payouts, VAT) · B23 business-rules catalogue (BR-n) · B24 tenancy model · B25 customer support and SLAs · B26 accessibility obligation per market · B27 top three ISO 25010 qualities from the business view

Critic BLOCKER: missing money flow or legal regime; attacks generic personas, invented statistics, everything rated Must.

Decides: D0.1 a business promise to a customer or partner; D0.2 a role's permissions (who may do what, in business terms); D0.3 a money flow (who pays whom and when, refunds, chargebacks, payouts, commission, tax); D0.4 a legal or privacy duty (the named regime and what it requires of the business); D0.5 data ownership and the retention policy; D0.6 release scope (each feature in, later or rejected); D0.7 the existence of a lifecycle state; D0.B the phase's BLOCKER rules: a missing money flow or legal regime, generic personas, invented statistics, everything rated Must.
Defers: X0.1 behaviour detail one story's acceptance criteria can settle (field lists, sorting, exact wording, exact table rows) -> phase 2; X0.2 attack defences and abuse limits beyond the business rule -> phase 4; X0.3 schema and API detail, including the mechanics of retention per record type -> phase 5; X0.4 screen layout and copy -> phase 6.

### Phase 1 Research (role: research analyst / technical due diligence)

R1 open questions · R2 competitor teardown (3–5 real products) · R3 user expectations · R4 legal with dated authoritative sources · R5 technical options compared · R6 third-party providers · R7 cost model at launch/10x/100x · R8 prior art and reuse · R9 decision log (ADRs) · R10 BRD changes · R11 source quality (URL + retrieval date, primary over secondary) · R12 build vs buy, lock-in, exit cost · R13 licence compatibility · R14 provider SLAs, quotas, data residency · R15 feasibility spikes · R16 new risks fed back to B16

Critic BLOCKER: an uncited legal, cost, security or feasibility claim that a decision depends on.

Decides: D1.1 a fact that changes a phase 0 decision (a regime applies or does not, a market or vendor exists, a cost's order of magnitude); D1.2 a feasibility claim; D1.3 a citation for every claim a decision depends on; any other claim is cited or marked as the author's assumption; D1.B the phase's BLOCKER rules: an uncited legal, cost, security or feasibility claim that a decision depends on.
Defers: X1.1 vendor or library choice among options already shown feasible -> phase 3; X1.2 exact pricing tiers, quotas and rate limits -> phase 5; X1.3 operational cost tuning -> phase 11.

### Phase 2 PRD (role: senior PM / requirements engineer)

P1 stories traced to goals · P2 EARS acceptance criteria · P3 role × action matrix incl. who must not · P4 entity rules · P5 every screen state · P6 validation rules · P7 notifications · P8 admin and audit · P9 search/filter/sort/pagination · P10 measurable NFRs · P11 analytics events · P12 migration and seed data · P13 release slicing · P14 open questions · P15 traceability · P16 ≥1 unwanted-behaviour AC per story · P17 limits and quotas · P18 privacy ACs (consent, export, deletion) · P19 audit log · P20 accessibility ACs · P21 i18n/RTL ACs · P22 glossary · P23 story map with walking skeleton

Critic BLOCKER: untestable AC or missing authorization rule.

Decides: D2.1 every story and its acceptance criteria (EARS, testable); D2.2 the role x action matrix, including who must not; D2.3 every NFR, with a number and a unit; D2.4 the per-story mapping from business rule to acceptance criterion; D2.5 per-story release scope (release slicing, walking skeleton); D2.6 business validation rules (topic P6): what counts as valid input or a valid state, in business terms; D2.B the phase's BLOCKER rules: an untestable AC or a missing authorization rule.
Defers: X2.1 component, technology or integration pattern -> phase 3; X2.2 attack defences beyond the authorization rule -> phase 4; X2.3 how a business validation rule decided in P6 is encoded: field types, formats, patterns, endpoints and error codes (never what counts as valid) -> phase 5; X2.4 screens, screen states and copy -> phase 6.

### Phase 3 HLD (role: staff architect)

H1 quality attributes ranked with trade-offs · H2 C4 context and containers as LikeC4 source · H3 architecture style with alternatives · H4 module boundaries · H5 data architecture · H6 performance design and budgets · H7 scalability · H8 concurrency and integrity · H9 integrations and failure behaviour · H10 security architecture · H11 reliability, backups, RTO/RPO · H12 observability · H13 deployment and rollback · H14 cost · H15 technology choices as ADRs · H16 future-proofing · H17 multi-tenancy isolation · H18 privacy and data residency · H19 i18n/RTL architecture · H20 fitness functions as dependency-cruiser rules in `.dependency-cruiser.json` (JSON only) · H21 operability for a solo operator · H22 ATAM risks, sensitivity and trade-off points · H23 readiness for native clients

Critic BLOCKER: no tenant-isolation design, or an unaddressed H1 trade-off.

Decides: D3.1 components and their boundaries; D3.2 data stores and data ownership per component; D3.3 the tenant-isolation design; D3.4 integration and deployment topology; D3.5 every H1 trade-off and the tactic for each top quality; D3.B the phase's BLOCKER rules: no tenant-isolation design, or an unaddressed H1 trade-off.
Defers: X3.1 threat-specific controls -> phase 4; X3.2 tables, columns, endpoints and state machines -> phase 5; X3.3 environments, accounts, instance sizes and the secrets layout -> phase 6b; X3.4 the library choice inside one component -> phase 7.

### Phase 4 Threat Model (role: security architect)

T1 assets · T2 data flows and trust boundaries · T3 STRIDE per element · T4 abuse cases · T5 authorization/IDOR · T6 authentication attacks · T7 injection and input · T8 privacy threats (LINDDUN categories) · T9 supply chain · T10 business-logic races · T11 controls mapped to OWASP ASVS 5.0.0 IDs (V1–V17) · T12 residual risk · T13 cross-tenant threats (queries, caches, files, jobs) · T14 feature abuse · T15 detection and alerting (Top 10:2025 A09) · T16 exceptional conditions and fail-open paths (A10) · T17 secrets and key management · T18 third-party trust (webhook signatures, SSRF, OAuth redirects) · T19 AI/LLM features or N/A · T20 ASVS level with reason

Critic BLOCKER: unmitigated high-impact authz or tenant threat.

Decides: D4.1 the threats at each trust boundary; D4.2 a mitigation for each high-impact threat (control type and where it sits); D4.3 abuse limits as numbers; D4.4 the SEC-n security requirements (SR- is shared resources, ruling 1 on increment 7); D4.B the phase's BLOCKER rules: an unmitigated high-impact authz or tenant threat.
Defers: X4.1 how a control is configured at an interface (header values, token lifetimes) -> phase 5; X4.2 how a control is implemented in code (library, configuration) -> phase 7; X4.3 how a control is verified -> phase 9.

### Phase 5 LLD (role: staff engineer / API designer)

L1 OpenAPI contract · L2 error model (RFC 9457 problem details) · L3 API conventions · L4 schema, indexes, migrations · L5 state machines · L6 key sequences · L7 concurrency details · L8 module design · L9 background jobs · L10 configuration · L11 test strategy · L12 traceability · L13 idempotency and retries · L14 pagination/filter/sort contract · L15 endpoint authorization map (operation → permission → tenant rule) · L16 versioning and deprecation · L17 zero-downtime expand/contract migrations · L18 caching and ETags · L19 rate limits per endpoint · L20 events and webhooks · L21 tenant scoping in data access · L22 critical invariants and how each is proven

Critic BLOCKER: missing authz or tenant scope; unapproved breaking change.

Decides: D5.1 schema and migrations; D5.2 every API, with its authorization and tenant scope; D5.3 the error model; D5.4 state machines; D5.5 validation rules as encoded (types, formats, patterns); D5.B the phase's BLOCKER rules: missing authz or tenant scope; an unapproved breaking change.
Defers: X5.1 screen states and copy -> phase 6; X5.2 code structure inside a module -> phase 7; X5.3 test cases -> phase 8.

### Phase 6 UX (role: design lead)

U1 information architecture · U2 flows · U3 design system · U4 every screen, every state · U5 responsive · U6 accessibility WCAG 2.2 AA · U7 languages and RTL · U8 content and microcopy · U9 motion · U10 brand · U11 usability check · U12 tokens in W3C DTCG format with computed contrast · U13 component × state inventory · U14 forms and error recovery · U15 system states per screen · U16 LCP/INP/CLS budgets · U17 themes · U18 RTL rules (mirroring, non-mirrored icons, numerals, bidi) · U19 email and notification templates · U20 touch targets and gesture alternatives

Critic BLOCKER: WCAG AA failure on a core journey or a missing state on a P1 screen.

Decides: D6.1 every P1 screen and its states; D6.2 flows; D6.3 copy; D6.4 WCAG AA obligations; D6.5 tokens, motion and assets; D6.B the phase's BLOCKER rules: a WCAG AA failure on a core journey, a missing state on a P1 screen.
Defers: X6.1 component implementation -> phase 7; X6.2 visual regression -> phase 10b.

### Phase 6b Provisioning (role: platform engineer)

V1 accounts · V2 secrets and keys · V3 environments · V4 domains and email · V5 quotas and costs · V6 test data · V7 readiness check · V8 least-privilege IAM and MFA · V9 spend caps · V10 account recovery / break-glass · V11 SPF, DKIM, DMARC · V12 environment parity, no production data elsewhere · V13 infrastructure record · V14 secret rotation · V15 sandbox vs live keys

Critic BLOCKER: a production credential reachable by the agent, or MFA missing.

Decides: D6b.1 environments, accounts and MFA; D6b.2 secrets handling; D6b.3 infrastructure as code; D6b.B the phase's BLOCKER rules: a production credential reachable by the agent, or MFA missing.
Defers: X6b.1 release gates and rollback -> phase 11; X6b.2 SLOs and alerting -> phase 11.

### Phase 7 Implementation (role: tech lead)

I1 task breakdown T- → AC · I2 definition of done per task · I3 slice order (walking skeleton, riskiest first) · I4 TypeScript strict, no unexplained any · I5 ESLint with type-aware rules · I6 dependency-cruiser rules pass · I7 knip clean · I8 complexity and file-size limits · I9 error handling and structured logging · I10 secure coding: validation, authz per handler, tenant scope · I11 no hard-coded user-facing strings · I12 squawk-clean migrations · I13 review findings resolved or waived · I14 ADR for every deviation from the LLD · I15 Conventional Commits

Critic BLOCKER: security or tenant defect; a test weakened or skipped to pass.

Decides: D7.1 the code matches the LLD and the tasks; D7.2 code standards and the phase-7 rules; D7.B the phase's BLOCKER rules: a security or tenant defect; a test weakened or skipped to pass.
Defers: X7.1 test coverage completeness -> phase 8; X7.2 security verification -> phase 9.

### Phase 8 Testing (role: SDET / QA lead)

TS1 strategy incl. what is not tested and why · TS2 AC traceability (`@AC-id` tags) · TS3 partitions, boundaries, decision tables, state transitions · TS4 a test per unwanted-behaviour AC · TS5 authz matrix allow and deny incl. cross-tenant · TS6 real-database integration (service containers the gate starts; no Testcontainers) · TS7 HTTP doubles (MSW), no live third-party calls · TS8 contract tests (Schemathesis, ephemeral environment only) · TS9 property tests for L22 invariants (fast-check) · TS10 mutation score (Stryker) · TS11 line/branch coverage · TS12 test-data builders · TS13 zero retries in the gate, quarantine list with expiry · TS14 axe checks · TS15 i18n missing-key and pseudo-locale/RTL checks · TS16 defect register

Critic BLOCKER: untested P1 AC, missing cross-tenant deny test, lowered threshold.

Decides: D8.1 a test per acceptance criterion; D8.2 thresholds set before the results; D8.B the phase's BLOCKER rules: an untested P1 AC, a missing cross-tenant deny test, a lowered threshold.
Defers: X8.1 exploratory and live checks -> phase 10a; X8.2 load and concurrency -> phase 10c.

### Phase 9 Security Verification (role: AppSec engineer)

SV1 scope and ASVS level · SV2 SAST · SV3 SCA · SV4 secrets in full history · SV5 container images · SV6 config/IaC · SV7 DAST passive baseline (ZAP) · SV8 API negative and fuzz tests · SV9 authz/IDOR evidence · SV10 authentication, sessions, tokens · SV11 CycloneDX SBOM (Trivy) · SV12 licence allow-list · SV13 headers, TLS, cookies · SV14 evidence for every SEC-ID · SV15 triage of SF-n findings · SV16 human residual-risk acceptance · SV17 MASVS or N/A

Critic BLOCKER: unresolved Critical/High; unverified authz or tenant control.

Decides: D9.1 everything in the phase's scope; security is never carried past phase 9.
Defers: nothing.

### Phase 10a Live Verification (role: QA lead / exploratory tester)

LV1 element inventory from U13 · LV2 trace or video per P1 AC · LV3 every role incl. forbidden attempts by UI and URL · LV4 every state observed · LV5 every locale incl. RTL · LV6 all breakpoints + one mobile device or emulation · LV7 axe + keyboard pass · LV8 Lighthouse CI assertions · LV9 no console errors or failed requests · LV10 notifications received · LV11 sandbox payments (success, failure, refund) · LV12 browsers by size · LV13 defects with repro and trace

Critic BLOCKER: unexercised P1 AC or element; "verified" by reading code.

Decides: D10a.1 everything in the phase's scope.
Defers: X10a.1 a defect listed in the release notes as a known issue (only if it breaks no P1 acceptance criterion and is not a security, privacy or tenant-isolation defect) -> phase 11.

### Phase 10b Regression (role: SDET)

RG1 scope (all P1 ACs, critical journeys) · RG2 Playwright E2E tagged by AC · RG3 API regression (Schemathesis + oasdiff) · RG4 visual baselines LTR and RTL (Playwright toHaveScreenshot, baselines in repo) · RG5 Maestro mobile flows or N/A · RG6 flakiness check (repeat-each, zero retries) · RG7 runtime budget · RG8 data reset · RG9 ownership · RG10 runs on every PR

Critic BLOCKER: uncovered critical journey; flaky gate test.

Decides: D10b.1 everything in the phase's scope.
Defers: X10b.1 a defect listed in the release notes as a known issue (only if it breaks no P1 acceptance criterion and is not a security, privacy or tenant-isolation defect) -> phase 11.

### Phase 10c Concurrency and Load (role: SRE / performance engineer)

CL1 workload model · CL2 p95/p99 and error-rate thresholds from SLOs · CL3 load, stress, spike (+ soak for M/L) · CL4 race tests with SQL invariant checks · CL5 slow queries, EXPLAIN, locks, deadlocks · CL6 fault injection (M/L) · CL7 backpressure and rate limits · CL8 capacity headroom · CL9 results vs H6 budgets · CL10 stated differences from production

Critic BLOCKER: invariant violation; SLO miss without ADR; thresholds set after seeing results.

Decides: D10c.1 everything in the phase's scope.
Defers: X10c.1 a defect listed in the release notes as a known issue (only if it breaks no P1 acceptance criterion and is not a security, privacy or tenant-isolation defect) -> phase 11.

### Phase 11 Release (role: release manager / SRE)

RL1 CI re-runs every gate tool at pinned versions · RL2 actions pinned by 40-char SHA, least-privilege permissions, zizmor and actionlint clean · RL3 SBOM attached (+ provenance for L) · RL4 production environment with required human reviewer · RL5 migration order and pre-deploy backup · RL6 rehearsed, timed rollback · RL7 kill switches · RL8 canary/blue-green (L) · RL9 smoke tests · RL10 logs, metrics, traces, error tracking · RL11 SLOs and alerts · RL12 uptime check · RL13 timed restore drill vs RTO/RPO · RL14 runbooks · RL15 changelog (release-please) · RL16 docs · RL17 privacy policy, terms, cookie consent, accessibility statement · RL18 human go/no-go record

Critic BLOCKER: no rehearsed rollback or restore; unpinned or injectable workflow.

Decides: D11.1 everything in the phase's scope.
Defers: X11.1 a process lesson -> phase 12.

### Phase 11b Store Release (role: mobile release manager)

SR1 human-owned store accounts · SR2 signing-key custody · SR3 versioning · SR4 privacy labels / data-safety form mapped from the SBOM and SDK list · SR5 review pre-check (demo account, in-app account deletion, purchase rules, UGC moderation) · SR6 localized metadata and screenshots incl. RTL · SR7 age rating · SR8 permission purpose strings · SR9 TestFlight/internal tracks · SR10 phased rollout and halt criteria · SR11 crash-free threshold · SR12 OTA policy or N/A · SR13 export compliance

Critic BLOCKER: privacy-label mismatch.

Decides: D11b.1 everything in the phase's scope.
Defers: X11b.1 a process lesson -> phase 12.

### Phase 12 Retro (role: engineering manager)

RT1 timeline · RT2 metrics (DORA four keys, phase cycle times, critic findings by severity, escaped defects) computed from git and the ledger · RT3 blameless went-well/went-poorly · RT4 contributing factors · RT5 MOADIX process changes · RT6 lessons queue, applied only after operator approval · RT7 actions with owner and date · RT8 cost (time, tokens, money) · RT9 tech-debt register · RT10 CLAUDE.md updates as approved diffs

Critic BLOCKER: a change to MOADIX rules without approval.

Decides: D12.1 everything in the phase's scope.
Defers: nothing.

### Phase B Baseline (role: staff engineer doing technical due diligence on an existing codebase)

BL1 system inventory · BL2 as-is C4 (LikeC4) · BL3 dependency graph and cycles · BL4 dead code · BL5 as-is schema · BL6 API inventory and drift · BL7 as-is BRD/PRD, each item tagged observed / inferred / unknown · BL8 test inventory (+ mutation on hotspots) · BL9 hotspots (churn × complexity from `git log --numstat`) · BL10 security baseline (phase 9 scanners) · BL11 as-is threat model (pytm) · BL12 ops baseline · BL13 known gaps and risks · BL14 characterization tests for top hotspots · BL15 frozen baseline tag. Also: the gate runs the product's existing test suite in the declared non-production environment

Critic BLOCKER: inferred behaviour presented as fact.

Decides: DB.1 what exists today, as the code shows it.
Defers: XB.1 anything to-be (a change, not a description of what exists): carried to the next feature cycle's phase 0 -> phase feature.

### Feature cycles (each in the feature's COVERAGE.md of the phase shown)

FC1 feature brief vs frozen BRD (phase 0) · FC2 impacted documents (phase 0) · FC3 new AC IDs, never reused (phase 2) · FC4 superseding ADRs for conflicts (phase 3) · FC5 oasdiff result (breaking change needs ADR + deprecation plan) (phase 5) · FC6 expand/contract migration (phase 5) · FC7 threat-model delta (phase 4) · FC8 regression impact (phase 10b) · FC9 flag and rollout (phase 11) · FC10 merge-back after release (phase 11) · FC11 feature size class. Feature additions get the full product-document validators, not a lighter check (phase 0)

Critic BLOCKER: frozen-document change without a superseding ADR.
