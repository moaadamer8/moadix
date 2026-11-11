#!/usr/bin/env python3
"""Shared utilities for claude-reflect hooks and scripts.

Cross-platform compatible (Windows, macOS, Linux).

MOADIX: trimmed copy for the reflect-queue skill. Kept verbatim: UTF-8 I/O,
timestamps, pattern definitions, detect_patterns, create_queue_item,
should_include_message. Replaced: every path and queue function (upstream kept
the queue in the user's Claude Code home directory, under projects/<encoded>/);
the queue is now docs/retro/learnings-queue.jsonl inside the product repo.
Removed: memory-file discovery, rule files, auto memory, session-transcript and
tool-error extraction, legacy migrations. See ../../MOADIX-CHANGES.md.
"""
import json
import re
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

# =============================================================================
# Hook I/O encoding
# =============================================================================

def ensure_utf8_io() -> None:
    """Force stdin/stdout/stderr to UTF-8 so hooks work on a Windows console.

    Windows defaults these streams to the locale codepage (cp1252, cp1251...).
    Two failures follow, both silent to the user:

    * Reading a non-ASCII prompt off stdin mangles it, so the *stored* learning
      is mojibake even though capture "succeeded".
    * Printing the acknowledgement raises ``UnicodeEncodeError`` on any emoji,
      which trips each hook's top-level ``except`` and replaces the
      confirmation with a stderr warning on every single capture.

    No-ops where a stream cannot be reconfigured -- already wrapped, detached,
    or replaced by a test harness.

    Credit: stdout/stderr half from #38 (@keitaemsden-lab), stdin half
    reported in #41 (@George-tmm).
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError, AttributeError):
            pass


# =============================================================================
# Queue location and operations (MOADIX)
# =============================================================================
#
# The queue lives inside the product repo, in a path the agent may always
# write (docs/**), never in the user's Claude Code home directory or the
# repo's Claude Code configuration directory. One JSON object per line, so an
# entry is appended without rewriting the file.

QUEUE_RELPATH = os.path.join("docs", "retro", "learnings-queue.jsonl")


def get_repo_root(repo: Optional[str] = None) -> Path:
    """Product repo root: --repo, else $CLAUDE_PROJECT_DIR, else the cwd."""
    return Path(repo or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def get_queue_path(repo: Optional[str] = None) -> Path:
    """docs/retro/learnings-queue.jsonl in the product repo."""
    return get_repo_root(repo) / QUEUE_RELPATH


def load_queue(repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read every entry; a malformed line is skipped, not fatal."""
    path = get_queue_path(repo)
    if not path.exists():
        return []
    items = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                items.append(item)
    except (IOError, OSError):
        return []
    return items


def append_to_queue(item: Dict[str, Any], repo: Optional[str] = None) -> Path:
    """Append one entry as a single JSON line."""
    path = get_queue_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


def save_queue(items: List[Dict[str, Any]], repo: Optional[str] = None) -> None:
    """Rewrite the queue atomically (used to clear it or keep undecided entries).

    Upstream's reason for the temp-file-and-replace, kept: a plain write
    truncates first, so a crash or a concurrent reader between truncate and
    write sees an empty or half-written file.
    """
    path = get_queue_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# =============================================================================
# Timestamp utilities
# =============================================================================

def iso_timestamp() -> str:
    """Get current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def backup_timestamp() -> str:
    """Get timestamp for backup filenames."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# =============================================================================
# Pattern definitions (from capture-learning.sh)
# =============================================================================

# Explicit marker patterns (highest confidence)
EXPLICIT_PATTERNS = [
    (r"remember:", "remember:", 0.90, 120),  # pattern, name, confidence, decay_days
]

# Positive feedback patterns
POSITIVE_PATTERNS = [
    (r"perfect!|exactly right|that's exactly", "perfect", 0.70, 90),
    (r"that's what I wanted|great approach", "great-approach", 0.70, 90),
    (r"keep doing this|love it|excellent|nailed it", "keep-doing", 0.70, 90),
]

