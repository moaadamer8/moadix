# MOADIX changes: bmad-forge-idea

- Upstream: https://github.com/bmad-code-org/BMAD-METHOD (tag v6.12.4)
- Commit: `bab9082c3e884e0d72c759bcd1a6d90bcc01be84`
- Path: `src/core-skills/bmad-forge-idea`
- Licence: MIT, `Copyright (c) 2025 BMad Code, LLC`, with the BMad trademark notice (copied as `LICENSE`).
- Vendored: 2026-11-11. Everything in the upstream directory was copied except `scripts/tests/` (test suites are not shipped). Files not listed below are verbatim.

## Changes

| File | Original text | Replacement | Category |
| --- | --- | --- | --- |
| (dir) | `scripts/tests/test_resolve_personas.py` | not copied | adaptation |
| SKILL.md (Exits, Hardened) | "If planning or dev skills are installed (`bmad-spec`, `bmad-prd`, `bmad-prfaq`, `bmad-build`), offer the file as their input; if none are, the file stands on its own — never treat a missing skill as an error." | "Tell the user the path; the file stands on its own. Which phase or skill uses it next is the operator's decision (MOADIX gate)." | auto-advance |
| SKILL.md (end) | "Flip the status at the end: `uv run {project-root}/_bmad/scripts/memlog.py set --workspace {workspace} --key status --value complete`." | removed; after the `on_complete` line: "Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate)." | mark-done |

Side effect, left as is: On Activation step 5 offers to resume any session whose memlog `status` is not `complete`. Since no session is marked complete now, every earlier session is offered for resume.

## Known dependencies

- BMad core shared scripts, referenced as `{project-root}/_bmad/scripts/...` and not bundled here (left unchanged on purpose): `memlog.py` (init, append), `resolve_customization.py`, `resolve_config.py`. Without a BMad core install these calls fail and the skill falls back to the defaults it describes.
- `scripts/resolve_personas.py` (bundled) reads the installed BMad agent roster and `bmad-party-mode` customization when present; with neither it returns an empty pool and the skill generates personas itself.
- `{workflow.on_complete}` (customize.toml, empty by default) runs operator-configured instructions at the end. Left in: it is operator configuration, and the MOADIX phase manifest still limits which skills it can call.

## Increment 6: output paths (MOADIX)

- `customize.toml`: `forge_output_path = "{output_folder}/forge"` -> `"{project-root}/sdlc/00-forge"`. Upstream writes under `_bmad-output/`, which no phase's path map owns, so every write was denied. The new folder is owned by phase 0 (gate/pathmap.py); in a feature cycle pass an explicit `doc_workspace` under `sdlc/features/<feature-id>/` instead.
- BMad core's shared scripts (`memlog.py`, `resolve_config.py`, `resolve_customization.py`, `config_utils.py`) are now vendored verbatim in MOADIX's gate (`gate/bmad/scripts/`) and installed by the gate into the product's `_bmad/scripts/` (with a MOADIX-written `_bmad/config.toml`), so the `uv run {project-root}/_bmad/scripts/...` calls above resolve.
