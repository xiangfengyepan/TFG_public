"""Tests for `evomas.core.workflow.graph_builder` + the runner's
super-step budget wiring.

`build_graph` is intentionally minimal now — it constructs the
`StateGraph` and lets LangGraph handle fan-out / fan-in / cycles
natively. The remaining structural rules (entry/end existence,
unreachable nodes, orphan dead-ends) are pre-flight diagnostics on the
frontend Topology page's Validate button; they don't have runtime
counterparts.

Covered here:
- linear chain compiles,
- multi-edge sources fan out without a router,
- per-edge hand-off log lines (summary + offered content),
- shared accumulator reducers (`thinking`, `errors`) survive fan-in,
- cycles in the topology compile (runner caps execution via
  `recursion_limit = EVOMAS_GRAPH_MAX_REVISITS * len(agents)`).
"""
from __future__ import annotations

import operator
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

import pytest

from evomas.core.workflow.graph_builder import build_graph
from evomas.exceptions.errors import TopologyError


class _State(TypedDict, total=False):
    errors: list[str]


def _fake_agent(name: str) -> SimpleNamespace:
    """A minimal stand-in for BaseAgent. `build_graph` only reads `.run()`
    (via `_wrap`) and writes `.predecessor_name`; everything else is for the
    runtime which these tests don't exercise."""
    return SimpleNamespace(
        name=name,
        predecessor_name=None,
        run=lambda state: {},
    )


def _agents(*names: str) -> dict[str, Any]:
    return {n: _fake_agent(n) for n in names}


def test_linear_chain_compiles() -> None:
    """Sanity baseline: a 3-node linear chain still builds — same shape
    as the `chain.json` topology."""
    cfg = {
        "entry": "a",
        "end": "c",
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    }
    graph = build_graph(cfg, _agents("a", "b", "c"), _State)
    assert graph is not None


def test_multi_edge_source_fans_out_without_router() -> None:
    """A source with two outgoing edges builds without any `route()` method
    on the agent — proves the conditional-dispatch path is gone."""
    cfg = {
        "entry": "root",
        "end": ["leaf_a", "leaf_b"],
        "edges": [
            {"from": "root", "to": "leaf_a"},
            {"from": "root", "to": "leaf_b"},
        ],
    }
    # Neither agent defines `route()`; pre-refactor this would have raised
    # TopologyError("node 'root' needs route(state) …"). Now it just compiles.
    graph = build_graph(cfg, _agents("root", "leaf_a", "leaf_b"), _State)
    assert graph is not None


# Well-formedness checks (unreachable END, orphan dead-ends, etc.) now
# live on the frontend's Topology page (`validateConfig()` behind the
# Validate toolbar button). `build_graph` itself just constructs +
# compiles; structural problems surface as a wrapped `TopologyError`
# from the catch block instead of explicit per-check raises.


def test_handoff_log_line_per_outgoing_edge(caplog: pytest.LogCaptureFixture) -> None:
    """After a node finishes, _wrap should emit a summary line plus an
    "offered" content line per outgoing edge. Run the compiled graph
    end-to-end so the wrap closure fires."""
    cfg = {
        "entry": "a",
        "end": "b",
        "edges": [{"from": "a", "to": "b"}],
    }
    agents = _agents("a", "b")
    # Each fake agent writes its own canonical producer slot.
    agents["a"].run = lambda state: {"a": "hello"}
    agents["b"].run = lambda state: {"b": "world"}

    graph = build_graph(cfg, agents, _State)

    caplog.set_level("INFO", logger="evomas.core.workflow.graph_builder")
    graph.invoke({})

    msgs = [r.message for r in caplog.records]
    # Summary line — no `keys=` jargon (dropped in the offered/received
    # refactor; the chip modal stopped showing keys too).
    summary_lines = [m for m in msgs if "-> [" in m and "payload=" in m]
    assert len(summary_lines) == 1
    assert "[a] -> [b]" in summary_lines[0]
    assert "keys=" not in summary_lines[0]
    assert "payload=str(5 B)" in summary_lines[0]
    # Offered content line — the source's producer-slot value inlined.
    offered_lines = [m for m in msgs if "[a] offered to [b]:" in m]
    assert len(offered_lines) == 1
    assert "hello" in offered_lines[0]