# Correction patterns (conservative set to minimize false positives)
# Format: (regex_pattern, pattern_name, is_strong)
#
# DESIGN NOTES:
# - These patterns are English-centric as a FAST first-pass filter
# - Non-English corrections are caught by semantic filtering during /reflect
# - We use STRUCTURAL signals (length, questions, task requests) for language-agnostic filtering
# - Users can use explicit markers like "remember:" in any language
#
CORRECTION_PATTERNS = [
    # Deliberately broad. An allowlist of continuations was tried and it
    # dropped the highest-value captures this plugin exists for -- project
    # rules like "no semicolons in this codebase", "no emojis in commit
    # messages", "no typescript any, ever" -- while still admitting benign
    # replies, because "it", "this", "you" and "i" are exactly the words that
    # open one. The benign shapes are denied by name in NON_CORRECTION_PHRASES
    # instead, and anything that slips past is caught by the semantic pass at
    # /reflect time. A false positive costs one queue line; a false negative
    # costs the learning.
    (r"^no[,.!:;\u2014\u2013-]+\s*\S", "no,", True),
    (r"^no\s+\S", "no-bare", True),
    (r"^don't\b|^do not\b", "don't", True),  # Starts with don't/do not
    (r"^stop\b|^never\b", "stop/never", True),  # Starts with stop/never
    (r"that's (wrong|incorrect)|that is (wrong|incorrect)", "that's-wrong", True),
    (r"^actually[,. ]", "actually", False),  # Starts with "actually"
    (r"^I meant\b|^I said\b", "I-meant/said", True),  # Clarification
    (r"^I told you\b|^I already told\b", "I-told-you", True),  # Higher confidence
    (r"use .{1,30} not\b", "use-X-not-Y", True),  # "use X not Y" - limited gap
]

# Guardrail patterns - "don't do X unless" constraints (highest confidence for corrections)
# These detect user frustrations about Claude making unwanted changes
# Format: (regex_pattern, pattern_name, confidence, decay_days)
GUARDRAIL_PATTERNS = [
    (r"don't (?:add|include|create) .{1,40} unless", "dont-unless-asked", 0.90, 120),
    (r"only (?:change|modify|edit|touch) what I (?:asked|requested|said)", "only-what-asked", 0.90, 120),
    (r"stop (?:refactoring|changing|modifying|editing) (?:unrelated|other|surrounding)", "stop-unrelated", 0.90, 120),
    (r"don't (?:over-engineer|add extra|be too|make unnecessary)", "dont-over-engineer", 0.85, 90),
    (r"don't (?:refactor|reorganize|restructure) (?:unless|without)", "dont-refactor-unless", 0.85, 90),
    (r"leave .{1,30} (?:alone|unchanged|as is)", "leave-alone", 0.85, 90),
    (r"don't (?:add|include) (?:comments|docstrings|type hints|annotations) (?:unless|to code)", "dont-add-annotations", 0.85, 90),
    (r"(?:minimal|minimum|only necessary) changes", "minimal-changes", 0.80, 90),
]

# Structural patterns indicating FALSE POSITIVES (language-agnostic)
# These focus on MESSAGE STRUCTURE rather than specific words
FALSE_POSITIVE_PATTERNS = [
    r"[?\uff1f]$",  # Ends with question mark (ASCII ? or full-width ？)
    r"[\u55ce\u5417\u5462\u304b\uae4c]$",  # Ends with CJK question particle (嗎吗呢か까)
    r"^(please|can you|could you|would you|help me)\b",  # Task request openers
    r"(help|fix|check|review|figure out|set up)\s+(this|that|it|the)\b",  # Task verbs
    r"(error|failed|could not|cannot|can't|unable to)\s+\w+",  # Error descriptions
    r"(is|was|are|were)\s+(not|broken|failing)",  # Bug reports
    r"^I (need|want|would like)\b",  # Task requests
    r"^(ok|okay|alright)[,.]?\s+(so|now|let)",  # Task continuations
]

