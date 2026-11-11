# MOADIX changes: pr-test-analyzer

- Upstream: https://github.com/anthropics/claude-plugins-official
- Commit: 43fd1f9db0941b2b83cb62268e35970d4a67c202
- Path: `plugins/pr-review-toolkit/agents/pr-test-analyzer.md` (vendored as `SKILL.md`)
- Licence: Apache-2.0 (`plugins/pr-review-toolkit/LICENSE` copied as `LICENSE`; upstream has no NOTICE file)
- Vendored: 2026-11-11. MOADIX phase 8 (Testing: AC-coverage critic).

`SKILL.md` carries the Apache-2.0 §4(b) change notice right after the frontmatter.

## Changes

| # | File | Original (quoted) | Replacement | Category |
|---|---|---|---|---|
| 1 | SKILL.md | file `agents/pr-test-analyzer.md` (a Claude Code agent definition) | `skills/pr-test-analyzer/SKILL.md`; the agent prompt is the skill body, unchanged except as below | adaptation |
| 2 | SKILL.md (frontmatter) | `model: inherit` / `color: cyan` | removed (agent-only keys; `name` and `description` kept, `name` already equals the directory name) | adaptation |
| 3 | SKILL.md (frontmatter `description`) | "… and a final pre-merge double-check before marking a PR ready." | "… and a final double-check of test coverage before the work is handed over for review." | mark-done |
| 4 | SKILL.md ("When to invoke") | "- **Pre-ready double-check.** Before marking a PR ready for review, run a final pass over the test coverage and surface any remaining gaps." | "- **Pre-handoff double-check.** Before the work is handed over for review, run a final pass over the test coverage and surface any remaining gaps." | mark-done |
| 5 | SKILL.md ("Output Format") | (no line; the output list ended at "5. **Positive Observations** …") | added: "Report findings only. Give no overall verdict on whether the tests are sufficient or the work can go ahead (no verdict; the operator decides, MOADIX gate)." | self-approve |
| 6 | SKILL.md | (none) | Apache change-notice HTML comment after the closing `---` | adaptation |

Wording such as "Use this agent" and "the agent body" in `description` is kept verbatim.

## Grep allowlist

None needed (no remaining hits).
