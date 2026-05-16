"""composio `mcp` adapter.

Upstream reference: https://github.com/composiohq/composio

Returns the live MCP catalog (name + description) as JSON — the composio
agent's MCP bridge expects to enumerate available tools before routing.
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def mcp() -> str:
    """List MCP-registered tools as JSON `[{name, description}]`."""
    from evomas.mcp.server import MCPServer
    catalog = [
        {"name": d.name, "description": d.description}
        for d in MCPServer().registry.tools.values()
    ]
    catalog.sort(key=lambda x: x["name"])
    logger.info("[composio.mcp] catalog size=%d", len(catalog))
    return json.dumps(catalog)