# English phrases that look like correction openers but are NOT corrections
# Especially important for CJK-mixed text where these appear naturally
NON_CORRECTION_PHRASES = [
    r"^no\s+problem",        # "No problem" - agreement
    r"^no\s+worries",        # "No worries" - agreement
    r"^no\s+need\b",         # "No need" - acknowledgment
    r"^no\s+way\b",          # "No way!" - surprise/exclamation
    r"^don't\s+worry",       # "Don't worry" - reassurance
    r"^don't\s+mind",        # "Don't mind" - agreement
    r"^don't\s+bother",      # "Don't bother" - polite decline
    r"^never\s+mind",        # "Never mind" - dismissal
    # Answers to a question, not corrections. These are why the "no"
    # patterns above need a deny-list at all.
    r"^no\s+idea\b",
    r"^no\s+(?:it|that|this|we|i|you|they)\s+"
    r"(?:works?|worked|looks?|seems?|sounds?|reads?)\b",
    r"^no\s+(?:it|that|this)\s+(?:'s|is|was)\s+(?:fine|good|ok|okay|right|correct)\b",
    r"^no\s+(?:i|we)\s+(?:think|guess|believe|reckon)\b",
    r"^no\s+(?:you|we|i)\s+(?:can|could|should)\s+go\s+ahead\b",
    r"^no\s+(?:i|we)(?:'m|'re| am| are)?\s+(?:all\s+)?(?:good|done|set|fine)\b",
    # Reports of absence: "no dialog appeared", "no changes were applied".
    r"^no\s+[\w-]+\s+(?:appeared|happened|occurred|showed|showed\s+up|returned"
    r"|existed|came|come|changed|matched|was|were|has|have|had)\b",
    r"^no\s+(?:rush|hurry|pressure|problem|stress)\b",
    r"^stop\s+worrying",     # "Stop worrying" - reassurance
]

# CJK correction patterns (parallel to English CORRECTION_PATTERNS)
# These detect explicit corrections in CJK languages
# Format: (regex_pattern, pattern_name, is_strong)
CJK_CORRECTION_PATTERNS = [
    # Japanese
    (r"^いや[、,.\s]|^いや違", "iya", True),       # いや、〜 / いや違う - "no, ..."
    (r"^違う[、，,.\s！!。]|^ちがう[、,.\s]", "chigau", True),  # 違う、〜 - "wrong, ..."
    (r"そうじゃなく[てけ]|そっちじゃなく[てけ]", "souja-nakute", True),  # "not that"
    (r"間違[いえっ]て", "machigatte", True),       # 間違ってる - "it's wrong"
    (r"じゃなくて.{0,30}にして", "janakute-nishite", True),  # 〜じゃなくて〜にして
    (r"^やめて[。！!]?\s*$", "yamete", True),      # やめて - "stop"
    (r"^そうじゃない", "souja-nai", True),          # そうじゃない - "that's not right"
    (r"って言った[のよでじゃ]", "tte-itta", True),   # って言ったのに - "I told you"
    # Chinese
    (r"^不是[，,. ]", "bushi", True),              # 不是、〜 - "no, ..."
    (r"^错了|^錯了", "cuole", True),               # 错了 - "wrong"
    (r"不要.{0,20}要", "buyao-yao", True),         # 不要X要Y - "don't X, use Y"
    # Korean
    (r"^아니[,. ]", "ani", True),                  # 아니, - "no, ..."
    (r"틀렸", "teullyeoss", True),                 # 틀렸 - "wrong"
]

# Maximum prompt length for live capture (UserPromptSubmit hook)
# Prompts longer than this are almost certainly system content, not user corrections.
# Exception: explicit "remember:" markers are always processed regardless of length.
MAX_CAPTURE_PROMPT_LENGTH = 500

# Forward-pivot patterns — phrases that indicate the message body is a
# task instruction following a positive-feedback opener, NOT retrospective
# feedback. "Perfect! Now let's add X" is structurally a task pivot, not
# validation of past work. Applied ONLY to positive-pattern matches; real
# corrections (e.g. "Now let's stop refactoring") still get captured by
# CORRECTION_PATTERNS since those signals are directive-as-content, not
# directive-as-followup.
#
# Distinct from FALSE_POSITIVE_PATTERNS (which apply to all detections)
# and NON_CORRECTION_PHRASES (which neutralize correction openers like
# "no problem"). This list neutralizes positive openers when the message
# body is a fresh request rather than reflection on past behavior.
# Narrow on purpose. A broader version rejected ordinary praise: "Nailed it!
# Please keep using this pattern", "that's exactly right, we need to remember
# this", "Perfect... Now I understand why it fails" -- all retrospective
# feedback that merely contains "please", "we need to" or "now I". A pivot
# has to introduce a NEW instruction, so require an imperative after it
# rather than any of those words appearing anywhere in the message.
_SLASH_COMMAND_RE = re.compile(r"/[A-Za-z][\w.-]*(?::[\w.-]+)?(?:\s|$)")

