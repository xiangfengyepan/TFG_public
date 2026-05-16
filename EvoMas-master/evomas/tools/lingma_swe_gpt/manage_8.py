"""lingma_swe_gpt `manage_8` (reset).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import reset, snapshot

logger = logging.getLogger(__name__)


@tool
def manage_8(agent: str = "default") -> str:
    """Wipe the agent's state (focus, context_files, history). Returns the
    cleared snapshot as JSON."""
    reset(agent)
    logger.info("[lingma.manage_8] agent=%s reset", agent)
    return json.dumps(snapshot(agent))
