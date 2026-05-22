"""Per-type agent base classes for the SWE-bench AGENT_TYPE taxonomy, plus the color palette `/api/agent-types` serves to the frontend (single source of truth for UI palette + node coloring)."""
from __future__ import annotations

from typing import Any

from evomas.agents.base_agent import BaseAgent
from evomas.agents.types.base_agent_type import BaseAgentType
from evomas.agents.types.bug_reproduction import BugReproductionAgent
from evomas.agents.types.environment_setup import EnvironmentSetupAgent
from evomas.agents.types.helper_proxy import HelperProxyAgent
from evomas.agents.types.locator import LocatorAgent
from evomas.agents.types.orchestrator import Orchestrator
from evomas.agents.types.patcher import PatcherAgent
from evomas.agents.types.reviewer import ReviewerAgent

# Ordered as in the SWE-bench AgentType.csv so the frontend palette renders
# them consistently. Each type is registered TWICE so a config block can spell
# `class` as either the AGENT_TYPE label ("Locator") or the Python class name
# ("LocatorAgent") -- both resolve via AGENT_REGISTRY in runner.py.
_TYPES: tuple[type[BaseAgent], ...] = (
    LocatorAgent,
    PatcherAgent,
    HelperProxyAgent,
    Orchestrator,
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
    "Orchestrator": "#e3b341",  # amber
    "Base agent":           "#8b949e",  # neutral gray
    "Bug reproduction":     "#f78166",  # coral
    "Environment setup":    "#39c5cf",  # teal
    "Reviewer":             "#db61a2",  # magenta
}


def list_agent_types() -> list[dict[str, Any]]:
    """Return the agent-type catalog the frontend renders, each entry carrying the type's full default block (prompts + tools + config) so the topology page can seed a dropped node without re-deriving anything client-side."""
    out: list[dict[str, Any]] = []
    # Iterate `_TYPES` (one entry per class), not TYPE_REGISTRY -- the
    # registry double-keys each class so `.values()` would emit duplicates.
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
    "Orchestrator",
    "PatcherAgent",
    "ReviewerAgent",
]
