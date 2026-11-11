# Harness v2 Design

2026-11-10 · Moad

v2 turns the harness into a Claude Code plugin whose gates are anchored in managed settings, so every operator action becomes a typed chat command such as APPROVE 1, recorded by the gate itself, instead of a terminal command, and each product keeps its own state in its own repo. Frozen on 2026-11-10 after an independent review. Changes from here go through a proposal.

## Amendment 1 (2026-11-11) — overrides the sections below where they differ
1. Approval code = authenticator code. At install, MOADIX creates a TOTP secret. The operator scans it into an authenticator app (Microsoft Authenticator chosen). The Mac keeps the secret in the Keychain, readable only by MOADIX's signed checker. Approving is one message, from the Mac or the phone: `APPROVE 1 482913`. Codes are single use; 3 wrong codes lock approvals until a code is entered at the Mac. This replaces the two-step code shown in the hook's block reason.
2. No silent blocks. The phone app does not display hook block messages (measured), so operator commands are never blocked. The hook records the action or refuses it, and tells the agent the outcome through added context. The agent relays it; the ledger stays the truth.
3. Signed ledger. Each ledger line carries an HMAC made with a second Keychain-locked key. A line written by anything else fails verification on STATUS.
4. Accepted risk, narrowed. Docker and Playwright run outside the sandbox (measured: Docker can write into sandbox-denied paths; Chromium crashes inside the sandbox). Code they run can still damage files, but cannot produce a valid approval code or a valid ledger signature, so forged approvals are detected.
5. Sandbox config adds a network allowlist (package registries, browser downloads) and write access to the npm and Playwright caches; Playwright and Docker are listed in excludedCommands.
6. Distribution: public marketplace. Licence obligations: rename the BMAD retrospective skill (BMad trademark), ship Impeccable's NOTICE, add change notices inside modified Apache-2.0 files, take pr-review-toolkit from anthropics/claude-plugins-official, add a not-affiliated line for awesome-design-md, and source the threat-model skill from anthropics/defending-code-reference-harness.
7. Measured and closed: Claude Code 2.1.322 supports onFailure "block"; no MDM or server-managed policy on this Mac; UserPromptSubmit fires for messages sent from the phone; a hook block reason is not shown to the agent.
Still to measure in increment 1: the Keychain lock (another process asking for the secret must get a prompt, not the secret), and that the agent's turn after an approval cannot see the secret.

## Goals and non-goals

**Goals**

1. **Zero operator terminal commands.** The operator types APPROVE 1, REOPEN 4 and the like in chat. A hook that fires only on human-submitted messages records it, and the agent then continues to the next phase on its own.
2. **Fresh-context verification.** Every verifying step runs in a subagent that did not build the thing, with a brief the gate writes.
3. **Per-phase skill sets.** Each phase loads only its selected skills (see Harness v2 — Skill Options per Phase, Final selection).
4. **Packaged as a plugin with per-project state.** One install; each product is its own repo with its own state; several products run in parallel sessions.
5. **Keep v1's central property:** the agent can never mark its own work done.

**Non-goals**

- Multi-user or team approval flows. One operator per machine.
- A hosted service. MOADIX is open source on GitHub and runs locally.
- Rewriting the validators. They are ported, not redesigned, except where a v1 defect is listed in section 7.

## Trust model

The gates are anchored in **managed settings**, a root-owned file the agent cannot write. Discovery measured that the user cannot write there without sudo, and that a cached sudo password does not reach a later Bash tool call. Everything below managed scope is treated as agent-writable.

**Managed settings carry:**

