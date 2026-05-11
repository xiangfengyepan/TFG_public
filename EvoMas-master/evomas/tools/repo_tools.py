from pathlib import Path
from typing import Iterable

from langchain_core.tools import tool

DEFAULT_IGNORES: tuple[str, ...] = (
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".pytest_cache",
    "build",
    "dist",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
)


def _iter_files(directory: Path, extension: str, ignores: Iterable[str]) -> list[str]:
    ignore_set = set(ignores)
    out: list[str] = []
    for p in directory.rglob(extension):
        if any(part in ignore_set for part in p.parts):
            continue
        if p.is_file():
            out.append(str(p.relative_to(directory)))
    out.sort()
    return out


def list_files_impl(directory: str, extension: str = "*.py") -> list[str]:
    base = Path(directory)
    if not base.is_dir():
        raise FileNotFoundError(f"directory not found: {directory}")
    return _iter_files(base, extension, DEFAULT_IGNORES)


def read_file_impl(path: str, with_line_numbers: bool = True, max_chars: int | None = None) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated to {max_chars} chars]"
    if with_line_numbers:
        lines = text.splitlines()
        width = max(3, len(str(len(lines))))
        return "\n".join(f"{i + 1:>{width}}: {line}" for i, line in enumerate(lines))
    return text


@tool
def list_files(directory: str, extension: str = "*.py") -> list[str]:
    """List files matching a glob extension under a directory (recursively).

    Args:
        directory: absolute path to a directory.
        extension: glob pattern (e.g., "*.py" or "*.md"). Default "*.py".

    Returns relative paths sorted alphabetically.
    """
    return list_files_impl(directory, extension)


@tool
def read_file(path: str, with_line_numbers: bool = True, max_chars: int | None = None) -> str:
    """Read a text file's contents, optionally prefixed with line numbers.

    Args:
        path: absolute path to a file.
        with_line_numbers: prefix each line with its line number (default True).
        max_chars: truncate to this many characters; None for no limit.
    """
    return read_file_impl(path, with_line_numbers, max_chars)
