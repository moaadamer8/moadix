# Gap-critic convergence: design (F-3)

Status: **§1–§9 approved by the operator with the rulings in §8, and built in 0.7.0;** where the build differs from the text, §9 says so. **§10 is a proposal for 0.7.2, not built.** Written for 0.6.4 from finding F-3 of the first product run (onlineMarket, size L). That run needed 7 gap-critic runs on phase 0, with totals of 19, 17, 15, 15, 8, 12 and 13 findings, and closed with PROCEED-PAST.

## 1. Why the critic does not converge

1. **No depth boundary.** The brief tells the critic to check every topic but not how deep. Each run went one level deeper, into detail a later phase settles: gift-order message routing, how long each record type is kept, uncollected pickups.
2. **No memory.** Every run starts blind. The critic cannot tell a regression from a new, deeper finding, or from a finding the operator already ruled on. It re-raises the same topic, and the agent fixes it again.
3. **Waivers are too broad.** `gap-critic.<topic>` waives every MAJOR on that topic, including MAJORs that appear later. The operator therefore cannot waive just the finding in front of them without also waiving future ones, and avoids waiving at all.

The design adds four parts: a depth boundary per phase (§2), carry items (§3), the critic's memory (§4) and per-finding waivers (§5). §6 covers what keeps them from weakening the review.

## 2. Depth boundary per phase

Each phase in `gate/config/coverage-topics.yaml` gets a `depth` block. The file is root-owned and installed with the gate, so neither the agent nor the critic can edit it:

```yaml
  "0":
    depth:
      decides:            # at this phase's depth: a gap here is BLOCKER/MAJOR as today
        - id: D0.1
          what: "a business promise to a customer or partner"
        ...
      defers:             # below this phase's depth: a gap here is a CARRY to the named phase
        - id: X0.1
          what: "behaviour detail one story's acceptance criteria can settle (field lists, sorting, exact wording, exact table rows)"
          to: "2"
        ...
```

The `decides` list wins every overlap. If a gap touches anything in it, it stays at this phase's depth, whatever a `defers` rule says.

The phase 0 rule is the operator's ruling recorded in F-3. The rules for the other phases follow the same pattern. Each line below is one rule: what the phase decides, then what it defers and to which phase.

