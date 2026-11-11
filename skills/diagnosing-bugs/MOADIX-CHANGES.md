# MOADIX changes: diagnosing-bugs

- Upstream: https://github.com/mattpocock/skills
- Commit: 4ae2317ddb22b046e26455e4f9c9b3aaaf62212d
- Path: skills/engineering/diagnosing-bugs
- Licence: MIT, Copyright (c) 2026 Matt Pocock (root LICENSE, copied here as `LICENSE`)
- Vendored: 2026-11-11, for MOADIX phase 7

Files copied: `SKILL.md`, `agents/openai.yaml`, `scripts/hitl-loop.template.sh` (the last two unchanged). No test suite upstream.

## Changes

### 1. SKILL.md, Phase 5: "next phase"
- Original: "… The codebase architecture is preventing the bug from being locked down. Flag this for the next phase."
- Replacement: "… Flag this in your report."
- Category: auto-advance (under MOADIX "the next phase" reads as a gate phase; the finding goes to the operator in the report instead)

### 2. SKILL.md, Phase 6: "declaring done"
- Original: "Required before declaring done:"
- Replacement: "Required before reporting the fix:"
- Category: mark-done

### 3. SKILL.md, Phase 6 checklist: commit / PR message
- Original: "- [ ] The hypothesis that turned out correct is stated in the commit / PR message, so the next debugger learns"
- Replacement: "- [ ] The hypothesis that turned out correct is stated in your report, so the next debugger learns" followed by a new paragraph: "Then stop and report: the loop command, the cause, the fix and the evidence. Do not commit; whether the work is accepted is the operator's decision (MOADIX gate)."
- Category: commit

## Grep allowlist (MOADIX-GREP-ALLOW.tsv)
- Phase 3: `("we just deployed a change to #3")` is an example of the user's domain knowledge, not an instruction to deploy.