| Setting | Effect |
| --- | --- |
| `enabledPlugins` (forced on) | MOADIX cannot be disabled from user, project or local settings; its hooks still run under `allowManagedHooksOnly` |
| `allowManagedHooksOnly` | No hook the agent writes elsewhere counts |
| `allowManagedPermissionRulesOnly` | No allow rule below managed scope can pre-approve anything |
| `disableBypassPermissionsMode: "disable"` | `--dangerously-skip-permissions` is rejected |
| `strictKnownMarketplaces` / `disableSideloadFlags` | No other plugin can be added |
| `sandbox` enabled, `allowUnsandboxedCommands: false`, `failIfUnavailable: true` | OS-level limits on every Bash command and every process it starts, including tests and builds |
| Sandbox `denyWrite`: `.sdlc/`, `.claude/`, `~/.claude/`, the ledger-anchor directory | No script, test or build can rewrite gate state, settings or the plugin; hooks run outside the sandbox and can still write |
| Sandbox `denyRead` + `permissions.deny` Read on `~/.claude/projects` | The agent cannot read transcripts, where blocked prompts and their codes are stored |
| `permissions.deny`: `CronCreate`, `CronDelete`, `ScheduleWakeup`, `SendMessage`, `ListAgents`; `crossSessionInbound: "refuse"`; `env.CLAUDE_CODE_DISABLE_CRON=1` | The agent cannot start a turn that looks like a typed command |
| `env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` | Verifiers cannot start further agents |
| `requiredMinimumVersion` ≥ 2.1.295 | `onFailure: "block"` is available on every gate hook |

**Invariants the hooks enforce** (each one gets a fixture test):

1. Every write to `.sdlc/` is denied to the agent's tools and, through the sandbox, to every process it runs. Only the gate's hooks write it.
2. Operator actions are recorded only by the `UserPromptSubmit` hook, and only with a valid one-time code.
3. The agent can request review but has no command that changes phase state.
4. `sudo`, plugin install/enable/disable, `claude mcp add`, nested `claude` sessions, scheduled tasks, cross-session messages and edits to any settings or plugin path are denied.
5. Skill invocations outside the current phase's set are denied (section 6).
6. Writes outside the current phase's allowed paths are denied (v1's path map, kept).
7. Every gate hook fails closed: `onFailure: "block"` and an explicit timeout.
8. The ledger's latest hash is mirrored to an anchor directory outside the product repo that the agent cannot write. STATUS compares the two, so a rewritten chain is detected.

**Residual risks, stated plainly:**

- **Prompt fatigue.** Approving on autopilot is the remaining weak point. Mitigation: REVIEW \<phase> prints the gate's own summary straight to you, untouched by the agent, before you type APPROVE.
- **Admin install.** Managed settings need `sudo` once per machine. Without it, MOADIX refuses to run and says why.
- **Auto mode.** Kept. Approvals no longer depend on permission prompts, so the auto-mode classifier cannot approve anything; at most it denies a call, which fails closed.
- **Docker.** Phases 7–10 need Docker, and a container with a host bind mount can write anywhere the user can, outside the sandbox. Mitigation: the hook denies docker and compose commands that mount paths outside the product repo, and the ledger anchor (invariant 8) makes any rewrite of gate state detectable. Measured in increment 1.
- **Policy not in effect.** If an MDM profile or organization server-managed settings exist, Claude Code uses those and ignores MOADIX's file. The installer checks that the active setting source is the file, and every session starts with a canary write to `.sdlc/` that must fail; otherwise MOADIX refuses to run.

## Layout

The harness and the products separate. The harness becomes one plugin repo; each product becomes its own repo with a `.sdlc/` directory. Parallel products are simply separate repos in separate Claude Code sessions, so the worktree question disappears.

**Plugin repo (`moadix`), installed once, pinned by version:**

- `.claude-plugin/plugin.json`
- `hooks/hooks.json` + the gate core (ported `gatecore.py`, validators)
- `commands/` — `/sdlc:status`, `/sdlc:request-review`, `/sdlc:approve`, `/sdlc:reopen`, `/sdlc:waive`, `/sdlc:unwaive`, `/sdlc:proceed-past`, `/sdlc:park`, `/sdlc:init`
- `agents/` — verifier agents with restricted tools
- `skills/` — the selected skills, vendored with attribution and pinned commits
- `templates/`, `CONSTITUTION.md`, `VERIFICATION.md`
- BMAD 6.12.4, pinned, wrap-don't-modify
- `managed/` — the managed-settings fragment and the one-time installer

**Product repo `.sdlc/`, owned by the gate:**

