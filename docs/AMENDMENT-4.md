# Amendment 4 (2026-11-12) — Hotfix lane, operate phase, media and motion, starter packs, cost and status, launch extras, lessons library, hardening

Extends DESIGN.md and Amendments 1–3; overrides them where they differ. Accepted by the operator on 2026-11-12. Build only after Amendment 3 is installed and the toy run has passed every phase; toy-run findings are folded into this amendment before it is built.

Rules that do not change: every check is run by the gate, not by the agent; every new tool is pinned and its LICENSE verified before use; no skill step may approve, commit, push or deploy; nothing here adds an agent-scheduled job (CronCreate and ScheduleWakeup stay denied).

## 1. Hotfix lane

Operator command: `HOTFIX <id> <code>` (exact whole message, TOTP code, same rules as `FEATURE`). Documents in `sdlc/hotfixes/<id>/`, state in `.sdlc/hotfixes/<id>/`. Trace prefix `HF-`.

| Step | Content | Deterministic check (gate-run) |
|---|---|---|
| HF1 Incident brief | Symptom, severity, blast radius, affected AC IDs, reproduction steps | Schema; at least one existing AC or BR ID referenced |
| HF2 Failing test | A test that reproduces the bug, committed before the fix | Test fails on the pre-fix commit, passes on the fix commit |
| HF3 Fix | Smallest change that makes HF2 pass | Diff limits below |
| HF4 Targeted tests | Tests of the touched modules plus their dependents | Exit 0 |
| HF5 Security delta | gitleaks, Semgrep, OSV on the diff | No new critical/high finding |
| HF6 Regression | Full phase 10b suite | Exit 0 |
| HF7 Release | Phase 11 release steps with rollback plan | As phase 11 |
| HF8 Follow-up | Root cause, why earlier phases missed it, document updates merged back | Must be approved within 7 days or `STATUS` shows it as overdue |

Diff limits (gate refuses the hotfix and tells the operator to use `FEATURE` when any is exceeded): no breaking API change (oasdiff), no migration other than additive (squawk), no new dependency, no change to auth, payment or tenant-isolation modules without a `WAIVE`, at most 10 files and 300 changed lines. Approvals: `APPROVE HF <code>` once, after HF6; the code reviewer and security verifiers still run with fresh context.

## 2. XS size class (feature cycles only)

Adds XS under FC11. Claims: at most 5 files, no schema change, no API change, no auth/payment/tenancy module touched, no new dependency, no new screen. The gate checks the claims against the real diff; a false claim reclassifies the feature to S. For XS, phases 1, 3, 4, 5, 6, 6b, 10c and 11b are N/A with the canned reason "XS: no change in this area (verified by diff)". Phases 0 (feature brief), 2 (ACs), 7, 8, 9, 10b, 11 and 12 always run.

## 3. Phase 13 Operate — role: site reliability engineer for a solo operator

Opens after phase 11 is approved and stays open. Runs when the operator opens a session or sends `STATUS`; never on an agent schedule. Continuous monitoring lives in the product's own CI and hosting, not in MOADIX.

OP1 SLOs with alert thresholds (from P10, H12) · OP2 uptime and synthetic checks of the top three journeys · OP3 error tracking wired and tested with a deliberate error · OP4 incident log (`INC-n`: time, impact, cause, fix, link to HF or FC) · OP5 postmortem per SEV1/SEV2 incident · OP6 backup restore drill on a stated cadence, with evidence · OP7 dependency and CVE watch (OSV and Trivy re-run on the released lockfile) · OP8 cost review against R7 · OP9 feedback intake, each item closed as HOTFIX, FEATURE or rejected with a reason · OP10 tool-pin and Claude Code version review.

Gate: every `INC-n` links to an `HF-` or `FC-` ID or a rejection reason; drill evidence is no older than the stated cadence; OP7 scan no older than 30 days. Overdue items appear in `STATUS`; they do not block feature work, except an open SEV1 incident, which blocks `FEATURE`.

