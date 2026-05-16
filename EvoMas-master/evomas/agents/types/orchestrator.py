"""Planner / Orchestrator — pure LLM-driven gateway that decides the next step."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


class OrchestratorAgent(LLMToolAgent):
    """Planner / Orchestrator agent.

    Shape mirrors the upstream Planner/Orchestrator agents catalogued at
    `evomas/config/agent_types/*.json` (OpenHands AgentController, HyperAgent
    planner, trae_agent TraeAgent, …): a thin LLM gateway with no tools.
    The graph builder routes the chain; this agent's job is to emit a short
    plan / dispatch acknowledgement that downstream agents can read.

    No custom run() / route() / __init__ — inherits LLMToolAgent. The graph
    builder handles single-edge static dispatch (and multi-edge conditional
    dispatch via the base route()), so we don't bake routing into this type.
    """

    AGENT_TYPE: ClassVar[str] = "Planner/Orchestrator"
    name = "orchestrator"

    OUTPUT_TYPE: ClassVar[Any] = str
    OUTPUT_DEFAULT: ClassVar[str] = ""

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are the Planner/Orchestrator of a multi-agent automated "
        "software-repair pipeline. You do not edit code yourself; you "
        "reason briefly about the problem and forward control to the next "
        "worker agent in the chain (typically Locator → Patcher → Reviewer "
        "→ Helper/Proxy).\n\n"
        "Respond with a one-line plan describing the dispatch decision. "
        "Emit NO tool calls — the base agent loop exits as soon as you "
        "respond without one. The graph topology handles routing."
    )
    DEFAULT_USER: ClassVar[str] = (
        "## Issue\n{issue}\n\n## Workspace\n{workspace}\n\n"
        "Decide the next step and respond with a one-line plan."
    )
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = ()
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":  0.0,
        "num_ctx":      2048,
        "num_predict":  512,
    }
