"""lingma_swe_gpt `manage_3` (remove_file).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import remove_file

logger = logging.getLogger(__name__)


@tool
def manage_3(path: str, agent: str = "default") -> str:
    """Drop `path` from the agent's `context_files` list. Returns the new
    state snapshot as JSON."""
    state = remove_file(agent, path)
    logger.info("[lingma.manage_3] agent=%s remove=%s", agent, path)
    return json.dumps(state)