## 4. Media and motion track

New topics:
- **U21 Motion spec (phase 6):** what animates, trigger, duration and easing tokens, purpose of each animation, reduced-motion variant for each.
- **U22 Asset plan (phase 6):** every image, illustration, icon set, animation file and video the product needs; for each: authored, generated or stock.
- **I16 Asset manifest (phase 7):** `sdlc/assets/ASSETS.json` — path, kind, source, licence, alt text, dimensions, bytes; for generated assets also generator, model, prompt and date.
- **LV14 Motion and media verification (phase 10a).**

Gate checks:
| Check | Rule |
|---|---|
| `asset-lint` | Every media file shipped by the build is in the manifest; licence and alt text non-empty; no file in the manifest is missing |
| Size budgets | Per-image and per-page byte budgets from U22; raster images served as AVIF or WebP; SVG optimised |
| Reduced motion | Playwright run with `prefers-reduced-motion: reduce`: no animation longer than the U21 fallback allows |
| Performance | Lighthouse CI assertions on CLS and INP with animations on; animations use transform/opacity only (lint) |
| Evidence | Playwright video of each U21 animation, LTR and RTL, given to the design reviewer |

3D is an accent, never the default style. It is used only where it adds value and only if the direction the operator chose (U24) calls for it. Every 3D use is listed in U22 with the place and the reason (for example a hero image, an empty state, an onboarding step, a key category icon); ordinary interface icons stay flat. The critic raises a MAJOR for 3D with no stated reason or 3D used across the whole interface. When used, 3D-look icons and illustrations are delivered as ordinary image assets (authored, stock with a licence, or generated), listed in the manifest like any other image. Real-time 3D (Three.js / React Three Fiber) is off by default and allowed only on a landing page, loaded lazily, with a static fallback and inside the Lighthouse budgets.

Generated images and video are optional and off by default. When turned on: the API key is in the Keychain and read only by the gate; a spend cap per product is set in phase 0; every generation is written to the ledger; no image of a real person; generated assets are labelled in the manifest.

Candidate tools — not yet vetted; vet version, licence and maintenance first, and stop and report any that fails: Motion (animation library), dotLottie/lottie-web, Rive runtime, sharp, svgo, the LottieFiles motion-design skill (vendored and stripped like every other skill), Remotion for video (check its company-licence terms), one image-generation API.

## 5. Starter packs

`packs/<domain>.yaml`, written and maintained by MOADIX, versioned, sources cited. First three: booking, e-commerce, SaaS admin. Chosen by a discovery question at the start of phase 0; more than one may apply.

Each pack supplies prompts, never requirements: feature checklist (feeds B4), entity lifecycles (B6), money flows (B22), legal regimes to check per market (B11), typical threats (phase 4), typical screens and states (P5, phase 6). Every pack item must be recorded in the BRD as accepted or rejected with a reason. Gate: `pack-lint` — every item ID of the chosen pack appears in `COVERAGE.md`.

## 6. Cost, time and status

- The gate records per phase: wall-clock time, session count and token usage. Token usage source must be verified during the build; if no reliable source exists, record time and sessions only and say so in `STATUS`.
- Budget per phase is set in phase 0 (B15). At 80% the operator is warned; a budget never blocks.
- `STATUS` reply, at most 15 lines, readable on a phone: current phase, what is waiting for the operator, open BLOCKER and MAJOR counts, overdue operate items, time and cost so far.
- `.sdlc/status.html`: a static page rebuilt by the gate from the ledger, with the same content in more detail. No server.

## 7. Launch extras (phase 11)

RL19 SEO: titles, descriptions, canonical URLs, sitemap, robots, structured data, share images; Lighthouse SEO assertion · RL20 analytics: every P11 event fires in a Playwright run and carries no personal data beyond what P18 allows · RL21 landing page (default on for M and L) · RL22 user guide and admin guide generated from the PRD with real screenshots; links checked; reviewed by a fresh-context critic for steps that do not match the product · RL23 legal pages present for each market in B10 (privacy, terms, accessibility statement where the market requires one).

