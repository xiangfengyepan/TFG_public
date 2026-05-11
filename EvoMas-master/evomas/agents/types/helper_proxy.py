"""Helper / Proxy — supports the topology without mutating the workspace."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


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
        "You are a read-only helper / proxy agent. You do not modify source files.\n\n"
        "Common duties:\n"
        "- Extract structured JSON from another agent's free-form output (e.g. parse a "
        "<files>…</files> or <patch>…</patch> block into a clean object).\n"
        "- Pick the best of several candidate patches by their validation scores. "
        "(When the LangGraph state already carries `candidate_patches`, that "
        "selection runs deterministically in code — you won't be asked to pick "
        "via the LLM.)\n"
        "- Answer factual questions about the code by reading it with `view` / `read_file` / "
        "`grep` / `glob`.\n\n"
        "When you have produced your answer, call `finish` with a one-sentence summary."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Task\n{issue}\n\n## Workspace\n{workspace}\n"
    )
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = (
        "read_file", "view", "grep", "glob", "list_files", "think", "finish",
    )
    # Lightweight read-only role.
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.2,
        "num_ctx":      4096,
        "num_predict":  512,
    }

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
