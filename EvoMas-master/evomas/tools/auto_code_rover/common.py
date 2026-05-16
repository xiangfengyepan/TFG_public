"""auto_code_rover `common` tool.

Upstream reference: https://github.com/AutoCodeRoverSG/auto-code-rover/blob/main/app/model/common.py

Upstream `app/model/common.py` is auto-code-rover's model dispatch layer
with a per-task token-accounting counter. We expose the same idea:
a tiny in-process accumulator other code can `record_tokens()` into, and
`common()` returns the current totals as JSON. Used by agents that want
to budget cost/tokens mid-run.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Module-level token accumulator. Keys: prompt, completion, total, calls.
_USAGE: dict[str, int] = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


def record_tokens(prompt: int = 0, completion: int = 0) -> dict[str, int]:
    """Update the running accumulator. Called by the llm-invoke layer
    after each model call. Returns the new totals."""
    _USAGE["prompt"] += int(prompt or 0)
    _USAGE["completion"] += int(completion or 0)
    _USAGE["total"] = _USAGE["prompt"] + _USAGE["completion"]
    _USAGE["calls"] += 1
    return dict(_USAGE)


def reset() -> None:
    """Test hook: zero the accumulator."""
    for k in _USAGE:
        _USAGE[k] = 0


@tool
def common(reset_after: bool = False) -> str:
    """Report the current per-task token-usage accumulator as JSON
    `{prompt, completion, total, calls}`. Set `reset_after=True` to
    zero the counter after reading."""
    snapshot: dict[str, Any] = dict(_USAGE)
    if reset_after:
        reset()
    logger.info("[auto_code_rover.common] usage=%s", snapshot)
    return json.dumps(snapshot)