| Phase | Decides (gap = BLOCKER/MAJOR) | Defers (gap = CARRY to phase) |
|---|---|---|
| **0 BRD** | D0.1 a business promise; D0.2 a role's permissions (who may do what, in business terms); D0.3 a money flow (who pays whom, when, refunds, payouts, tax); D0.4 a legal or privacy duty (named regime and what it requires of the business); D0.5 data ownership and the retention *policy*; D0.6 release scope (each feature in, later or rejected); D0.7 the existence of a lifecycle state | X0.1 behaviour detail one story's ACs can settle (field lists, sorting, exact wording, table rows) → **2**; X0.2 attack defences and abuse limits beyond the business rule → **4**; X0.3 schema and API detail, including per-record-type retention mechanics → **5**; X0.4 screen layout and copy → **6** |
| **1 Research** | D1.1 a fact that changes a phase 0 decision (a regime applies or does not, a market or vendor exists, a cost's order of magnitude); D1.2 a feasibility claim; D1.3 a citation for every claim | X1.1 vendor or library choice among feasible options → **3**; X1.2 exact pricing tiers, quotas, rate limits → **5**; X1.3 operational cost tuning → **11** |
| **2 PRD** | D2.1 every story and its ACs (EARS, testable); D2.2 the role × action matrix; D2.3 every NFR with a number and a unit; D2.4 the per-story mapping from business rule to AC; D2.5 per-story release scope; D2.6 business validation rules: what counts as valid (P6) | X2.1 component, technology or integration pattern → **3**; X2.2 attack defences beyond the authorization rule → **4**; X2.3 how a P6 rule is encoded (field types, formats, patterns, endpoints, error codes; never what counts as valid) → **5**; X2.4 screens, states, copy → **6** |
| **3 HLD** | D3.1 components and their boundaries; D3.2 data stores and data ownership per component; D3.3 the tenant-isolation design; D3.4 integration and deployment topology; D3.5 every H1 trade-off and the tactic for each top quality | X3.1 threat-specific controls → **4**; X3.2 tables, columns, endpoints, state machines → **5**; X3.3 environments, accounts, sizes, secrets layout → **6b**; X3.4 library choice inside one component → **7** |
| **4 Threat Model** | D4.1 threats per trust boundary; D4.2 a mitigation per high-impact threat (control type and where it sits); D4.3 abuse limits as numbers; D4.4 the SEC-n security requirements | X4.1 how a control is configured at an interface (header values, token lifetimes) → **5**; X4.2 how it is implemented in code → **7**; X4.3 how it is verified → **9** |
| **5 LLD** | D5.1 schema and migrations; D5.2 every API with authz and tenant scope; D5.3 the error model; D5.4 state machines; D5.5 validation rules | X5.1 screen states and copy → **6**; X5.2 code structure inside a module → **7**; X5.3 test cases → **8** |
| **6 UX** | D6.1 every P1 screen and its states; D6.2 flows; D6.3 copy; D6.4 WCAG AA obligations; D6.5 tokens, motion, assets | X6.1 component implementation → **7**; X6.2 visual regression → **10b** |
| **6b Provisioning** | D6b.1 environments, accounts, MFA; D6b.2 secrets handling; D6b.3 IaC | X6b.1 release gates and rollback → **11**; X6b.2 SLOs and alerting → **11** |
| **7 Implementation** | D7.1 the code matches the LLD and the tasks; D7.2 code standards and the phase-7 rules | X7.1 coverage completeness → **8**; X7.2 security verification → **9** |
| **8 Testing** | D8.1 a test per AC; D8.2 thresholds set before results | X8.1 exploratory and live checks → **10a**; X8.2 load and concurrency → **10c** |
| **9 Security Verification** | everything in scope | nothing (security is never carried past 9) |
| **10a / 10b / 10c** | everything in scope | X10a.1 / X10b.1 / X10c.1 a known issue for the release notes → **11** only, and only if it breaks no P1 acceptance criterion and is not a security, privacy or tenant-isolation defect (hard rule) |
| **11 / 11b Release** | everything in scope | X11.1 process lessons → **12** |
| **12 Retro**, **B Baseline** | everything in scope | B: X B.1 anything "to-be" → a feature cycle (FC topics); 12: nothing |

A gap that matches no defers rule is judged at the current phase exactly as before (ruling Q1d). Every phase also gets four hard rules:

- A carry's target must be later than the current phase and not yet approved or proceeded past.
- Nothing in the phase's `blockers` string or its `decides` list can be carried.
- Nothing about security, privacy or tenant isolation can be carried past phase 9.
- A carry may name only a rule ID that exists in the current phase's `defers` list.

## 3. Carry items

**Severity.** `CRITIC.json` gets a fourth severity, `CARRY`. A carry finding has the usual fields plus two more: `defer_rule` (for example `X0.1`) and `to` (the phase). The schema refuses a carry if its rule is not in the phase's `defers` list, if `to` differs from what that rule says, or if any hard rule in §2 is broken. A carry never blocks APPROVE and is never waived.

**The gate writes the register.** When the phase is approved or proceeded past, the gate copies the phase's open carries into `.sdlc/carry/<scope>.json`. This file is gate-owned and append-only, and its digest goes in the APPROVE ledger line. Each item gets a stable ID, `CARRY-<from>-<n>`, and keeps its source quote and citation at the approved commit. The agent never writes the register.

**Input to the target phase.** In the target phase:

- `.sdlc/coverage/<scope>-<label>-COVERAGE.md`, the skeleton the gate already writes, lists every carry addressed to that phase as `- CARRY-0-3: <what>`.
- The phase's `COVERAGE.md` must list each carry, with an anchor to the section that settles it or `N/A: <reason>`.
- coverage-lint fails on a missing carry, as it does on a missing topic.
- The target phase's critic brief lists each carry with its source quote. A carry left unsettled is a MAJOR on the target phase, and a carry the target phase cannot settle is a BLOCKER.

**Closing a carry.** A carry is closed only when the target phase is approved with that carry's line passing coverage-lint and the critic raising no finding on it. The register records the commit and ledger sequence that closed it. Proceeding past the target phase does not close its carries: they move to STATUS as "open carries" and count as open in phase 11's scorecard.

## 4. The critic's memory

**What the brief adds.** The brief gets a section, `## Earlier runs on this phase`. The gate builds it from evidence it already keeps:

- Each earlier run's `CRITIC.json`, with its commit, archived in `.sdlc/cache/verify/<label>/gap-critic/runs/` before the next launch overwrites it.
- The ledger, for waivers and PROCEED-PAST.
- The carry register.

**What it lists.** For each earlier finding: run number, ID, topic, severity, quote, citation at that run's commit, and one disposition, worked out by the gate (§5 says how a finding is identified):

| Disposition | How the gate knows it | What the critic must do |
|---|---|---|
| **waived** | an active WAIVE names this finding (§5) | Not re-raise it. If the cited text changed since the waiver, the waiver has lapsed (§5), and the critic judges the new text as new. |
| **carried** | the finding was a CARRY in the last run, the text is unchanged, and the rule is still valid | Not re-raise it at this phase. |
| **ruled** | a `DISCOVERY.md` Q-n or an ADR committed after the run cites the finding's ID (`Rules: GC-0-7`) | Check that the document now says what the ruling chose. If it does not, raise a **regression** (`regression_of: GC-0-7`). |
| **fixed?** | none of the above, and the cited lines changed after the run | Check the fix. Closed: say nothing. Not closed: raise a **regression**. |
| **open** | none of the above, and the cited lines are unchanged | Raise it again with the same ID. |

**Identity of a finding.** The gate gives each finding a stable ID, `GC-<label>-<n>`, the first time it appears. To match a new finding to an old one, the critic must set `same_as: GC-0-7`. The gate checks that claim: the topic must match and the citation must sit in the same section, by heading anchor. A finding without `same_as` is new.

**New findings on unchanged text.** These are the main cause of non-convergence. A new finding on text that has not changed since the previous run is marked `late: true` by the gate (not by the critic), and the operator sees the count. Late findings still block at their severity, so nothing is hidden, but a critic that keeps finding new things on unchanged text becomes visible as such.

## 5. A waiver binds one finding

- **The id.** The waiver id becomes `gap-critic.GC-<label>-<n>`. `gap-critic.<topic>` is no longer accepted for new waivers. With 0.6.4, one WAIVE can already name several ids under one code.
- **What it records.** At WAIVE time the gate writes the finding's fingerprint into the ledger payload: topic, citation path and section anchor, and the sha256 of the cited lines at the evidence's commit.
- **What it covers.** In a later run, the waiver covers a finding only if the finding has `same_as` that ID, the gate accepts that claim, and the fingerprint still matches. It never covers a new finding on the same topic.
- **When it lapses.** If the cited lines change, the waiver lapses. STATUS shows "waiver gap-critic.GC-0-7 lapsed: the text changed", and the finding is judged afresh.
- **Old waivers.** Topic waivers already in a ledger (`gap-critic.B9`) keep working until they expire, but only for the findings that existed when they were recorded. The ledger's PROCEED-PAST `passed_findings` and the archived run tell the gate which findings those were. Open question Q3 below.

## 6. Keeping "later phase" from weakening the review

The risk is that a real gap gets labelled "later phase" and is never closed. The following counter it:

1. **The boundary is not the agent's to write, nor the critic's.** The `decides` and `defers` lists live in the root-owned catalogue. A carry must name an existing rule ID, and the gate checks every hard rule in §2 deterministically. The BRD's own "Carried to later phases" section (F-3's workaround) has no force: only the critic's CARRY findings enter the register.
2. **`decides` wins every overlap.** If a gap touches a promise, a role's permissions, a money flow, a legal duty, data ownership or retention policy, scope, or a lifecycle state, it cannot be carried, whatever detail it also contains. The brief says so in those words, and the schema rejects a carry whose quote matches a `decides` rule's keywords (a cheap lexical tripwire, not a judgement).
3. **Carries cannot disappear.** The target phase cannot be approved until every carry addressed to it is settled (§3). Proceeding past it keeps the carries open, and phase 11's scorecard counts open carries as release blockers. "Later" means a named phase with a gate, never "never".
4. **A fresh critic audits each carry, later.** The target phase's critic gets each carry with its source quote and one extra question: should this have been decided earlier? If yes, it raises a MAJOR, "decided too late", citing the `decides` rule. The operator then chooses between REOPEN of the earlier phase and a WAIVE with a reason. So a carry gets reviewed twice: once by the critic that proposed it, and once by a later critic that sees the consequences.
5. **The agent cannot carry.** Only the critic, in fresh context, classifies. The agent's builder session never sees the depth rules as a tool for argument; it sees only the critic's findings. The critic's brief keeps its current rule that nothing the builder wrote reaches it, apart from the documents.
6. **The operator sees every carry.** The APPROVE and REVIEW summaries list the carries (ID, rule, target phase, one line each). They are never hidden in a MINOR file. A new command, `UNCARRY GC-0-7 <code>`, would let the operator pull a carry back to the current phase as a MAJOR (Q2).
7. **Numbers stay visible.** STATUS shows, per phase: runs, findings per run, late findings, carries out and carries in, and waivers that lapsed. If one critic run carries more than a threshold (proposed: more than half of its MAJOR-or-worse findings), the gate adds a line to the summary for the operator. It does not refuse.

