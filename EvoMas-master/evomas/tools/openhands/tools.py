"""OpenHands CodeActAgent + ReadOnlyAgent tools (lightweight reimplementations).

Each tool exposes the same name and parameter shape as upstream OpenHands so
prompts copied verbatim from the OpenHands repo continue to make sense, while
the implementation is grounded in plain Python + subprocess against the EvoMas
workspace.
"""
from __future__ import annotations

import fnmatch
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# In-memory undo stack for str_replace_editor (path -> list[snapshots]).
_UNDO_STACK: dict[str, list[str]] = {}

_MAX_OUTPUT = 30_000


def _truncate(text: str, n: int = _MAX_OUTPUT) -> str:
    if len(text) <= n:
        return text
    return text[:n] + "\n<response clipped>"


# ─── think ────────────────────────────────────────────────────────────────────
@tool
def think(thought: str) -> str:
    """Use the tool to think about something. It will not obtain new information or make any changes to the repository, but just log the thought. Use it when complex reasoning or brainstorming is needed."""
    logger.info("[think] %s", thought)
    return f"Your thought has been logged."


# ─── str_replace_editor ───────────────────────────────────────────────────────
def _file_view(path: Path, view_range: list[int] | None) -> str:
    if path.is_dir():
        out: list[str] = []
        base_depth = len(path.parts)
        for p in sorted(path.rglob("*")):
            if any(part.startswith(".") for part in p.relative_to(path).parts):
                continue
            depth = len(p.parts) - base_depth
            if depth > 2:
                continue
            out.append(str(p.relative_to(path)))
        return _truncate("\n".join(out) or "(empty)")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if view_range:
        start, end = view_range[0], view_range[1]
        end = len(lines) if end == -1 else end
        sel = lines[start - 1 : end]
        offset = start
    else:
        sel = lines
        offset = 1
    width = max(3, len(str(offset + len(sel))))
    return _truncate(
        "\n".join(f"{offset + i:>{width}}\t{line}" for i, line in enumerate(sel))
    )


def _push_undo(p: Path) -> None:
    if p.is_file():
        _UNDO_STACK.setdefault(str(p.resolve()), []).append(
            p.read_text(encoding="utf-8", errors="replace")
        )


@tool
def str_replace_editor(
    command: str,
    path: str,
    file_text: str | None = None,
    old_str: str | None = None,
    new_str: str | None = None,
    insert_line: int | None = None,
    view_range: list[int] | None = None,
) -> str:
    """Custom editing tool for viewing, creating and editing files in plain-text format.

    Commands:
      - view: cat -n a file or list a directory (depth 2).
      - create: write a new file (fails if it already exists).
      - str_replace: exact-match unique substring replacement.
      - insert: insert text after `insert_line`.
      - undo_edit: revert the last edit at `path`.
    """
    p = Path(path)
    if command == "view":
        if not p.exists():
            return f"Error: path {path} does not exist."
        return _file_view(p, view_range)

    if command == "create":
        if p.exists():
            return f"Error: file already exists at: {path}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(file_text or "", encoding="utf-8")
        return f"File created successfully at: {path}"

    if command == "str_replace":
        if not p.is_file():
            return f"Error: file does not exist: {path}"
        if old_str is None:
            return "Error: `old_str` is required for str_replace."
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_str)
        if count == 0:
            return "Error: `old_str` not found in file."
        if count > 1:
            return f"Error: `old_str` matched {count} times — make it unique."
        _push_undo(p)
        p.write_text(text.replace(old_str, new_str or "", 1), encoding="utf-8")
        return "The file has been edited."

    if command == "insert":
        if not p.is_file():
            return f"Error: file does not exist: {path}"
        if insert_line is None:
            return "Error: `insert_line` is required for insert."
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        if not 0 <= insert_line <= len(lines):
            return f"Error: insert_line {insert_line} out of range [0, {len(lines)}]."
        _push_undo(p)
        lines = lines[:insert_line] + [(new_str or "")] + lines[insert_line:]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "The file has been edited."

    if command == "undo_edit":
        key = str(p.resolve())
        stack = _UNDO_STACK.get(key) or []
        if not stack:
            return "Error: no edits to undo for this file."
        prev = stack.pop()
        p.write_text(prev, encoding="utf-8")
        return "Last edit reverted."

    return f"Error: unknown command {command!r}."


