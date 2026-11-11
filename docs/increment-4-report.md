# Increment 4: verifiers

2026-11-11. Built per DESIGN.md §5 (fresh-context verification) and Amendment 1. Nothing was installed or pushed: the live gate still runs increment 3 until the operator reruns `managed/install.sh`, and the agents reach Claude Code only once this repo is pushed and the plugin updated.

## 1. The updatedInput measurement

**The question.** Does a managed PreToolUse hook's `updatedInput` actually replace an Agent call's prompt on Claude Code 2.1.322 (`~/.local/bin/claude -> versions/2.1.322`)?

**Not measured live, and it could not be from this session:**
- Hooks are managed-only, so a probe hook cannot be added below the managed policy.
- Changing the managed policy needs sudo.
- Nested `claude` is denied by invariant 4.

Running the versioned binary by its path would have dodged that last rule, so I didn't.

**What the 2.1.322 code shows (static reading, not a measurement):**

| Path | What it does with `updatedInput` |
|---|---|
| Managed hook pass (`managedHooksOnly: true`) | Takes the pass's `updatedInput` and rebuilds the tool call from it (`H_t(tool, tool_use_id, w)`) before the rest of the permission flow runs. This is the path MOADIX's hooks take. |
| Hooks that ran on another machine, or answers that came over the network | A changed input is refused and the call becomes a deny: "A settings hook changed this tool call's input. That is allowed only for calls that run in the same environment as the hook…". A local command hook does not take this path. |
| Hook input in a subagent | Carries `agent_id` and `agent_type` (schema text: "Present only when the hook fires from within a subagent"). The verifier restrictions rely on this. |

So the code says it should work for MOADIX's local managed hook. That is still a reading, not a measurement.

**How the build stays safe either way.** The replacement prompt carries a one-time **receipt** (128 random bits). The gate stores only its sha256, and evidence counts only if it quotes the receipt.

| What Claude Code does with the replacement | Result |
|---|---|
| Applies it | The verifier sees the brief and the receipt. |
| Refuses it | The launch is denied. |
| Ignores it silently | The verifier never sees the receipt, so no evidence can pass and APPROVE of phases 6, 7 and 8 refuses. |

Nothing in this increment passes on an unproven replacement.

**Live measurement (operator, once).** `moadix:replacement-probe` is a probe agent. The hook always replaces its prompt with `PROBE-REPLACED <nonce>` and logs the nonce, plus the `agent_type` the probe's own tool call reports, to `~/Library/Logs/moadix/probe.log`. It produces no schedule and no evidence. The steps are in `docs/INSTALL.md` → "Measuring the verifier prompt replacement".

If the reply is anything other than `PROBE-REPLACED` with the matching nonce, stop and report it before increment 5.

## 2. What was built