## 7. What would change (when this is approved)

- `gate/config/coverage-topics.yaml`: a `depth` block per phase, with the rules from §2.
- `gate/config/critic.schema.json`: `CARRY`, `defer_rule`, `to`, `same_as`, `regression_of`.
- `gate/contract.py`: `critic_check` handles carries, `same_as` and fingerprints; coverage-lint handles carry lines.
- `gate/verify.py`: archiving earlier runs, and the brief's "Earlier runs" and carry sections.
- `gate/opcmd.py` and `gate/state.py`:
  - the carry register on APPROVE and PROCEED-PAST;
  - finding-bound waivers and lapsing;
  - `UNCARRY`, if Q2 is accepted;
  - STATUS counters.
- `gate/v1/build_scorecard.py`: open carries count as release blockers.
- `commands/coverage.md` (generated): the depth table and carries.
- Tests:
  - every hard rule, with a planted violation;
  - a three-run convergence fixture (fixed, ruled, carried, waived, regression, late);
  - lapse on a text change;
  - a carry that is never settled blocks the target phase;
  - "decided too late" at the target phase.

## 8. The operator's rulings

- **Q1. The depth table.** Accepted, with four corrections. All four are in `gate/config/coverage-topics.yaml`.
  - a. D4.4 names the security requirements **SEC-n**. SR- means shared resources (ruling 1 of increment 7).
  - b. Phase 2 decides business validation rules: what counts as valid (D2.6, topic P6). X2.3 defers only how such a rule is encoded (formats, patterns, field types, endpoints, error codes), never what counts as valid, to phase 5.
  - c. 10a/10b/10c defer a defect to the release notes as a known issue (X10a.1, X10b.1, X10c.1 → 11) only if it breaks no P1 acceptance criterion and is not a security, privacy or tenant-isolation defect. This is a hard rule. The carry must name the affected AC in `ac` (or `none`), and the gate reads each story's `**Priority:**` (must or P1) from the PRD.
  - d. A gap that matches no defers rule is judged at the current phase exactly as before. The brief, the catalogue and `/moadix:coverage` say so.
