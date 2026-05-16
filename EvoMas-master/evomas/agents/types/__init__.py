"""Per-type agent base classes.

The SWE-bench agent-type taxonomy lists eight broad roles an agent can play
inside a multi-agent topology. Each row maps to a thin base class here that
documents the role's expected state contract and slots cleanly under
`LLMToolAgent` (so concrete subclasses inherit the function-calling loop +
fallback machinery for free).

Topology JSON blocks reference these types by their `AGENT_TYPE` label
(e.g. `"class": "Locator"`) -- the runtime registry resolves the name
to the matching base class without any bespoke per-agent Python.

Color palette is defined here so `/api/agent-types` can serve it to the
frontend (single source of truth — UI palette + node coloring).
"""
from __future__ import annotations

from typing import Any

from evomas.agents.base_agent import BaseAgent
from evomas.agents.types.base_agent_type import BaseAgentType
from evomas.agents.types.bug_reproduction import BugReproductionAgent
from evomas.agents.types.environment_setup import EnvironmentSetupAgent
from evomas.agents.types.helper_proxy import HelperProxyAgent
from evomas.agents.types.locator import LocatorAgent
from evomas.agents.types.orchestrator import OrchestratorAgent
from evomas.agents.types.patcher import PatcherAgent
from evomas.agents.types.reviewer import ReviewerAgent

# Ordered as in the SWE-bench AgentType.csv so the frontend palette renders
# them in a consistent, intentional order. Each type is registered TWICE so a
# config block can spell its `class` either as the human-readable AGENT_TYPE
# (e.g. "Locator", "Helper/Proxy") OR the Python class name from
# evomas/agents/types/ (e.g. "LocatorAgent", "HelperProxyAgent"). Both
# resolve to the same class via the AGENT_REGISTRY in runner.py.
_TYPES: tuple[type[BaseAgent], ...] = (
    LocatorAgent,
    PatcherAgent,
    HelperProxyAgent,
    OrchestratorAgent,
    BaseAgentType,
    BugReproductionAgent,
    EnvironmentSetupAgent,
    ReviewerAgent,
)
TYPE_REGISTRY: dict[str, type[BaseAgent]] = {}
for _cls in _TYPES:
    TYPE_REGISTRY[_cls.AGENT_TYPE] = _cls
    TYPE_REGISTRY[_cls.__name__] = _cls

# Stable tints used both by the frontend palette and the topology graph.
TYPE_COLORS: dict[str, str] = {
    "Locator":              "#388bfd",  # blue
    "Patcher":              "#56d364",  # green
    "Helper/Proxy":         "#a371f7",  # purple
    "Planner/Orchestrator": "#e3b341",  # amber
    "Base agent":           "#8b949e",  # neutral gray
    "Bug reproduction":     "#f78166",  # coral
    "Environment setup":    "#39c5cf",  # teal
    "Reviewer":             "#db61a2",  # magenta
}


def list_agent_types() -> list[dict[str, Any]]:
    """Return the agent-type catalog the frontend renders.

    Each entry now carries the type's full default agent block — system /
    user prompts, tool whitelist, and Ollama hyperparameter map — so the
    topology page can seed a freshly-dropped node with the correct config
    without re-deriving anything client-side.
    """
    out: list[dict[str, Any]] = []
    # Iterate `_TYPES` (one entry per class) — TYPE_REGISTRY now keys each
    # class twice (AGENT_TYPE label + Python class name) so its `.values()`
    # would emit duplicates and the topology palette would render two chips
    # per type.
    for cls in _TYPES:
        doc = (cls.__doc__ or "").strip().splitlines()
        out.append({
            "type":            cls.AGENT_TYPE,
            "color":           TYPE_COLORS.get(cls.AGENT_TYPE, "#888"),
            "description":     doc[0] if doc else "",
            "class":           cls.__name__,
            "default_system":  cls.DEFAULT_SYSTEM,
            "default_user":    cls.DEFAULT_USER,
            "default_tools":   list(cls.DEFAULT_TOOLS),
            "default_config":  dict(cls.DEFAULT_CONFIG),
        })
    return out


__all__ = [
    "TYPE_REGISTRY",
    "TYPE_COLORS",
    "list_agent_types",
    "BaseAgentType",
    "BugReproductionAgent",
    "EnvironmentSetupAgent",
    "HelperProxyAgent",
    "LocatorAgent",
    "OrchestratorAgent",
    "PatcherAgent",
    "ReviewerAgent",
]
