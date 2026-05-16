"""suna `tools` tool.

Upstream reference: https://github.com/kortix-ai/suna

Suna is a general-purpose assistant framework; its "tools" namespace
holds the agent's tool registry. The closest useful operation for an
EvoMas suna agent is "list the tools I can call (optionally filtered by
keyword)" — implemented here against the live MCP registry.
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def tools(category: str = "") -> str:
    """List MCP-registered tool names, optionally filtered to names or
    descriptions containing `category` (case-insensitive substring).
    Returns JSON `{tools: [...], count: N}`."""
    from evomas.mcp.server import MCPServer
    cat = (category or "").strip().lower()
    out: list[str] = []
    for descriptor in MCPServer().registry.tools.values():
        haystack = f"{descriptor.name} {descriptor.description}".lower()
        if not cat or cat in haystack:
            out.append(descriptor.name)
    out.sort()
    logger.info("[suna.tools] category=%r -> %d tools", category, len(out))
    return json.dumps({"tools": out, "count": len(out)})
