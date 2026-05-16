"""suna tool re-implementations.

Mirror of `evomas.tools.openhands` for the suna repo. Each tool is a
LangChain `@tool`-decorated function exposed via `SUNA_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.suna.tools import tools

SUNA_TOOLS = (tools,)

__all__ = ["SUNA_TOOLS", "tools"]
