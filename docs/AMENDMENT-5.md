# Amendment 5 (2026-11-21) — Autonomy: clean phases close themselves, and phases are built by orchestrated agents

Extends DESIGN.md and Amendments 1–4; overrides them where they differ. Proposed by the operator on 2026-11-21. Draft for review: nothing here is built, and section 5 lists the rulings still needed.

Build only after one product has passed every phase on the current design. Both parts are off by default and are turned on per product through ADOPT.

Principle that does not change: the agent never accepts a problem on the operator's behalf. Everything that needs a judgement or an exception (a waiver, a skipped check, a scope choice, an answer to a question) still needs the operator and a code.

## 1. Clean phases close themselves

### 1.1 Policy

`.sdlc-proposals/autonomy.yaml`, adopted with `ADOPT <code>` into `.sdlc/autonomy.yaml`:

```yaml
auto_close: ["4", "5", "6b", "7", "8", "9", "10a", "10b", "10c"]   # the operator's choice per product
pause_after: 3        # optional: stop for the operator after this many auto-closes in a row
```

- Default: `auto_close` is empty, which is today's behaviour.
- Never auto-closed, whatever the file says (ADOPT refuses the file): **0** BRD, **2** PRD, **6** UX, **11** Release, **11b** Store release, **12** Retro, **B** Baseline. These are the phases that decide what the product is, what ships, and what is learned.
- Any other phase is the operator's choice.

### 1.2 What "clean" means

The gate closes a listed phase only when all of these hold on the current commit:

| Condition | Detail |
|---|---|
| Validators | Every validator of the phase is PASS. One FAIL or UNKNOWN is not clean. |
| Verifiers | Every scheduled verifier has current evidence (document-set digest matches). |
| Findings | No open BLOCKER, no open MAJOR, no high or medium design-review finding. MINORs do not count. |
| No exception used | No waiver recorded in this phase, no PROCEED-PAST, no frozen finding the critic rated BLOCKER. |
| Carries | Every carry addressed to this phase is settled. |
| Questions | Every discovery question of the phase has an operator answer, or the log says there were none. |
| Proposals | Nothing is pending in `.sdlc-proposals/`. |
| Budget | The phase is inside its critic-run limit and its cost budget (Amendment 4). |

If any condition fails, nothing changes from today: the phase waits for `APPROVE`, `APPROVE … WITH-WAIVERS` or `PROCEED-PAST` with a code.

### 1.3 Who closes it, and how it is recorded

- The gate's own worker closes the phase when it finishes the review run. The agent has no command or file for it and cannot request it.
- The ledger line is a new type, `AUTO-CLOSE`, signed like every line. It carries the validator result digest, each evidence digest, the policy file's digest and the counts of findings. It can never be read as an `APPROVE`.
- `STATUS` and `phase.yaml` show the phase as `AUTO-CLOSED`. Later phases, trace checks and the release scorecard treat it as closed.

### 1.4 What the operator sees

- Every auto-close is reported in the session with the same summary an approval would show.
- `STATUS` lists the phases auto-closed since the operator's last command.
- The next approval the operator gives (a never-list phase, or any phase that was not clean) shows every phase auto-closed since the previous human approval, with its counts and MINORs file.
- `REOPEN` works on an auto-closed phase exactly as on an approved one.
- With `pause_after: n`, the gate stops after n auto-closes in a row and waits for any operator command.

### 1.5 Tests

Attack corpus additions, each of which must end without an auto-close: a failing validator, an UNKNOWN validator, stale evidence, a forged CRITIC.json, an open MAJOR, a waiver in the phase, an unanswered question, a pending proposal, a phase not in the policy, a never-list phase in the policy (ADOPT refused), a policy file written by the agent without ADOPT, and an attempt to write an `AUTO-CLOSE` line.

## 2. Orchestrated phase agents

### 2.1 Roles

