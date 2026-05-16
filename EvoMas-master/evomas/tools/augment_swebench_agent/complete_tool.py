"""augment_swebench_agent `complete_tool`.

Upstream reference: https://github.com/augmentcode/augment-swebench-agent

Signals task completion. Writes `.evomas/state.json` with
`{completed, result, ts}` into `workspace` (when provided) so an external
orchestrator can observe the marker, and returns the JSON record.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def complete_tool(result: str = "", workspace: str = "", agent: str = "augment") -> str:
    """Mark `agent` as done with optional `result`. Returns JSON
    `{agent, completed, result, ts}`. When `workspace` is set, drops
    a `.evomas/state.json` file inside it for out-of-process callers."""
    record = {"agent": agent, "completed": True, "result": result, "ts": time.time()}
    if workspace:
        try:
            p = Path(workspace) / ".evomas"
            p.mkdir(parents=True, exist_ok=True)
            (p / "state.json").write_text(json.dumps(record), encoding="utf-8")
        except OSError:
            pass
    logger.info("[augment.complete] %s", record)
    return json.dumps(record)
