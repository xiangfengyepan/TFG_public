"""lingma_swe_gpt `manage_2` (add_file).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import add_file

logger = logging.getLogger(__name__)


@tool
def manage_2(path: str, agent: str = "default") -> str:
    """Add `path` to the agent's `context_files` list. Returns the new
    state snapshot as JSON."""
    state = add_file(agent, path)
    logger.info("[lingma.manage_2] agent=%s add=%s", agent, path)
    return json.dumps(state)
