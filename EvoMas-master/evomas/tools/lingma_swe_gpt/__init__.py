"""lingma_swe_gpt tool re-implementations.

Mirror of `evomas.tools.openhands` for the lingma_swe_gpt repo. Each tool is a
LangChain `@tool`-decorated function exposed via `LINGMA_SWE_GPT_TOOLS` and registered
with the MCP server in `evomas.mcp.server.default_registry`.
"""
from evomas.tools.lingma_swe_gpt.manage import manage
from evomas.tools.lingma_swe_gpt.manage_2 import manage_2
from evomas.tools.lingma_swe_gpt.manage_3 import manage_3
from evomas.tools.lingma_swe_gpt.manage_4 import manage_4
from evomas.tools.lingma_swe_gpt.manage_5 import manage_5
from evomas.tools.lingma_swe_gpt.manage_6 import manage_6
from evomas.tools.lingma_swe_gpt.manage_7 import manage_7
from evomas.tools.lingma_swe_gpt.manage_8 import manage_8

LINGMA_SWE_GPT_TOOLS = (manage, manage_2, manage_3, manage_4, manage_5, manage_6, manage_7, manage_8,)

__all__ = ["LINGMA_SWE_GPT_TOOLS", "manage", "manage_2", "manage_3", "manage_4", "manage_5", "manage_6", "manage_7", "manage_8"]
