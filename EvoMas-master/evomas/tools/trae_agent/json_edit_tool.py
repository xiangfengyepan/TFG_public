"""trae_agent `json_edit_tool`.

Upstream reference: https://github.com/bytedance/trae-agent/blob/main/trae_agent/tools/json_edit_tool.py
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


import json
from pathlib import Path


@tool
def json_edit_tool(path: str, key: str, value: str) -> str:
    """Read a JSON file, set top-level `key` to `value` (parsed as JSON
    if possible, else stored as a string), write it back, return "ok"."""
    p = Path(path)
    if not p.is_file():
        return f"error: {path} is not a file."
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"error: {path} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return "error: top-level JSON value must be an object to set a key."
    try:
        data[key] = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        data[key] = value
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "ok"