- **Q2. UNCARRY.** Yes, with a code: `UNCARRY <GC id or CARRY id> <code>`.
- **Q3. Old topic waivers.** As recommended.
- **Q4. The carry threshold.** It only informs.
- **Q5. Proceeding past a target phase.** Carries stay open after PROCEED-PAST of their target phase and count as release blockers. The exit: the operator may close one open carry with `WAIVE CARRY-<phase>-<n> …` and a reason, one item at a time. The waiver is recorded in the ledger with the carry's text. A security, privacy or tenant-isolation carry cannot be waived.
- **Q6. Late findings.** They are counted and shown, never downgraded. A late BLOCKER or MAJOR blocks at its severity.

## 9. Where the build differs from the text above

- **The register is the ledger, not a separate file.** §3 proposed `.sdlc/carry/<scope>.json`. Instead, each APPROVE or PROCEED-PAST line carries the phase's carries (`carries`, with their text) and the carries it closed (`carries_closed`), and `state.replay` rebuilds the register from the verified ledger. There is no second copy that could drift from it, and `phase.yaml` does not change (the register lives under unrendered keys).
- **Archived runs and stable ids** live in `.sdlc/critic/<scope>-<label>.json`, which is gate-owned. A run is archived when the gate first checks stamped evidence, or before a relaunch supersedes it.
- **Old topic waivers (Q3).** A 0.6.x waiver ledger line does not say which findings were open when it was recorded, and the evidence of that time was overwritten. So "only the findings that existed when they were recorded" is implemented as: only a MAJOR on that topic, in the phase where the waiver was recorded, whose cited text already existed at the waiver's commit. A finding on text written later is not covered.
- **A WAIVE of a finding needs current evidence.** If the documents changed since the critic ran, the operator waits for the next run and waives the finding by its (unchanged) GC id.
- **Two kinds of rule check.** The tripwires that test a carry against a phase's `decides` rules and the security, privacy and tenant classes are lexical: lists of words in the catalogue. They refuse a carry that names them, and do not judge meaning. The other hard rules (rule, target, order, closed phase, P1 AC) are exact.

