---
description: How a MOADIX feature cycle works (FEATURE <id> <code>): where the feature's documents go and what the gate checks. Changes no gate state.
---
A feature cycle adds a feature to a product whose baseline is approved (released at phase 11, or onboarded at phase B). Only the operator starts one, by typing `FEATURE <feature-id> <code>`. One feature is active at a time.

**Where things go.** The feature runs the same 16 phases, scoped to the feature. Its documents are ADDITIONS, in `sdlc/features/<feature-id>/`, named like the product's: `00-brd.md` (new goals and the feature's `- **Size:**`), `02-prd.md` (new stories, EARS acceptance criteria), `03-hld.md`, `04-threat-model.md` (new SEC-IDs), `05-lld.md` and `05-lld/`, `06-ux.md`, `06b-provisioning.md`, `07-tasks.md`, `08-test-report.md`, `09-security-report.md`, `10a-…`, `10b-…`, `10c-…`, `11-release.md`. Templates for the main ones are in the plugin's `templates/feature/`. Code paths (`src/`, `tests/`, …) are the product's, writable in the phase that owns them.

**Frozen.** The product's approved documents (`sdlc/NN-*.md`) cannot be written during a feature. A BMAD skill's run folder goes under the feature too: pass an explicit `doc_workspace` such as `sdlc/features/<feature-id>/02-prd/`.

**What the gate checks** (check-feature, every phase): each addition traces (story → goal, task → story, every story has a design, a task and a test result); no ID the product already defines is reused (BG, US, SEC, TB, T); a new SEC-ID names an existing trust boundary; and no acceptance criterion contradicts an approved one (same trigger, opposite response) or declares that it supersedes one. Approved requirements are frozen: a feature adds, never contradicts.

**Merge.** When the operator approves the feature's phase 11, the gate merges its additions of phases 0 to 6b into the product's documents, records the merge (every file's sha256) in the ledger line, and commits it. Tasks, tests and verification stay in the feature folder as its record. A feature's phase 11 can only be approved, never proceeded past.

Use `/moadix:request-review` when a phase is ready, as usual.
