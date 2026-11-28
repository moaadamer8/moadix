# Amendment 5 (2026-11-21, revised 2026-11-28) — Autonomy: the operator directs, MOADIX runs the workflow

Extends DESIGN.md and Amendments 1–4; overrides them where they differ. Proposed by the operator on 2026-11-21; revised with the operator's rulings and autonomy direction on 2026-11-28. Nothing here is built.

Build only after one product has passed every phase on the current design. Every part is off by default and is turned on per product through ADOPT.

## 0. Goal and principles

Goal, in the operator's words: "I initialize a product, provide its initial business context, approve the seven mandatory milestones, and let MOADIX execute the remaining SDLC work independently. I want to direct the engineering team, not operate the engineering workflow."

Three levels of autonomy:
- **Execution:** the agent does routine work without asking.
- **Validation:** the agent checks its own work, fixes failures and re-verifies. Passing must never come from weakening a check (section 4).
- **Escalation:** the agent asks only for a business decision, a significant architectural trade-off, an unresolved risk, a mandatory gate, or an authorization outside its scope.

Unchanged: the agent never silently waives a finding, bypasses a mandatory check, invents a business decision, or acts on production. Accepting a risk, skipping a failing check and changing the gate's governance stay operator decisions with a code.

## 1. The seven mandatory gates

Always an explicit `APPROVE <ph> <code>`, never automatic, whatever any policy file says (ADOPT refuses such a file):

| Phase | Name | The operator decides |
|---|---|---|
| 0 | BRD | Vision, target users, purpose |
| 2 | PRD | Feature scope and behaviour |
| 6 | UX | Experience, screens, design |
| 11 | Release | Shipping to real users |
| 11b | Store release | App Store / Google Play publishing (mobile only) |
| 12 | Retro | Lessons learned and improvements |
| B | Baseline | The takeover assessment of an existing product |

Ruling R1 (2026-11-28): phase 9 is not on this list.

### 1.1 The approval package

At a mandatory gate, the agent prepares one package: the deliverables, the decisions taken since the last gate (including every auto-closed phase with its counts and MINORs file), the assumptions, the open risks, and the exact line the operator must send. Reporting progress never needs an approval.

## 2. Clean phases close themselves

Policy in `.sdlc-proposals/autonomy.yaml`, adopted with `ADOPT <code>` into `.sdlc/autonomy.yaml`. Default when adopted: every phase not in section 1.

### 2.1 What "clean" means

All must hold on the current commit (ruling R2: clean means clean):

| Condition | Detail |
|---|---|
| Validators | Every validator PASS. One FAIL or UNKNOWN is not clean. |
| Verifiers | Every scheduled verifier has current evidence. |
| Findings | No open BLOCKER or MAJOR, no high or medium design-review finding. MINORs do not count. |
| No exception | No waiver, no PROCEED-PAST, no frozen BLOCKER in this phase. |
| Risk acceptance | Nothing awaits operator acceptance: in phase 9, no unaccepted unfixed scanner finding (0.8.2) and no residual risk added or changed since the last acceptance. |
| Carries | Every carry addressed to this phase is settled. |
| Questions | Every question has an operator answer, or there were none. |
| Proposals | Nothing pending in `.sdlc-proposals/`. |
| Budget | Inside the critic-run limit and the cost budget. |

If any fails, the phase needs one operator command, and only one (section 5).

### 2.2 Recording

The gate's worker closes the phase; the agent cannot request it. Ledger line type `AUTO-CLOSE`, signed, with validator and evidence digests, the policy digest and finding counts. It can never be read as an `APPROVE`. `STATUS` shows `AUTO-CLOSED`. `REOPEN` works on it as on an approved phase.

Ruling R3 (2026-11-28): no `pause_after`. The run keeps going until something needs the operator.

## 3. Actions the agent may take without a code

Each is requested by the agent with a code-free command, checked by the gate against the rules below, and recorded as a signed ledger line of its own type. A request that breaks a rule is refused and becomes an escalation. Manual operator use of each command stays.

