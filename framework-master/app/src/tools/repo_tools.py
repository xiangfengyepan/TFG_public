# from __future__ import annotations
# import os
# from pathlib import Path
# from typing import List

# from langchain_core.tools import tool
# from app.src.tools.tool_registry import ToolRegistry
# from app.src.agents.base_agent import BaseAgent

# @ToolRegistry.tool("list_files_tool")
# @tool
# def list_files_tool(path: str, recursive: bool = True, max_files: int = 200) -> List[str]:
#     """
#     List file paths under a directory (relative to repository root).
    
#     Args:
#         path: Directory path to list. Relative paths are resolved from the repository root.
#         recursive: Whether to search recursively.
#         max_files: Upper bound on number of files returned.
#     """
#     repo_root = BaseAgent.get_repo_root()
#     base = Path(path)
#     if not base.is_absolute():
#         base = repo_root / base
#     base = base.resolve()

#     try:
#         base.relative_to(repo_root.resolve())
#     except Exception as e:
#         raise ValueError(f"Path escapes repository root: {path}. {e}")

#     results: List[str] = []

#     if recursive:
#         for dirpath, _, filenames in os.walk(base):
#             for fname in filenames:
#                 p = Path(dirpath) / fname
#                 rel = str(p.resolve().relative_to(repo_root.resolve()))
#                 results.append(rel)
#                 if len(results) >= max_files:
#                     return results
#     else:
#         for p in base.iterdir():
#             if p.is_file():
#                 rel = str(p.resolve().relative_to(repo_root.resolve()))
#                 results.append(rel)
#                 if len(results) >= max_files:
#                     return results

#     return results