# MOADIX changes: test-driven-development

- Upstream: https://github.com/obra/superpowers
- Commit: 22f0b463e7a5e579904dd6211a520321035526f7
- Path: skills/test-driven-development
- Licence: MIT, Copyright (c) 2025 Jesse Vincent (root LICENSE, copied here as `LICENSE`)
- Vendored: 2026-11-11, for MOADIX phase 7

Files copied: `SKILL.md`, `writing-good-tests.md`. No test suite in the skill directory.

## Changes

### 1. SKILL.md, Verify GREEN: "call the change done"
- Original: "Before you call the change done, run the project's test command …"
- Replacement: "Before you report the change, run the project's test command …"
- Category: mark-done

### 2. SKILL.md, Verification Checklist heading
- Original: "Before marking work complete:"
- Replacement: "Before reporting the work:"
- Category: mark-done

### 3. writing-good-tests.md, "Behavior, not text": reference to another superpowers skill
- Original: "… Documents that instruct agents are tested by the consuming agent's behavior (superpowers:writing-skills); prose for humans earns no test at all."
- Replacement: "… agent's behavior; prose for humans earns no test at all."
- Category: auto-advance (points to a skill that is not vendored and not in the phase manifest)

### 4. writing-good-tests.md, section heading
- Original: "## Tests Ship With the Implementation"
- Replacement: "## Tests Come With the Implementation"
- Category: ship

### 5. writing-good-tests.md, same section
- Original: "\"complete\" means. Ship the tests the behavior needs and only those:"
- Replacement: "\"complete\" means. Write the tests the behavior needs and only those:"
- Category: ship

Kept verbatim: "catches bugs before commit" in the Common Rationalizations table (a rebuttal, not an instruction to commit; not a grep hit). Upstream SKILL.md has no "commit after green" step and no REQUIRED SUB-SKILL reference.

## Grep allowlist
None needed.
