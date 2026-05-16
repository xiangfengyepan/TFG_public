"""Generic LangGraph builder driven by a unified config dict.

The config shape is the one produced by `evomas.config.loader.load_config`:
- `entry`: name of the start node
- `end`: name (string) or list of names of the node(s) that route to END.
- `edges`: list of `{"from": ..., "to": ...}` records

Wiring rules (purely structural — no agent introspection):
- A node listed in `end` with no outgoing edges gets a static edge to END.
- Any node with one or more outgoing edges gets a *static* edge to every
  one of its targets. LangGraph fans the targets out in parallel using
  its super-step scheduler; multi-edge sources do not consult any agent
  router — every successor runs.

Cycles are allowed; the runner caps per-node revisits via `recursion_limit`
(see `evomas/core/workflow/runner.py:_max_revisits`).

Pre-flight validation (orphan dead-ends, unreachable nodes, etc.) lives
on the frontend Topology page's Validate button. This module just
constructs + compiles the graph — any structural problem the frontend
missed surfaces as a `TopologyError` wrapping whatever LangGraph (or
the wiring code) raised, so callers get a consistent error type.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from evomas.agents.base_agent import BaseAgent
from evomas.exceptions.errors import OllamaMemoryError, TopologyError
from evomas.utils.handoff import preview_payload, summarize_payload

# Cap on the inline content embedded in each hand-off log line. The full
# producer-slot value still rides on the SSE `handoff.preview` event
# (capped at 16 KB) for the chip modal; this tighter cap keeps the
# human-readable `.log` scannable for runs with multi-KB diffs.
_HANDOFF_LOG_PREVIEW_CHARS: int = 1000

logger = logging.getLogger(__name__)


def _wrap(
    agent: BaseAgent, targets: list[str]
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node(state: dict[str, Any]) -> dict[str, Any]:
        try:
            delta = agent.run(dict(state))
        except OllamaMemoryError:
            raise
        except Exception as exc:
            logger.error("agent %s failed: %s", agent.name, exc)
            errors: list[str] = list(state.get("errors") or [])
            errors.append(f"{agent.name}: {exc}")
            return {"errors": errors}

        # Hand-off log: per outgoing edge we emit a summary line plus an
        # "offered" content line. The canonical producer slot is
        # `delta[agent.name]` (edge-driven IO contract); fall back to the
        # whole delta when the agent wrote to other keys. The receiver
        # side logs the matching "received" line from `LLMToolAgent._run_llm_loop`
        # so the `.log` is self-sufficient — no need to cross-reference
        # NDJSON or stitch together the source's `|resp` stream.
        if targets and isinstance(delta, dict):
            primary = delta.get(agent.name, delta)
            payload_summary = summarize_payload(primary)
            offered_preview = preview_payload(
                primary, max_chars=_HANDOFF_LOG_PREVIEW_CHARS,
            ).replace("\n", "\\n")
            for target in targets:
                logger.info(
                    "[%s] -> [%s] payload=%s",
                    agent.name, target, payload_summary,
                )
                if offered_preview.strip():
                    logger.info(
                        "[%s] offered to [%s]: %s",
                        agent.name, target, offered_preview,
                    )
        return delta

    return node


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

    Pre-flight validation lives on the frontend's Topology page (the
    Validate toolbar button calls `validateConfig()` and surfaces every
    well-formedness check before the user kicks off a run). This
    function therefore just constructs the graph — any structural
    problem the frontend missed surfaces as a `TopologyError` wrapping
    whatever LangGraph or the wiring code raised, so the runtime still
    gives a useful message instead of an opaque traceback.
    """
    try:
        entry = config.get("entry")
        end_set = _normalize_end(config.get("end", []))

        edges = config.get("edges") or []
        out_edges: dict[str, list[str]] = {}
        in_edges: dict[str, list[str]] = {}
        for e in edges:
            src, tgt = e["from"], e["to"]
            out_edges.setdefault(src, []).append(tgt)
            in_edges.setdefault(tgt, []).append(src)

        # Edge-driven IO: tell each agent who feeds it so its `run()` can
        # read `state[self.predecessor_name]` without hardcoding upstream
        # node ids. Multi-upstream nodes see the first incoming edge.
        for node_name, agent in agents.items():
            upstream = in_edges.get(node_name) or []
            agent.predecessor_name = upstream[0] if upstream else None

        graph = StateGraph(state_cls)
        for name, agent in agents.items():
            graph.add_node(name, _wrap(agent, list(out_edges.get(name, []))))

        graph.add_edge(START, entry)

        # Structural wiring: one static edge per (source, target) pair.
        # LangGraph fans multi-edge sources out in parallel. No agent
        # introspection.
        for source, targets in out_edges.items():
            for target in targets:
                graph.add_edge(source, target)

        # Static-edge wiring for end nodes that have no outgoing real edges.
        for name in end_set:
            if name not in out_edges:
                graph.add_edge(name, END)

        return graph.compile()
    except TopologyError:
        # Let our own well-formedness errors propagate as-is (e.g. from
        # `_normalize_end` rejecting a non-string `end` field).
        raise
    except Exception as exc:
        # Anything LangGraph or the wiring code raised — wrong agent id
        # in `entry`/`end`/an edge, duplicate node add, etc. — surface
        # as a `TopologyError` so callers (runner, api/server) get a
        # consistent error type to render in the UI.
        raise TopologyError(
            f"failed to compile graph from config: {type(exc).__name__}: {exc}"
        ) from exc
