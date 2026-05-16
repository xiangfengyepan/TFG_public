"""MCP registration + shape assertions for `evomas.tools.augment_swebench_agent`.

Mirrors the OpenHands-shaped checks in `evomas/tests/test_tools.py`: every
`@tool`-decorated callable in `AUGMENT_SWEBENCH_AGENT_TOOLS` must be a LangChain `BaseTool`
with a non-empty name/description, and MCP must expose each one through
the default registry.
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import BaseTool

from evomas.mcp.server import MCPServer
from evomas.tools.augment_swebench_agent import (
    AUGMENT_SWEBENCH_AGENT_TOOLS,
    complete_tool,
    sequential_thinking_tool,
    str_replace_tool,
)

_EXPECTED_NAMES = ("sequential_thinking_tool", "complete_tool", "str_replace_tool",)


def test_tools_are_basetool_with_name_and_description() -> None:
    """Each tool exposes the LangChain `BaseTool` contract."""
    for tool in AUGMENT_SWEBENCH_AGENT_TOOLS:
        assert isinstance(tool, BaseTool), tool
        assert tool.name, f"missing name: {tool}"
        assert (tool.description or "").strip(), f"missing description: {tool.name}"


def test_tool_names_match_expected_inventory() -> None:
    """The package exports exactly the names referenced by the variant
    catalog at `evomas/config/agent_types/`."""
    got = {t.name for t in AUGMENT_SWEBENCH_AGENT_TOOLS}
    assert got == set(_EXPECTED_NAMES), got


def test_mcp_default_registry_exposes_every_tool() -> None:
    """MCP's `default_registry()` registers every tool in the bundle."""
    registered = set(MCPServer().registry.tools.keys())
    for name in _EXPECTED_NAMES:
        assert name in registered, f"{name!r} not in MCP registry"


def test_sequential_thinking_tool_records_chain() -> None:
    s = json.loads(sequential_thinking_tool.invoke({"thought": "a", "step": 1, "total": 3, "agent": "X"}))
    assert s == {"agent": "X", "step": 1, "total": 3, "thought": "a"}


def test_complete_tool_writes_workspace_marker(buggy_repo: Path) -> None:
    record = json.loads(complete_tool.invoke({
        "result": "all good",
        "workspace": str(buggy_repo),
        "agent": "X",
    }))
    assert record["completed"] is True and record["result"] == "all good"
    marker = buggy_repo / ".evomas" / "state.json"
    assert marker.is_file()
    assert json.loads(marker.read_text())["completed"] is True


def test_str_replace_tool_edits_workspace(buggy_repo: Path) -> None:
    """str_replace_tool delegates to openhands.str_replace_editor; this
    happy-path covers the existing real impl alongside the new ones."""
    out = str_replace_tool.invoke({
        "command": "str_replace",
        "path": str(buggy_repo / "calc.py"),
        "old_str": "return a - b",
        "new_str": "return a + b",
    })
    assert "edited" in out.lower() or "successfully" in out.lower()
    assert "return a + b" in (buggy_repo / "calc.py").read_text()