| File | Replaces in v1 | Notes |
| --- | --- | --- |
| `product.yaml` | phase-paths governed\_root, product-app.yaml, product-tests.yaml | One file: platform ruling, size, app run command, test targets, path map |
| `phase.yaml` | harness/status/phase.yaml | Same schema, one product only |
| `ledger.jsonl` | approvals and waivers in phase.yaml | Append-only, hash-chained; every operator action is one line |
| `evidence/` | scattered evidence paths | Index of evidence with sha256, source sha, produced\_for |
| `knowledge.md` | path-keyed agent memory, the addendum | Operational facts about the running product, read by verification |
| `untested.yaml` | nothing (F59) | Acceptance criteria known to be untested; 10a must read it |

State changes only through gate commands (the GSD pattern), and `/sdlc:status` runs a drift check that recomputes the hash chain and compares `phase.yaml` against the ledger.

## Operator actions: typed commands

The agent moves through each phase on its own and stops only at a gate. The human approves by typing a command in chat. `APPROVE <phase_number>` is the official approval: `APPROVE 1` approves phase 1 and authorizes MOADIX to proceed to phase 2.

**Why this is safe:** a `UserPromptSubmit` hook does **not** fire only on typed messages. It also fires on turns Claude Code starts itself (scheduled tasks, `/loop`, background subagents reporting back, messages from other sessions), and its input has no field saying where a prompt came from. So a matching message alone proves nothing. Two layers close this: managed settings deny every way the agent can start a turn (section 2), and every state-changing command needs a **one-time code that only you ever see**.

**Flow:**

1. The agent finishes phase 1 and says "Phase 1 ready for review."
2. You type `APPROVE 1`.
3. The hook runs the validators on cached results (so it stays well under its timeout) and blocks the message. The block reason is shown to you and is not added to the agent's context: the gate's own summary (validator results, evidence count, source commit, open waivers) and a one-time code, for example `To approve, type: APPROVE 1 K7Q2`.
4. You type `APPROVE 1 K7Q2`.
5. The hook checks the code (single use, expires after 10 minutes, bound to phase 1 and that source commit), appends the ledger line, updates `phase.yaml`, and tells the agent "Phase 1 approved; proceed to phase 2".
6. The agent continues into phase 2 without further input.

The agent never sees the code: it is not in the agent's context, and the transcript files where Claude Code stores blocked prompts are read-denied to the agent.

**The full command set** (each must be the whole message, nothing else):

| Command | Needs a code | Effect |
| --- | --- | --- |
| `APPROVE <phase>` | Yes | Approve and advance |
| `REOPEN <phase> <reason>` | Yes | Reopen a phase |
| `WAIVE <id> owner=<x> expiry=<date> reason=<text>` | Yes | Record a waiver (high severity stays unwaivable) |
| `UNWAIVE <id>` | Yes | Revoke a waiver |
| `PROCEED-PAST <phase> <reason>` | Yes | Progression waiver |
| `PARK` | Yes | Stop the stack, measure live counts, record them, tag |
| `REVIEW <phase>` | No | Gate-printed summary only |
| `STATUS` | No | Gate-printed state of every phase |

Every state-changing command works the same way: type it once to see the summary and get a code, then type it again with the code.

**Rules:**

- **Exact message only.** `APPROVE 1` inside a pasted report, a quote or a longer message does not count. Agent reports are pasted into chat often.
- **One-time code for every state change.** Single use, 10-minute expiry, bound to the action and the source commit, shown only in the hook's block reason.
- **No agent-started turns.** Scheduled tasks, wakeups and cross-session messages are denied in managed settings, and the session's messaging socket is outside the sandbox (section 2).
- **Fail closed.** Every gate hook sets `onFailure: "block"` and an explicit timeout. A broken Python, a crash or a timeout blocks the action instead of letting it through.

## Fresh-context verification

A verifier never sees the builder's framing. The gate writes its brief, the verifier writes evidence, and the gate decides.

