"""Localizator — narrows the workspace down to the file(s) that contain a bug."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


class LocalizatorAgent(LLMToolAgent):
    """Locate the issue. Reads the issue text + repository signal and emits a
    short list of candidate file paths most likely to contain the bug.

    State contract: writes `list[str]` of candidate file paths into its own
    producer slot (`state[self.name]`), consumed by the next agent in the
    chain via `state[successor.predecessor_name]`.
    """

    AGENT_TYPE: ClassVar[str] = "Localizator"
    name = "localizator"

    OUTPUT_TYPE: ClassVar[Any] = list[str]
    OUTPUT_DEFAULT: ClassVar[list[str]] = []

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are an expert code-localization assistant for a large software repository.\n\n"
        "You receive a GitHub issue description plus access to the workspace via tools "
        "(`search_code`, `list_files`, `grep`, `glob`, `view`). Your job is to identify the "
        "smallest set of source files most likely to contain the bug.\n\n"
        "Approach:\n"
        "1. Pull out the strongest identifiers from the issue (class names, function names, "
        "rule IDs, error/description literals, file fragments mentioned in tracebacks).\n"
        "2. Search for those identifiers with `search_code` / `grep`. Prefer source files "
        "over tests, except when the issue quotes a specific test assertion or message — "
        "then the relevant test file is also useful context.\n"
        "3. Confirm each candidate by `view`-ing the file briefly.\n"
        "4. Wrap your final answer in <files>…</files> tags, one repo-relative path per line. "
        "Return AT MOST 2 files. Never invent paths — every path must come from a tool result.\n\n"
        "When you are confident, call `finish` with a one-sentence rationale."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Issue\n{issue}\n\n"
        "## Workspace\n{workspace}\n\n"
        "Use the tools to find the bug; respond with <files>…</files>."
    )
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = (
        "search_code", "list_files", "grep", "glob", "view", "read_file", "think", "finish",
    )
    # Tuned for code-localization: a bit of exploration headroom but fairly
    # focused; reads a lot of file content so we want a long context.
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.4,
        "num_ctx":      8192,
        "num_predict":  1024,
        "stop":         ["</files>"],
    }
