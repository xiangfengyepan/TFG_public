from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool

from app.src.tools.tool_registry import ToolRegistry
from app.src.agents.base_agent import BaseAgent


EXCLUDED_DIRS: Tuple[str, ...] = (
    "venv",
    ".venv",
    "env",
    "node_modules",
    ".git",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
)

DEFAULT_SEARCH_EXTS: Tuple[str, ...] = (
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
    ".txt"
)


@ToolRegistry.tool("read_file_tool")
@tool
def read_file_tool(path: str, max_bytes: int = 200000) -> str:
    """
    Read file contents as text. Raises FileNotFoundError or ValueError if file cannot be read.
    
    Args:
        path: File path. Relative paths are resolved from the repository root.
        max_bytes: Maximum bytes to read.
    """
    repo_root = BaseAgent.get_repo_root()
    p = Path(path)
    if not p.is_absolute():
        p = repo_root / p
    p = p.resolve()

    try:
        p.relative_to(repo_root.resolve())
    except Exception as e:
        raise ValueError(f"Path escapes repository root: {path}. {e}")

    if not p.exists():
        raise FileNotFoundError(f"File does not exist at path: {path}")
        
    if not p.is_file():
        raise IsADirectoryError(f"Path is a directory, not a file: {path}")

    size = p.stat().st_size
    if size <= 0:
        raise ValueError(f"File is completely empty: {path}")
        
    if size > max_bytes:
        with p.open("rb") as f:
            raw = f.read(max_bytes)
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return raw.decode("latin-1", errors="ignore")

    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        try:
            return p.read_text(encoding="latin-1", errors="ignore")
        except Exception as inner_e:
            raise ValueError(f"Failed to decode file {path} as text. {inner_e}")


@ToolRegistry.tool("write_file_tool")
@tool
def write_file_tool(path: str, content: str) -> str:
    """
    Write text content to a file inside the repository (creates parent directories if needed).
    
    Args:
        path: File path. Relative paths are resolved from the repository root.
        content: New content to write.
    """
    repo_root = BaseAgent.get_repo_root()
    p = Path(path)
    if not p.is_absolute():
        p = repo_root / p
    p = p.resolve()

    try:
        p.relative_to(repo_root.resolve())
    except Exception as e:
        raise ValueError(f"Path escapes repository root: {path}. {e}")

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return "OK"


@ToolRegistry.tool("search_code_tool")
@tool
def search_code_tool(
    query: str,
    path: str = ".",
    use_regex: bool = False,
    max_results: int = 20,
    file_exts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Search for query occurrences in repository source files.
    Returns a JSON-serializable dict of matches with file + line context.
    
    Args:
        query: Search query. Treated as regex when use_regex=true; otherwise plain substring match.
        path: Root directory to search from (relative to repository root).
        use_regex: Whether to treat query as a regex.
        max_results: Maximum number of matches.
        file_exts: Optional list of file extensions to include (e.g., ['.py','.ts']). If null, uses a broad default.
    """
    repo_root = BaseAgent.get_repo_root()
    base = Path(path)
    if not base.is_absolute():
        base = repo_root / base
    base = base.resolve()

    try:
        base.relative_to(repo_root.resolve())
    except Exception as e:
        raise ValueError(f"Path escapes repository root: {path}. {e}")

    exts = tuple(file_exts) if file_exts else DEFAULT_SEARCH_EXTS
    exts = tuple(e.lower() for e in exts)

    pattern = None
    if use_regex:
        pattern = re.compile(query)

    matches: List[Dict[str, Any]] = []

    for dirpath, dirnames, filenames in os.walk(base):
        # prune directories topdown not supported since we don't have topdown=True here;
        # keep it simple but still skip excluded/hidden folders.
        parts = Path(dirpath).parts
        if any(p.startswith(".") for p in parts):
            # Skip hidden paths entirely.
            continue
        if any(p in EXCLUDED_DIRS for p in parts):
            continue

        for fname in filenames:
            if fname.startswith("."):
                continue
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in exts:
                continue
            try:
                if fpath.stat().st_size > 1_000_000:
                    continue
            except Exception:
                continue

            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                try:
                    text = fpath.read_text(encoding="latin-1", errors="ignore")
                except Exception:
                    continue

            if not text:
                continue

            for idx, line in enumerate(text.splitlines(), start=1):
                if use_regex:
                    if pattern and pattern.search(line):
                        rel = str(fpath.resolve().relative_to(repo_root.resolve()))
                        matches.append(
                            {"file_path": rel, "line_no": idx, "line": line.strip()}
                        )
                else:
                    if query in line:
                        rel = str(fpath.resolve().relative_to(repo_root.resolve()))
                        matches.append(
                            {"file_path": rel, "line_no": idx, "line": line.strip()}
                        )
                if len(matches) >= max_results:
                    return {
                        "query": query,
                        "matches": matches,
                        "match_count": len(matches),
                    }

    return {"query": query, "matches": matches, "match_count": len(matches)}


@ToolRegistry.tool("read_files_batch_tool")
@tool
def read_files_batch_tool(
    paths: List[str], max_bytes_per_file: int = 50000
) -> Dict[str, str]:
    """
    Read multiple files in one call.
    Returns a mapping from relative file path to text content.
    
    Args:
        paths: List of file paths (relative to repository root).
        max_bytes_per_file: Maximum bytes read per file.
    """
    results: Dict[str, str] = {}
    for rel in paths:
        try:
            results[rel] = read_file_tool.invoke({"path": rel, "max_bytes": max_bytes_per_file})
        except Exception:
            results[rel] = ""
    return results