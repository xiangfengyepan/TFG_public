"""claude_coder `index` tool.

Upstream reference: https://github.com/anthropics/claude-code/blob/main/src/index.ts

Returns a JSON summary of a workspace directory: root path, top-level file
list (up to 100 entries, depth 2), and an extension histogram. The shape
matches what an agent typically asks for first when given a fresh repo
checkout — "what am I looking at?" — without having to grep + list_files
itself.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".angular", ".pytest_cache"}


@tool
def index(workspace: str = ".") -> str:
    """Summarize a workspace: root, top-level entries, language histogram.

    Returns a JSON string with keys `root`, `entries`, `extensions`. Use
    this as the first call when handed an unfamiliar repository.
    """
    root = Path(workspace).resolve()
    if not root.is_dir():
        return json.dumps({"error": f"not a directory: {workspace}"})
    entries: list[str] = []
    ext_counts: Counter[str] = Counter()
    for p in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        rel = p.relative_to(root)
        if len(rel.parts) > 2:
            continue
        if p.is_file():
            ext_counts[p.suffix or "(none)"] += 1
            if len(entries) < 100:
                entries.append(str(rel))
        elif p.is_dir() and len(rel.parts) == 1:
            entries.append(f"{rel}/")
    out = {
        "root": str(root),
        "entries": entries,
        "extensions": dict(ext_counts.most_common(10)),
    }
    logger.info("[claude_coder.index] %s -> %d entries", root, len(entries))
    return json.dumps(out)
