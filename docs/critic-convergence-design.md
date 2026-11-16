# Gap-critic convergence: design (F-3)

Status: **design for the operator's review. Nothing here is built.** Written for 0.6.4 from finding F-3 of the first product run (onlineMarket, size L). That run needed 7 gap-critic runs on phase 0, with totals of 19, 17, 15, 15, 8, 12 and 13 findings, and closed with PROCEED-PAST.

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
| **2 PRD** | D2.1 every story and its ACs (EARS, testable); D2.2 the role × action matrix; D2.3 every NFR with a number and a unit; D2.4 the per-story mapping from business rule to AC; D2.5 per-story release scope | X2.1 component, technology or integration pattern → **3**; X2.2 attack defences beyond the authorization rule → **4**; X2.3 field types, validation patterns, endpoints, error codes → **5**; X2.4 screens, states, copy → **6** |
| **3 HLD** | D3.1 components and their boundaries; D3.2 data stores and data ownership per component; D3.3 the tenant-isolation design; D3.4 integration and deployment topology; D3.5 every H1 trade-off and the tactic for each top quality | X3.1 threat-specific controls → **4**; X3.2 tables, columns, endpoints, state machines → **5**; X3.3 environments, accounts, sizes, secrets layout → **6b**; X3.4 library choice inside one component → **7** |
| **4 Threat Model** | D4.1 threats per trust boundary; D4.2 a mitigation per high-impact threat (control type and where it sits); D4.3 abuse limits as numbers; D4.4 the SR-n security requirements | X4.1 how a control is implemented (header values, library, configuration) → **5** or **7**; X4.2 how a control is verified → **9** |
| **5 LLD** | D5.1 schema and migrations; D5.2 every API with authz and tenant scope; D5.3 the error model; D5.4 state machines; D5.5 validation rules | X5.1 screen states and copy → **6**; X5.2 code structure inside a module → **7**; X5.3 test cases → **8** |
| **6 UX** | D6.1 every P1 screen and its states; D6.2 flows; D6.3 copy; D6.4 WCAG AA obligations; D6.5 tokens, motion, assets | X6.1 component implementation → **7**; X6.2 visual regression → **10b** |
| **6b Provisioning** | D6b.1 environments, accounts, MFA; D6b.2 secrets handling; D6b.3 IaC | X6b.1 release gates and rollback → **11**; X6b.2 SLOs and alerting → **11** |
| **7 Implementation** | D7.1 the code matches the LLD and the tasks; D7.2 code standards and the phase-7 rules | X7.1 coverage completeness → **8**; X7.2 security verification → **9** |
| **8 Testing** | D8.1 a test per AC; D8.2 thresholds set before results | X8.1 exploratory and live checks → **10a**; X8.2 load and concurrency → **10c** |
| **9 Security Verification** | everything in scope | nothing (security is never carried past 9) |
| **10a / 10b / 10c** | everything in scope | X10.1 known issues for the release notes → **11** only |
| **11 / 11b Release** | everything in scope | X11.1 process lessons → **12** |
| **12 Retro**, **B Baseline** | everything in scope | B: X B.1 anything "to-be" → a feature cycle (FC topics); 12: nothing |

Every phase also gets four hard rules:

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

## 8. Open questions for the operator

- **Q1. The depth table (§2).** Accept it as written, or amend rows? Phase 0 is your F-3 ruling. The other phases are my proposal.
- **Q2. UNCARRY.** Add an operator command to pull a carry back as a MAJOR? Recommended. Without it, the only lever is REOPEN, after the fact.
- **Q3. Old topic waivers.** Honour them only for the findings that existed when they were recorded (recommended), until expiry? Or end them at the update?
- **Q4. The carry threshold in §6.7.** Is "more than half of the MAJOR-or-worse findings" right, and should it only inform (proposed) or refuse?
- **Q5. Proceeding past a target phase.** Its carries stay open and block phase 11 (proposed). Or should the PROCEED-PAST itself be refused while carries addressed to that phase are open?
- **Q6. Late findings.** Only counted (proposed), or should a late MAJOR on unchanged text drop to MINOR after N runs (for example from run 4)? Dropping it would converge faster but could hide a real gap the critic missed earlier.