### 3.1 Fix before escalating

On any finding, the agent first tries to fix it, re-runs the checks and re-verifies, within the phase's critic-run limit and cost budget. A waiver or PROCEED-PAST request to the operator must list the fix attempts and why each failed.

### 3.2 AUTO-REOPEN

The agent may reopen an earlier phase when a correction belongs there, only if all hold:
- the target is not a mandatory gate (0, 2, 6, 11, 11b, 12, B): reopening one of those is always the operator's `REOPEN` with a code;
- the reopen names the finding that needs it, and the gate's path map confirms the fix touches the target phase's paths;
- the fix stays inside the approved requirements: it does not change a PRD acceptance criterion, a UX decision or an operator ruling;
- the issue's correction budget is not used up (ruling R6): at most three unsuccessful correction cycles per issue, where a cycle is one fix attempt with its re-run checks, and every AUTO-REOPEN for that issue counts as one cycle. After the third, the agent escalates with the history of all three.

Phases reset by the reopen go to draft as today and may auto-close again when clean. The fix lane (Amendment 4 proposal 8) is preferred when it applies, because it avoids the reopen.

### 3.2.1 Phase 4 (threat model)

Ruling R7 (2026-11-28): the agent may AUTO-REOPEN phase 4 whenever needed, including when implementation changes reveal new risks. It updates the threat model, investigates, fixes where the rules allow, and re-runs the security validations. Limits:
- it counts toward R6 like any other reopen;
- it may add or strengthen a security requirement (SEC-ID), never remove or weaken one: removing, narrowing or downgrading a SEC-ID, a threat's severity or a mitigation is a weakening (section 4) and is escalated;
- security findings are never waived automatically and mandatory security checks are never bypassed;
- an unresolved critical or high risk is escalated to the operator;
- every change keeps its audit trail: the ledger line, the commit, and the decision registry entry (6.3).

### 3.3 CARRY-SETTLED (replaces most UNCARRY)

A carry is settled automatically when the target phase's evidence shows the carried item resolved, cited by file and line and checked by that phase's critic. Dropping a carry that is not resolved stays the operator's `UNCARRY` with a code. A carry of a security item can never pass phase 9 either way.

### 3.4 AUTO-COLLAPSE

A phase that demonstrably does not apply is collapsed from an operator ruling already in the ledger: the platform profile from phase 0 (for example 11b for WEB) or the size ruling (for example 10c where the size defaults say so). Any other collapse stays the operator's `COLLAPSE` with a code.

### 3.5 Routine technical decisions

The agent decides technical questions inside the approved BRD, PRD, UX and rulings, recorded as ADRs. A decision that changes cost, scope, a user-visible behaviour or a significant architectural trade-off is escalated as a question.

### 3.6 Questions

Questions are collected into one round per phase where possible and answered with code-free `ANSWER <phase> <round> <text>`, logged by the gate with its hash; the builder's brief quotes the gate's copy (ruling R4).

## 4. Validation must not be weakened

A fix may not pass by loosening a check. The gate flags, and the phase's critic must review, any commit in the phase that: deletes or skips a test or assertion, widens an accepted value, raises a threshold or timeout in a check, narrows a scan or mutation scope, or adds an allowlist entry. A flagged change with no ADR and no critic acceptance blocks auto-close. Allowlists and scope changes stay ADOPT.

## 5. Final behaviour of the commands