# ─── execute_ipython_cell (best-effort: runs in a fresh subprocess) ──────────
@tool
def execute_ipython_cell(code: str) -> str:
    """Run a cell of Python code. Variables do NOT persist between calls in this implementation (a fresh `python -c` subprocess is used)."""
    try:
        proc = subprocess.run(
            ["python", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "Error: cell timed out after 60s."
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return _truncate(out.strip() or "(no output)")


# ─── edit_file (LLMBasedFileEditTool) — minimal: full-file overwrite ──────────
@tool
def edit_file(path: str, content: str, start: int = 1, end: int = -1) -> str:
    """Edit a file by replacing the slice [start, end] (1-indexed inclusive) with `content`. `start=end=-1` appends to the file. If the file does not exist, it is created."""
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"File created at {path}."
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if start == -1 and end == -1:
        new_text = text.rstrip("\n") + "\n" + content + ("\n" if not content.endswith("\n") else "")
    else:
        end_eff = len(lines) if end == -1 else end
        start_eff = max(1, start)
        replacement = content.splitlines()
        new_lines = lines[: start_eff - 1] + replacement + lines[end_eff:]
        new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    _push_undo(p)
    p.write_text(new_text, encoding="utf-8")
    return f"File edited at {path}."


# ─── condensation_request (no-op signal) ──────────────────────────────────────
@tool
def condensation_request() -> str:
    """Request a condensation of the conversation history. In this lightweight runtime this is a no-op acknowledged by the controller."""
    return "Condensation requested."


# ─── finish ───────────────────────────────────────────────────────────────────
@tool
def finish(message: str) -> str:
    """Signals the completion of the current task or conversation. The controller stops the agent loop after this is called."""
    logger.info("[finish] %s", message)
    return f"FINISH: {message}"


# ─── execute_bash ─────────────────────────────────────────────────────────────
def _execute_bash_impl(command: str, cwd: str | None = None, timeout: int = 30) -> str:
    if not command.strip():
        return "(empty command)"
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s."
    parts: list[str] = []
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(proc.stderr)
    parts.append(f"[exit code: {proc.returncode}]")
    return _truncate("\n".join(p.rstrip() for p in parts if p))


@tool
def execute_bash(command: str, cwd: str | None = None, timeout: int = 30) -> str:
    """Execute a bash command in the workspace. Returns stdout/stderr and exit code."""
    return _execute_bash_impl(command, cwd, timeout)


# Alias: OpenHands' canonical name in some places is just "bash".
@tool
def bash(command: str, cwd: str | None = None, timeout: int = 30) -> str:
    """Alias for execute_bash."""
    return _execute_bash_impl(command, cwd, timeout)


# ─── grep (ReadOnlyAgent) ────────────────────────────────────────────────────
@tool
def grep(pattern: str, path: str | None = None, include: str | None = None) -> list[str]:
    """Fast content search tool. Returns up to 100 matching file paths sorted by mtime.

    Args:
        pattern: regex.
        path: directory to search (default: current).
        include: file glob (e.g. "*.py").
    """
    base = Path(path or ".")
    if not base.is_dir():
        return [f"Error: {base} is not a directory"]
    rx = re.compile(pattern)
    matches: list[tuple[float, str]] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if include and not fnmatch.fnmatch(p.name, include):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if rx.search(text):
            matches.append((p.stat().st_mtime, str(p)))
    matches.sort(reverse=True)
    return [m[1] for m in matches[:100]]


# ─── glob (ReadOnlyAgent) ────────────────────────────────────────────────────
@tool
def glob_(pattern: str, path: str | None = None) -> list[str]:
    """Fast file pattern matching tool. Returns up to 100 matching paths sorted by mtime."""
    base = Path(path or ".")
    if not base.is_dir():
        return [f"Error: {base} is not a directory"]
    matches: list[tuple[float, str]] = []
    for p in base.rglob(pattern):
        if not p.is_file():
            continue
        matches.append((p.stat().st_mtime, str(p)))
    matches.sort(reverse=True)
    return [m[1] for m in matches[:100]]


# Register glob_ under the upstream name "glob" so the MCP catalog surfaces it
# correctly without shadowing the stdlib `glob` module here.
glob_.name = "glob"


# ─── view (ReadOnlyAgent) ────────────────────────────────────────────────────
@tool
def view(path: str, view_range: list[int] | None = None) -> str:
    """Reads a file or list directories from the local filesystem (cat -n style)."""
    p = Path(path)
    if not p.exists():
        return f"Error: path {path} does not exist."
    return _file_view(p, view_range)


# Catalog used to register all tools with the MCP server in one shot.
OPENHANDS_TOOLS: list[Any] = [
    think,
    str_replace_editor,
    execute_ipython_cell,
    edit_file,
    condensation_request,
    finish,
    execute_bash,
    bash,
    grep,
    glob_,
    view,
]