## 10. Proposed for 0.7.2: scoped runs, claim severity, citations without network, section fingerprints, size bars

Status: **proposed, not built; for the operator's review.** Source: the task-tracker run on 0.7.0, findings MF-12 and MF-17 to MF-20 (`~/task-tracker/docs/moadix-findings.md`). On phase 1, runs 1 to 3 had 16, 4 and 10 findings. Earlier findings converged: they were checked and closed, and none was raised again. New findings on unchanged text grew from 2 to 7, so the runs still do not converge. §4's memory makes late findings visible but does not stop them, and Q6 keeps them at full severity.

### 10.1 What a run may review

**Runs 1 and 2 of a phase are full reviews,** as today.

**From run 3 on, a run is scoped.** The brief gives the critic two things to review:

1. the earlier findings, with the gate's dispositions (§4);
2. the text changed since the previous run, as a diff of the document set from run n-1's commit to HEAD. Each hunk comes with its whole section (heading to next heading), so the critic reads the change in context.

The brief tells the critic to review only those two. It may still read any document, to judge a change against it.

**The frozen-text rule.** From run 3 on, the critic may not raise a new finding (no `same_as`, no `regression_of`) on frozen text. Frozen text is a section that did not change between run n-2's commit and HEAD, so both previous runs read it as it is now. There are two exceptions, and both must be BLOCKERs:

- **(a)** a security, privacy or tenant-isolation gap;
- **(b)** a contradiction with an approved upstream document.

**The gate enforces the rule from the diff, not the critic.** For each new finding of run n ≥ 3, the gate:

1. resolves its citation to a section at HEAD (`critic._section`, as for `same_as`);
2. decides whether that section is frozen. It runs `git diff -U0 <run n-2 commit> HEAD -- <path>` and maps the hunks to sections. A section with no added, removed or changed line is frozen. A section that did not exist at run n-2 is not frozen;
3. if the section is frozen, checks the exception:
   - (a) needs `exception: "security" | "privacy" | "tenant"`. The finding's quote or fix must match that class's words in the catalogue: the same lexical tripwire carries use (§9, "two kinds of rule check").
   - (b) needs `exception: "upstream"` and a second citation, `upstream: path:line`. That path must belong to an earlier phase that is APPROVED or PROCEED-PAST, and the line must exist at HEAD. The gate checks that the path is upstream and closed. It does not judge whether the contradiction is real; the critic does.
4. if the section is frozen and the exception is missing or fails its check, the finding does not count. Two options for what happens to it, **ruling A1**:
   - **(i) Recommended.** The gate moves it to the MINOR file, tagged `frozen` with the reason, and counts it on STATUS as "frozen-text findings: n". It blocks nothing, and the operator can still read it.
   - (ii) The evidence fails, and the critic must run again.

   (i) keeps every word visible and costs no run. (ii) is stricter, but it spends a run on what is, by this rule, a non-finding.

A finding about missing text cites the nearest line in the section where the text belongs. If that section is frozen, the rule applies. Deleting text changes its section, so a gap a deletion opens is never frozen.