| Command | Behaviour |
|---|---|
| `STATUS` | Read-only, no code. |
| `REVIEW <ph>` | Read-only, no code. Lists everything that awaits the operator. |
| `APPROVE <ph>` | Automatic for clean non-mandatory phases (AUTO-CLOSE). Explicit, with a code, at the seven mandatory gates. |
| `APPROVE <ph> WITH-WAIVERS` | Explicit acceptance of unresolved findings. One code also accepts every pending ADOPT, waiver and risk REVIEW listed (Amendment 4 proposal 11). |
| `WAIVE` | Explicit risk acceptance, after the agent's fix attempts (3.1). |
| `PROCEED-PAST <ph>` | Explicit authorization. Never for security in phase 9. |
| `ADOPT` | Explicit approval of governance changes. |
| `REOPEN <ph>` | AUTO-REOPEN under 3.2; the operator's code for mandatory gates and anything outside 3.2. |
| `UNCARRY` | CARRY-SETTLED under 3.3; the operator's code to drop an unresolved carry. |
| `COLLAPSE` | AUTO-COLLAPSE under 3.4; the operator's code otherwise. |
| `INIT` | Operator-initiated, once per product. |
| `ANSWER` | Code-free answers, one round per phase where possible. |

Target: clean phases need no command; any other non-mandatory phase needs at most one code.

## 6. Orchestrated phase agents (optional execution mode)

The aim is more reliable autonomous execution with less supervision, not more agents for their own sake.

### 6.1 Mode

`orchestration: on` in `autonomy.yaml`, off by default. Single-agent execution stays the default, recommended for sizes XS and S; orchestration is offered for M and L. Every autonomy rule in sections 1 to 5 applies the same way in both modes.

### 6.2 Roles

| Role | Does | May not |
|---|---|---|
| Orchestrator (main session) | Coordinates only: requests briefs from the gate, launches builders and verifiers, relays question rounds and summaries, starts the next phase (R5) | Write a phase document or product code, or act as a substitute builder; the path map refuses its writes to `sdlc/` and product paths |
| Phase builder (fresh `moadix:phase-builder`) | Executes one phase, or one task of it, from a clean context | Launch agents, talk to the operator, write outside its write scope |
| Verifier (fresh, as today) | Reviews and writes evidence | Anything else, as today |

Reviewers stay independent from builders: different agents, no shared conversation. The gate decides completion from its own validators and the verifiers' evidence, never from a builder's claim that it is done.

### 6.3 The phase handoff contract

A standardized, versioned contract (`handoff/v1`), generated and enforced by the gate like a verifier's brief (prompt replacement, one-time receipt). Every builder receives:
- the phase's role, coverage topics and size defaults;
- every relevant upstream artifact, by path and digest;
- the operator's approved decisions and rulings, and every ANSWER so far (the gate's copies);
- assumptions in force, with who made each;
- findings to fix on a fix round, with their history;
- dependencies and constraints, including carries addressed to the phase and standing instructions;
- the expected deliverables and their acceptance criteria;
- its write scope.

A change to the contract format bumps its version; the gate refuses a brief whose version it does not support.

**Decision registry.** Every important decision lives in a project artifact or in `sdlc/decisions.md` (append-only, one entry per decision: ID, date, who decided, phase, what, why, superseded-by). Nothing essential may exist only in an agent's conversation. The gap critic treats a decision that a deliverable relies on and that is not in an artifact or the registry as a finding.

### 6.4 Write permissions

Each builder may write only its authorized phase files, as the gate's path map gives them. Shared files (the traceability matrix, the decision registry, the findings register) are written only through gate-listed operations: append-only entries, each tagged with the builder's receipt. Any other shared-file change needs an operator-approved operation listed in the brief. The gate refuses a commit outside the builder's scope.

### 6.5 Recovery and resumption

All progress is persisted: phase status and ledger in `.sdlc/`, deliverables committed per task, the handoff contract and the receipts stored by the gate. If a builder fails or a session ends, a fresh orchestrator rebuilds its position from `STATUS` and the ledger, and a fresh builder continues from the last commit with a new brief. A task that was in progress is resumed or restarted, never lost silently; a builder that fails twice on the same task stops the run (section 7).

### 6.6 Parallel work

