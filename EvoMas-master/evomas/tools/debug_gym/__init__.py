"""debug_gym tool re-implementations.

Mirror of `evomas.tools.openhands` for the debug_gym repo. Each tool is a
LangChain `@tool`-decorated function exposed via `DEBUG_GYM_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.debug_gym.tool import tool

DEBUG_GYM_TOOLS = (tool,)

__all__ = ["DEBUG_GYM_TOOLS", "tool"]