def test_handoff_log_fans_out_per_target(caplog: pytest.LogCaptureFixture) -> None:
    """For a multi-edge source, _wrap emits one summary + offered line pair
    per outgoing target — the same source agent appears multiple times."""
    cfg = {
        "entry": "root",
        "end": ["leaf_a", "leaf_b"],
        "edges": [
            {"from": "root", "to": "leaf_a"},
            {"from": "root", "to": "leaf_b"},
        ],
    }
    agents = _agents("root", "leaf_a", "leaf_b")
    agents["root"].run = lambda state: {"root": [1, 2, 3]}
    agents["leaf_a"].run = lambda state: {"leaf_a": "A"}
    agents["leaf_b"].run = lambda state: {"leaf_b": "B"}

    graph = build_graph(cfg, agents, _State)
    caplog.set_level("INFO", logger="evomas.core.workflow.graph_builder")
    graph.invoke({})

    msgs = [r.message for r in caplog.records]
    summary_lines = [m for m in msgs if "-> [" in m and "payload=" in m]
    # `root` is the only node with outgoing edges; two targets => two summaries.
    assert any("[root] -> [leaf_a]" in m for m in summary_lines)
    assert any("[root] -> [leaf_b]" in m for m in summary_lines)
    assert len(summary_lines) == 2
    # And two matching offered-content lines.
    offered_lines = [m for m in msgs if "offered to" in m]
    assert any("[root] offered to [leaf_a]" in m for m in offered_lines)
    assert any("[root] offered to [leaf_b]" in m for m in offered_lines)
    assert len(offered_lines) == 2


def test_fan_in_with_shared_accumulator_does_not_crash() -> None:
    """When two parallel branches both write to a shared accumulator slot
    (`thinking` / `errors`) in the same super-step, LangGraph rejects the
    concurrent write unless the slot has a reducer. The example.json config
    triggered this with a 3-way fan-in into reviewer. Reducers on `errors`
    and `thinking` in `state_factory.RUNTIME_INPUTS` fix it."""
    from evomas.core.workflow.state_factory import build_state_class

    cfg = {
        "entry": "root",
        "end": "sink",
        "edges": [
            {"from": "root", "to": "a"},
            {"from": "root", "to": "b"},
            {"from": "a", "to": "sink"},
            {"from": "b", "to": "sink"},
        ],
    }
    agents = _agents("root", "a", "b", "sink")
    # Both `a` and `b` write to `thinking` — the shared accumulator that
    # used to blow up. With the reducer in place the two strings concatenate.
    agents["root"].run = lambda state: {"root": "go"}
    agents["a"].run = lambda state: {"a": "A out", "thinking": "[a] thought "}
    agents["b"].run = lambda state: {"b": "B out", "thinking": "[b] thought "}
    agents["sink"].run = lambda state: {"sink": "done"}

    # build_state_class reads OUTPUT_TYPE off `type(agent)` — our
    # SimpleNamespace fakes don't carry one, so build the TypedDict
    # manually with just the RUNTIME_INPUTS so reducer wiring is exercised.
    state_cls = build_state_class(cfg, {})
    graph = build_graph(cfg, agents, state_cls)
    final = graph.invoke({"thinking": "", "errors": []})

    # Reducer = operator.add for str → concatenation of all parallel writes.
    assert "[a] thought" in final["thinking"]
    assert "[b] thought" in final["thinking"]


def test_cycle_in_topology_compiles() -> None:
    """Cycles are allowed at build time. The runtime cap is enforced by
    the runner's recursion_limit (max_revisits * num_agents super-steps)."""
    cfg = {
        "entry": "a",
        "end": "c",
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},  # back-edge
            {"from": "b", "to": "c"},
        ],
    }
    graph = build_graph(cfg, _agents("a", "b", "c"), _State)
    assert graph is not None


# ── runner.py: revisit-budget env wiring ──────────────────────────────────

def test_max_revisits_defaults_to_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var set → default of 2 from DEFAULT_MAX_REVISITS."""
    from evomas.core.workflow import runner

    monkeypatch.delenv("EVOMAS_GRAPH_MAX_REVISITS", raising=False)
    assert runner._max_revisits() == runner.DEFAULT_MAX_REVISITS == 2


def test_max_revisits_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from evomas.core.workflow import runner

    monkeypatch.setenv("EVOMAS_GRAPH_MAX_REVISITS", "5")
    assert runner._max_revisits() == 5


def test_max_revisits_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-integer env values warn and fall back to the default rather than
    crashing the run with a ValueError."""
    from evomas.core.workflow import runner

    monkeypatch.setenv("EVOMAS_GRAPH_MAX_REVISITS", "not-a-number")
    assert runner._max_revisits() == runner.DEFAULT_MAX_REVISITS


