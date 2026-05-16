"""composio tool re-implementations.

Mirror of `evomas.tools.openhands` for the composio repo. Each tool is a
LangChain `@tool`-decorated function exposed via `COMPOSIO_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.composio.langchain_agent import langchain_agent
from evomas.tools.composio.mcp import mcp
from evomas.tools.composio.openai_agents import openai_agents
from evomas.tools.composio.tool_router_mcp import tool_router_mcp

COMPOSIO_TOOLS = (langchain_agent, mcp, openai_agents, tool_router_mcp,)

__all__ = ["COMPOSIO_TOOLS", "langchain_agent", "mcp", "openai_agents", "tool_router_mcp"]
