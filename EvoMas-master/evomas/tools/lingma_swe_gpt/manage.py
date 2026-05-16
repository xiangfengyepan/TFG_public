"""lingma_swe_gpt `manage` (list state).

Upstream reference: https://github.com/AlibabaCloudDocs/lingma-swe-gpt

The CSV importer split lingma's `manage` URL into 8 distinct tool names;
each (`manage`, `manage_2..8`) implements one upstream context-mgmt op
backed by `evomas.tools.lingma_swe_gpt._state`. This file is the
canonical `manage` — returns the full per-agent state snapshot.
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from evomas.tools.lingma_swe_gpt._state import snapshot

logger = logging.getLogger(__name__)


@tool
def manage(agent: str = "default") -> str:
    """Return the agent's current state as JSON
    `{focus, context_files, history}`."""
    state = snapshot(agent)
    logger.info("[lingma.manage] agent=%s -> %s", agent, state)
    return json.dumps(state)
