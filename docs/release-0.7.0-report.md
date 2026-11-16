# 0.7.0: gap-critic convergence, PROCEED-PAST at the release gate, standing instructions

Built from `docs/critic-convergence-design.md`, which the operator approved with rulings Q1–Q6 and Additions 1–4 (review of 0.6.4). §8 of that document records the rulings, and §9 says where the build differs from its text. 0.7.0 includes 0.6.4, which was committed but not installed.

## Built

| Ruling / addition | What the gate does now | Where |
|---|---|---|
| Depth per phase (Q1, with corrections a–d) | Each gated phase has a `depth` block: what it decides and what it defers, to which phase. a: D4.4 names SEC-n. b: phase 2 decides business validation (D2.6, P6, what counts as valid), and X2.3 defers only its encoding (formats, patterns, error codes) to 5. c: 10a/10b/10c defer only known issues, to 11, under a hard rule. d: a gap matching no defers rule is judged at the current phase exactly as before. The brief, the catalogue and `/moadix:coverage` all say so. | `gate/config/coverage-topics.yaml`, `gate/critic.py` |
| Carries | A new severity, CARRY, with `defer_rule`, `to` and `class` (and `ac` for a known issue). The hard rules are checked deterministically; a carry that breaks one fails the evidence. The rules: the rule belongs to the phase; the target is the rule's target, a later phase, not closed; nothing decides-level or BLOCKER-level (lexical tripwire); a gap with security, privacy or tenant terms must be classed so; such a gap never goes past phase 9; a known issue breaks no P1 AC (read from `**Priority:**` must/P1) and is not a security, privacy or tenant-isolation defect. APPROVE and PROCEED-PAST record the phase's carries in the ledger line (`CARRY-<phase>-<n>`, with their text); the ledger is the register. The target phase's skeleton pre-lists each carry, its coverage-lint requires it, and its critic brief lists it, with the question "should this have been decided earlier?". APPROVE of the target closes the carries its critic raised nothing on. | `gate/critic.py`, `gate/contract.py`, `gate/state.py` replay, `gate/opcmd.py` |
| Memory | Each critic run is archived (`.sdlc/critic/<scope>-<label>.json`, gate-owned), and its findings get stable ids, `GC-<phase>-<n>`. The brief lists every earlier finding with the gate's disposition: waived, carried, ruled (a `Rules: GC-…` line in DISCOVERY.md or an ADR), fixed? (the cited text is gone) or open. `same_as` and `regression_of` are checked: same topic, and for same_as the same section. A new finding on text unchanged since the last run is marked late: counted, shown, never downgraded (Q6). | `gate/critic.py`, `gate/verify.py` |
| Per-finding waivers | `WAIVE gap-critic.GC-…` records the finding's fingerprint (topic, path, section, sha256 of the cited text). It lapses when that text changes, and STATUS names the lapse. A topic waiver is refused for new waivers. A waiver needs current evidence. | `gate/opcmd.py`, `gate/critic.py` |
| UNCARRY (Q2) | `UNCARRY <GC id or CARRY id> <code>`. A GC id: the carry counts as a MAJOR of the current phase. A CARRY id: the carry is readdressed to the current phase, whose COVERAGE.md must settle it. | `gate/opcmd.py`, `gate/state.py` |
| Old topic waivers (Q3) | They cover a MAJOR only in the phase where they were recorded, and only on text that existed at their commit (§9 of the design says why this is the closest exact reading). | `gate/critic.py` waiver_covers |
| Carry threshold (Q4) | When a run carries more than half of its MAJOR-or-worse findings, the summary says so. It only informs. | `gate/contract.py` critic_check |
| PROCEED-PAST of a target (Q5) | The carries addressed to that phase stay open, STATUS lists them as release blockers, and the phase-11 scorecard blocks on them. `WAIVE CARRY-…` with a reason closes one, and the ledger line carries its text. It is refused while the target phase is still to come, and always for a security, privacy or tenant-isolation carry. | `gate/opcmd.py`, `gate/v1/build_scorecard.py` |
| Evidence freshness (Addition 1) | Each schedule records the verifier's document set and its digest (git blob ids), and the evidence must echo `docset_sha256`. A result stays current while the digest at HEAD matches. Citations and quotes are checked at the commit the verifier reviewed. | `gate/verify.py` docset, staleness |
| PROCEED-PAST at the release gate (Addition 2, item 6 of 0.6.4) | build-scorecard counts a PROCEED-PAST phase as closed: no "not APPROVED" and no predecessor blocker. Each one is listed (tag PPST) with its reason and every finding it passed that no waiver now covers. The APPROVE 11 reply (recorded or refused) lists the same, plus the open carries. Open carries block. | `gate/v1/build_scorecard.py`, `gate/validate.py` phase_doc, `gate/v1/hlib.py`, `gate/opcmd.py` |
| Standing instructions (Addition 3) | Built as proposed. `.sdlc-proposals/standing.md` goes through ADOPT and lands in `.sdlc/standing.md` with the gate's header: "Standing instructions cannot change any gate rule". SessionStart shows them in full when they match their ADOPT line; a hand edit is reported instead of shown. STATUS gives one line. | `gate/adopt.py`, `gate/session.py`, `docs/standing-instructions-proposal.md` |

