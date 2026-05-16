"""patchwork `tool` tool.

Upstream reference: https://github.com/patched-codes/patchwork/blob/main/patchwork/common/tools/tool.py

The upstream `tool.py` is patchwork's base Tool class. The closest useful
operation for a patchwork agent is a workspace source-file manifest —
list every `.py` file with a 1-line module-docstring summary so the LLM
gets a navigable index without a separate ls + read round-trip.
"""
from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def _summary(p: Path) -> str:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return ""
    doc = ast.get_docstring(tree)
    if not doc:
        return ""
    return doc.splitlines()[0][:120]


@tool
def tool(workspace: str = ".", limit: int = 50) -> str:
    """Return a JSON manifest of `.py` files under `workspace` with each
    file's module-docstring first line (when present). Output is capped
    at `limit` entries."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        return json.dumps({"error": f"not a directory: {workspace}"})
    out: list[dict[str, str]] = []
    for p in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        out.append({
            "path": str(p.relative_to(root)).replace("\\", "/"),
            "summary": _summary(p),
        })
        if len(out) >= limit:
            break
    logger.info("[patchwork.tool] %s -> %d files", root, len(out))
    return json.dumps({"files": out, "count": len(out)})
