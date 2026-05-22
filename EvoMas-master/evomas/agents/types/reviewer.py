"""Reviewer — verifies that a candidate patch actually resolves the issue."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


class ReviewerAgent(LLMToolAgent):
    """Reviews the patcher's workspace edits (apply / lint / semantic match) via the `generate_diff` MCP tool, since the diff isn't a template placeholder."""

    AGENT_TYPE: ClassVar[str] = "Reviewer"
    name = "reviewer"

    # Output bundles `{patches, validations}` so the downstream ensembler
    # can read both via a single predecessor slot -- no multi-upstream lookup.
    OUTPUT_TYPE: ClassVar[Any] = dict[str, Any]
    OUTPUT_DEFAULT: ClassVar[dict[str, Any]] = {}

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are a strict code-review agent. The upstream patcher has\n"
        "already applied its edits to the workspace; you do NOT receive\n"
        "the patch text inline. Call `generate_diff` to retrieve the\n"
        "current diff against the base commit -- THAT is the patch you\n"
        "are reviewing.\n\n"
        "## Checks (in order)\n"
        "1. Is the change minimal and targeted?\n"
        "2. Does it match the bug class the issue describes? Most common\n"
        "   case: a description / error-message bug needs ONLY the emitted\n"
        "   string (e.g. `description=...`) changed -- not the class\n"
        "   docstring, not the triggering logic. An early-return guard or\n"
        "   try/except wrap for a class-1 bug is a FAIL.\n"
        "3. `run_flake8` on every modified .py file. New lint errors = FAIL.\n"
        "4. Are tests files untouched? (Editing tests = FAIL.)\n\n"
        "## Important: do NOT reset the workspace\n"
        "Even on FAIL, leave the patcher's edits on disk. The downstream\n"
        "ensembler reads the workspace diff as the final patch, so wiping\n"
        "the tree would erase the only candidate we have. Report FAIL as a\n"
        "signal only.\n\n"
        "## Output\n"
        "Wrap your verdict in <review>...</review>. First line PASS or\n"
        "FAIL, second line a one-sentence reason. Once the verdict is\n"
        "written, emit no further tool calls — the loop exits as soon as\n"
        "you respond without one."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Issue\n{issue}\n\n"
        "## Workspace\n{workspace}\n\n"
        "## Upstream (patcher summary)\n{predecessor}\n\n"
        "Call `generate_diff` to see the candidate patch, then verify it\n"
        "against the checks above and respond with\n"
        "<review>PASS|FAIL</review>."
    )
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = (
        "generate_diff", "apply_patch", "run_flake8",
        "normalize_patch", "reset_repo",
        "read_file",
    )
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.2,
        "num_ctx":      4096,
        "num_predict":  512,
        "stop":         ["</review>"],
    }
