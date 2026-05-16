"""composio `langchain_agent` adapter.

Upstream reference: https://github.com/composiohq/composio

Returns the agent registry from a loaded EvoMas config in LangChain-flavoured
shape: `[{name, class, model, tools: [names]}]`. Composio's langchain
adapter expects this exact shape to wrap agents into LangChain runnables.
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def langchain_agent(config: str = "chain") -> str:
    """List the agents in `config` (default: the `chain` predefined
    topology) as JSON `[{name, class, model, tools}]`."""
    from evomas.config.loader import load_config
    try:
        cfg = load_config(config)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc), "config": config})
    agents = []
    for name, block in (cfg.get("agents") or {}).items():
        agents.append({
            "name": name,
            "class": block.get("class", ""),
            "model": block.get("model", ""),
            "tools": [t.get("name") for t in (block.get("tools") or []) if isinstance(t, dict)],
        })
    logger.info("[composio.langchain_agent] config=%s -> %d agents", config, len(agents))
    return json.dumps(agents)
