"""claude_coder tool re-implementations.

Mirror of `evomas.tools.openhands` for the claude_coder repo. Each tool is a
LangChain `@tool`-decorated function exposed via `CLAUDE_CODER_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.claude_coder.index import index

CLAUDE_CODER_TOOLS = (index,)

__all__ = ["CLAUDE_CODER_TOOLS", "index"]
