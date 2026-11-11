# MOADIX changes: reflect-queue

- Upstream: https://github.com/BayramAnnakov/claude-reflect
- Commit: b6c42326903af3dd2bf3772b979730a44d8548ca
- Paths drawn on: `SKILL.md`, `commands/reflect.md`, `commands/view-queue.md`, `commands/skip-reflect.md`, `hooks/hooks.json`, `scripts/capture_learning.py`, `scripts/read_queue.py`, `scripts/clear_queue.py`, `scripts/project_paths.py`, `scripts/lib/__init__.py`, `scripts/lib/reflect_utils.py`
- Licence: MIT, Copyright (c) 2025 Bayram Annakov (root LICENSE, copied here as `LICENSE`)
- Vendored: 2026-11-11, for MOADIX phase 12 (Retro)

Upstream is a plugin (hooks + slash commands + a claude-reflect skill), not a single skill directory. This skill keeps its queue pattern: corrections are captured into a queue during work, then reviewed with the human at reflection time. Upstream test suites (`tests/`, `mod/hooks/reflect.test.tsx`) are not copied.

## Files

| MOADIX file | Upstream source | Status |
|---|---|---|
| `SKILL.md` | `SKILL.md` + steps from `commands/reflect.md`, `commands/view-queue.md`, `commands/skip-reflect.md` | rewritten around upstream text (changes 1-12) |
| `scripts/capture_learning.py` | `scripts/capture_learning.py` | adapted (changes 13-15) |
| `scripts/read_queue.py` | `scripts/read_queue.py` | adapted (change 16) |
| `scripts/clear_queue.py` | `scripts/clear_queue.py` | adapted (change 17) |
| `scripts/lib/__init__.py` | `scripts/lib/__init__.py` | verbatim |
| `scripts/lib/reflect_utils.py` | `scripts/lib/reflect_utils.py` | trimmed (changes 18-20) |
| `LICENSE` | `LICENSE` | verbatim |

## Not vendored (adaptation)

- `hooks/hooks.json` (UserPromptSubmit capture, PreCompact check, PostToolUse `post_commit_reminder.py`, SessionStart reminder): a plugin skill cannot install hooks under MOADIX (only managed hooks run). Capture is now an explicit step (change 2). The post-commit reminder is dropped with it.
- `scripts/project_paths.py`: it only resolves paths under `~/.claude/projects/<encoded>/` (session transcripts, queue, auto memory). MOADIX's queue is a fixed repo path and transcripts are not readable by the agent (sandbox `denyRead` on `~/.claude/projects`).
- `scripts/check_learnings.py`, `session_start_reminder.py`, `post_commit_reminder.py`, `extract_session_learnings.py`, `extract_tool_errors.py`, `extract_tool_rejections.py`, `compare_detection.py`, `scripts/legacy/*`: hook helpers or transcript scanners under `~/.claude/projects`.
- `scripts/lib/semantic_detector.py`: runs `claude -p` (a nested Claude session, denied by MOADIX invariant 4). The agent does the semantic review itself in Step 2.
- `commands/reflect-skills.md` and the `--scan-history`, `--dedupe`, `--organize`, `--targets`, `--review` modes of `commands/reflect.md`: transcript scanning and memory-tier reorganisation under `~/.claude/`, outside the queue pattern.
- `mod/` (a Claude Code UI mod), `assets/`, `README.md`, `CHANGELOG.md`, `BACKLOG.md`, `DISTRIBUTION.md`, `RELEASING.md`, `CLAUDE.md`, `.claude-plugin/`, `.github/`: plugin packaging and docs, not part of the pattern.

## Changes to text

### 1. SKILL.md frontmatter (new)
- Original: "name: claude-reflect / description: Self-learning system that captures corrections during sessions and reminds users to run /reflect to update CLAUDE.md. …"
- Replacement: `name: reflect-queue` (equals the directory name) and a description of the explicit capture + retro review with per-item operator agreement.
- Category: adaptation

### 2. SKILL.md, How It Works, Stage 1
- Original: "**Stage 1: Capture (Automatic)** Hooks detect correction patterns (\"no, use X\", \"actually...\", \"use X not Y\") and queue them to `~/.claude/learnings-queue.json`."
- Replacement: "**Stage 1: Capture (explicit, during any phase)**" — the agent runs `capture_learning.py --text … --note … --phase …` itself when the operator corrects it; queue is `docs/retro/learnings-queue.jsonl`; capture only, no edits at capture time; fallback of appending one JSON line by hand.
- Category: adaptation (no hooks; queue moved out of `~/.claude` into an always-writable repo path)

