# MOADIX changes: threat-model

- Upstream: https://github.com/anthropics/defending-code-reference-harness
- Commit: d3bea6b5793b5f3d59a75ebe69a58efa88383145
- Path: `.claude/skills/threat-model/` (SKILL.md, README.md, bootstrap.md, interview.md, schema.md)
- Licence: Apache-2.0, `Copyright 2026 Anthropic PBC` (repo-root LICENSE copied as `LICENSE`; upstream has no NOTICE file)
- Vendored: 2026-11-11. MOADIX phase 4 (Threat Model).

## Changes

None. All five files are byte-identical to upstream, so no Apache change notice is needed in them.

Reviewed for self-approve, mark-done, auto-advance and commit/merge/ship instructions: none found. Kept on purpose:

- SKILL.md `bootstrap-then-interview` step 3 ("Immediately continue into interview mode") chains the skill's own two modes after the owner opts in at step 1. It is not an advance to another phase or skill.
- interview.md Q4 "Did we do a good job?" is a question asked of the application owner (a human checkpoint), not a self-assessment that closes the phase.
- `status` values in schema.md (`mitigated`, `risk_accepted`, ...) and `"status": "complete"` in the bootstrap checkpoint file are threat-row and checkpoint data, not phase status.

## Grep allowlist

See `MOADIX-GREP-ALLOW.tsv`: 6 rows, all descriptive (checkpoint key merging, deploy-time config as analysis input, the target system's deployment in context prose, "merge" of subagent table rows, a threat-analysis question about the target's automated approval/merge paths, git commit hashes as evidence).

## Known gaps (not changed)

- bootstrap.md and SKILL.md `allowed-tools` call `python3 .claude/skills/_lib/checkpoint.py`, a shared upstream helper outside this skill directory. It is not vendored; under MOADIX the path does not exist.
- Re-read notes cite `.claude/skills/threat-model/*.md` (upstream install path).
- `allowed-tools` includes `Bash(git:*)`, which is broader than the read-only git use the skill describes.

## Change added during integration review (2026-11-11)

| File | Original | Replacement | Category |
|---|---|---|---|
| SKILL.md (frontmatter `allowed-tools`) | `Bash(git:*)` | `Bash(git log:*)`, `Bash(git show:*)`, `Bash(git diff:*)`, `Bash(git blame:*)`, `Bash(git rev-parse:*)` | commit (the wildcard pre-granted `git commit` / `git push`; the skill only reads history) |

SKILL.md now carries the Apache-2.0 §4(b) change notice after its frontmatter.

**Known gap:** the skill writes `<target-dir>/THREAT_MODEL.md`. MOADIX's phase-4 path map allows only `sdlc/04-*.md`, so in a product the agent must name the output `sdlc/04-threat-model.md`; the hook denies the default path. Reconciling skill output paths with the path map is listed for increment 6 (toy run).
