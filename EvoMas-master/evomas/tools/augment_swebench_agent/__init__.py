"""augment_swebench_agent tool re-implementations.

Mirror of `evomas.tools.openhands` for the augment_swebench_agent repo. Each tool is a
LangChain `@tool`-decorated function exposed via `AUGMENT_SWEBENCH_AGENT_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.augment_swebench_agent.sequential_thinking_tool import sequential_thinking_tool
from evomas.tools.augment_swebench_agent.complete_tool import complete_tool
from evomas.tools.augment_swebench_agent.str_replace_tool import str_replace_tool

AUGMENT_SWEBENCH_AGENT_TOOLS = (sequential_thinking_tool, complete_tool, str_replace_tool,)

__all__ = ["AUGMENT_SWEBENCH_AGENT_TOOLS", "sequential_thinking_tool", "complete_tool", "str_replace_tool"]
