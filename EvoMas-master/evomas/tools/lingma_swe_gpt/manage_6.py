"""lingma_swe_gpt `manage_6` (set_focus).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import set_focus

logger = logging.getLogger(__name__)


@tool
def manage_6(path: str, agent: str = "default") -> str:
    """Set `agent`'s `focus` to `path`. Returns the new state snapshot."""
    state = set_focus(agent, path)
    logger.info("[lingma.manage_6] agent=%s focus=%s", agent, path)
    return json.dumps(state)