FORWARD_PIVOT_PATTERNS = [
    r"\b(now|next)[, ]+let'?s\b",
    r"\b(now|next)[, ]+(we|i)\s+(need to|should|have to|must|will)\b",
    r"\blet'?s (add|do|build|move|update|change|fix|implement)\b",
    r"\bgo ahead and\s+\w+",
]

# Maximum message length for weak patterns (structural heuristic)
# Long messages are more likely to be context/tasks than corrections
MAX_WEAK_PATTERN_LENGTH = 150

# Very short messages without question marks are more likely corrections
MIN_SHORT_CORRECTION_LENGTH = 80

# Minimum length for a positive to be worth queueing.
# Bare praise ("i love it", "perfect!", "nailed it") has no referent — by the
# time /reflect runs, there is no way to tell what was being praised, so it
# cannot become a memory. Longer positives usually name the thing.
MIN_POSITIVE_CONTEXT_LENGTH = 25


def detect_patterns(text: str) -> Tuple[Optional[str], str, float, str, int]:
    """
    Detect patterns in text and return classification.

    Returns:
        Tuple of (type, matched_patterns, confidence, sentiment, decay_days)
        type: "explicit", "positive", "auto", "guardrail", or None
        matched_patterns: Space-separated pattern names
        confidence: 0.0 to 1.0
        sentiment: "correction" or "positive"
        decay_days: Number of days until decay
    """
    # Slash-command guard — /loop, /reflect, /ia:full-review etc. expand
    # into long skill bodies that incidentally contain correction tokens
    # (e.g. "use" + "not" in unrelated text). Slash commands are skill
    # invocations, never user feedback, so they should never enter the
    # queue. This is the FIRST check because no downstream pattern
    # (explicit, positive, correction, guardrail) should fire on them.
    # A slash COMMAND, not any leading slash. The earlier startswith("/")
    # also ate absolute paths and comments -- "/etc/hosts is wrong, use
    # 127.0.0.1 not localhost" and "/Users/bob/gen.ts - remember: never edit
    # generated files" both vanished, the second one breaking the documented
    # promise that "remember:" is always processed. A command is one token of
    # word characters (optionally plugin:name) with no second slash.
    if _SLASH_COMMAND_RE.match(text.lstrip()):
        return (None, "", 0.0, "correction", 90)

    # Too short to be actionable (e.g. "OK", "好", "yes")
    # CJK characters carry more meaning per char, so use a lower threshold
    stripped = text.strip()
    has_cjk = bool(re.search(r'[\u3000-\u9fff\uf900-\ufaff\uac00-\ud7af]', stripped))
    short_threshold = 2 if has_cjk else 4
    if len(stripped) <= short_threshold:
        return (None, "", 0.0, "correction", 90)

    # Check for explicit "remember:" - always highest priority
    for pattern, name, confidence, decay in EXPLICIT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return ("explicit", name, confidence, "correction", decay)

    # Check for guardrail patterns - "don't do X unless" constraints
    # These are high-confidence corrections about unwanted behavior
    for pattern, name, confidence, decay in GUARDRAIL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return ("guardrail", name, confidence, "correction", decay)

    # Check for FALSE POSITIVE patterns - skip these messages
    for fp_pattern in FALSE_POSITIVE_PATTERNS:
        if re.search(fp_pattern, text, re.IGNORECASE):
            return (None, "", 0.0, "correction", 90)

    # Check for non-correction English phrases (before correction patterns)
    # Prevents "No problem", "Don't worry" etc. from being caught as corrections
    for nc_pattern in NON_CORRECTION_PHRASES:
        if re.search(nc_pattern, text, re.IGNORECASE):
            return (None, "", 0.0, "correction", 90)

    # Check for positive patterns
    matched_positive = []
    for pattern, name, confidence, decay in POSITIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            matched_positive.append(name)

    if matched_positive:
        # Bare praise carries no referent — drop it rather than queue an
        # item that /reflect cannot turn into anything.
        if len(text.strip()) < MIN_POSITIVE_CONTEXT_LENGTH:
            return (None, "", 0.0, "positive", 90)

        # Forward-pivot guard — "Perfect! Now let's add X" matches the
        # positive pattern but the body is a fresh task instruction, not
        # retrospective feedback. Reject so we don't pollute the queue
        # with task pivots (which are never reusable learnings).
        # Applied ONLY here, not to corrections — "Now let's stop X" is
        # a legitimate correction even when phrased as a task pivot.
        for fp_pattern in FORWARD_PIVOT_PATTERNS:
            if re.search(fp_pattern, text, re.IGNORECASE):
                return (None, "", 0.0, "correction", 90)
        return ("positive", " ".join(matched_positive), 0.70, "positive", 90)

    # Skip long messages for weak patterns (likely task requests)
    text_length = len(text)

    # Check for CJK correction patterns (language-specific)
    # Use stripped text for anchor patterns (^/$) to handle leading/trailing whitespace
    matched_cjk = []
    cjk_strong = False
    for pattern, name, is_strong in CJK_CORRECTION_PATTERNS:
        if re.search(pattern, stripped):
            matched_cjk.append(name)
            if is_strong:
                cjk_strong = True

    if matched_cjk:
        confidence = 0.75 if cjk_strong else 0.60
        decay_days = 90 if cjk_strong else 60
        if text_length < MIN_SHORT_CORRECTION_LENGTH:
            confidence = min(0.90, confidence + 0.10)
        elif text_length > 300:
            confidence = max(0.50, confidence - 0.15)
        return ("auto", " ".join(matched_cjk), confidence, "correction", decay_days)

    # Check for English correction patterns
    matched_corrections = []
    pattern_count = 0
    has_strong_pattern = False
    has_i_told_you = False

    for pattern, name, is_strong in CORRECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            # Skip weak patterns in long messages
            if not is_strong and text_length > MAX_WEAK_PATTERN_LENGTH:
                continue
            matched_corrections.append(name)
            pattern_count += 1
            if is_strong:
                has_strong_pattern = True
            if name == "I-told-you":
                has_i_told_you = True

    if matched_corrections:
        # Calculate confidence based on pattern count, type, and length
        if has_i_told_you:
            confidence = 0.85
            decay_days = 120
        elif pattern_count >= 3:
            confidence = 0.85
            decay_days = 120
        elif pattern_count >= 2:
            confidence = 0.75
            decay_days = 90
        elif has_strong_pattern:
            confidence = 0.70
            decay_days = 60
        else:
            confidence = 0.55  # Reduced for weak single patterns
            decay_days = 45

        # Adjust confidence based on message length (structural signal)
        # Short messages are more likely to be direct corrections
        if text_length < MIN_SHORT_CORRECTION_LENGTH:
            confidence = min(0.90, confidence + 0.10)  # Boost for short messages
        elif text_length > 300:
            confidence = max(0.50, confidence - 0.15)  # Reduce for long messages
        elif text_length > 150:
            confidence = max(0.55, confidence - 0.10)

        return ("auto", " ".join(matched_corrections), confidence, "correction", decay_days)

    return (None, "", 0.0, "correction", 90)


