"""augment_swebench_agent `str_replace_tool` tool.

Upstream reference: https://github.com/augmentcode/augment-swebench-agent/blob/main/augment_swebench_agent/str_replace_tool.py
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


from evomas.tools.openhands.tools import str_replace_editor as _editor


@tool
def str_replace_tool(
    path: str,
    old_str: str | None = None,
    new_str: str | None = None,
    file_text: str | None = None,
    insert_line: int | None = None,
    view_range: list[int] | None = None,
    command: str = "str_replace",
) -> str:
    """Exact-match string replacement in a file (openhands str_replace_editor
    semantics). `command` accepts view/create/str_replace/insert/undo_edit."""
    return _editor.invoke({
        "command": command,
        "path": path,
        "old_str": old_str,
        "new_str": new_str,
        "file_text": file_text,
        "insert_line": insert_line,
        "view_range": view_range,
    })
