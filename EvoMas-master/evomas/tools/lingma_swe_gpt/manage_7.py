"""lingma_swe_gpt `manage_7` (get_focus).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import get_focus

logger = logging.getLogger(__name__)


@tool
def manage_7(agent: str = "default") -> str:
    """Return the agent's current `focus` path (empty string if unset)."""
    focus = get_focus(agent)
    logger.info("[lingma.manage_7] agent=%s -> focus=%s", agent, focus)
    return focus or ""
