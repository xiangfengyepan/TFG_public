"""joycode_agent `sequential_thinking_tool`.

Upstream reference: https://github.com/JoyCodeAgent/joycode-agent

Logs a reasoning step and returns a structured ack. Each call is
self-contained; the orchestrator's text log captures the full trajectory.
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def sequential_thinking_tool(
    thought: str,
    step: int = 0,
    total: int = 0,
    agent: str = "joycode",
) -> str:
    """Record a thought for `agent` and return JSON
    `{agent, step, total, thought}`."""
    summary = {"agent": agent, "step": step, "total": total, "thought": thought}
    logger.info("[joycode.thinking] %s", summary)
    return json.dumps(summary)
