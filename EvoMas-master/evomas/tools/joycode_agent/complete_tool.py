"""joycode_agent `complete_tool`.

Upstream reference: https://github.com/JoyCodeAgent/joycode-agent

Writes a `.evomas/state.json` marker into `workspace` (when provided)
and returns the structured record.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def complete_tool(result: str = "", workspace: str = "", agent: str = "joycode") -> str:
    """Mark `agent` as done with optional `result`. Returns JSON
    `{agent, completed, result, ts}`. When `workspace` is set, drops
    a `.evomas/state.json` file inside it."""
    record = {"agent": agent, "completed": True, "result": result, "ts": time.time()}
    if workspace:
        try:
            p = Path(workspace) / ".evomas"
            p.mkdir(parents=True, exist_ok=True)
            (p / "state.json").write_text(json.dumps(record), encoding="utf-8")
        except OSError:
            pass
    logger.info("[joycode.complete] %s", record)
    return json.dumps(record)