| Part | Where | What |
|---|---|---|
| Roles | `gate/config/verifiers.yaml` | design-reviewer (6, Impeccable), code-reviewer (7, code-review), typescript-reviewer (7, only when the range changes TS/JS), ac-coverage-critic (8, pr-test-analyzer, must map every AC). Findings at `critical`/`high` fail; the gate decides, not the verifier. |
| Brief generator | `gate/verify.py` `build_brief` | Built from artifacts only:<br>• diff range: base = the commit the previous phase was approved on (from the ledger), head = HEAD<br>• the changed files in the role's scope, which are the required evidence paths<br>• story and AC IDs with their `sdlc/02-*.md` lines<br>• the `knowledge.md` sections that mention them<br>• method skill, evidence format<br>Deterministic: two different builder prompts give the same brief hash. The gate writes `brief.md` and `schedule.json` (base, head, required paths, brief sha256, receipt sha256) under `.sdlc/cache/verify/<phase>/<role>/`. |
| Agent-tool hook | `gate/pretool.py`, `verify.on_agent_launch` | A main-thread `Agent`/`Task` call for `moadix:<role>`:<br>• **replaced**: `permissionDecision: allow` + `updatedInput`, with the prompt set to brief + brief hash + receipt<br>• **refused** when the role is not scheduled for the current phase (wrong phase, or `when: changed` and nothing in scope), the tree is dirty, the gate state fails integrity, or it is outside a product<br>• a bare or foreign `code-reviewer` is refused in a product<br>Any subagent in a product calling Agent is refused (depth capped at 1, on top of `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`). |
| Verifier restrictions | `verify.restrict` (managed hook; plugin agents ignore their own hooks and permissionMode) | A verifier, by `agent_type` (namespaced or bare), may use only:<br>• Read, Grep, Glob, TodoWrite<br>• SubagentHandback, to return its result (exact name; added in 0.2.1 after the live probe lost its reply)<br>• Bash, read-only: allowlisted verbs, read-only git subcommands, no redirects, no `sed -i`, `find -delete`, `--output=`, interpreters or opaque code<br>• Write/Edit only inside `.sdlc/cache/verify/<phase>/<role>/evidence/`<br>• Skill: its method skill only<br>No Agent, MCP, WebFetch or WebSearch. |
| Agents | `agents/*.md` | The four verifiers (`tools: Read, Grep, Glob, Bash, Write, Skill`), each adapting its vendored method: no sub-agents, base commit from the brief, read-only, findings only. Plus `replacement-probe` (`tools: Read`). |
| Evidence check | `verify.check_role`, `gate/v1/check_verifiers.py` | Missing / stale / failing / ok. Checks:<br>• role<br>• `source_commit` = HEAD = the brief's head<br>• brief hash = the gate's, and `brief.md` still matches it<br>• receipt<br>• no verdict-like keys at any depth<br>• every required path in `reviewed`<br>• every citation resolves at HEAD (`git show HEAD:path`, line in range)<br>• severity vocabulary<br>• AC critic: every AC mapped, each with ≥1 resolving test<br>A new launch supersedes old evidence. |
| Validators | `registry.yaml` | `check-verifiers-6/7/8`. The validator cache key now includes a digest of `.sdlc/cache/verify/<phase>/`, so new evidence makes the cached result stale and the Stop hook reruns it. APPROVE then reads it as for any validator. |

**Where evidence lives, and why.** Evidence goes in `.sdlc/cache/verify/…`:
- It is gitignored, so it can't dirty the tree or move HEAD. Committing it would make the evidence stale against its own commit.
- The builder's tools are kept out by the `.sdlc/` rule, and every Bash process by the sandbox.

This is a narrow exception to invariant 1: one directory, written only by that verifier's Write/Edit tool.

## 3. Tests

| Suite | Where | Result |
|---|---|---|
| Increment-4 suite `tests/verifiers/run.py` | this session, stub checker | **89/89** (`docs/evidence/increment-4-suite.txt`) |
| … brief | | 13/13:<br>• builder prompt replaced<br>• no builder text reaches the verifier<br>• range, required paths, story/AC IDs with lines, relevant knowledge only<br>• `brief.md` hash = schedule = prompt<br>• receipt not on disk<br>• same brief for a different builder prompt<br>• Task alias<br>• non-verifier untouched |
| … schedule | | 10/10:<br>• phase-8 and phase-6 verifiers refused in 7<br>• TS reviewer scheduled only when TS changed<br>• bare and foreign names refused<br>• dirty tree, integrity failure and outside-product refused<br>• outside a product a foreign bare name is left alone |
| … restrict | | 32/32:<br>• Write allowed only to its own evidence file; refused for source, README, the gate's `schedule.json`/`brief.md`, another role's dir, `../` escape, outside the repo<br>• no NotebookEdit, Agent, Task, WebFetch or MCP<br>• only its method skill<br>• read-only Bash allowed (`git diff`, `grep -i`)<br>• writing Bash refused (redirects, `git commit`/`checkout`, `sed -i`, `find -delete`, `python3 -c`, `npm test`, `git diff --output`)<br>• bare agent type restricted too<br>• no subagent nests<br>• builder cannot write evidence by tool or Bash<br>• sandbox and depth env checked<br>• agent tool lists checked |
| … evidence | | 21/21. Each of these fails:<br>• wrong commit<br>• wrong brief hash<br>• wrong receipt<br>• dead citation (missing file, line past end)<br>• no citations<br>• verdict field (top level and nested)<br>• unreviewed required path<br>• high-severity finding<br>• not JSON<br>• missing<br>• tampered `brief.md`<br>• superseded launch<br>• new commit (stale)<br>• AC with no test, AC left out, dead test citation<br>Controls pass. |
| … approve | | 7/7. APPROVE 7 is refused:<br>• with no verifier launched<br>• with one of two<br>• with a critical finding<br>• before the gate re-ran on new evidence<br>• after a new commit<br>It is recorded with good evidence from both, and the ledger line shows `check-verifiers-7: pass`. |
| … probe | | 5/5:<br>• prompt replaced in and outside a product<br>• nonce logged<br>• `agent_type` logged<br>• no other tools<br>• no schedule or evidence |
| Increment-2 suite | this session | **290/290** (`docs/evidence/increment-2-suite-after-increment-4.txt`). The registry-count check now counts the 21 v1 ports and the 3 new verifier checks separately. |
| Increment-3 suite | this session | **43/43** |
| check-static (ruff, mypy, shellcheck), check-hardcoded-state | this session | clean (`docs/evidence/increment-4-static.txt`). Three hardcoded-state exemptions were added for the phase labels in `verifiers.yaml`, a policy decision like `check_threat_model`'s. ruff/mypy ran with uv's tool and cache directories in `$TMPDIR`, because the sandbox blocks `~/.local/share/uv`. |
| Live: updatedInput on a real Agent call | **not run** (needs the installed gate and plugin) | section 1 |
| Real corpus | **not run** (Keychain; Terminal only) | unchanged from increment 3 |

