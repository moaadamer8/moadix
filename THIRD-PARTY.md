# Third-party components

MOADIX's own code is MIT-licensed (see `LICENSE`). The components below are copied (vendored) from other projects at a pinned commit. Each keeps its own licence, which is shipped next to it. Their licences, not MOADIX's, govern them.

`skills/SOURCES.yaml` is the machine-readable record of the same data. Every change MOADIX made to a component is listed in that component's `MOADIX-CHANGES.md`. Files from Apache-2.0 sources that MOADIX modified also carry a change notice at the top (Apache-2.0 §4(b)). The policy is in `skills/VENDORING.md`.

## Vendored skills

| Component (in this repo) | Source | Commit | Upstream path | Licence | Copyright / attribution | Licence files here |
|---|---|---|---|---|---|---|
| `skills/bmad-forge-idea` | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/core-skills/bmad-forge-idea` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. BMad is a trademark of BMad Code, LLC; MOADIX is not affiliated with it. | `LICENSE` |
| `skills/bmad-deep-recon` | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/core-skills/bmad-deep-recon` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. | `LICENSE` |
| `skills/bmad-prd` | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/bmm-skills/plan/bmad-prd` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. | `LICENSE`, `LICENSE.cc-sdd` |
| ↳ EARS patterns in `assets/prd-template.md` | [gotalab/cc-sdd](https://github.com/gotalab/cc-sdd) | `e2a0c671aef37a482404905b409ab5c27092b25b` | `tools/cc-sdd/templates/shared/settings/rules/ears-format.md` | MIT | Copyright (c) 2025 gotalab | `skills/bmad-prd/LICENSE.cc-sdd` |
| `skills/bmad-architecture` | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/bmm-skills/plan/bmad-architecture` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. | `LICENSE`, `LICENSE.spec-kit` |
| ↳ data-model / contracts split in `assets/spine-template.md` | [github/spec-kit](https://github.com/github/spec-kit) | `40dd00f39763ccf653ccb18deb684d006f522176` | `templates/commands/plan.md`, `templates/plan-template.md` | MIT | Copyright GitHub, Inc. | `skills/bmad-architecture/LICENSE.spec-kit` |
| `skills/threat-model` | [anthropics/defending-code-reference-harness](https://github.com/anthropics/defending-code-reference-harness) | `d3bea6b5793b5f3d59a75ebe69a58efa88383145` | `.claude/skills/threat-model` | Apache-2.0 | Copyright 2026 Anthropic PBC. Modified (change notice in `SKILL.md`). | `LICENSE` |
| `skills/threat-mitigation-mapping` | [wshobson/agents](https://github.com/wshobson/agents) | `9c61ab243def98f72da12abd41cfcf5bcd91af9d` | `plugins/security-scanning/skills/threat-mitigation-mapping` | MIT | Copyright (c) 2024 Seth Hobson | `LICENSE` |
| `skills/ui-ux-pro-max` | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | `6ae86f61f520d6ca229d2f40e070410638c908c5` | `.claude/skills/ui-ux-pro-max` | MIT | Copyright (c) 2024 Next Level Builder. The repo's Apache-2.0 `ui-styling` sub-skill is not included. | `LICENSE` |
| `skills/impeccable` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | `c1e0e5492fbb524f5df84d635ecfae7dc438ec45` | `.claude/skills/impeccable` (trimmed to critique and audit) | Apache-2.0 | Copyright 2025 Paul Bakaus. Modified (change notices in `SKILL.md`, `critique.md`, `audit.md`, `audit.native.md`). | `LICENSE`, `NOTICE.md` |
| ↳ `reference/ios.md`, `reference/android.md` | [ehmo/platform-design-skills](https://github.com/ehmo/platform-design-skills) (via Impeccable) | as shipped in Impeccable at the commit above | — | MIT | ehmo. Credited in `skills/impeccable/NOTICE.md`. | `skills/impeccable/NOTICE.md` |
| `skills/apple-design` | [emilkowalski/skills](https://github.com/emilkowalski/skills) | `715c1807e08c497cfd1dc4feb450a2a3300ef2a9` | `skills/apple-design` | MIT | Copyright (c) 2026 Emil Kowalski. Not affiliated with Apple Inc. | `LICENSE` |
| `skills/code-review` | [mattpocock/skills](https://github.com/mattpocock/skills) | `4ae2317ddb22b046e26455e4f9c9b3aaaf62212d` | `skills/engineering/code-review` | MIT | Copyright (c) 2026 Matt Pocock | `LICENSE` |
| `skills/diagnosing-bugs` | [mattpocock/skills](https://github.com/mattpocock/skills) | `4ae2317ddb22b046e26455e4f9c9b3aaaf62212d` | `skills/engineering/diagnosing-bugs` | MIT | Copyright (c) 2026 Matt Pocock | `LICENSE` |
| `skills/test-driven-development` | [obra/superpowers](https://github.com/obra/superpowers) | `22f0b463e7a5e579904dd6211a520321035526f7` | `skills/test-driven-development` | MIT | Copyright (c) 2025 Jesse Vincent | `LICENSE` |
| `skills/verification-before-completion` | [obra/superpowers](https://github.com/obra/superpowers) | `22f0b463e7a5e579904dd6211a520321035526f7` | `skills/verification-before-completion` | MIT | Copyright (c) 2025 Jesse Vincent | `LICENSE` |
| `skills/typescript-reviewer` | [affaan-m/ECC](https://github.com/affaan-m/ECC) | `d2ef2680594f9a17526a6e1a2e18b3d242c5d17b` | `agents/typescript-reviewer.md` (agent, vendored as a skill) + `rules/typescript/` | MIT | Copyright (c) 2026 Affaan Mustafa | `LICENSE` |
| `skills/pr-test-analyzer` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | `43fd1f9db0941b2b83cb62268e35970d4a67c202` | `plugins/pr-review-toolkit/agents/pr-test-analyzer.md` (agent, vendored as a skill) | Apache-2.0 | Anthropic (the licence states no copyright line). Modified (change notice in `SKILL.md`). | `LICENSE` |
| `skills/javascript-testing-expert` | [dubzzz/fast-check](https://github.com/dubzzz/fast-check) | `7c69eca58443340f2a37045b9cf5cb7e09973eac` | `skills/javascript-testing-expert` | MIT | Copyright (c) 2017 Nicolas DUBIEN | `LICENSE` |
| `skills/phase-retrospective` | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/bmm-skills/ship/bmad-retrospective` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. Adapted from the BMad Method retrospective workflow; renamed because BMad is a trademark of BMad Code, LLC. | `LICENSE` |
| `skills/reflect-queue` | [BayramAnnakov/claude-reflect](https://github.com/BayramAnnakov/claude-reflect) | `b6c42326903af3dd2bf3772b979730a44d8548ca` | `scripts/{capture_learning,read_queue,clear_queue}.py`, `scripts/lib` (adapted); `SKILL.md` newly written | MIT | Copyright (c) 2025 Bayram Annakov | `LICENSE` |

## Vendored templates

| Component (in this repo) | Source | Commit | Upstream path | Licence | Copyright / attribution | Licence files here |
|---|---|---|---|---|---|---|
| `templates/DESIGN.md` | [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) | `fcc70284932276d085f01ef9f83edde90b1258cb` | `design-md/notion/DESIGN.md` | MIT | Copyright (c) 2026 VoltAgent. Not affiliated with, endorsed by or sponsored by Notion; Notion and its marks belong to their owner. | `templates/LICENSE.awesome-design-md` |

## Referenced, not included

These are named in the phase manifest but no code from them is in this repo.

| Component | Source | Use |
|---|---|---|
| context7 (MCP server) | [upstash/context7](https://github.com/upstash/context7) (reviewed at `681554c5d3a688c67879d02d4f01d79ffd15df13`) | Allowed in phase 1 if the operator installs it. |
| redocly-cli | [Redocly/redocly-cli](https://github.com/Redocly/redocly-cli) | Run by the gate in phase 5 (planned). |

## Trademarks

BMad is a trademark of BMad Code, LLC. Apple, Notion, Anthropic, Claude and the other names above belong to their owners. MOADIX is not affiliated with, endorsed by or sponsored by any of them.
