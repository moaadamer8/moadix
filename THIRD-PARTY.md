# Third-party components

MOADIX's own code is MIT-licensed (see `LICENSE`). The components below are copied (vendored) from other projects at a pinned commit. Each keeps its own licence, which is shipped next to it. Their licences, not MOADIX's, govern them.

`skills/SOURCES.yaml` is the machine-readable record of the same data. Every change MOADIX made to a component is listed in that component's `MOADIX-CHANGES.md`. Files from Apache-2.0 sources that MOADIX modified also carry a change notice at the top (Apache-2.0 §4(b)). The policy is in `skills/VENDORING.md`.

## Vendored skills

| Component (in this repo) | Source | Commit | Upstream path | Licence | Copyright / attribution | Licence files here |
|---|---|---|---|---|---|---|
| `skills/forge-idea` (upstream `bmad-forge-idea`) | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/core-skills/bmad-forge-idea` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. BMad is a trademark of BMad Code, LLC; MOADIX is not affiliated with it. | `LICENSE` |
| `skills/deep-recon` (upstream `bmad-deep-recon`) | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/core-skills/bmad-deep-recon` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. | `LICENSE` |
| `skills/prd` (upstream `bmad-prd`) | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/bmm-skills/plan/bmad-prd` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. | `LICENSE`, `LICENSE.cc-sdd` |
| ↳ EARS patterns in `assets/prd-template.md` | [gotalab/cc-sdd](https://github.com/gotalab/cc-sdd) | `e2a0c671aef37a482404905b409ab5c27092b25b` | `tools/cc-sdd/templates/shared/settings/rules/ears-format.md` | MIT | Copyright (c) 2025 gotalab | `skills/prd/LICENSE.cc-sdd` |
| `skills/architecture` (upstream `bmad-architecture`) | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (v6.12.4) | `bab9082c3e884e0d72c759bcd1a6d90bcc01be84` | `src/bmm-skills/plan/bmad-architecture` | MIT (with trademark notice) | Copyright (c) 2025 BMad Code, LLC. BMad Method by BMad Code, LLC. | `LICENSE`, `LICENSE.spec-kit` |
| ↳ data-model / contracts split in `assets/spine-template.md` | [github/spec-kit](https://github.com/github/spec-kit) | `40dd00f39763ccf653ccb18deb684d006f522176` | `templates/commands/plan.md`, `templates/plan-template.md` | MIT | Copyright GitHub, Inc. | `skills/architecture/LICENSE.spec-kit` |
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

## Fetched unmodified, never vendored: MPL-2.0 (ruling 3 on increment 7)

MPL-2.0 is accepted only for tools and product dependencies that are fetched unmodified from their registry and never copied into this repository. None of these files is in this repository; the installer (`managed/fetch_tools.py`) or the product's own package manager fetches them, checked against the pinned lockfile or version.

| Component | Version | Licence | Reaches MOADIX through | Source (registry) |
|---|---|---|---|---|
| lightningcss (and its 11 platform packages) | 1.33.0 | MPL-2.0 | dependency of `likec4` 1.60.0 (`tools/npm/likec4/package-lock.json`) | https://registry.npmjs.org/lightningcss |
| axe-core | 4.14.0 | MPL-2.0 | dependency of `@lhci/cli` 0.15.1 via lighthouse (`tools/npm/lhci/package-lock.json`) | https://registry.npmjs.org/axe-core |
| hypothesis | 6.170.14 | MPL-2.0 | dependency of Schemathesis 4.32.7 (`tools/py/schemathesis/requirements.txt`) | https://pypi.org/project/hypothesis/ |
| certifi | 2026.10.23 | MPL-2.0 | dependency of Schemathesis 4.32.7 (`tools/py/schemathesis/requirements.txt`) | https://pypi.org/project/certifi/ |
| axe-core | 4.14.0 | MPL-2.0 | product dependency (phases 6, 8, 10a), pinned in `gate/config/tools.yaml` `product_dependencies` | https://registry.npmjs.org/axe-core |
| @axe-core/playwright | 4.14.0 | MPL-2.0 | product dependency (phases 6, 8, 10a), pinned in `gate/config/tools.yaml` `product_dependencies` | https://registry.npmjs.org/@axe-core/playwright |

The licences of hypothesis and certifi were taken from their PyPI metadata; the others were read from the LICENSE file in the published package (docs/evidence/increment-7-licences.md).

## Pulled unmodified by digest and executed, never vendored: container images (ruling 1 on increment 7c)

The confined runner (`gate/confined.py`, `gate/config/confinement.yaml`) pulls these images unmodified, by digest, from their official source and runs them. None of them is in this repository and MOADIX never redistributes them. Ruling 1 on increment 7c: such software may carry any OSI-approved licence, GPL and LGPL included; anything non-OSI or with a field-of-use restriction stops and is reported.

The licences below are the main software's, plus the `License:` identifiers found in the image's Debian/Ubuntu `/usr/share/doc/*/copyright` files (scan of 2026-11-14, `docs/increment-7d-report.md` section 2). Every image contains some non-OSI identifiers, mostly for documentation and data files. No field-of-use restriction was found. Because of those identifiers, every image is `status: blocked` until the operator rules.

| Image (catalogue name) | Reference (digest) | Source | Main software licence | Non-OSI identifiers found |
|---|---|---|---|---|
| node | `docker.io/library/node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54` | https://hub.docker.com/_/node (Docker Official Image, Debian 12) | Node.js: MIT (bundled deps MIT/BSD/ISC/Apache-2.0); npm: Artistic-2.0 | GFDL-NIV (manuals), CC-BY-3.0, public-domain, Beerware (libmd, PAM), Latex2e, verbatim-copy notices on the GPL/LGPL texts (liblzma5 and others) |
| node-full | `docker.io/library/node:24-bookworm@sha256:9d266751ca3d7fdbe651c878ffd5ad0a42fed49a18c283509267c97f025b7496` | https://hub.docker.com/_/node (Docker Official Image, Debian 12; Stryker needs `ps`) | as node | as node, plus perl's RRA-KEEP-THIS-NOTICE, TEXT-TABS and DONT-CHANGE-THE-GPL notices |
| python | `docker.io/library/python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` | https://hub.docker.com/_/python (Docker Official Image, Debian 13) | CPython: PSF-2.0 | as node |
| chromium | `mcr.microsoft.com/playwright:v1.64.1-noble@sha256:2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f` | https://mcr.microsoft.com/en-us/artifact/mar/playwright (Microsoft, Ubuntu 24.04) | Playwright: Apache-2.0; Chromium: BSD-3-Clause and others | GFDL, CC-BY-3.0/4.0, CC-BY-SA-2.0/3.0/4.0 (icon and theme data), public-domain, Beerware, BSL-1 |
| zap | `ghcr.io/zaproxy/zaproxy:20261026-stable@sha256:030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238` | https://github.com/zaproxy/zaproxy/pkgs/container/zaproxy (ZAP project, Debian 12, ZAP 2.17.0) | ZAP: Apache-2.0 | GFDL, CC-BY, public-domain, Beerware |
| postgres | `docker.io/library/postgres:17-bookworm@sha256:40865bc877a289da75963d97d72b59633f639fc5af7a4e856bfa3714cae5b536` | https://hub.docker.com/_/postgres (Docker Official Image, Debian 12, PostgreSQL 17) | PostgreSQL licence (OSI-approved) | GFDL, public-domain, Beerware |
