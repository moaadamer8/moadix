---
description: How MOADIX onboarding phase B (Baseline) works for a product that already has code: the documents, the templates and what the gate checks. Changes no gate state.
---
The operator's `INIT <product-id> <code>` on a repository that already has code starts the product in **onboarding mode at phase B (Baseline)**. In phase B you document what exists. You do not change the product's code.

Write these, from the plugin's `templates/baseline/` (one file each):

- `sdlc/00-brd.md`: as-is BRD, purpose, users, business goals (BG-n)
- `sdlc/02-prd.md`: as-is PRD, one story per current feature, EARS acceptance criteria where possible (otherwise mark `(as-is, not EARS: <why>)`)
- `sdlc/03-architecture.md`: components and where they live
- `sdlc/04-threat-model.md`: threats to the current system, each SEC-ID with `**Current status:**` mitigated, partial, open or unknown
- `sdlc/B-test-inventory.md`: test command, test environment (never production), suites, coverage per acceptance criterion
- `sdlc/B-known-gaps.md`: the known-gaps register (untested acceptance criteria, every SEC-ID not mitigated, anything else not in order)
- `sdlc/B-accounts.md`: accounts and services in use, by name, with where the code configures them. Never a secret value.

**Every claim cites code that exists**, as `path:line` or `path:start-end` at the commit you document. check-baseline resolves every citation against HEAD; one dead citation fails the phase. Behaviour you cannot find in the code is not a claim. It goes in the gaps register.

The baseline records the current state. It does not certify the code. Gaps go to the register, never into approvals.

When the documents are committed, launch the fresh-context verifier `moadix:baseline-verifier` (the gate writes its brief) and then call `/moadix:request-review B`. The operator approves with `APPROVE B <code>`. From then on every change is a feature cycle (`/moadix:feature`).
