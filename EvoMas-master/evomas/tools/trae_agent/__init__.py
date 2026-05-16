"""trae_agent tool re-implementations.

Mirror of `evomas.tools.openhands` for the trae_agent repo. Each tool is a
LangChain `@tool`-decorated function exposed via `TRAE_AGENT_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.trae_agent.bash_tool import bash_tool
from evomas.tools.trae_agent.ckg_tool import ckg_tool
from evomas.tools.trae_agent.edit_tool import edit_tool
from evomas.tools.trae_agent.json_edit_tool import json_edit_tool
from evomas.tools.trae_agent.sequential_thinking_tool import sequential_thinking_tool
from evomas.tools.trae_agent.task_done_tool import task_done_tool

TRAE_AGENT_TOOLS = (bash_tool, ckg_tool, edit_tool, json_edit_tool, sequential_thinking_tool, task_done_tool,)

__all__ = ["TRAE_AGENT_TOOLS", "bash_tool", "ckg_tool", "edit_tool", "json_edit_tool", "sequential_thinking_tool", "task_done_tool"]