## 8. Lessons library

- Location: `~/.moadix/lessons/`, one file per lesson, signed by the gate. The agent cannot write there.
- A lesson enters only through an approved phase 12 retro (`APPROVE 12`): id, phase, rule, evidence, source product. No secrets and no customer data.
- At the start of each phase the gate adds the lessons for that phase to the agent's context and lists them in `COVERAGE.md`; the phase must state how each was applied or why it does not apply.
- A later approved retro can retire a lesson. No new operator command.

## 9. Hardening (answers to the known gaps)

| Gap | Change |
|---|---|
| Unproven end to end | Not a design change: the toy run must pass all phases, then the onlineMarket parity check, before this amendment is built |
| Tied to Claude Code internals | The gate holds a list of Claude Code versions on which the full corpus has passed. On any other version, operator commands are not recorded and the reply says why; re-running the installer runs the corpus and adds the version |
| Hard to adopt | `managed/doctor.sh` checks checker signature, Keychain items, managed settings, plugin version and Claude Code version, and prints one line per check; its result is shown in `STATUS`. Linux install tested in CI |
| Trial mode | Installs without sudo for evaluation. Every reply to an operator command and every status view starts with "TRIAL — approvals are not secure". A trial ledger can never become a trusted one; moving to a full install requires `ADOPT` |
| Hostile code only detected | Docker and Playwright steps run with no secrets in the environment, a dedicated network with an egress allowlist, the repository mounted read-only except an output directory, a non-root user, no Docker socket inside the container, and resource limits. For size L a throwaway VM is recommended. The residual risk stays documented as accepted |

## 10. Size rule additions

| Item | S | M | L |
|---|---|---|---|
| Hotfix lane, operate phase, cost and status, lessons | on | on | on |
| Motion spec U21 | on, may be "no motion" | on | on |
| Generated media | off unless asked | off unless asked | off unless asked |
| Landing page RL21 | off | on | on |
| Guides RL22 | user guide | both | both |
| OP2 synthetic checks | one journey | three | three |

## 11. Design quality pipeline (phase 6 and 10a)

Goal: the product must look professionally designed, not like a generic AI-built SaaS page. Visual quality is an acceptance criterion separate from "it works". The operator has no design-tool experience, so every choice is made by looking at real rendered screens. Figma, Spline and other hand-design tools stay out of scope.

New topics in phase 6, in this order:
- **U23 Reference research:** 5 real products in the same domain (from R2 where possible). For each: Playwright screenshots of the key screens, what works, what to borrow, what to avoid. Evidence stored with the phase.
- **U24 Three visual directions:** three clearly different directions (typography, colour, layout, imagery, motion character), each built as real code for the same two key screens, rendered by Playwright at phone and desktop width, LTR and RTL. The operator is shown the screenshots and picks one, or asks for a mix; the choice is logged as a `Q-n` answer. The design system (U3, U12) is built only after the choice.
- **U25 Signature elements:** 2–3 things that make this product recognisable (for example an illustration style, an icon style, one distinctive interaction), each with a rule for where it is used.
- **U26 Anti-generic check:** the Impeccable anti-pattern list applied to the chosen direction; every hit fixed or justified.

Gate: three direction folders exist, each with the four screenshots; a recorded operator choice; tokens derive from the chosen direction. Critic: MAJOR when two directions are not visibly different, or when the chosen direction matches a known generic pattern without justification.

Phase 10a addition — **LV15 Visual review:** the design reviewer (fresh context) receives screenshots of every P1 screen at all breakpoints plus the chosen direction and tokens, and reports screens that drift from the direction, look unfinished or look generic. MAJOR findings need a fix or a `WAIVE`. The implementation agent cannot close a UI task on "it renders".

