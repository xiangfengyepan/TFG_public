"""MCP registration + shape assertions for `evomas.tools.auto_code_rover`.

Mirrors the OpenHands-shaped checks in `evomas/tests/test_tools.py`: every
`@tool`-decorated callable in `AUTO_CODE_ROVER_TOOLS` must be a LangChain `BaseTool`
with a non-empty name/description, and MCP must expose each one through
the default registry.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

from evomas.mcp.server import MCPServer
from evomas.tools.auto_code_rover import AUTO_CODE_ROVER_TOOLS, agent_write_patch
from evomas.tools.auto_code_rover.common import common, record_tokens, reset

_EXPECTED_NAMES = ("agent_write_patch", "common",)


def test_tools_are_basetool_with_name_and_description() -> None:
    """Each tool exposes the LangChain `BaseTool` contract."""
    for tool in AUTO_CODE_ROVER_TOOLS:
        assert isinstance(tool, BaseTool), tool
        assert tool.name, f"missing name: {tool}"
        assert (tool.description or "").strip(), f"missing description: {tool.name}"


def test_tool_names_match_expected_inventory() -> None:
    """The package exports exactly the names referenced by the variant
    catalog at `evomas/config/agent_types/`."""
    got = {t.name for t in AUTO_CODE_ROVER_TOOLS}
    assert got == set(_EXPECTED_NAMES), got


def test_mcp_default_registry_exposes_every_tool() -> None:
    """MCP's `default_registry()` registers every tool in the bundle."""
    registered = set(MCPServer().registry.tools.keys())
    for name in _EXPECTED_NAMES:
        assert name in registered, f"{name!r} not in MCP registry"


@pytest.fixture(autouse=True)
def _reset_token_accumulator() -> None:
    reset()


def test_common_reports_zero_when_nothing_recorded() -> None:
    out = json.loads(common.invoke({}))
    assert out == {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


def test_common_reports_recorded_tokens() -> None:
    record_tokens(prompt=10, completion=5)
    record_tokens(prompt=3, completion=2)
    out = json.loads(common.invoke({}))
    assert out == {"prompt": 13, "completion": 7, "total": 20, "calls": 2}


def test_common_reset_after_zeros_counter() -> None:
    record_tokens(prompt=10, completion=5)
    json.loads(common.invoke({"reset_after": True}))
    assert json.loads(common.invoke({})) == {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


def test_agent_write_patch_applies_diff(buggy_repo: Path) -> None:
    patch = (
        "diff --git a/calc.py b/calc.py\n"
        "--- a/calc.py\n"
        "+++ b/calc.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    return a + b\n"
    )
    result = agent_write_patch.invoke({"patch": patch, "repo_path": str(buggy_repo)})
    assert result == "ok"
    assert "return a + b" in (buggy_repo / "calc.py").read_text()
