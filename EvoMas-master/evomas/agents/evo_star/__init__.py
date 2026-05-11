"""Hand-coded agents for the evo-star linear topology.

These four classes carry bespoke Python (BM25 keyword extraction, multi-
candidate scoring, deterministic patch ensembling) that the generic
LLMToolAgent loop can't express on its own. The evo-star.json config
references them by class name; every other shipped config uses the type-
driven LLMToolAgent subclasses under `evomas/agents/types/` instead.

`ManagerAgent` was removed when evo-star migrated from a hub-and-spoke
graph to a static linear chain (`localize → patch → validate → ensembler`).
Its retry-loop role is no longer needed: under out-degree-1 routing the
chain runs through once and terminates.
"""
from evomas.agents.evo_star.ensembler_agent import EnsemblerAgent
from evomas.agents.evo_star.localize_agent import LocalizeAgent
from evomas.agents.evo_star.patch_agent import PatchAgent
from evomas.agents.evo_star.validate_agent import ValidateAgent

__all__ = [
    "EnsemblerAgent",
    "LocalizeAgent",
    "PatchAgent",
    "ValidateAgent",
]
