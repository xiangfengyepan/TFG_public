"""Upstream-basename aliases for the OpenHands tool catalog.

The OpenHands variant catalog (`evomas/config/agent_types/OpenHands.json`)
lists tool names as the upstream file basenames (`ipython`, `llm_based_edit`,
`browser`), but the EvoMas re-implementations live under more explicit
function names (`execute_ipython_cell`, `edit_file`, no browser stub yet).
This module exposes thin alias wrappers so MCP can register the upstream
names and `test_variant_tool_coverage` sees full coverage.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from evomas.tools.openhands.tools import edit_file, execute_ipython_cell

logger = logging.getLogger(__name__)


@tool
def ipython(code: str) -> str:
    """Run an IPython cell. Alias for `execute_ipython_cell` — same impl,
    upstream-basename name so the OpenHands variant catalog resolves."""
    return execute_ipython_cell.invoke({"code": code})


@tool
def llm_based_edit(path: str, instruction: str = "", content: str | None = None) -> str:
    """LLM-driven file edit. Alias for `edit_file` — same impl, upstream
    basename so the OpenHands variant catalog resolves."""
    return edit_file.invoke({
        "path": path,
        "instruction": instruction,
        "content": content,
    })


@tool
def browser(action: str = "", url: str = "") -> str:
    """Browser interaction stub. The OpenHands `browser` tool drives a
    Playwright session — EvoMas doesn't ship a browser runtime, so this
    returns an informative error instead of crashing the agent loop."""
    logger.warning("[openhands.browser] called but no browser runtime: %s %s", action, url[:120])
    return "error: openhands browser tool not configured in this EvoMas install (no Playwright runtime)"


OPENHANDS_ALIAS_TOOLS = (ipython, llm_based_edit, browser)

__all__ = ["OPENHANDS_ALIAS_TOOLS", "ipython", "llm_based_edit", "browser"]
