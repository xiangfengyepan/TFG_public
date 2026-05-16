"""lingma_swe_gpt `manage_4` (history).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import history

logger = logging.getLogger(__name__)


@tool
def manage_4(agent: str = "default", n: int = 20) -> str:
    """Return the last `n` history entries for `agent` as a JSON list."""
    out = history(agent, n=n)
    logger.info("[lingma.manage_4] agent=%s -> %d entries", agent, len(out))
    return json.dumps(out)