## Verifiers that stay tied to HEAD (Addition 1)

Every verifier except these three now compares document-set digests. The document set is the required paths, plus, for the gap critic, the upstream documents its brief lists, and for the AC-coverage critic, the PRD files.

- **live-verifier (10a).** It exercises the running app built from the whole tree. Any file, not only its scope, can change what it saw.
- **baseline-verifier (B).** It checks the baseline's claims against code anywhere in the repository, so its document set is the whole tree.
- **sf-triager (9).** It triages the Claude Security scan, and the gate keys that scan to HEAD (`gate/secscan.py`). A new HEAD means a new scan.

A schedule written before 0.7.0 has no digest, so it also compares HEAD. Evidence written before 0.7.0 lacks `docset_sha256` and must be produced again.

## How an existing product behaves after the update (onlineMarket)

I read the product's state without changing it. Phase 0 is PROCEED-PAST (ledger seq 9), phase 1 is current, and there is no gap-critic run on phase 1 yet. The ledger has six topic waivers, all expiring 2026-12-31: `gap-critic.B12`, `B6`, `B23`, `B14`, `B21` and `B4`. `sdlc/1/CARRIED.md` is committed.

- **Gate state.** `phase.yaml` renders the same: the new state lives under unrendered keys, and the render version is unchanged. The update causes no drift.
- **PROCEED-PAST on phase 0.**
  - The phase-11 scorecard now counts phase 0 as closed. It lists phase 0 under PPST with its recorded reason, which names F-4.
  - The ledger line passed no findings (`passed_findings` is absent; only `check-contract-0` failed), so it lists none as still open.
  - The APPROVE 11 reply will list phase 0 the same way. Nothing about it blocks the release.
- **The six topic waivers.** STATUS keeps listing them until 2026-12-31.
  - Under Q3, each covers only a MAJOR in phase 0, the phase it was recorded in. Phase 0 is closed, so they now cover nothing.
  - They never applied to phase 1's topics.
  - They cannot be renewed in topic form: a new waiver names one finding by its GC id.
- **`sdlc/1/CARRIED.md`.** It stays an ordinary phase-1 document; it is not imported into the gate's register (Addition 4).
  - Phase 2's gap critic will see it among the upstream documents it reads for contradictions.
  - The gate itself does not require phase 2 to settle its items.
  - If the operator wants one of them tracked by the gate, the phase-1 critic can raise it as a CARRY to phase 2 on its next run, under a defers rule of phase 1. Otherwise phase 2 meets it as a gap like any other.
- **Phase 1 in progress.**
  - The first gap-critic launch on 0.7.0 is run 1, and its brief has the new sections.
  - Phase 1 decides D1.1–D1.3 and D1.B. It defers vendor choice to 3, pricing detail to 5 and cost tuning to 11.
  - Topic-form waivers are refused; findings are waived by GC id.

## How I read one point of the rulings

**Q5, "per item".** I read it as: each carry is its own waiver, recorded with its own text, and a waiver never covers a carry it does not name. With F-5, a single WAIVE message can still name several carry ids, each recorded and checked alone. If you meant one carry per message, it is a one-line change in `gate/opcmd.py` (refuse a carry id in a multi-id WAIVE).

## Tests

- `tests/inc8/run.py`: new suite, 72 checks.
  - catalogue: the corrections a–d;
  - every hard rule, with a planted violation, including Q1c;
  - a convergence fixture over phase 0, with fixed?, ruled, waived, carried, late, regression, a refused same_as, a lapse, the carry recorded, required and audited in phase 2, and closed on APPROVE 2;
  - UNCARRY both ways;
  - Q5: proceed past, release blocker, carry waiver, a privacy carry refused;
  - the scorecard;
  - freshness both ways, plus the tied roles and a wrong digest;
  - standing instructions;
  - Q3 migration.
- Updated for the rulings:
  - `tests/inc7` and `tests/inc7b`: topic waivers became GC-id waivers.
  - `tests/verifiers`: the commit is now compared with the reviewed commit.
  - `tests/lib/contract_fixture.py`: the critic stand-in echoes `docset_sha256`, as a real critic does.
- Every sandbox suite passes; the counts are in the commit message.
- Not run here: the corpus, the install dry run and the confined-engine suite need the Keychain or Docker. They are steps 2–4 of "Updating from 0.6.3 to 0.7.0" in `docs/INSTALL.md`.
