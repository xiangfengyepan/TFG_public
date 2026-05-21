"""Orchestrator — pure LLM-driven gateway that decides the next step."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


class Orchestrator(LLMToolAgent):
    """Orchestrator agent.

    Shape mirrors the upstream Orchestrator agents catalogued at
    `evomas/config/agent_types/*.json` (OpenHands AgentController, HyperAgent
    planner, trae_agent TraeAgent, …): a thin LLM gateway with no tools.
    The graph builder routes the chain; this agent's job is to emit a short
    plan / dispatch acknowledgement that downstream agents can read.
    """

    AGENT_TYPE: ClassVar[str] = "Orchestrator"
    name = "orchestrator"

    OUTPUT_TYPE: ClassVar[Any] = str
    OUTPUT_DEFAULT: ClassVar[str] = ""

    DEFAULT_SYSTEM: ClassVar[str] = (
        "You are the Orchestrator of a multi-agent automated "
        "software-repair pipeline. You do not edit code yourself; you "
        "decide which worker agent(s) should run next.\n\n"
        "Respond with a SINGLE line containing the names of the next "
        "agent(s) to dispatch, separated by spaces or commas. The exact "
        "agent names are listed in the user prompt. The graph runtime "
        "parses your reply for whole-word matches of those names and "
        "routes the run accordingly. Emit NO tool calls — the base agent "
        "loop exits as soon as you respond without one."
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
