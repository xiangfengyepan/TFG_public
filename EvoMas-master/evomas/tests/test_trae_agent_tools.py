"""MCP registration + shape assertions for `evomas.tools.trae_agent`.

Mirrors the OpenHands-shaped checks in `evomas/tests/test_tools.py`: every
`@tool`-decorated callable in `TRAE_AGENT_TOOLS` must be a LangChain `BaseTool`
with a non-empty name/description, and MCP must expose each one through
the default registry.
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import BaseTool

from evomas.mcp.server import MCPServer
from evomas.tools.trae_agent import (
    TRAE_AGENT_TOOLS,
    ckg_tool,
    json_edit_tool,
    sequential_thinking_tool,
    task_done_tool,
)

_EXPECTED_NAMES = ("bash_tool", "ckg_tool", "edit_tool", "json_edit_tool", "sequential_thinking_tool", "task_done_tool",)


def test_tools_are_basetool_with_name_and_description() -> None:
    """Each tool exposes the LangChain `BaseTool` contract."""
    for tool in TRAE_AGENT_TOOLS:
        assert isinstance(tool, BaseTool), tool
        assert tool.name, f"missing name: {tool}"
        assert (tool.description or "").strip(), f"missing description: {tool.name}"


def test_tool_names_match_expected_inventory() -> None:
    """The package exports exactly the names referenced by the variant
    catalog at `evomas/config/agent_types/`."""
    got = {t.name for t in TRAE_AGENT_TOOLS}
    assert got == set(_EXPECTED_NAMES), got


def test_mcp_default_registry_exposes_every_tool() -> None:
    """MCP's `default_registry()` registers every tool in the bundle."""
    registered = set(MCPServer().registry.tools.keys())
    for name in _EXPECTED_NAMES:
        assert name in registered, f"{name!r} not in MCP registry"


def test_sequential_thinking_tool_records_chain() -> None:
    s = json.loads(sequential_thinking_tool.invoke({
        "thought": "explore", "step": 1, "total": 4, "agent": "trae-test",
    }))
    assert s == {"agent": "trae-test", "step": 1, "total": 4, "thought": "explore"}


def test_task_done_tool_writes_workspace_marker(buggy_repo: Path) -> None:
    record = json.loads(task_done_tool.invoke({
        "result": "done", "workspace": str(buggy_repo), "agent": "trae-test",
    }))
    assert record["completed"] is True
    assert (buggy_repo / ".evomas" / "state.json").is_file()


def test_ckg_tool_lists_top_level_symbols(buggy_repo: Path) -> None:
    """ckg_tool returns top-level class/function definitions via ast.parse."""
    out = ckg_tool.invoke({"path": str(buggy_repo / "calc.py")})
    assert "def add" in out
    assert "def multiply" in out


def test_json_edit_tool_round_trips(buggy_repo: Path) -> None:
    target = buggy_repo / "data.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    out = json_edit_tool.invoke({"path": str(target), "key": "b", "value": "2"})
    assert out == "ok"
    data = json.loads(target.read_text())
    assert data == {"a": 1, "b": 2}
