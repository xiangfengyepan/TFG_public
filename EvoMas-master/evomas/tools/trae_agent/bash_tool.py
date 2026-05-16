"""trae_agent `bash_tool` tool.

Upstream reference: https://github.com/bytedance/trae-agent/blob/main/trae_agent/tools/bash_tool.py
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


from evomas.tools.openhands.tools import execute_bash as _exec_bash


@tool
def bash_tool(command: str, cwd: str = ".", timeout: int = 120) -> str:
    """Run a shell command in `cwd` and capture stdout+stderr. Delegates
    to the openhands `execute_bash` implementation (subprocess.run with a
    timeout, no PTY)."""
    return _exec_bash.invoke({"command": command, "cwd": cwd, "timeout": timeout})
