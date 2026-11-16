# 0.6.4: fixes from the first product run

Source: `~/onlinemarket-v2/docs/moadix-findings.md`, findings F-1 to F-4, plus the operator's F-5. The product was read and nothing in it was changed.

## Built

| Item | Change | Where |
|---|---|---|
| F-4 | discovery-lint accepts a question of fact. The question marks it with `Recommendation: none (question of fact)`; the product run's wording, `None, it is a fact`, also passes. The question still needs 2-4 options and the operator's `Chosen:`. A question marked as fact that also names a letter fails. A missing recommendation still fails, and the message now says how to mark a fact. | `gate/contract.py` discovery_lint |
| F-5 | One WAIVE can name up to 20 findings under one code, comma-separated: `WAIVE gap-critic.B9,gap-critic.B12 owner=… scope=… expiry=… reason=… <code>`. Each id is checked as if it were waived alone. If one id is refused (a BLOCKER, a duplicate, an existing waiver, or the 512-character action limit), the whole message is refused and nothing is recorded. The ledger gets one line carrying `ids`, and replay turns it into one waiver per id. Old single-id lines replay as before. | `gate/opcmd.py`, `gate/state.py` replay |
| F-2 | The clean-tree checks ignore OS metadata files in any folder: `.DS_Store`, `._*`, `.Spotlight-V100`, `.Trashes`, `Thumbs.db`, `desktop.ini`. These checks are the validators' tree state, the verifier launch (`commit first`) and the phase 9 scan scheduler. INIT also appends the names to the repository's `.git/info/exclude`, which is local and never committed. A product initialised earlier (onlineMarket) still gets the clean-tree exemption. It does not get the exclude lines; the operator can add them in Terminal if wanted. | `gate/validation.py` (`OS_METADATA`, `status_pathspec`, `exclude_os_metadata`), `gate/verify.py`, `gate/secscan.py`, `gate/opcmd.py` INIT |
| F-1 | A feedback run of the linters no longer needs the checker program. When the ledger cannot be verified where the run happens (the plugin cache has no `bin/moadix-checker`), it replays the ledger unverified, prints a `NOTE feedback run: …` line, and lints. The gate's own runs still use the verified state. The `-lint` suffix the agent typed is accepted. `/moadix:coverage` now gives the exact command with `${CLAUDE_PLUGIN_ROOT}`. | `gate/contract.py` main, `gate/state.py` unverified_state |
| 5 | `/moadix:coverage` sets out discovery in rounds: only questions that do not depend on each other; 2-4 lettered options; a recommendation with one line of why (or the fact mark); a one-line answer; as many rounds as needed; never a guess. The log format is unchanged. | `gate/contract.py` coverage_doc, `commands/coverage.md` (regenerated) |
| 8 | Live-check row 4 uses a literal path. Row 11 says the real protected project id is needed, and why: with the placeholder, the shell reads `<…>` as a redirection, and the guard refuses the command for that reason instead. The update procedure is renamed to 0.6.4. | `docs/INSTALL.md` |

Tests: `tests/inc7/run.py`, group `0.6.4`, 21 new checks. Each change has a passing control and a planted case that must fail.

## Proposed, not built

- F-3, critic convergence: `docs/critic-convergence-design.md`, for review.
- Item 7, standing instructions: `docs/standing-instructions-proposal.md`.

## Stopped: item 6 (PROCEED-PAST)

The ruling to document was that later phases, trace checks and feature cycles treat a PROCEED-PAST phase as closed. The code does not do this in one place, so per the instruction nothing was documented and no test was added.

- **Treated as closed (as intended):**
  - phase progression (`state.DONE`);
  - the trace-lint approved-ID set (`contract._approved_ids`);
  - the verifiers' commit range (`verify.base_commit`, from the phase's recorded commit);
  - the baseline a FEATURE needs (`opcmd.baseline_approved`);
  - the retro-pending check;
  - REOPEN.
- **Not treated as closed:** `gate/v1/hlib.py` `v1_phase_doc` maps PROCEED-PAST to v1's `in-review`. Phase 11's `build-scorecard` (`gate/v1/build_scorecard.py`, lines 561 and 1053-1066) counts every phase that is not `APPROVED` as not approved. For a product whose phase 0 was proceeded past and whose later phases were approved, it raises:
  - one PROGRESSION blocker, `phase(s) not APPROVED: 0` (release BLOCKED);
  - one INTEGRITY blocker per later phase, `phase N is APPROVED but its predecessor(s) 0 are not`. That is 13 of them.

  `check-approvals` (also phase 11) only lists phase 0 as "not yet approved" and does not fail.
- **How this was shown:** a probe, kept out of the repository, ran `build_scorecard.py` on two phase docs that differ only in phase 0 (APPROVED vs PROCEED-PAST). The blockers above appear only for PROCEED-PAST.
- **Consequence for onlineMarket:** its phase 11 scorecard will refuse the release until phase 0 is reopened and approved, unless phase 11 is itself proceeded past.
- **Needs a ruling.** One option: v1_phase_doc maps PROCEED-PAST to a closed status that the scorecard accepts but reports, for example "PROCEEDED PAST at seq N: <reason>". The other: the scorecard keeps blocking by design, and the documentation says so.

## Not run here

These need the Keychain or Docker, so they run in Terminal: `tests/corpus/run.py`, `tests/install/dryrun.py` and `tests/confined-engine/run.py`. 0.6.4 changes nothing they depend on except that INIT now writes `.git/info/exclude`. The installer was not run.