Phases never run in parallel. Inside a phase, tasks run in parallel only after the gate has checked their dependencies (from the phase's task list) and their file ownership: each parallel builder gets a non-overlapping write scope, and the gate refuses overlapping scopes and concurrent conflicting changes. When one task is blocked, independent tasks continue.

### 6.7 Prove it before relying on it

Before orchestration is relied on for a real product:
- **Spike:** test on the pinned Claude Code version: whether an agent can spawn agents (and the gate refuses it if it can), the permissions and hooks a spawned agent runs under, how complete the context handoff is, and recovery after a killed agent and a closed session. The report states each limit found.
- **Measure:** run the same product type in both modes and compare token cost, elapsed time, quality (findings per phase at review), missed requirements, and rework (fix rounds and reopens). Orchestration becomes the recommended mode for M and L only if it is better on quality and rework at an acceptable cost.

## 7. When the run stops

The orchestrator stops, reports, and never retries on its own when: a mandatory gate is ready (with its package, 1.1); a question round needs the operator; a phase is not clean and needs one code; a budget is crossed; a validator is UNKNOWN; a builder fails twice; an AUTO action is refused; or the gate reports an integrity failure.

## 8. What does not change

The one-time code, the signed ledger, the rule that a confirmed high finding cannot be waived, the rule that security cannot pass phase 9 by PROCEED-PAST, the critic-run limit with the scoped third run, and the denial of scheduled tasks and cross-session messages: an unattended run is one session working until a stop condition.

## 9. Conflicts found and how they are resolved

| Operator direction | Conflict with the earlier design | Resolution |
|---|---|---|
| Reopen phases automatically | A reopen could undo an operator decision | 3.2: never a mandatory gate, only inside approved requirements, tied to a finding, with a budget |
| Resolve obsolete carries automatically | A dropped carry hides unfinished work | 3.3: settled only with evidence; dropping stays a code |
| Collapse irrelevant phases automatically | Collapse was an operator judgement | 3.4: only from a ruling already in the ledger |
| Phase 9 not mandatory | Unfixed scanner findings and residual risks need acceptance | 2.1: phase 9 auto-closes only when nothing awaits acceptance; otherwise one code |
| Fix findings and re-run checks autonomously | Fixes could pass by weakening checks | Section 4 |
| Continue when a task is blocked | Phases are sequential | 6: within the phase only |
| Keep going with no pause (R3) | Many phases could close unseen | 1.1: every auto-close appears in the next approval package; STATUS lists them |
| Reopen the threat model on its own (R7) | Security requirements could be quietly weakened | 3.2.1: add or strengthen only; removing or weakening a SEC-ID is escalated |
| Builders modify only their own files | Some files are shared by every phase | 6.4: shared files only through gate-listed append-only operations |
| Correction limit per issue (R6) | A per-issue limit alone allows many reopens in total | Each issue gets three cycles; the critic-run limit and the cost budget still cap the phase |

## 10. Build order

1. Sections 2, 3.3, 3.4, 4 and 5 (auto-close, carry settling, auto-collapse, the weakening check, one code per phase), with attack-corpus cases. Prove on a size S product.
2. Section 3.1 and 3.2 (fix-first, AUTO-REOPEN), after the fix lane (Amendment 4 proposal 8).
3. The 6.7 spike on Claude Code's agent limits, with its report.
4. Section 6, sequential builders, with the handoff contract, decision registry, write scopes and recovery.
5. The 6.7 measurement on one product in both modes.
6. Section 6.6, parallel builders, last.

Each part is one increment with its own report, fixture tests, a version bump and a tag.

## 11. Rulings

All decided on 2026-11-28:
- R1: the seven mandatory gates, without phase 9.
- R2: clean means clean.
- R3: no pause_after.
- R4: gate-logged, code-free ANSWER.
- R5: the orchestrator starts the next phase directly.
- R6: three unsuccessful correction cycles per issue; each AUTO-REOPEN for the issue counts as one.
- R7: AUTO-REOPEN of phase 4 allowed, counted toward R6, with no automatic waiver or bypass, escalation of unresolved critical and high risks, and a full audit trail (3.2.1).
- Orchestration: optional per product, single agent by default for small products, with the requirements in section 6.
