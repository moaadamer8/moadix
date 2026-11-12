# MOADIX changes: bmad-architecture

- Upstream: https://github.com/bmad-code-org/BMAD-METHOD (tag v6.12.4)
- Commit: `bab9082c3e884e0d72c759bcd1a6d90bcc01be84`
- Path: `src/bmm-skills/plan/bmad-architecture`
- Licence: MIT, `Copyright (c) 2025 BMad Code, LLC`, with the BMad trademark notice (copied as `LICENSE`).
- Also includes the data-model / contracts split from spec-kit (https://github.com/github/spec-kit @ `40dd00f39763ccf653ccb18deb684d006f522176`, `templates/commands/plan.md` "Phase 1: Design & Contracts" items 1-2 and the `data-model.md` / `contracts/` layout in `templates/plan-template.md`, MIT, `Copyright GitHub, Inc.`); its licence is `LICENSE.spec-kit`.
- Vendored: 2026-11-11. Everything in the upstream directory was copied except `scripts/tests/` (test suites are not shipped). Files not listed below are verbatim.

## Changes

| File | Original text | Replacement | Category |
| --- | --- | --- | --- |
| (dir) | `scripts/tests/test_lint_spine.py` | not copied | adaptation |
| (dir) | (none) | added `LICENSE.spec-kit` (copy of spec-kit's LICENSE) | adaptation |
| SKILL.md On Activation step 3 | "If the real ask is requirements / UX / a capability contract / epic breakdown / an agent, invoke the `bmad-prd`, `bmad-ux`, `bmad-spec`, `bmad-create-epics-and-stories`, or `bmad-workflow-builder` (if the BMad Builder module is installed) skill instead." | "… tell the user it belongs to another skill (`bmad-prd`, `bmad-ux`, `bmad-spec`, `bmad-create-epics-and-stories`, or `bmad-workflow-builder`) and stop; the operator decides which phase runs (MOADIX gate)." | auto-advance |
| SKILL.md Finalize step 6 | "Offer to invoke the `bmad-spec` skill to adopt the spine as a companion, keeping `AD` IDs stable so downstream can cite them." | "Keep `AD` IDs stable so downstream can cite them." | auto-advance |
| SKILL.md Finalize step 7 | "**Close.** Set the spine's own frontmatter `status: final`, `updated: {date}`; log a `memlog.py append --type event --text "spine finalized"` …" | "**Close.** Set the spine's own frontmatter `updated: {date}`; log a `memlog.py append --type event --text "spine ready for operator review"` …" | mark-done |
| SKILL.md Finalize step 7 | "Next, **lead with `bmad-spec`** — recommend adopting/refreshing the spine as a spec companion (…), then `bmad-create-epics-and-stories` or — epic altitude — `bmad-build`; or invoke `bmad-help` to route." | removed | auto-advance |
| SKILL.md Finalize | (no step 9) | new step 9: "Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate)." | auto-advance |
| references/headless.md (last paragraph) | "`complete` stands alone ·" | "`complete` means no open questions remain (the operator still reviews it; only the MOADIX gate approves a phase) ·" | self-approve |
| assets/spine-template.md frontmatter | "status: draft               # draft · final" | "status: draft               # draft only; the MOADIX gate records the operator's decision, not this field" | mark-done |
| assets/spine-template.md | (none) | New sections "Data Model" (entities, key fields, relationships, validation rules, state transitions; a large shape goes to a companion `data-model.md`) and "Contracts" (interfaces exposed to users or other systems, contract format per project type, files in a companion `contracts/`; skip if purely internal), inserted after "Structural Seed" with an HTML-comment attribution line, written as HTML-comment guidance plus a placeholder table like the rest of the template. | adaptation |

Left as is: the Reviewer Gate has the agent apply clear fixes to its own spine at Finalize. That edits the draft; the reviewers return quality verdicts, not an approval. `{workflow.external_handoffs}` and `{workflow.on_complete}` (empty by default) are operator configuration.

## Known dependencies

- BMad core shared scripts, referenced as `{project-root}/_bmad/scripts/...` and not bundled here (left unchanged on purpose): `memlog.py` (init, append), `resolve_customization.py`, `resolve_config.py`. Without a BMad core install these calls fail and the skill falls back to the defaults it describes.
- `scripts/lint_spine.py` (bundled) needs `uv`. It does not check section names, so the added Data Model / Contracts sections do not affect it.
- `{workflow.doc_standards}` defaults to `skill:bmad-review`; `{workflow.finalize_reviewers}` lists review lenses. If such a skill is not allowed in the phase, the rubric walker still runs.

## Increment 6: output paths (MOADIX)

- `customize.toml`: `spine_output_path = "{planning_artifacts}/architecture"` -> `"{project-root}/sdlc/03-architecture"`. Upstream writes under `_bmad-output/`, which no phase's path map owns, so every write was denied. The new folder is owned by phase 3 (gate/pathmap.py); in a feature cycle pass an explicit `doc_workspace` under `sdlc/features/<feature-id>/` instead.
- BMad core's shared scripts (`memlog.py`, `resolve_config.py`, `resolve_customization.py`, `config_utils.py`) are now vendored verbatim in MOADIX's gate (`gate/bmad/scripts/`) and installed by the gate into the product's `_bmad/scripts/` (with a MOADIX-written `_bmad/config.toml`), so the `uv run {project-root}/_bmad/scripts/...` calls above resolve.