def create_queue_item(
    message: str,
    item_type: str,
    patterns: str,
    confidence: float,
    sentiment: str,
    decay_days: int,
    project: Optional[str] = None
) -> Dict[str, Any]:
    """Create a properly formatted queue item."""
    return {
        "type": item_type,
        "message": message,
        "timestamp": iso_timestamp(),
        "project": project or os.getcwd(),
        "patterns": patterns,
        "confidence": confidence,
        "sentiment": sentiment,
        "decay_days": decay_days,
    }


def should_include_message(text: str) -> bool:
    """Check if a message should be included in learning detection.

    Filters out system content like XML tags, JSON, tool results, and
    session continuations that should never be treated as user corrections.

    Used by both session file extraction and live capture (UserPromptSubmit hook).
    """
    # Skip empty lines
    if not text.strip():
        return False

    # Skip lines starting with certain patterns
    skip_patterns = [
        r"^<",              # XML tags (<task-notification>, <system-reminder>, etc.)
        r"^\[",             # Brackets
        r"^\{",             # JSON
        r"tool_result",
        r"tool_use_id",
        r"<command-",
        r"<task-notification>",
        r"<system-reminder>",
        r"This session is being continued",
        r"^Analysis:",
        r"^\*\*",           # Bold text
        r"^   -",           # Indented lists
    ]

    for pattern in skip_patterns:
        if re.search(pattern, text):
            return False

    return True


# Backward-compatible alias
_should_include_message = should_include_message
