"""lingma_swe_gpt `manage_5` (clear_history).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import clear_history

logger = logging.getLogger(__name__)


@tool
def manage_5(agent: str = "default") -> str:
    """Reset the agent's history list. Returns the new state snapshot."""
    state = clear_history(agent)
    logger.info("[lingma.manage_5] agent=%s history cleared", agent)
    return json.dumps(state)
