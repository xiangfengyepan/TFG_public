"""Patcher — produces (and optionally selects) the patch that fixes the bug."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


class PatcherAgent(LLMToolAgent):
    """Write the patch / select the best patch among multiple candidates / apply it.

    State contract: writes `candidate_patches: list[str]` (or `final_patch: str | None`
    when also acting as the final selector).
    """

    AGENT_TYPE: ClassVar[str] = "Patcher"
    name = "patcher"

    OUTPUT_TYPE: ClassVar[Any] = list[str]
    OUTPUT_DEFAULT: ClassVar[list[str]] = []

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are an expert software engineer producing a MINIMAL bug-fix patch.\n\n"
        "## Step 0: REQUIRED pre-flight\n"
        "Your FIRST tool call MUST be `detect_bug_class(issue_text, workspace)`.\n"
        "It returns `{bug_class, evidence, matched_quoted_string?, matched_file?, matched_line?}`.\n\n"
        "- If `bug_class == 1` (description / error-message bug):\n"
        "  IMMEDIATELY call `derive_description_fix(workspace, matched_file,\n"
        "  matched_quoted_string)`. It returns `{new_string, absolute_path,\n"
        "  ...}`. Use `new_string` VERBATIM (do not paraphrase, do not\n"
        "  adjust plurality, do not drop the trailing period) as the\n"
        "  replacement for `matched_quoted_string` via `str_replace_editor`\n"
        "  (`str_replace` command, exact unique match) -- and pass\n"
        "  `absolute_path` (NOT the repo-relative `file`) as the tool's\n"
        "  `path` argument. Then `finish`. Do NOT explore the workspace\n"
        "  further -- the helper already pinned the right answer.\n"
        "- If `bug_class == 2` (behaviour) or `bug_class == 3` (API): fall\n"
        "  through to the workflow below.\n\n"
        "## Bug-class context (informational)\n"
        "1. **Description / error-message bug** -- handled by Step 0 above.\n"
        "2. **Behaviour bug** -- wrong output on specific input. Logic change\n"
        "   only; look at any test file the localizator returned -- the\n"
        "   assertion pins the expected behaviour.\n"
        "3. **API signature mismatch** -- align names/types only.\n\n"
        "## Workflow (class 2 / 3 only -- class 1 exits after Step 0)\n"
        "1. Read the issue carefully.\n"
        "2. `read_file` / `view` the source file to locate the change site.\n"
        "3. Apply via `str_replace_editor` (`str_replace`, exact unique match)\n"
        "   or `edit_file`. ONE line replaced. Never modify tests.\n"
        "4. Verify with `generate_diff`. If you emit an inline `<patch>`\n"
        "   block, pass it through `normalize_patch` before `apply_patch`.\n"
        "5. Optionally `run_flake8` on touched .py files; fix any new errors.\n"
        "6. `finish` with a one-sentence summary.\n\n"
        "## Anti-patterns (always fail the harness)\n"
        "- Adding an early-return guard when the issue quotes a description.\n"
        "- Editing the class docstring instead of the `description=` argument.\n"
        "- Wrapping the buggy code in `try / except`.\n"
        "- Touching test files (the harness fixes the test it scores against).\n"
        "- Multi-hunk patches when one-hunk suffices.\n"
        "- Paraphrasing the `derive_description_fix` result. The harness is\n"
        "  character-exact; the helper's `new_string` IS the answer.\n\n"
        "## Strict diff format (when emitting inline)\n"
        "- Wrap the entire patch in <patch>...</patch>.\n"
        "- `diff --git a/<path> b/<path>`, `--- a/...`, `+++ b/...`.\n"
        "- Hunk header `@@ -<old> +<new> @@`. Context lines start with one\n"
        "  space; removed `-`, added `+`. 3 lines of context above and below.\n"
        "- Repo-relative paths verbatim from the file headers."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Issue\n{issue}\n\n"
        "## Workspace\n{workspace}\n\n"
        "First call `detect_bug_class` (REQUIRED). If it reports class 1,\n"
        "follow the Step 0 path in the system prompt. Otherwise apply the\n"
        "smallest change that resolves the issue. Do NOT modify test files."
    )
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = (
        # Step-0 deterministic helpers (see evomas/tools/hardcoded.py).
        "detect_bug_class", "derive_description_fix",
        # General-purpose tools for class 2 / 3 fallback.
        "read_file", "view", "grep", "list_files",
        "str_replace_editor", "edit_file",
        "apply_patch", "normalize_patch", "generate_diff", "run_flake8",
        "think", "finish",
    )
    # Patches need maximum determinism + a long context for the file body
    # plus the agent's own bug-class taxonomy in the system prompt.
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.2,
        "num_ctx":      16384,
        "num_predict":  2048,
        "stop":         ["</patch>"],
    }