**Regressions.** A `regression_of: GC-x` must cite the section the original finding cited, or a section changed since the run that raised GC-x. Otherwise it is refused as a regression and treated as a new finding under the rules above (MF-18: GC-1-17's regression cited ADR-003, a document the earlier finding only named). `same_as` keeps its 0.7.0 rule: same topic, same section.

**Why runs 1 and 2, and not just run 1.** Run 2 checks the fixes of run 1, and is the second full read of the text. The phase-0 and phase-1 data on two products show real misses in run 2 (GC-1-18, the licence sentence, a BLOCKER that run 1 passed). After two full reads, a new finding on unchanged text has a falling chance of being real and a rising cost. The two exceptions keep the classes where a miss is expensive.

**What 0.7.0 already does that stays.** `late` marking stays, for runs 1 and 2 only: from run 3, a late finding can only exist through an exception. Q6 (late findings are never downgraded) is unchanged for runs 1 and 2. For runs ≥ 3, A1 replaces it for frozen text. This is a change to a ruling, so it needs the operator's yes.

### 10.2 When a finding's text changed (MF-17)

Today a finding counts as fixed when its cited lines are gone at HEAD (`critic.present`). A fix that adds lines next to the cited line, and leaves that line as it was, is recorded as `open`. That happened to GC-1-14.

**Proposal.** The fingerprint gets a second hash, `section_sha`: the sha256 of the cited section's body, with whitespace normalized and the heading excluded.

| Use | Unit | Change |
|---|---|---|
| Disposition `fixed?` | the section | `fixed?` when the cited lines are gone **or** `section_sha` changed. `open` only when both are unchanged. The brief shows the section's diff for a `fixed?` finding whose cited lines are still there, so the critic sees what changed next to them. |
| Frozen text (§10.1) | the section | the same unit, so "changed" means one thing everywhere |
| Waiver lapse (§5) | the cited lines, as today | **ruling A2**: recommended unchanged. The operator accepted that text. An unrelated edit in the same section should not take the waiver back and force another run. The alternative is to lapse on `section_sha` too: stricter, and noisier. |
| `late` (runs 1 and 2) | the cited lines, as today | unchanged |

A citation range (`path:12-18`) is one unit. A section is located by its heading anchor, so line shifts do not matter. A document with no headings is one section. For a very long section, one edit reopens all of it; this design accepts that over guessing a smaller unit.

### 10.3 Severity of an uncited claim (MF-19)

Today D1.3 ("a citation for every claim") and D1.B make every uncited claim a BLOCKER. Example: "MIT is permissive and compatible with any licence" (GC-1-18), a sentence nothing downstream used.

**Proposed rule.** A finding about a claim with no citation sets `kind: "uncited"`, plus two fields:

- `claim_class`: one of `legal`, `cost`, `security`, `feasibility`, `other`.
  - `legal`: a regime applies or not, or what it requires.
  - `cost`: a price, a fee, or a cost's order of magnitude.
  - `security`: a security property of a vendor, library or control.
  - `feasibility`: something can or cannot be done with a named technology, vendor or API.
- `decision`: what depends on the claim. It is one of:
  - a `Q-n` in this or a later phase's DISCOVERY.md whose `Chosen:` rests on it;
  - an `ADR-nnn`;
  - a decides rule of this phase (`D1.1`, `D1.2`);
  - `none`.

| claim_class | decision is an existing id | decision is `none` |
|---|---|---|
| legal, cost, security, feasibility | **BLOCKER** | **MAJOR** |
| other | **MAJOR** | **MINOR** |

**What the gate checks.**

- The finding's `decision` id must exist: the Q-n heading in a DISCOVERY.md, the ADR file, or the D rule in the catalogue. A missing id fails the evidence.
- The severity must be the table's cell. If the critic gives a different severity, the gate records the table's severity and notes "severity set by the uncited-claim rule (§10.3)". This is a fixed mapping from two fields the critic fills in, not a second judgement. Q6's "never downgraded" was about late findings, so it does not apply here.
- The class itself is the critic's judgement. The gate cannot check it beyond the lexical tripwire for security, privacy and tenant terms. That tripwire makes `security` mandatory when the quote names such terms.

**Catalogue changes.**

- D1.3 becomes "a citation for every claim a decision depends on (§10.3); any other claim is cited or marked as the author's assumption".
- D1.B becomes "an uncited legal, cost, security or feasibility claim that a decision depends on".
- The global BLOCKER text, "a claim that needs a citation and has none", points at the same rule.

A claim marked `Assumption:` in the text is not uncited. If a decision rests on it, it belongs in R1 (open questions) or B21 (riskiest-assumption tests).

### 10.4 Judging citations without network access (MF-20)

The critic runs with no network access. The verifier tool set has no WebFetch, and the sandbox allowlist has no general web. It cannot open a cited page, so a finding must never rest on what the critic assumes a page says.

**Division of labour.**

- **The gate's link and date check decides whether a citation exists and is reachable.** cite-lint already does this: a URL on the line, a retrieval date, `links.json` status. The critic does not re-judge it. A finding of "no citation" on a line where cite-lint found a URL and a date is refused. The gate checks this from cite-lint's result for that line.
- **The critic judges support only from text in the documents.** A claim is "supported" when the document quotes the source next to the citation (a quoted sentence or a block quote, at most about two sentences) and the quote says what the claim says. The critic may raise:
  - `basis: "quote-contradicts"`: the document's quote says something else (MAJOR, or BLOCKER under §10.3's classes with a decision);
  - `basis: "quote-insufficient"`: the quote does not cover the whole claim (the §10.3 table, read as "uncited" for the uncovered part);
  - `basis: "no-quote"`: a §10.3 BLOCKER-class claim with a decision is cited but has no quote (MAJOR: "add the source's sentence"). For any other claim, a missing quote is not a finding.
