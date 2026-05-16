"""debug_gym `tool` tool.

Upstream reference: https://github.com/microsoft/debug-gym/blob/main/debug_gym/tool.py

The upstream `tool.py` is debug-gym's base Tool class — not directly a
callable. The closest useful operation for an EvoMas debug-gym agent is
"what's testable in this workspace?", so this tool enumerates test files
and returns a JSON manifest the agent can iterate over.
"""
from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_TEST_GLOBS = ("test_*.py", "*_test.py", "tests.py")
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


@tool
def tool(workspace: str = ".") -> str:
    """List test files under `workspace` so a debugging agent knows
    what to run / inspect. Returns JSON with `tests` (list of relative
    paths) and `count`."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        return json.dumps({"error": f"not a directory: {workspace}"})
    matches: list[str] = []
    for p in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        name = p.name
        if any(fnmatch.fnmatch(name, g) for g in _TEST_GLOBS):
            matches.append(str(p.relative_to(root)).replace("\\", "/"))
    matches.sort()
    logger.info("[debug_gym.tool] %s -> %d test files", root, len(matches))
    return json.dumps({"tests": matches, "count": len(matches)})
