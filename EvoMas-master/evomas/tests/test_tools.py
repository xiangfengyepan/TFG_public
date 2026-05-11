import subprocess
from pathlib import Path

import pytest

from evomas.mcp.server import MCPServer, ToolRegistry, get_server
from evomas.tools.lint_tools import run_flake8_impl
from evomas.tools.patch_tools import apply_patch_impl, generate_diff_impl, reset_repo_impl
from evomas.tools.repo_tools import list_files_impl, read_file_impl
from evomas.tools.search_tools import search_code_impl

_GOOD_PATCH: str = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n"
    "+++ b/calc.py\n"
    "@@ -1,5 +1,5 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a + b\n"
    " \n"
    " def multiply(a, b):\n"
    "     return a * b\n"
)


# ── tool implementations (unit) ───────────────────────────────────────────────

def test_list_files_finds_python(buggy_repo: Path) -> None:
    files = list_files_impl(str(buggy_repo), "*.py")
    assert "calc.py" in files
    assert "test_calc.py" in files


def test_read_file_with_line_numbers(buggy_repo: Path) -> None:
    content = read_file_impl(str(buggy_repo / "calc.py"), with_line_numbers=True)
    assert "1: def add(a, b):" in content
    assert "return a - b" in content


def test_search_code_ranks_relevant(buggy_repo: Path) -> None:
    results = search_code_impl("add function returns difference", str(buggy_repo))
    assert results
    assert "calc.py" in [r["path"] for r in results]


def test_run_flake8_clean(buggy_repo: Path) -> None:
    result = run_flake8_impl(str(buggy_repo / "calc.py"))
    assert "ok" in result and "output" in result


def test_apply_patch_dry_run(buggy_repo: Path) -> None:
    result = apply_patch_impl(_GOOD_PATCH, str(buggy_repo), dry_run=True)
    assert result["ok"] is True, result["output"]
    assert result["applied"] is False


def test_apply_patch_then_diff(buggy_repo: Path) -> None:
    result = apply_patch_impl(_GOOD_PATCH, str(buggy_repo), dry_run=False)
    assert result["applied"] is True, result["output"]
    diff = generate_diff_impl(str(buggy_repo))
    assert "return a + b" in diff
    assert "return a - b" in diff


def test_apply_patch_rejects_bad_hunk(buggy_repo: Path) -> None:
    # Context lines that do not exist in calc.py — git cannot fuzzy-match them.
    bad = (
        "diff --git a/calc.py b/calc.py\n"
        "--- a/calc.py\n"
        "+++ b/calc.py\n"
        "@@ -100,3 +100,3 @@\n"
        " def nonexistent_function(x, y, z):\n"
        "-    return x - y - z\n"
        "+    return x + y + z\n"
        " \n"
    )
    assert apply_patch_impl(bad, str(buggy_repo), dry_run=True)["ok"] is False


def test_reset_repo(buggy_repo: Path) -> None:
    (buggy_repo / "calc.py").write_text("garbage\n")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=buggy_repo, capture_output=True, text=True
    ).stdout.strip()
    reset_repo_impl(str(buggy_repo), base)
    assert "garbage" not in generate_diff_impl(str(buggy_repo))


# ── MCP server ────────────────────────────────────────────────────────────────

_EXPECTED_TOOLS = {"read_file", "list_files", "search_code", "run_flake8",
                   "apply_patch", "generate_diff", "reset_repo"}


def test_mcp_singleton_identity() -> None:
    assert get_server() is get_server()


def test_mcp_registry_contains_all_tools() -> None:
    server = MCPServer()
    assert _EXPECTED_TOOLS.issubset(set(server.registry.tools.keys()))


def test_mcp_tools_list_schema() -> None:
    listing = MCPServer().registry.list()
    names = {t["name"] for t in listing}
    assert _EXPECTED_TOOLS.issubset(names)
    for entry in listing:
        assert "inputSchema" in entry
        assert "description" in entry


def test_mcp_call_list_files(buggy_repo: Path) -> None:
    server = MCPServer()
    files = server.call("list_files", {"directory": str(buggy_repo), "extension": "*.py"})
    assert "calc.py" in files


def test_mcp_call_read_file(buggy_repo: Path) -> None:
    content = MCPServer().call("read_file", {"path": str(buggy_repo / "calc.py")})
    assert "def add" in content


def test_mcp_call_search_code(buggy_repo: Path) -> None:
    results = MCPServer().call("search_code", {
        "query": "add subtract difference",
        "directory": str(buggy_repo),
        "top_k": 5,
    })
    assert any(r["path"] == "calc.py" for r in results)


def test_mcp_call_apply_patch_dry_run(buggy_repo: Path) -> None:
    result = MCPServer().call("apply_patch", {
        "patch_str": _GOOD_PATCH,
        "repo_path": str(buggy_repo),
        "dry_run": True,
    })
    assert result["ok"] is True
    assert result["applied"] is False


def test_mcp_call_reset_repo(buggy_repo: Path) -> None:
    (buggy_repo / "calc.py").write_text("garbage\n")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=buggy_repo, capture_output=True, text=True
    ).stdout.strip()
    MCPServer().call("reset_repo", {"repo_path": str(buggy_repo), "base_commit": base})
    assert "garbage" not in generate_diff_impl(str(buggy_repo))


def test_mcp_call_unknown_tool_raises() -> None:
    with pytest.raises(KeyError, match="unknown tool"):
        MCPServer().call("nonexistent_tool", {})


def test_mcp_handle_tools_list() -> None:
    resp = MCPServer().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert resp["id"] == 1
    assert "tools" in resp["result"]


def test_mcp_handle_tools_call(buggy_repo: Path) -> None:
    resp = MCPServer().handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "list_files", "arguments": {"directory": str(buggy_repo)}},
    })
    assert "content" in resp["result"]


def test_mcp_handle_unknown_method() -> None:
    resp = MCPServer().handle({"jsonrpc": "2.0", "id": 3, "method": "bogus", "params": {}})
    assert "error" in resp
    assert resp["error"]["code"] == -32601


# ── agents use the MCP singleton ──────────────────────────────────────────────

def test_agents_share_mcp_singleton() -> None:
    from evomas.agents.evo_star import LocalizeAgent, PatchAgent, ValidateAgent

    server = get_server()
    assert LocalizeAgent().mcp is server
    assert PatchAgent().mcp is server
    assert ValidateAgent().mcp is server