1. **The gate generates the brief** from artifacts, never from the builder's summary: story and acceptance-criteria IDs, the diff range (base and head commits), the required evidence paths, and the relevant `knowledge.md` entries.
2. **The gate enforces the brief.** A managed PreToolUse hook on the `Agent` tool replaces a verifier's prompt with the gate's brief (`updatedInput`) and refuses any verifier the gate didn't schedule. The gate, not the verifier, computes the brief hash.
3. **The verifier is a plugin agent with a restricted tool list** (no Write outside its evidence directory, no `.sdlc/`, no Agent tool, no network tools for browser verifiers). Plugin agents ignore their own `hooks` and `permissionMode`, so restriction comes from the managed hooks, which apply to every agent.
4. **The verifier writes an evidence file** stamped with the source commit and the brief's hash. It never writes a verdict field the gate reads as approval.
5. **The gate checks the evidence** (citations resolve, commit matches, required paths present) and includes the result in the REVIEW summary.

**Verifier roles:**

| Role | Phase | Source of its method |
| --- | --- | --- |
| Code reviewer (spec + standards) | 7 | Pocock code-review |
| TypeScript reviewer | 7 | ECC typescript-reviewer |
| AC-coverage critic | 8 | pr-test-analyzer |
| Security finding source | 9 | Claude Security plugin (SARIF) |
| Live verifier | 10a | Playwright MCP, network tools withheld |
| Design reviewer | 6 | Impeccable critique/audit |

A verifier's own "ready to proceed" or "approve" language is stripped from the vendored skill text.

## Per-phase skills

The selection is fixed in Harness v2 — Skill Options per Phase (Final selection). This section is how it is enforced.

- **Vendored, not installed.** Each skill is copied into `skills/` with its licence, source URL and pinned commit in `skills/SOURCES.yaml`. Self-approve, auto-advance and commit steps are removed, and each removal is recorded beside the skill.
- **A phase manifest** in the plugin maps each phase to its allowed skills, MCP servers and deterministic tools.
- **The hook enforces it.** A `Skill` tool call or an MCP tool call outside the current phase's manifest is denied with the phase named in the reason.
- **Deterministic tools are run by the gate,** not the agent: Redocly in 5, gitleaks/OSV/Trivy/Semgrep in 9, k6 thresholds in 10c. The agent can run them for feedback, but only the gate's run counts.
- **Context cost is budgeted.** The manifest lists each skill's size; `/sdlc:status` shows the always-on cost per phase.
- **Upgrading a vendored skill** is a proposal with a diff against the pinned version, approved like any other change.

## From v1

**Kept as is:** the 16 phases; CONSTITUTION.md and VERIFICATION.md; the validators; the two-axis scorecard and exit-code contract; waiver governance and the progression waiver; provenance stamping; the four-tier path map (re-rooted at the product repo).

**Replaced:** `gate.sh` terminal commands → typed chat commands (APPROVE, REOPEN, WAIVE…) recorded by the UserPromptSubmit hook; the four control files → `.sdlc/product.yaml` + `phase.yaml`; repo-local hooks → managed plugin hooks; product folders inside the harness repo → separate product repos.

**v1 defects fixed in v2:**

| Defect | Fix |
| --- | --- |
| Harness tests read or start the live product (test\_sandbox incident; W02, P59c, PW05) | Every harness test builds its own fixture; a hook denies harness tests touching a product's compose project |
| 41 of 43 operator touchpoints rely on convention | All are typed commands recorded only from human-sent messages (section 4) |
| Settings files were agent-writable; settings reload live | Managed settings (section 2) |
| An acceptance criterion can pass phase 8 untested (F59) | Coverage per acceptance criterion + `untested.yaml` read by 10a |
| Denial reasons name the wrong class of path | Each path class has its own reason text, tested |
| Gate false positives: `git stash list`, `*.pem` in a read-only find, bare `.`, `tar -C`, `git checkout` in a scratch copy | Command classifier rewritten against a fixture corpus of read-only commands |
| `sudo` treated as a transparent prefix | Denied |
| Operational knowledge lived only in path-keyed agent memory | `.sdlc/knowledge.md`, read by verification |
| Parking didn't stop the product; counts were hand-written | `/sdlc:park` procedure (section 4) |
| Checksums pinned to an unpinned "latest" download | Provisioning records source version and URL with the checksum |
| Waiver cites an uncommitted, regenerable file | Waivers cite evidence by sha256 in the evidence index |
| 10a instrument copies cookies into transcripts | Network tools withheld from verifiers; Playwright storage-state |
| check-seam duplicate globs; check-static S506 false positive; check-hardcoded-state substring match | Fixed during the port |