Skills: keep ui-ux-pro-max, Impeccable, apple-design and the DESIGN.md template; each keeps one job (knowledge base, anti-generic critique, platform polish, written spec). Anthropic frontend-design stays rejected as a separate skill because Impeccable covers the same ground; re-check this claim against both sources during the build and report if it is wrong. Mobbin is not added (a browsing site for people; no agent interface confirmed).

21st.dev MCP is added as an **optional** component source, off by default, turned on per product by a discovery question in phase 6. Rules when on: available only in phases 6 and 7; `search` and `get_component` only, AI generation off unless the operator asks; every component taken is copied into the repository as ordinary source and listed in `sdlc/assets/COMPONENTS.json` (name, source URL, author, licence, date); a component with no clear licence is not used; imported components go through the code reviewer, axe and RTL checks like own code and must be restyled to the U12 tokens; the API key is a low-privilege key supplied by the operator and never written to the repository. Verify during the build: the MCP's own licence, the free-tier limits, and whether the key can be kept out of the agent's shell; stop and report if any of these is a problem.

## 12. Deep security audit (phase 9 and Baseline)

Add the Cloudflare `security-audit-skill` (MIT; verify the LICENSE file and pin the commit) as **SV18** in phase 9 and as a Baseline topic. On by default for sizes M and L; off for S and XS unless the operator asks.

Adaptation required before use: its hunter, coverage-critic and verifier roles are registered with the gate so their briefs are generated and enforced like every other verifier; output goes to `.sdlc/cache/verify/9/security-audit/` instead of the home directory; target code runs only inside the existing sandbox rules; its `findings.json` feeds the sf-triager. `confirmed` critical and high findings block; `needs_validation` findings block until triaged or waived, as already ruled for unconfirmed security findings.

## 13. Build order

1. Hotfix lane, XS class, operate phase, version check, doctor, deep security audit.
2. Design quality pipeline, media and motion, launch extras.
3. Starter packs, cost and status, lessons library, trial mode, container isolation.

Each part is one increment with its own report, tests on fixtures only, a `plugin.json` version bump and a tag.

## Proposals for review: not decided, do not build

Nothing in this section is ruled. Each item records a gap or an idea for the operator to decide on; no increment may build from it until the operator rules on it. Items 1 to 7 come from an audit of the coverage topics (`gate/config/coverage-topics.yaml`) for a hosted, real product.

### Production readiness

1. **Long-lead approvals.** Phase 0 asks which outside approvals the product needs: payment provider, business identity, email sender, domain, app stores, regulators. Phase 1 researches each lead time and outputs a long-lead list with a start-by date per item. Phase 6b checks the status of each.
   Open questions: is this a new topic in phases 0, 1 and 6b, or an extension of B15, R14 and V1? Is the start-by date counted back from a target release date, and who sets that date? Does a missed start-by date block a phase or only warn?

2. **Pending-external items in 6b.** Phase 6b records each item waiting on an outside party as "requested, waiting on <provider> since <date>, needed by phase <n>". The item is carried forward with no code. Phase 11 cannot release while an item needed for production is still pending.
   Open questions: where does the list live (a 6b document, or the ledger like CARRY)? Is it the same mechanism as CARRY or a separate one? Can the operator waive a pending item at phase 11, and if so, with what record?

3. **TLS.** Phase 6b covers getting the certificate and setting up automatic renewal. Phase 11 covers monitoring the expiry date.
   Open questions: new V- and RL- topics, or an extension of V4 and RL12? Is a product whose host manages TLS for it (a platform-managed certificate) N/A, or does it still need the expiry check?

4. **Staging.** A hosted product requires a staging environment. Phases 10a to 10c run against staging instead of the gate's local origin.
   Open questions: how does this fit the current rule that live gates reach the app only at `http://sut.localhost:<port>`? Does the gate need staging credentials, and how is that kept within the 6b BLOCKER that the agent never holds production credentials? Is staging required at size S, or is it a size default?

