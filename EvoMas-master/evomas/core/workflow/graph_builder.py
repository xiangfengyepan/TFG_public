"""Generic LangGraph builder driven by a unified config dict.

The config shape is the one produced by `evomas.config.loader.load_config`:
- `entry`: name of the start node
- `end`: name (string) or list of names of the node(s) that route to END.
- `edges`: list of `{"from": ..., "to": ...}` records

Routing rules:
- A node listed in `end` with no outgoing edges gets a static edge to END.
- A node listed in `end` with one or more outgoing edges gets a conditional
  dispatch through its `route(state)` method; END is always a valid choice.
- A node not listed in `end`:
  * exactly one outgoing edge → static edge to that target
  * multiple outgoing edges → conditional dispatch via `route(state)`
    (END is still wired in as a safety-net target so a buggy router can't
    loop forever — see `_resolve_choice`)
- A node not listed in `end` AND with no outgoing edges is an orphan
  dead-end and rejected at build time.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from evomas.agents.base_agent import BaseAgent
from evomas.exceptions.errors import OllamaMemoryError, TopologyError

logger = logging.getLogger(__name__)


def _wrap(agent: BaseAgent) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node(state: dict[str, Any]) -> dict[str, Any]:
        try:
            return agent.run(dict(state))
        except OllamaMemoryError:
            raise
        except Exception as exc:
            logger.error("agent %s failed: %s", agent.name, exc)
            errors: list[str] = list(state.get("errors") or [])
            errors.append(f"{agent.name}: {exc}")
            return {"errors": errors}

    return node


def _resolve_choice(choice: Any, valid_targets: list[str]) -> str:
    """Clamp a router's choice to either a known target or END."""
    if choice == END:
        return END
    if isinstance(choice, str) and choice in valid_targets:
        return choice
    logger.warning("router returned %r not in %s; routing to END", choice, valid_targets)
    return END


def _software_router(
    agent: BaseAgent, source: str, targets: list[str]
) -> Callable[[dict[str, Any]], str]:
    # Prefer the instance method so config-driven agents (e.g. `LLMToolAgent`
    # whose plan lives on the instance) work alongside class-level static
    # `route(state)` methods used by hand-coded agents like `ManagerAgent`.
    route_attr = getattr(agent, "route", None)
    if route_attr is None:
        raise TopologyError(
            f"node '{source}' needs `route(state)` (multi-edge or in 'end') "
            f"but {type(agent).__name__} has no `route(state)` method"
        )

    def _route(state: dict[str, Any]) -> str:
        return _resolve_choice(route_attr(state), targets)

    return _route


def _normalize_end(raw_end: Any) -> set[str]:
    """Coerce the JSON's `end` field into a set of node names. Accepts a
    single string ("manager_agent") or a list (["a", "b"])."""
    if isinstance(raw_end, str):
        return {raw_end} if raw_end else set()
    if isinstance(raw_end, list):
        return {s for s in raw_end if isinstance(s, str) and s}
    raise TopologyError(
        f"'end' must be a string or list of strings; got {type(raw_end).__name__}"
    )


def build_graph(
    config: dict[str, Any],
    agents: dict[str, BaseAgent],
    state_cls: type,
) -> Any:
    """Compile a graph from a unified config dict.

    `state_cls` is produced by `state_factory.build_state_class(config)`.
    `agents` maps node name → instantiated agent (already configured with its block).
    """
    entry = config.get("entry")
    if not entry:
        raise TopologyError("config missing required 'entry' field")
    if entry not in agents:
        raise TopologyError(f"entry node '{entry}' not in agent registry")

    if "end" not in config:
        raise TopologyError("config missing required 'end' field")
    end_set = _normalize_end(config["end"])
    for name in end_set:
        if name not in agents:
            raise TopologyError(f"end node '{name}' not in agent registry")

    edges = config.get("edges") or []
    out_edges: dict[str, list[str]] = {}
    in_edges: dict[str, list[str]] = {}
    for e in edges:
        src, tgt = e["from"], e["to"]
        if src not in agents:
            raise TopologyError(f"edge source '{src}' not in agent registry")
        if tgt not in agents:
            raise TopologyError(f"edge target '{tgt}' not in agent registry")
        out_edges.setdefault(src, []).append(tgt)
        in_edges.setdefault(tgt, []).append(src)

    # Edge-driven IO: tell each agent who feeds it so the agent's `run()`
    # can read `state[self.predecessor_name]` without hardcoding upstream
    # node ids. Under the out-degree-1 linear-chain model every node has
    # at most one predecessor; the entry node has none. When a node has
    # multiple incoming edges (future fan-in topologies), the first one
    # wins — agents that need richer upstream views read additional slots
    # explicitly by node id.
    for node_name, agent in agents.items():
        upstream = in_edges.get(node_name) or []
        agent.predecessor_name = upstream[0] if upstream else None

    # A node with no outgoing edges and not declared in `end` is an orphan
    # dead-end. Catch this at build time so the runtime doesn't silently
    # stall on a node that has no exit.
    for name in agents:
        if name not in out_edges and name not in end_set:
            raise TopologyError(
                f"node '{name}' has no outgoing edges and is not in 'end'; "
                f"add it to 'end' or give it at least one outgoing edge"
            )

    graph = StateGraph(state_cls)
    for name, agent in agents.items():
        graph.add_node(name, _wrap(agent))

    graph.add_edge(START, entry)

    # Per-source dispatch.
    # - Single-edge source NOT in `end` → static edge.
    # - Single-edge source IN `end`     → conditional (route() picks between
    #   the one target and END).
    # - Multi-edge source                → conditional (route() picks among
    #   targets and may also return END as a safety-net or intentional exit).
    for source, targets in out_edges.items():
        if len(targets) == 1 and source not in end_set:
            graph.add_edge(source, targets[0])
            continue
        route_fn = _software_router(agents[source], source, targets)
        routes = {t: t for t in targets}
        routes[END] = END
        graph.add_conditional_edges(source, route_fn, routes)

    # Static-edge wiring for end nodes that have no outgoing real edges.
    for name in end_set:
        if name not in out_edges:
            graph.add_edge(name, END)

    return graph.compile()
