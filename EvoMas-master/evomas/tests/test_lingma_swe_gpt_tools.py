"""MCP registration + shape assertions for `evomas.tools.lingma_swe_gpt`.

Mirrors the OpenHands-shaped checks in `evomas/tests/test_tools.py`: every
`@tool`-decorated callable in `LINGMA_SWE_GPT_TOOLS` must be a LangChain `BaseTool`
with a non-empty name/description, and MCP must expose each one through
the default registry.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.tools import BaseTool

from evomas.mcp.server import MCPServer
from evomas.tools.lingma_swe_gpt import (
    LINGMA_SWE_GPT_TOOLS,
    manage,
    manage_2,
    manage_3,
    manage_4,
    manage_5,
    manage_6,
    manage_7,
    manage_8,
)
from evomas.tools.lingma_swe_gpt._state import reset as reset_state

_EXPECTED_NAMES = ("manage", "manage_2", "manage_3", "manage_4", "manage_5", "manage_6", "manage_7", "manage_8",)


def test_tools_are_basetool_with_name_and_description() -> None:
    """Each tool exposes the LangChain `BaseTool` contract."""
    for tool in LINGMA_SWE_GPT_TOOLS:
        assert isinstance(tool, BaseTool), tool
        assert tool.name, f"missing name: {tool}"
        assert (tool.description or "").strip(), f"missing description: {tool.name}"


def test_tool_names_match_expected_inventory() -> None:
    """The package exports exactly the names referenced by the variant
    catalog at `evomas/config/agent_types/`."""
    got = {t.name for t in LINGMA_SWE_GPT_TOOLS}
    assert got == set(_EXPECTED_NAMES), got


def test_mcp_default_registry_exposes_every_tool() -> None:
    """MCP's `default_registry()` registers every tool in the bundle."""
    registered = set(MCPServer().registry.tools.keys())
    for name in _EXPECTED_NAMES:
        assert name in registered, f"{name!r} not in MCP registry"


_AGENT = "lingma-test"


@pytest.fixture(autouse=True)
def _reset_lingma_state() -> None:
    reset_state()


def test_manage_lists_initial_empty_state() -> None:
    state = json.loads(manage.invoke({"agent": _AGENT}))
    assert state == {"focus": "", "context_files": [], "history": []}


def test_manage_2_adds_file() -> None:
    state = json.loads(manage_2.invoke({"path": "calc.py", "agent": _AGENT}))
    assert state["context_files"] == ["calc.py"]
    assert "add_file:calc.py" in state["history"]


def test_manage_3_removes_file() -> None:
    manage_2.invoke({"path": "calc.py", "agent": _AGENT})
    state = json.loads(manage_3.invoke({"path": "calc.py", "agent": _AGENT}))
    assert state["context_files"] == []


def test_manage_4_returns_history_slice() -> None:
    manage_2.invoke({"path": "a.py", "agent": _AGENT})
    manage_2.invoke({"path": "b.py", "agent": _AGENT})
    out = json.loads(manage_4.invoke({"agent": _AGENT, "n": 5}))
    assert out == ["add_file:a.py", "add_file:b.py"]


def test_manage_5_clears_history() -> None:
    manage_2.invoke({"path": "a.py", "agent": _AGENT})
    state = json.loads(manage_5.invoke({"agent": _AGENT}))
    assert state["history"] == []


def test_manage_6_set_and_manage_7_get_focus() -> None:
    state = json.loads(manage_6.invoke({"path": "calc.py", "agent": _AGENT}))
    assert state["focus"] == "calc.py"
    assert manage_7.invoke({"agent": _AGENT}) == "calc.py"


def test_manage_8_resets_agent_state() -> None:
    manage_2.invoke({"path": "a.py", "agent": _AGENT})
    manage_6.invoke({"path": "calc.py", "agent": _AGENT})
    state = json.loads(manage_8.invoke({"agent": _AGENT}))
    assert state == {"focus": "", "context_files": [], "history": []}
