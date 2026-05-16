"""swe_agent tool re-implementations.

Mirror of `evomas.tools.openhands` for the swe_agent repo. Each tool is a
LangChain `@tool`-decorated function exposed via `SWE_AGENT_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.swe_agent.tools import tools

SWE_AGENT_TOOLS = (tools,)

__all__ = ["SWE_AGENT_TOOLS", "tools"]
