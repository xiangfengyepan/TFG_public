"""joycode_agent tool re-implementations.

Mirror of `evomas.tools.openhands` for the joycode_agent repo. Each tool is a
LangChain `@tool`-decorated function exposed via `JOYCODE_AGENT_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.joycode_agent.sequential_thinking_tool import sequential_thinking_tool
from evomas.tools.joycode_agent.complete_tool import complete_tool
from evomas.tools.joycode_agent.str_replace_tool import str_replace_tool

JOYCODE_AGENT_TOOLS = (sequential_thinking_tool, complete_tool, str_replace_tool,)

__all__ = ["JOYCODE_AGENT_TOOLS", "sequential_thinking_tool", "complete_tool", "str_replace_tool"]
