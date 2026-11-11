# MOADIX changes: code-review

- Upstream: https://github.com/mattpocock/skills
- Commit: 4ae2317ddb22b046e26455e4f9c9b3aaaf62212d
- Path: skills/engineering/code-review
- Licence: MIT, Copyright (c) 2026 Matt Pocock (root LICENSE, copied here as `LICENSE`)
- Vendored: 2026-11-11, for MOADIX phase 7 (method of the code-reviewer verifier, which writes findings only)

Files copied: `SKILL.md`, `agents/openai.yaml` (unchanged). No test suite upstream.

## Changes

### 1. SKILL.md, Overview: sequential fallback when sub-agents cannot be started
- Original: "… then this skill aggregates their findings. Start every sub-agent with a fresh context window."
- Replacement: same text, followed by "If you cannot start sub-agents (a MOADIX verifier cannot), run the two axes one after the other instead: finish and write down the Standards report before you read the spec."
- Category: adaptation (MOADIX sets `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`, so the verifier cannot spawn the two parallel sub-agents)

### 2. SKILL.md, Overview: findings-only statement (added)
- Original: (none)
- Replacement: "This review reports findings only. It gives no overall verdict and never states that the change is acceptable, ready or done; the operator decides that (MOADIX gate)."
- Category: self-approve (makes explicit that the review output is findings, not an approval verdict)

### 3. SKILL.md, Overview: setup skill reference
- Original: "The issue tracker should have been provided to you. If not, tell the user to run `/setup-matt-pocock-skills`."
- Replacement: "The issue tracker should have been provided to you. If not, ask the operator where this product's issues and specs live."
- Category: auto-advance (routes to a skill that is not vendored and not in the phase manifest)

### 4. SKILL.md, step 5 Aggregate: stop after the summary (added)
- Original: "End with a one-line summary: total findings per axis, and the worst issue _within each axis_ (if any). Don't pick a single winner across axes: …"
- Replacement: same text, followed by "Stop there. Do not add a verdict, a recommendation to accept the change, or a next step; the operator reads the findings and decides."
- Category: self-approve

Upstream had no "approve"/"LGTM" wording; the "Standards pass, Spec fail" lines in _Why two axes_ are kept verbatim as an explanation of why the axes are separate, not as a verdict the review emits.

## Grep allowlist (MOADIX-GREP-ALLOW.tsv)
- `merge-base` (description and step 1): git term for the diff base.
- "Do **not** merge or rerank findings" (step 5): forbids combining the two reports.
