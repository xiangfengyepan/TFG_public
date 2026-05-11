"""Planner / Orchestrator — central hub that dispatches to worker agents."""
from __future__ import annotations

from typing import Any, ClassVar

from langgraph.graph import END

from evomas.agents.llm_tool_agent import LLMToolAgent


class OrchestratorAgent(LLMToolAgent):
    """Plans and coordinates: separates planning from execution and dispatches
    file edits to designated workers. Software-routed (the langgraph software
    router calls `route(state)` after each invocation), so the body skips the
    LLM call entirely and just advances the plan-step counter.

    State contract:
      * `step: int` — index into `self.plan`, incremented by `run()` and
        consumed by `route()`.
    JSON block fields (in addition to LLMToolAgent's):
      * `plan: list[str]` — node names to dispatch to, in order.
    """

    AGENT_TYPE: ClassVar[str] = "Planner/Orchestrator"
    name = "orchestrator"

    # Orchestrator is a router, not a producer; its slot is unused under the
    # linear-chain model (every node has out-degree 1). Slot stays `Any` so
    # the TypedDict still has a placeholder if some future config wires it
    # up as a regular producer.
    OUTPUT_TYPE: ClassVar[Any] = Any
    OUTPUT_DEFAULT: ClassVar[Any] = None

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are the orchestrator of a multi-agent automated software-repair pipeline. "
        "You do not edit code yourself. You break down the problem and dispatch tasks to "
        "specialized worker agents (Localizator, Patcher, Reviewer, Helper/Proxy). "
        "When the LLM is asked to think, it should reason about WHICH worker should run "
        "next given the state of the current attempt."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Issue\n{issue}\n\n## Workspace\n{workspace}\n\n"
        "Decide the next worker to dispatch."
    )
    # Orchestrator nodes are software-routed and don't need any MCP tools.
    # `think` / `finish` are kept in DEFAULT_TOOLS for cosmetic palette
    # purposes; the body never actually invokes an LLM in this type.
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = ("think", "finish")
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.2,
        "num_ctx":      2048,
        "num_predict":  512,
    }

    def __init__(
        self,
        config_block: dict[str, Any] | None = None,
        node_name: str | None = None,
    ) -> None:
        super().__init__(config_block, node_name=node_name)
        block = config_block or {}
        # `plan` is a fixed sequence of worker node names. Each call to
        # `route(state)` returns `plan[step - 1]` until the list is
        # exhausted, at which point we yield langgraph END.
        self.plan: list[str] = list(block.get("plan") or [])

    # ─── Node body ───────────────────────────────────────────────────────
    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Router-mode body: no LLM call, just bump the plan counter so
        # `route(state)` (called next by the software router) can pick the
        # next worker.
        return {"step": int(state.get("step") or 0) + 1}

    # ─── Routing ─────────────────────────────────────────────────────────
    def route(self, state: dict[str, Any]) -> Any:
        """Plan-driven dispatch. `step` is incremented by `run()` before
        this is called, so the worker for this iteration is
        `plan[step - 1]`. When the plan is exhausted we return
        langgraph's `END`."""
        if not self.plan:
            return END
        idx = int(state.get("step") or 0) - 1
        if 0 <= idx < len(self.plan):
            return self.plan[idx]
        return END