- **The brief says so in those words.** "You have no network. Never state what a cited page says unless the document quotes it. Judge support only from quoted text."
- **What the gate checks.** For `quote-*`, a quote exists on or next to the cited lines (a `"…"` or a `>` line within the citation's section). A finding whose `basis` is missing or does not fit the text is refused. GC-1-20 and GC-1-21 ("the source may not support it", from the footnote list alone) would have been refused.

This also strengthens the documents: a decision-bearing claim now carries the sentence it rests on, so a later reader does not need the page either.

### 10.5 Size S and the critic's bars

Some topics carry a number: R2 "competitor teardown (3–5 real products)", B27 "top three ISO 25010 qualities". The critic holds an S product to the same number as an L product.

**Proposal.** Size relaxes only **quantity** bars, never a class bar:

- **Relaxable.** Counts of competitors, alternatives or products to compare. Proposed for S: R2 at **2–3** real products, and B13 (competitors in the BRD) at least **2**.
- **Never relaxed.**
  - legal, privacy, security and tenant-isolation bars;
  - the citation rule (§10.3), whose classes do not depend on size;
  - EARS and testability;
  - a decides rule's depth.

**Where it is recorded.** In the root-owned catalogue, next to the size rule that already lives there: `gate/config/coverage-topics.yaml` gets `sizes.S.bars: [{topic: R2, bar: "2–3 real products", reason: "..."}]`.

- The critic's brief and `/moadix:coverage` show the bar in place of the topic title's number, so the agent and the critic read the same bar.
- The operator can restore the full bar for one product through the existing override channel (`ADOPT` of `coverage-overrides.yaml`, `turn_on: [R2]`).
- Nothing is recorded in the BRD: the size is (B19), and the catalogue maps the size to the bars.

M and L keep today's numbers. **Ruling A4**: the two numbers above.

0.7.1 removed the other size problem, two definitions of S (MF-2). S now has one definition, `sizes.S.profile` in this catalogue, and `profiles.yaml` points at it.

### 10.6 What would change

- `gate/critic.py`:
  - `section_sha` in the fingerprint;
  - the `fixed?` rule;
  - frozen-section detection from `git diff -U0`;
  - the exception checks;
  - the regression location rule;
  - the uncited-claim table;
  - the `basis` checks;
  - the brief's scoped section and the "no network" text.
- `gate/config/critic.schema.json`: `exception`, `upstream`, `kind`, `claim_class`, `decision`, `basis`.
- `gate/config/coverage-topics.yaml`: D1.3 and D1.B text, the global BLOCKER text, `sizes.S.bars`.
- `gate/contract.py`: the rendering of bars and the new rules in `/moadix:coverage`.
- `gate/verify.py`: the scoped brief for run ≥ 3 and the diff with section context. A1 decides between the MINOR file and failed evidence.
- Tests:
  - a four-run fixture: a full run 1, a full run 2, then run 3 with a planted new finding on a frozen section (refused or moved), a planted security BLOCKER on frozen text (kept), and an upstream contradiction with a valid and an invalid `upstream` citation;
  - MF-17's case: added lines next to a cited line, giving `fixed?`;
  - each cell of the §10.3 table;
  - a `no-citation` finding on a line cite-lint accepts (refused);
  - a `quote-contradicts` finding without a quote (refused);
  - R2's bar at S and M.

### 10.7 Rulings needed

- **A1.** A new finding on frozen text that fails the exceptions: moved to the MINOR file as `frozen` (recommended), or the evidence fails?
- **A2.** Waiver lapse stays on the cited lines (recommended), or also on the section?
- **A3.** The §10.3 table as written, including the gate setting the table's severity when the critic's differs?
- **A4.** S bars: R2 at 2–3 products and B13 at least 2, with no other relaxation?
- **A5.** Q6 is amended for runs ≥ 3 as in §10.1, and is unchanged for runs 1 and 2?