5. **Hosting provider.** Choosing the hosting provider becomes its own phase 1 topic, decided by an ADR in phase 3.
   Open questions: a new R- topic, or a required part of R5 and R6? Is a matching H- topic needed, or is an ADR under H15 enough?

6. **Monthly cost.** Phase 3 gives a monthly figure at launch, at 10x and at 100x. Phase 11 gets a cost topic (budget alerts, spend caps), so the X1.3 handoff ("operational cost tuning" to phase 11) has a topic to land on.
   Open questions: does the phase 3 figure replace R7, or refine it? How does the phase 11 topic relate to V9 (spend caps in 6b)? Should the gap critic treat an uncited monthly figure as a BLOCKER, like other cost claims a decision depends on?

7. **Privacy per market.** Each target market (B10) is mapped to its privacy regime, with dated sources. The mapping is checked in phase 4 (threats) and phase 11 (policies, consent, notices).
   Open questions: does the mapping belong in B11 or R4? Is "market" a country, or can it be a region such as the EU? What does phase 4 check beyond T8: one T8 entry per regime?

### Fewer operator commands

8. **Fix lane.** Two cases, both without reopening an approved phase:
   - (a) **Tests for a later phase's own findings.** Phases 9 and 10a to 10c add tests for the findings they make without `REOPEN 8`. This is what happened in task-tracker's phase 9.
   - (b) **Fixes for defects found in testing (MF-42).** Phases 8, 10a and 10b may fix `src/**` without `REOPEN 7`, only together with a test that names a TS16 defect-register entry and fails before the fix (at the parent commit) and passes after it (at HEAD). MF-42 (task-tracker, phase 8, MOADIX 0.7.5): phase 8 may write `tests/**`, but no phase after 7 owns `src/**`, so a one-line fix needs `REOPEN 7`, phase 7's verifiers and gap critic again, and a new `APPROVE 7`. The finding also suggests re-running phase 7's exec checks on that commit and listing the change for the next code review.
   Open questions: which phases may use it (8, 9, 10a to 10c)? May the lane change only test files, or also the fix itself? How is the added test reviewed, and is it recorded in the ledger?

9. **Every SEC-ID has a test.** Phase 8's critic checks that every SEC-ID from the threat model has a test.
   Open questions: a check in the ac-coverage-critic or in the gap critic? Is it the same trace format as `@AC-id`? Which SEC-IDs are exempt because they are verified only in phase 9 (scans, configuration)?

10. **One ADOPT per product.** Phase 6b collects every gate setting the product will need into one proposal, so the operator ADOPTs once.
    Open questions: which settings can be known by 6b, and which only appear later (for example phase 9 gitleaks allows)? Does a later change still need its own ADOPT?

11. Decided in Amendment 5, section 5 (one code per phase).
12. Decided in Amendment 5, section 3.4 (AUTO-COLLAPSE).

### Next-round backlog

- MF-67 (task-tracker, phase 7 reopen, MOADIX 0.8.3): check-trivy does not build the root `docker-compose.yml`. `built_targets` builds only the root `Dockerfile`, each `build:` of the `live.compose` file and each Dockerfile under `tests/gate/`, so an image the operator's own compose file builds is neither built nor scanned, silently. The gate's builds also ignore `build.target`, so a multi-stage Dockerfile is scanned at its last stage, not the stage Compose builds. The finding suggests reading each `build:` of the root compose file (or failing on any compose `build:` the gate does not build), passing `build.target` as `--target`, and keying an image's accepted unfixed findings on (Dockerfile path, target).
- A helper that proposes updates to pinned packages and images.

Open questions: does MF-67 take the read-the-root-compose fix or the fail-on-unbuilt-`build:` fix, and does `--target` ship with it? Does the update helper only propose (an `.sdlc-proposals/` file for ADOPT), and which pins does it cover: OS packages, npm packages, images, gate tools?
