"""Build the workflow `TypedDict` state class dynamically from a unified config.

Under the linear-chain workflow model, every agent owns a single state slot
keyed by its node id (`state[self.name]`). The slot's static type comes from
the agent class's `OUTPUT_TYPE: ClassVar` declared in Python — JSON no longer
carries per-agent `state` declarations.

`RUNTIME_INPUTS` is the small set of slots seeded by the runner (instance,
workspace_path, issue_text) plus a couple of accumulators (errors, thinking).
`final_patch` is no longer a runtime input — the runner reads `state[cfg.end]`
after the graph completes (see `evomas/core/workflow/runner.py`).

Reducer wiring: with fan-out topologies (multiple downstream nodes scheduled
in the same LangGraph super-step), two parallel agents will return overlapping
deltas — every LLMToolAgent always writes `{"thinking": ...}`, and any branch
that errors out adds to `errors`. Plain LangGraph channels use `LastValue`
semantics and reject concurrent writes (`INVALID_CONCURRENT_GRAPH_UPDATE`).
We tag the two accumulator slots with `Annotated[..., reducer]` so the
super-step merges instead of crashing. Per-agent producer slots stay as plain
`LastValue` channels because each agent uniquely owns its `state[self.name]`
slot by node-id convention.
"""
from __future__ import annotations

import operator
from copy import deepcopy
from typing import Annotated, Any, TypedDict

from evomas.agents.base_agent import BaseAgent

# Runtime-seeded keys present in every workflow state, regardless of topology.
# The runner seeds `instance`, `workspace_path`, and `issue_text` from the
# SWE-bench instance; `errors` and `thinking` accumulate during the run.
# `errors` / `thinking` use `Annotated[..., operator.add]` so fan-in branches
# concatenate cleanly (list-concat for errors, string-concat for thinking).
RUNTIME_INPUTS: list[dict[str, Any]] = [
    {"name": "instance",       "type": dict[str, Any]},
    {"name": "workspace_path", "type": str},
    {"name": "issue_text",     "type": str},
    {"name": "errors",         "type": Annotated[list[str], operator.add], "default": []},
    {"name": "thinking",       "type": Annotated[str,       operator.add], "default": ""},
]


def build_state_class(
    config: dict[str, Any],
    agents: dict[str, BaseAgent],
) -> type:
    """Return a `TypedDict` whose slots are `RUNTIME_INPUTS` plus one slot
    per agent node, named by node id and typed by the class's `OUTPUT_TYPE`."""
    fields: dict[str, Any] = {}
    for entry in RUNTIME_INPUTS:
        fields[entry["name"]] = entry["type"]
    for node_name, agent in agents.items():
        fields[node_name] = type(agent).OUTPUT_TYPE
    # total=False matches the original EvomasState semantics: every key is optional
    return TypedDict("EvomasState", fields, total=False)  # type: ignore[operator]


def build_initial_state(
    config: dict[str, Any],
    agents: dict[str, BaseAgent],
    runtime_inputs: dict[str, Any],
) -> dict[str, Any]:
    """Build the dict the graph is invoked with. RUNTIME_INPUTS defaults seed
    first, then per-agent `OUTPUT_DEFAULT` (deep-copied to avoid shared-ref
    bugs), then the caller's runtime inputs overlay everything.
    """
    state: dict[str, Any] = {}
    for entry in RUNTIME_INPUTS:
        if "default" in entry:
            state[entry["name"]] = deepcopy(entry["default"])
    for node_name, agent in agents.items():
        default = getattr(type(agent), "OUTPUT_DEFAULT", None)
        if default is not None:
            state[node_name] = deepcopy(default)
    state.update(runtime_inputs)
    return state
