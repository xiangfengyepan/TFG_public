"""Helper / Proxy — supports the topology without mutating the workspace."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent
from evomas.tools.patch_tools import generate_diff_impl


class HelperProxyAgent(LLMToolAgent):
    """Read-only / proxy roles -- ask about code, transform output into JSON, drive a browser session, etc. -- doubling as the deterministic final-patch selector when the predecessor bundles `{patches, validations}`."""

    AGENT_TYPE: ClassVar[str] = "Helper/Proxy"
    name = "helper_proxy"

    # Canonical ensembler slot for star-style chains -- emits the final patch
    # string. Slot stays `str` on the LLM-fallthrough branch too; the empty
    # default signals "no patch produced".
    OUTPUT_TYPE: ClassVar[Any] = str
    OUTPUT_DEFAULT: ClassVar[str] = ""

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are a read-only finalizer agent. You do not modify source files.\n\n"
        "Available tools (use ONLY these):\n"
        "  * `read_file(path, with_line_numbers, max_chars)` — read a file's contents.\n"
        "  * `list_files(directory, extension)` — recursive glob listing.\n"
        "  * `search_code(query, directory)` — BM25 search across .py files.\n\n"
        "Duty: in the linear chain topology you receive the reviewer's verdict\n"
        "and the workspace already contains the patcher's edits. Respond with\n"
        "a one-line acknowledgement (e.g. 'patch accepted: <one-sentence summary>')\n"
        "and emit NO tool calls — the loop exits as soon as you respond without\n"
        "a tool call. The base runner reads the workspace `git diff` as the\n"
        "final prediction patch.\n\n"
        "If the predecessor bundles `{patches, validations}` the framework\n"
        "selects the best candidate deterministically before your run; you'll\n"
        "never be asked to pick via the LLM."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Task\n{issue}\n\n## Workspace\n{workspace}\n\n"
        "## Upstream (reviewer verdict)\n{predecessor}\n\n"
        "Respond with a one-line acknowledgement. Emit no tool calls."
    )
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = (
        "read_file", "list_files", "search_code",
    )
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.2,
        "num_ctx":      4096,
        "num_predict":  512,
    }

    def _producer_value(self) -> str:
        """Surface the workspace `git diff` so the prediction's `model_patch` gets a diff, not the LLM ack text (which the SWE-bench harness can't apply); falls back to the response text on an unchanged workspace so the runner's own diff fallback can still fire."""
        workspace = (self._last_workspace_path or "").strip()
        if workspace:
            diff = generate_diff_impl(workspace) or ""
            if diff.strip():
                return diff
        return self._final_response_text

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Predecessor (typically a Reviewer) forwards a bundle
        # `{patches, validations}` we score and pick from. Topologies that
        # never populate the bundle fall through to the generic LLM loop.
        upstream = state.get(self.predecessor_name or "")
        if not isinstance(upstream, dict):
            return super().run(state)
        candidates: list[str] = list(upstream.get("patches") or [])
        if not candidates:
            return super().run(state)

        results: list[dict[str, Any]] = list(upstream.get("validations") or [])

        if results and len(results) == len(candidates):
            scored = sorted(
                zip(candidates, results),
                key=lambda pr: (
                    pr[1].get("score", 0),
                    pr[1].get("applies", False),
                    pr[1].get("flake8_ok", False),
                    pr[1].get("review_pass", False),
                ),
                reverse=True,
            )
            best_patch, best_result = scored[0]
            self.logger.info(
                "helper_proxy ensembler: picked candidate %s (score=%s applies=%s)",
                best_result.get("patch_idx"),
                best_result.get("score"),
                best_result.get("applies"),
            )
            if best_result.get("score", 0) > 0 and best_patch.strip():
                return {self.name: best_patch}
            # All zero-score -- only fall back to a candidate that applies,
            # else we'd submit a doomed patch the harness rejects.
            applies_map = {
                r.get("patch_idx", i): r.get("applies", False)
                for i, r in enumerate(results)
            }
            fallback = next(
                (p for i, p in enumerate(candidates) if p.strip() and applies_map.get(i, False)),
                "",
            )
            self.logger.info(
                "helper_proxy ensembler: zero-score fallback applies=%s len=%d",
                bool(fallback), len(fallback),
            )
            return {self.name: fallback}

        # No validation_results -- pick first non-empty candidate so the
        # runner's `final_patch` lookup has something.
        self.logger.warning(
            "helper_proxy ensembler: no/mismatched validation results; using first non-empty"
        )
        return {self.name: next((p for p in candidates if p and p.strip()), "")}