### 3. SKILL.md, How It Works, Stage 2
- Original: "**Stage 2: Process (Manual)** User runs `/reflect` to review and apply queued learnings to CLAUDE.md files."
- Replacement: "**Stage 2: Process (with the operator, at the retro)** … Each learning is written only after the operator agrees to that one item."
- Category: adaptation

### 4. SKILL.md, Available Commands table (removed)
- Original: "| `/reflect` | Process queued learnings with human review | … | `/skip-reflect` | … | `/view-queue` | …"
- Replacement: removed; the steps are in the SKILL.md sections "Processing the Queue (retro)" and "Viewing the Queue". Slash commands are not vendored.
- Category: adaptation

### 5. SKILL.md, "When to Remind Users" (removed)
- Original: "Remind users about `/reflect` when: - They complete a feature or meaningful work unit … - Context is about to compact and queue has items"
- Replacement: removed. The retro runs at MOADIX phase 12, which the operator starts; the agent does not prompt for it on its own.
- Category: auto-advance

### 6. SKILL.md, Correction Detection Patterns
- Original: the five-bullet list.
- Replacement: kept verbatim, plus a paragraph saying `capture_learning.py` uses the same detector and queues unrecognised text as type `manual`.
- Category: adaptation

### 7. SKILL.md, Learning Destinations
- Original: "`~/.claude/CLAUDE.md` … `./CLAUDE.md` … `./CLAUDE.local.md` … `./.claude/rules/*.md` … `~/.claude/rules/*.md` … `~/.claude/projects/<project>/memory/*.md` … `commands/*.md` - Skill improvements"
- Replacement: only `./CLAUDE.md`, `docs/retro/learnings.md`, or another `docs/` file the operator names; explicit ban on `~/.claude/` and `.claude/`.
- Category: adaptation (MOADIX path map: `CLAUDE.md` and `docs/**` always writable; `~/.claude/**` and `.claude/**` never). Skill-file edits are also dropped: vendored skills change only through an approved upgrade proposal.

### 8. SKILL.md, Processing steps (from commands/reflect.md Steps 1-9)
- Original: Step 1 "Read the queue with `python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/read_queue.py\"` …"; Step 1.5 semantic validation via `claude -p`; Step 3 project-aware filtering with "Offer: [a]pprove | [e]dit | [s]kip"; Step 5 summary table; 5b "Apply all (Recommended)" / "Select which to apply" / "Review details first" / "Skip all"; Step 6 "Apply [N] learnings to target files?" with "Yes, apply all"; Step 7 apply to CLAUDE.md, rule files, auto memory, skill files; Step 8 `clear_queue.py`; Step 9 "DONE: Applied [N] learnings"; Step 10 "touch \"<session_dir>/.reflect-initialized\"".
- Replacement: Steps 1-7 in SKILL.md: load; agent's own review (replaces `claude -p`); summary table (kept, Target column now a file path); per-item learning card (upstream "Full learning card format", kept) ending with "Write this? [y]es | [e]dit | [d]ifferent destination | [s]kip | [l]ater"; write agreed items with Edit; clear queue with `--keep`; report.
- Category: adaptation (per-item operator agreement; "apply all" removed so nothing is written without the operator answering for that item); the "[a]pprove" option label is reworded to "[y]es" since it is the operator's answer, not an agent approval.

### 9. SKILL.md, Step 5 "Do not commit anything." (added)
- Original: (none)
- Replacement: "Do not commit anything. The written files are part of the retro's output for the operator to review."
- Category: commit

### 10. SKILL.md, Step 7 Report
- Original: "DONE: Applied [N] learnings … ✓ ~/.claude/CLAUDE.md … ⚡ commands/deploy.md …"
- Replacement: "Learnings written: [N]" with `./CLAUDE.md` and `docs/retro/learnings.md` rows, then "Then stop. Whether the retro is accepted is the operator's decision (MOADIX gate)."
- Category: mark-done

### 11. SKILL.md, Step 10 Mark Initialized (removed)
- Original: "Create marker file for THIS project so first-run detection won't trigger again. … `touch \"<session_dir>/.reflect-initialized\"`"
- Replacement: removed (wrote under `~/.claude/projects`).
- Category: adaptation

