"""Helper / Proxy — supports the topology without mutating the workspace."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent
from evomas.tools.patch_tools import generate_diff_impl


class HelperProxyAgent(LLMToolAgent):
    """Read-only / proxy roles: ask questions about code, transform raw model
    output into structured JSON, drive a browser session, etc. Doesn't itself
    write source-file changes.

    Doubles as a final-patch selector (the "ensembler" role) when the LangGraph
    state carries `candidate_patches`: in that case `run()` skips the LLM tool
    loop entirely and writes `final_patch` deterministically using the same
    score-then-applies ranking as `evomas/agents/evo_star/ensembler_agent.py`.
    Topologies that don't populate `candidate_patches` see the original
    `LLMToolAgent.run()` behaviour unchanged.

    State contract: reads `candidate_patches: list[str]` and (optionally)
    `validation_results: list[dict]`; writes `final_patch: str` when the
    ensembler branch fires. Otherwise free-form.
    """

    AGENT_TYPE: ClassVar[str] = "Helper/Proxy"
    name = "helper_proxy"

    # Helper/Proxy is the canonical ensembler slot for star-style chains:
    # it emits the final patch string. Even when it falls back to the
    # generic LLM tool loop (no `candidate_patches` in scope) the slot type
    # stays `str` — the empty-string default signals "no patch produced".
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
    # Lightweight read-only role.
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.2,
        "num_ctx":      4096,
        "num_predict":  512,
    }

    def _producer_value(self) -> str:
        """Same rationale as `PatcherAgent._producer_value`: HelperProxy is
        the canonical finalizer / ensembler slot, and `runner.py` reads
        `state[end_key]` straight into the prediction's `model_patch`. The
        LLM ack text the loop produces ("patch accepted: …") is useful
        for the hand-off chip face but the wrong value for the prediction
        file — the SWE-bench harness would receive a sentence instead of
        a diff and fail to apply it.

        Surface the workspace `git diff` instead; fall back to the
        captured response text only when the workspace has zero changes
        (so the runner's own `generate_diff_impl` fallback still has a
        chance to fire on an empty slot, preserving the pre-refactor
        behaviour for chains that never modify the workspace).

        Only fires on the LLM-fallthrough branch — when `run()` short-
        circuits with `return {self.name: best_patch}` (the ensembler
        path) this override is never consulted.
        """
        workspace = (self._last_workspace_path or "").strip()
        if workspace:
            diff = generate_diff_impl(workspace) or ""
            if diff.strip():
                return diff
        return self._final_response_text

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Edge-driven input: under the linear-chain model the predecessor
        # (typically a Reviewer / Validate agent) forwards a bundle
        # `{patches: list[str], validations: list[dict]}` so we can score
        # and pick from a single slot. When the predecessor produced
        # nothing of that shape (e.g. a generic type-driven topology that
        # never populated the bundle), fall through to the generic
        # LLMToolAgent loop — its behaviour is unchanged.
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
            # All zero-score: only fall back to a candidate that actually applies,
            # so we don't submit a doomed patch that fails the harness.
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

        # No validation_results — pick the first non-empty candidate. Better
        # than empty for the runner's `final_patch` lookup.
        self.logger.warning(
            "helper_proxy ensembler: no/mismatched validation results; using first non-empty"
        )
        return {self.name: next((p for p in candidates if p and p.strip()), "")}
