#!/usr/bin/env python3
"""Print the current project's learnings queue as JSON. Helper for slash commands.

MOADIX: reads docs/retro/learnings-queue.jsonl in the product repo
(--repo, else $CLAUDE_PROJECT_DIR, else cwd). Read-only.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.reflect_utils import load_queue  # noqa: E402
import json  # noqa: E402

repo = None
if len(sys.argv) > 2 and sys.argv[1] == "--repo":
    repo = sys.argv[2]

print(json.dumps(load_queue(repo), indent=2, ensure_ascii=False))