### 12. SKILL.md, Viewing the Queue / discard / Size Check / Example
- Original: `commands/view-queue.md` output format footer "Commands: /reflect - Process and save learnings / /skip-reflect - Discard all learnings"; `commands/skip-reflect.md` "Are you sure? [y/n]"; reflect.md Size Check "/reflect --dedupe … /reflect --organize"; SKILL.md example "[Hook captures this correction to queue] … Apply to ~/.claude/CLAUDE.md? [y/n]".
- Replacement: one-line-per-item view (format kept, command footer removed); discard keeps the "Are you sure? [y/n]" confirmation; Size Check suggests consolidating or moving entries to `docs/retro/learnings.md`; example shows the explicit capture call and the per-item question with `./CLAUDE.md`. Formatting Rules and Section Headers kept verbatim.
- Category: adaptation

## Changes to scripts

### 13. capture_learning.py: hook input replaced by a CLI
- Original: "Detect and capture correction patterns from user prompts. UserPromptSubmit hook." … `input_data = sys.stdin.read()` … `data = json.loads(input_data)` … `prompt = data.get("prompt") …` … `project_dir = project_dir_from_transcript(data.get("transcript_path"))`
- Replacement: `argparse` with `--text` (or plain stdin), `--note`, `--phase`, `--repo`; no transcript path.
- Category: adaptation (no hooks)

### 14. capture_learning.py: queue path
- Original: `queue_path = queue_path_for_folder(project_dir) if project_dir else get_queue_path()` (under `~/.claude/projects/<encoded>/learnings-queue.json`), whole-file `load_queue_at`/`save_queue_at`.
- Replacement: `append_to_queue(queue_item, args.repo)` → `docs/retro/learnings-queue.jsonl` in the product repo, one JSON line per entry.
- Category: adaptation

### 15. capture_learning.py: undetected text, length filter, error handling
- Original: queued only `if item_type:`; skipped prompts longer than `MAX_CAPTURE_PROMPT_LENGTH` unless they contain "remember:"; any exception printed a warning and exited 0 ("Never block on errors").
- Replacement: undetected text is queued as type `manual`, confidence 0.60 (the agent calls the script only for text it judged a correction); no length filter (explicit calls are not raw prompts); errors exit non-zero so the agent sees them. Optional `note`/`phase` fields added to the entry.
- Category: adaptation

### 16. read_queue.py
- Original: `print(json.dumps(load_queue(), indent=2))` reading the `~/.claude` queue.
- Replacement: optional `--repo`; reads the JSONL repo queue; `ensure_ascii=False`.
- Category: adaptation

### 17. clear_queue.py
- Original: positional project argument; `save_queue([], project)` on the `~/.claude` queue; docstring about `echo "[]" > ~/.claude/learnings-queue.json`.
- Replacement: `--repo` and `--keep "1,4"` (keeps entries the operator deferred); clears the JSONL repo queue. Docstring: run only after the operator decided every item or said to discard them.
- Category: adaptation

### 18. lib/reflect_utils.py: path and queue functions replaced
- Original: `get_queue_path`, `project_dir_from_transcript`, `queue_path_for_folder`, `load_queue_at`, `save_queue_at`, `get_global_queue_path`, `migrate_global_queue`, `get_backup_dir`, `get_claude_dir`, `get_cleanup_period_days`, `load_queue`, `save_queue`, `append_to_queue` (all under `~/.claude`).
- Replacement: `QUEUE_RELPATH = docs/retro/learnings-queue.jsonl`, `get_repo_root`, `get_queue_path`, `load_queue`, `append_to_queue`, `save_queue` (atomic temp-file-and-replace and its rationale kept from `save_queue_at`).
- Category: adaptation

### 19. lib/reflect_utils.py: removed sections
- Original: CLAUDE.md/rule-file discovery and @-include graph, `suggest_claude_file`, project-folder encoders and legacy migrations, auto memory, `extract_user_messages`, `extract_tool_rejections`, tool-error extraction/aggregation.
- Replacement: removed (all read or write under `~/.claude` or parse transcripts). Unused imports `unicodedata` and `deque` dropped.
- Category: adaptation

### 20. lib/reflect_utils.py: kept verbatim
- `ensure_utf8_io`, timestamp utilities, every pattern list, `detect_patterns`, `create_queue_item`, `should_include_message` and its alias. Module docstring extended with a MOADIX note.
- Category: adaptation (docstring only)

## Grep allowlist
None needed.
