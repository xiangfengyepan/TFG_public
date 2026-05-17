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
import re
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from evomas.agents.base_agent import BaseAgent
from evomas.agents.types.orchestrator import OrchestratorAgent
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


def _make_router(
    source: str, targets: list[str],
) -> Callable[[dict[str, Any]], list[str]]:
    """Conditional-edge router for an OrchestratorAgent hub. Reads the
    orchestrator's final response text at `state[source]`, scans it for
    whole-word mentions of each candidate target, and returns the
    matched names. Falls back to all targets when nothing matches so
    the run continues — better to over-dispatch than stall on a parser
    miss (the warning log surfaces these for diagnosis)."""
    patterns: dict[str, re.Pattern[str]] = {
        t: re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in targets
    }

    def route(state: dict[str, Any]) -> list[str]:
        text = state.get(source) or ""
        if not isinstance(text, str):
            text = str(text)
        picked = [t for t in targets if patterns[t].search(text)]
        if picked:
            logger.info("[%s] LLM routed to %s (out of %s)", source, picked, targets)
            return picked
        logger.warning(
            "[%s] LLM emitted no parseable target in %r; falling back to all %s",
            source, text[:200], targets,
        )
        return list(targets)

    return route


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

        # Structural wiring. Default = one static edge per (source, target)
        # pair, fanning multi-edge sources out in parallel. Exception:
        # OrchestratorAgent nodes with ≥2 outgoing edges get an LLM-driven
        # conditional edge — the router (`_make_router`) parses
        # `state[source]` for whole-word target names and routes
        # accordingly. Other classes keep the static fan-out.
        for source, targets in out_edges.items():
            agent = agents.get(source)
            if isinstance(agent, OrchestratorAgent) and len(targets) >= 2:
                graph.add_conditional_edges(
                    source,
                    _make_router(source, targets),
                    {t: t for t in targets},
                )
            else:
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