| Role | Runs as | Does | May not |
|---|---|---|---|
| Orchestrator | The main session | Launches builders and verifiers, relays questions and summaries to the operator | Write a phase document or product code |
| Phase builder | A fresh agent per phase, `moadix:phase-builder` | Writes the phase's documents or code inside the phase's path map, commits, hands back | Launch agents, talk to the operator, write outside the phase's paths |
| Verifier | A fresh agent per review, as today | Reviews and writes evidence | Anything else, as today |

The orchestrator launches the verifiers, not the builder. Assumption to verify during the build: in the pinned Claude Code versions an agent launched by an agent cannot launch another. If it can, the gate must still refuse it.

### 2.2 The builder's brief

Generated and enforced by the gate, exactly like a verifier's brief (prompt replacement, one-time receipt). It contains:
- the phase's role and coverage topics, with size defaults and operator rulings;
- the list of input documents (upstream phases, carried items addressed to this phase, standing instructions);
- the earlier critic findings on this phase, when this is a fix round;
- the operator's answers so far;
- the paths it may write.

Nothing from the orchestrator's conversation reaches the builder except through these documents.

### 2.3 Questions

A builder cannot ask the operator. It hands back one round of questions (numbered, lettered options, a recommendation each). The orchestrator shows them to the operator unchanged and passes the answer back. See ruling R4 on how the gate protects the answers.

### 2.4 The loop for one phase

1. The orchestrator launches the builder with the gate's brief.
2. The builder hands back questions, or a commit.
3. Questions go to the operator; the builder is launched again with the answers.
4. On a commit, the gate runs its validators and the orchestrator launches the verifiers.
5. Findings go to a new builder launch as a fix round, within the run limit.
6. The phase ends by auto-close (section 1), or the orchestrator stops and gives the operator the summary and the exact line to send.

### 2.5 Parallel work

Phases never run in parallel. Inside one phase, the orchestrator may launch several builders when the gate can give each a write scope that does not overlap with the others: research dimensions, LLD modules, implementation tasks. The gate refuses overlapping scopes and refuses a commit outside the builder's scope.

### 2.6 When the run stops

The orchestrator stops and reports, and never retries on its own, when: the operator must answer a round, a phase is not clean, a never-list phase is ready for approval, `pause_after` is reached, a budget threshold is crossed, a validator is UNKNOWN, a builder fails twice, or the gate reports an integrity failure.

### 2.7 Mode

`orchestration: on` in `autonomy.yaml`, default off. When on, the main session's writes to `sdlc/` and to product code are refused by the path map; only builders write there.

## 3. What this does not change

- Operator commands, the one-time code, the signed ledger, and the rule that a BLOCKER cannot be waived.
- Policy-denied tools: scheduled tasks and cross-session messages stay denied. An unattended run is one session that keeps working until a stop condition; it is not a scheduled job.
- The three-run limit and the scoped third run.

## 4. Build order

1. Section 1, with its corpus additions. Prove it on a size S product.
2. Section 2, sequential builders only.
3. Section 2.5, parallel builders, last.

Each part is one increment with its own report, tests on fixtures only, a version bump and a tag.

## 5. Rulings needed from the operator

- **R1.** The never-list in 1.1: 0, 2, 6, 11, 11b, 12 and B. Add or remove any?
- **R2.** Does a medium design-review finding stop an auto-close (proposed), or only a high one?
- **R3.** `pause_after`: a default value, or off unless set?
- **R4.** Protecting answers to builder questions. Proposed: the operator answers with a command the gate records (`ANSWER <phase> <text> <code>` is too heavy for every round, so the proposal is a code-free `ANSWER <phase> <round> <text>` that the gate logs with its hash, and the builder's brief quotes the gate's copy). The alternative is to trust the orchestrator to relay answers, as the single agent does today.
- **R5.** May the orchestrator be allowed to continue into the next phase after an operator approval without a new message from the operator (proposed: yes), or should every approval end the turn?
