"""augment_swebench_agent `sequential_thinking_tool`.

Upstream reference: https://github.com/augmentcode/augment-swebench-agent

Records a step of reasoning to the log and returns a structured ack the
agent can use to verify its own step counter. No shared cross-tool state
— each call is self-contained.
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
    agent: str = "augment",
) -> str:
    """Record a thought for `agent` and return JSON
    `{agent, step, total, thought}`. The orchestrator's text log captures
    every call so the trajectory is reconstructable post-run."""
    summary = {"agent": agent, "step": step, "total": total, "thought": thought}
    logger.info("[augment.thinking] %s", summary)
    return json.dumps(summary)
