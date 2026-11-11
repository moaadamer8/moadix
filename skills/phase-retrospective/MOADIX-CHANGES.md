# MOADIX changes: phase-retrospective

- Upstream: https://github.com/bmad-code-org/BMAD-METHOD (tag v6.12.4)
- Commit: `bab9082c3e884e0d72c759bcd1a6d90bcc01be84`
- Path: `src/bmm-skills/ship/bmad-retrospective`
- Licence: MIT, `Copyright (c) 2025 BMad Code, LLC`, with the BMad trademark notice (copied as `LICENSE`).
- Vendored: 2026-11-11. Everything in the upstream directory was copied except `scripts/tests/` (test suites are not shipped). Files not listed below are verbatim.

## Changes

| File | Original text | Replacement | Category |
| --- | --- | --- | --- |
| (dir) | `scripts/tests/` (test_sprint_status.py, test_git_evidence.py, fixtures/) | not copied | adaptation |
| (dir) | directory `bmad-retrospective` | renamed `phase-retrospective` (BMad trademark: the skill's name, title and description carry no BMad mark) | adaptation |
| SKILL.md frontmatter | "name: bmad-retrospective" | "name: phase-retrospective" | adaptation |
| SKILL.md frontmatter description | "… and produce a retrospective with sourced findings, action items, and an acceptance decision." | "… and produce a retrospective with sourced findings, proposed action items, and a recommended acceptance verdict for the operator." | self-approve |
| SKILL.md (under title) | (none) | "Adapted from the BMad Method retrospective workflow (MIT). See LICENSE and MOADIX-CHANGES.md." (origin attribution, which BMad's TRADEMARK.md allows) | adaptation |
| SKILL.md Inputs table | "epic detection + final status update" | "epic detection (read only)" | mark-done |
| SKILL.md Phase 4 | "A human decision always overrides. An epic that fails …" | "A human decision always overrides. The verdict is a recommendation for the operator: it approves nothing and gates nothing (MOADIX gate). An epic that fails …" | self-approve |
| SKILL.md Phase 4 | "… the per-item evidence Phase 5's status offer reads." | "… the per-item evidence the operator reads." | mark-done |
| SKILL.md Phase 5 | "Finalize the retrospective document and update sprint status. Load `references/retro-document.md` for the document's sections and the exact `sprint_status.py update` invocation that marks the retro key `done`, appends the action items, and validates the write. Where the Phase 4 follow-through has evidence … offer `--set-action-status` … In stories mode, finalize `{spec-folder}/RETROSPECTIVE.md` and stop there: no `sprint_status.py` call, …" | "Finalize the retrospective document. … This skill does not write `sprint-status.yaml`, story artifacts, `SPEC.md` or `stories.yaml`: the proposed action items, and any status transitions … stay in the document for the operator to apply. …", then "Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate)." | mark-done |
| references/retro-document.md title + intro | "# Finalize: Retrospective Document and Sprint Status … Two writes: the retrospective document, and the `sprint-status.yaml` update. Stories mode makes only the first." | "# Finalize: Retrospective Document … One write: the retrospective document. This skill does not write `sprint-status.yaml` …" | mark-done |
| references/retro-document.md | "… an epic gate or orchestrator keys off `verdict` to decide whether to hold the next epic:" | "… The `verdict` is a recommendation for the operator; it approves nothing and gates nothing (MOADIX gate):" | auto-advance |
| references/retro-document.md | "Do not encode the verdict in the sprint-status retro key — that key's value stays `done` …" and the paragraph "That holds for a **rejected** epic too: the update below marks the retro key `done` …" | removed | mark-done |
| references/retro-document.md Sections | "the selector Phase 5 would need to act on each" | "the selector the operator would need to act on each" | mark-done |
| references/retro-document.md | whole section "## Sprint-status update" (the `sprint_status.py update … --set-retro-done --add-action … --verdict …` command, its result handling, the `--set-action-status` command and its rules) | replaced by "## Sprint status and action items": "Do not edit `sprint-status.yaml` or any story artifact. The proposed action items … stay in this document; the operator decides which to apply." | mark-done |
| references/retro-document.md Finish | (none) | appended "Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate)." | auto-advance |
| references/acceptance-verdict.md | "One or the other is what Phase 5 needs to name the item at all." | "One or the other is what the operator needs to name the item at all." | mark-done |
| references/acceptance-verdict.md | "That record is exactly what Phase 5's `--set-action-status` offer reads: the selector becomes the JSON, the evidence is what the user is asked to confirm, and the proposed status is written only if they confirm it." | "That record is what the operator reads to decide each item's status; this skill writes no status." | mark-done |
| references/acceptance-verdict.md (end) | "The verdict and its evidence carry into the Phase 5 document." | + "The verdict is a recommendation for the operator; it does not approve the epic or the phase (MOADIX gate)." | self-approve |
| customize.toml | "# Workflow customization surface for bmad-retrospective." | "# Workflow customization surface for phase-retrospective." | adaptation |
| customize.toml | "… after the retrospective / document is saved and sprint-status is updated." | "… after the retrospective / document is saved." | mark-done |
| scripts/sprint_status.py | The whole `update` subcommand: `cmd_update` (sets `epic-N-retrospective` to `done`, appends action items, `--set-action-status`, bumps `last_updated`), `_restore`, `_atomic_write`, `_dump_bytes`, `_slugify`, `_selector_label`, `_match_action_items`, `_comment_counts`, constants `DATE_FORMAT`, `ACTION_STATUSES`, `VERDICTS`, the `p_update` parser, and the imports only they used | removed. The script keeps only the read-only `detect-epic` subcommand, unchanged. Module docstring and parser description rewritten to say so, with a "Modified by MOADIX" note. The `_load_yaml` comments about write indentation are kept verbatim although they now describe a removed path. | mark-done |

Left as is: the verdict vocabulary (`accepted` / `accepted-with-open-items` / `rejected`) is kept so documents stay readable by existing tools, but it is now stated as a recommendation to the operator. The skill still invokes `bmad-review` (Phase 2) and, on request, `bmad-party-mode` (Phase 3) inside the phase; neither approves or advances anything.

## Known dependencies

- BMad core shared scripts, referenced as `{project-root}/_bmad/scripts/...` and not bundled here (left unchanged on purpose): `resolve_customization.py`, `resolve_config.py`. Without a BMad core install these calls fail and the skill falls back to the defaults it describes.
- `scripts/sprint_status.py detect-epic` (bundled, read only) needs `uv` and `ruamel.yaml`; `scripts/git_evidence.py` (bundled) runs read-only `git log --numstat`.
- `bmad-review` and `bmad-party-mode` skills: optional; the skill runs those lenses inline when they are unavailable or not allowed in the phase.
- Sprint-mode inputs (`sprint-status.yaml`, story files) come from BMad's sprint workflow; stories mode needs a spec folder (`SPEC.md`, `stories.yaml`).
