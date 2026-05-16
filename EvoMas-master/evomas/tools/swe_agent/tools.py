"""swe_agent `tools` tool.

Upstream reference: https://github.com/SWE-agent/SWE-agent/tree/main/tools

The upstream `tools/` directory bundles the full SWE-agent toolset. The
closest useful operation for an EvoMas swe_agent variant is "give me a
schema-level manifest of every callable tool" — implemented here against
the live MCP registry. Returns full descriptors (name, description,
inputSchema), not just names, so the LLM can self-route without a
separate /tools/list round-trip.
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def tools() -> str:
    """Return a JSON manifest of every MCP-registered tool: a list of
    `{name, description, inputSchema}` objects. Use this to discover
    available capabilities mid-run."""
    from evomas.mcp.server import MCPServer
    manifest = MCPServer().registry.list()
    logger.info("[swe_agent.tools] manifest size=%d", len(manifest))
    return json.dumps(manifest)