def test_max_revisits_clamps_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 / negative values would let LangGraph hang on the first super-step
    with recursion_limit=0; clamp up to 1."""
    from evomas.core.workflow import runner

    monkeypatch.setenv("EVOMAS_GRAPH_MAX_REVISITS", "0")
    assert runner._max_revisits() == 1
    monkeypatch.setenv("EVOMAS_GRAPH_MAX_REVISITS", "-3")
    assert runner._max_revisits() == 1


class _DiamondState(TypedDict, total=False):
    """State for the 3-way fan-out / fan-in test below. Declares the reducer
    annotations on `thinking` / `errors` the same way `state_factory.
    RUNTIME_INPUTS` does (`Annotated[..., operator.add]`) and the five
    producer slots the diamond's fake agents write to. SimpleNamespace fakes
    don't carry `OUTPUT_TYPE`, so `build_state_class` can't declare these
    slots dynamically -- declaring them by hand here is the lightest way to
    let the parallel writes survive the super-step merge."""
    thinking: Annotated[str, operator.add]
    errors: Annotated[list[str], operator.add]
    source: str
    a: str
    b: str
    c: str
    sink: str


def test_multi_fan_out_and_fan_in_propagate_state() -> None:
    """3-way fan-out + 3-way fan-in (the `multi-chain.json` shape, minus its
    `reviewer → ensembler` linear tail). Asserts the edges actually carry
    state: each branch reads its predecessor's producer slot, the sink reads
    all three branch slots, and the accumulator reducers (`thinking`,
    `errors`) merge all three parallel writes without raising
    INVALID_CONCURRENT_GRAPH_UPDATE."""
    cfg = {
        "entry": "source",
        "end": "sink",
        "edges": [
            {"from": "source", "to": "a"},
            {"from": "source", "to": "b"},
            {"from": "source", "to": "c"},
            {"from": "a", "to": "sink"},
            {"from": "b", "to": "sink"},
            {"from": "c", "to": "sink"},
        ],
    }
    agents = _agents("source", "a", "b", "c", "sink")

    # Each fake `run` embeds its predecessor's slot value in its own output,
    # so a dropped edge would show up as a KeyError or a wrong final string.
    agents["source"].run = lambda s: {
        "source": "S", "thinking": "[source] ", "errors": ["[source]"],
    }
    agents["a"].run = lambda s: {
        "a": f"A<-{s['source']}", "thinking": "[a] ", "errors": ["[a]"],
    }
    agents["b"].run = lambda s: {
        "b": f"B<-{s['source']}", "thinking": "[b] ", "errors": ["[b]"],
    }
    agents["c"].run = lambda s: {
        "c": f"C<-{s['source']}", "thinking": "[c] ", "errors": ["[c]"],
    }
    agents["sink"].run = lambda s: {
        "sink": f"sink<-{s['a']}|{s['b']}|{s['c']}",
        "thinking": "[sink] ",
        "errors": ["[sink]"],
    }

    graph = build_graph(cfg, agents, _DiamondState)
    final = graph.invoke({"thinking": "", "errors": []})

    # ─── Edge propagation ──────────────────────────────────────────────
    # Source → {a, b, c}: each branch's output embeds the source slot.
    assert final["source"] == "S"
    assert final["a"] == "A<-S"
    assert final["b"] == "B<-S"
    assert final["c"] == "C<-S"
    # {a, b, c} → sink: sink's output embeds all three upstream slots.
    assert final["sink"].startswith("sink<-")
    assert "A<-S" in final["sink"]
    assert "B<-S" in final["sink"]
    assert "C<-S" in final["sink"]

    # ─── Reducer accumulators survive 3-way fan-in ────────────────────
    for tag in ("[source]", "[a]", "[b]", "[c]", "[sink]"):
        assert tag in final["thinking"], f"thinking missing {tag}: {final['thinking']!r}"
    assert set(final["errors"]) == {"[source]", "[a]", "[b]", "[c]", "[sink]"}