## 4. Known gaps (stated plainly)

- **The live measurement is pending** (section 1). Until it is done, verifier evidence passing in a real session is unproven; the fixture suite proves the gate's side only.
- **How Claude Code spells a plugin agent's `agent_type` in hook input is unmeasured.** It could be `moadix:code-reviewer` or `code-reviewer`. The restrictions accept both; the probe log will show which.
- **Evidence is per machine.** `.sdlc/cache/` is gitignored. The APPROVE line records the validator result digest, and the check-verifiers output in it carries each evidence file's sha256 prefix, but the evidence files themselves are not committed. Archiving them into `.sdlc/evidence/` at APPROVE is a later step if you want them in the repo.
- **Docker and Playwright run outside the sandbox** and could write into the evidence directory (accepted risk, Amendment 1 §4). They cannot produce the receipt, so such evidence fails.
- **The receipt's secrecy assumes** the builder never sees the replaced prompt, the hook's output or the verifier's transcript (transcripts are read-denied). The verifier is told not to repeat the receipt in its reply. Even if it did, the builder cannot write the evidence directory.
- **Scope of stories.** The brief lists every story in `sdlc/02-*.md`, not only those the range implements: there is no task→commit mapping yet.
- **Verifiers cannot run tools.** Bash is read-only, so the TypeScript reviewer does not run `tsc` and the AC critic does not run tests; they reason from code. The gate-run tools arrive in increment 5.
- **No waiver for a verifier finding.** A `critical`/`high` finding blocks APPROVE; the only way past is to fix it and verify again, or `PROCEED-PAST`.
- **Phase 6 now has a validator.** APPROVE 6 needs design-reviewer evidence, where before phase 6 had no validator at all.
- **Deferred to increment 5:** the security finding source (Claude Security plugin, SARIF) and the live verifier (Playwright MCP).

## 5. Install steps (operator, in Terminal)

1. Close every Claude Code session.
2. `cd ~/moadix && git log --oneline -1` (note the commit), then `git push`. The agents ship in the plugin, which installs from GitHub.
3. `managed/install.sh`. It asks for your password once and re-copies the gate: new `verify.py`, `v1/check_verifiers.py` and `config/verifiers.yaml`, plus the updated registry and exemptions. The policy is unchanged, because the PreToolUse matcher `*` already covers the Agent tool. Key and ledgers are kept.
4. Open Claude Code and run `/plugin marketplace update moadix`, then `/reload-plugins`. Expect the agent count to rise by 5 (four verifiers and the probe); skills stay at 19.
5. Do the measurement in `docs/INSTALL.md` → "Measuring the verifier prompt replacement" and send me the reply line and `tail -5 ~/Library/Logs/moadix/probe.log`.
6. Optional: `/usr/bin/python3 tests/verifiers/run.py` (expect `89 checks, 89 passed, 0 failed`) and the corpus (`tests/corpus/run.py`, expect `128 checks, 128 passed, 0 failed`).
