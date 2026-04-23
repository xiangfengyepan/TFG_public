from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.src.agents.base_agent import BaseAgent
from app.src.tools.code_tools import read_files_batch_tool
from langchain_core.tools import tool
from app.src.tools.tool_registry import ToolRegistry

from paths import CONTEXT_COLLECTOR_AGENT_JSON


# TODO check max_bytes_per_file
@tool("read_files_batch_context_tool")
def read_files_batch_context_tool(
    paths: List[str], max_bytes_per_file: int = 40000
) -> Dict[str, str]:
    """Read multiple files in one call for context collection."""
    return ToolRegistry.execute(
        "read_files_batch_tool",
        {"paths": paths, "max_bytes_per_file": max_bytes_per_file},
    )


class ContextCollectorAgent(BaseAgent):
    """
    Collects code snippets from relevant files before bug detection.
    This gives downstream agents concrete file content instead of only tree metadata.
    """

    def __init__(self):
        with open(CONTEXT_COLLECTOR_AGENT_JSON, "r") as f:
            self.hyperparameters = json.load(f)
        super().__init__()

    SUPPORTED_SOURCE_EXTS: Tuple[str, ...] = (
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".java",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".sql",
    )

    def _iter_tree_files(self, node: Dict[str, Any], parent: str = "") -> List[str]:
        name = node.get("name", "")
        node_type = node.get("type", "directory")

        if node_type == "file":
            if parent:
                return [f"{parent}/{name}".lstrip("./")]
            return [name.lstrip("./")]

        files: List[str] = []
        current_parent = parent
        if name not in ("", "."):
            current_parent = f"{parent}/{name}".strip("/")

        for child in node.get("children", []) or []:
            files.extend(self._iter_tree_files(child, current_parent))
        return files

    def run(self, state: dict) -> dict:
        repo_tree = state.get("repo_tree") or {}
        if not repo_tree:
            return {
                "repo_snippets": [],
                "context_collector_error": "Missing repo_tree in state.",
            }

        files = self._iter_tree_files(repo_tree)
        source_files = [
            p for p in files if Path(p).suffix.lower() in self.SUPPORTED_SOURCE_EXTS
        ]

        # TODO check
        # Prioritize Python and test files for APR use cases.
        source_files.sort(
            key=lambda p: (
                "test" not in p.lower(),
                Path(p).suffix.lower() != ".py",
                len(p),
            )
        )
        # TODO check
        source_files = source_files[:30]

        # TODO check
        content_map = read_files_batch_context_tool.invoke(
            {"paths": source_files, "max_bytes_per_file": 40000}
        )
        snippets = [
            {"file_path": path, "content": content}
            for path, content in content_map.items()
            if isinstance(content, str) and content.strip()
        ]

        return {
            "repo_snippets": snippets,
            "repo_snippets_count": len(snippets),
        }