## Build increments

v1 stays untouched on `master` throughout; v2 is built in a new plugin repo. Each increment ends with its fixture tests green and a short report.

1. **Trust core.** Plugin skeleton; managed settings with the sandbox, deny lists and minimum version; installer with the policy-in-effect check; the hook invariants (section 2), all fail-closed; `.sdlc/` state with the hash-chained ledger and its anchor; the typed-command hook with one-time codes. Proof: an attack corpus showing that no agent output, tool result, file, pasted report, scheduled task, cross-session message, background subagent, script, test run or Docker mount can record an operator action or rewrite gate state.
2. **Gate port.** v1 validators and gatecore moved into the plugin, re-rooted at the product repo; the command classifier rewritten against a read-only-command corpus; every harness test on fixtures only.
3. **Skills.** Vendor the Final selection, strip self-approve steps, write the phase manifest, enforce it in the hook.
4. **Verifiers.** Brief generator, restricted verifier agents, evidence stamping.
5. **New tools.** Redocly, gitleaks, OSV, Trivy, Semgrep, Playwright MCP, k6, release-please, dotenvx, wired as gate-run checks.
6. **Toy run, gates only.** The toy product through phases 0–12 under v2. About an hour; it exercises the new gates before they touch real data.
7. **onlineMarket migration (last).**

**onlineMarket migration:**

1. Restore the database from `~/Backups/onlinemarket-2026-11-10/` (pending since the test\_sandbox incident) and verify 7,835 dead letters.
2. Extract `onlineMarket/` into its own repo with full history (`git filter-repo` or `subtree split`).
3. Generate `.sdlc/` from v1's `phase.yaml`, waivers and evidence; carry the ledger forward with every v1 operator action as an imported, marked line.
4. Move the addendum's operational facts into `.sdlc/knowledge.md`.
5. **Parity check:** run every v1 validator and its v2 port at the same commit; verdicts must match exactly. Any difference stops the migration.
6. Continue from phase 10c under v2.

## Open questions to verify before building

These are measured in increment 1 before anything depends on them. If any answer is "no", the design changes here first.

1. **Phone approvals:** does `UserPromptSubmit` fire for messages from the mobile app and Remote Control, and does the mobile app show a hook's block reason? The one-time code depends on both. If not, approvals from the phone need another channel.
2. **Docker escape:** which docker and compose commands can mount outside the repo, and does the hook catch them?
3. **Sandbox vs. product work:** do tests, builds, Docker and Playwright still run under the sandbox and its deny lists?
4. **Private Git marketplace:** can managed `enabledPlugins` force-enable a plugin from one? Not stated in the docs.

Settled by the docs: force-enabled plugin hooks run under `allowManagedHooksOnly`; `permission_mode` includes `dontAsk`; a file-based managed policy reloads when the file changes.

**Decisions for you:**

- Plugin repo name: `moadix` (decided). Plugin commands are therefore namespaced /moadix:\*; /sdlc:\* in this doc means the same commands.
- Every product in its own repo, with the plugin running per repo: yes (decided).
- Without the one-time setup, MOADIX refuses to run (decided). No advisory mode. MOADIX is released as open source and installed like any other plugin, plus that setup step. Its licence, and whether BMAD and every vendored skill's licence allow redistribution inside it, are checked in increment 1.
- Platforms: macOS and Linux, including rented VMs. Windows only through WSL2; native Windows is checked later (decided).
- Machine-wide effect: managed settings apply to every Claude Code session on the machine. MOADIX is installed on Moad's personal Mac. In repos without `.sdlc/` it stays passive, but the sandbox, the scheduled-task ban and managed-hooks-only still apply. The README says so plainly and suggests a VM to anyone who uses Claude Code for other work (decided).
