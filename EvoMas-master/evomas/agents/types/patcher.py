"""Patcher — produces (and optionally selects) the patch that fixes the bug."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent
from evomas.tools.patch_tools import generate_diff_impl


class PatcherAgent(LLMToolAgent):
    """Write / select / apply the patch; writes the workspace `git diff` into `state[self.name]` (the patch is the real artifact, not the LLM ack text)."""

    AGENT_TYPE: ClassVar[str] = "Patcher"
    name = "patcher"

    OUTPUT_TYPE: ClassVar[Any] = str
    OUTPUT_DEFAULT: ClassVar[str] = ""

    def _producer_value(self) -> str:
        """Surface the workspace `git diff` so the chip and downstream agents get the patch text directly; falls back to the LLM response if no workspace was pinned or the diff was empty."""
        workspace = (self._last_workspace_path or "").strip()
        if workspace:
            diff = generate_diff_impl(workspace) or ""
            if diff.strip():
                return diff
        return self._final_response_text

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are an expert software engineer producing a MINIMAL bug-fix patch.\n"
        "You have a small toolbox of deterministic Python helpers; use them.\n\n"
        "## Step 0: REQUIRED first tool call\n"
        "Call `apply_description_fix(issue_text, workspace)`. It atomically:\n"
        "  1. detects whether the issue is a description / error-message bug,\n"
        "  2. derives the verbatim replacement from the source docstring,\n"
        "  3. builds a unified diff and applies it to the workspace.\n\n"
        "- If the result has `ok: true`: the workspace is ALREADY patched.\n"
        "  Respond with a single line acknowledging the fix and DO NOT call\n"
        "  any further tools. The base agent loop exits as soon as you\n"
        "  respond without a tool call. You are done.\n"
        "- If the result has `ok: false` and `bug_class` is 2 or 3: continue\n"
        "  with the general workflow below. (`bug_class: 2` is a behaviour\n"
        "  bug — wrong output on a specific input. `bug_class: 3` is an API\n"
        "  signature mismatch.)\n\n"
        "## General workflow (class 2 / 3 only)\n"
        "1. Identify the change site:\n"
        "   - If the locator emitted a `<files>` list, start with `read_file`\n"
        "     on the first entry.\n"
        "   - Otherwise use `search_code(query, workspace)` to find candidate\n"
        "     locations, then `read_file` to inspect them.\n"
        "2. Construct a unified diff manually. Wrap it in `<patch>…</patch>`.\n"
        "   Format requirements:\n"
        "     * `diff --git a/<path> b/<path>` header,\n"
        "     * `--- a/<path>` and `+++ b/<path>` file markers,\n"
        "     * `@@ -<old_start>,<old_count> +<new_start>,<new_count> @@`,\n"
        "     * removed lines start with `-`, added with `+`, context with a single space,\n"
        "     * 3 lines of context above and below the hunk,\n"
        "     * repo-relative paths.\n"
        "3. Call `apply_patch(patch_str=<your diff>, repo_path=workspace)`.\n"
        "   - If `ok: false`: call `normalize_patch(patch_str=<your diff>)`\n"
        "     to repair common hunk-header / blank-line mistakes, then\n"
        "     `apply_patch` the normalized result. ONE retry max.\n"
        "4. Optionally call `run_flake8(file_path=<touched.py>)` and fix any\n"
        "   syntax/name errors with a follow-up `apply_patch` call.\n"
        "5. Once a patch has applied successfully, respond with a one-line\n"
        "   summary and stop emitting tool calls.\n\n"
        "## Anti-patterns (always fail the harness)\n"
        "- Paraphrasing the `apply_description_fix` / `derive_description_fix`\n"
        "  output. The harness is character-exact.\n"
        "- Wrapping the buggy code in `try / except`.\n"
        "- Touching test files. The harness scores the very tests you'd be\n"
        "  modifying — never edit them.\n"
        "- Multi-hunk patches when one hunk suffices.\n"
        "- Calling tools NOT in your tool list. The runtime will reject them."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Issue\n{issue}\n\n"
        "## Workspace\n{workspace}\n\n"
        "## Upstream (locator)\n{predecessor}\n\n"
        "Your FIRST tool call MUST be\n"
        "`apply_description_fix(issue_text=<the Issue above>, repo_path=workspace)`.\n"
        "If it returns `ok: true`, you are done — respond with a one-line\n"
        "acknowledgement and emit NO further tool calls. Otherwise follow the\n"
        "general workflow in the system prompt. Do NOT modify test files."
    )
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = (
        # Step-0 deterministic class-1 fixer (detect + derive + apply_patch).
        "apply_description_fix",
        # Lower-level helpers, kept callable for diagnostics.
        "detect_bug_class", "derive_description_fix",
        # General-purpose tools from evomas/tools/ only -- no openhands names.
        "read_file", "list_files", "search_code",
        "apply_patch", "normalize_patch", "generate_diff", "run_flake8",
    )
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.2,
        "num_ctx":      16384,
        "num_predict":  2048,
        "stop":         ["</patch>"],
    }
