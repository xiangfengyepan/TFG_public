import pytest

from evomas.config.loader import (
    AgentConfig,
    agent_config_from_block,
    list_configs,
    load_config,
)
from evomas.core.workflow.runner import _build_agents
from evomas.core.workflow.state_factory import (
    build_initial_state,
    build_state_class,
)
from evomas.exceptions.errors import ConfigError


# ── unified config ────────────────────────────────────────────────────────────

def test_list_configs_includes_chain() -> None:
    # Loader returns filename stems; the chain topology ships as
    # `evomas/config/predefined/chain.json` so the stem is `chain`.
    assert "chain" in list_configs()


def test_load_unknown_config_raises() -> None:
    with pytest.raises(ConfigError):
        load_config("does_not_exist")


def test_chain_top_level_shape() -> None:
    cfg = load_config("chain")
    # `id` is the human-facing identifier carried in the JSON itself; the
    # on-disk filename stem is the routing key used by `load_config`.
    assert cfg["id"] == "chain"
    # Linear chain: locator → patcher → reviewer → finalizer.
    assert cfg["entry"] == "locator"
    assert cfg["end"] == "finalizer"
    assert isinstance(cfg["edges"], list) and cfg["edges"]
    assert isinstance(cfg["agents"], dict)
    assert set(cfg["agents"]) == {
        "locator",
        "patcher",
        "reviewer",
        "finalizer",
    }


# ── per-agent model knobs ─────────────────────────────────────────────────────

@pytest.mark.parametrize("agent_name", [
    "locator",
    "patcher",
    "reviewer",
    "finalizer",
])
def test_agent_config_extracts_valid_knobs(agent_name: str) -> None:
    cfg = load_config("chain")
    block = cfg["agents"][agent_name]
    knobs = agent_config_from_block(block)
    assert isinstance(knobs, AgentConfig)
    assert knobs.model == "ollama/qwen3.5:9b"
    assert 0.0 <= knobs.temperature <= 1.0
    assert knobs.num_ctx > 0


# ── topology shape ────────────────────────────────────────────────────────────

def test_chain_is_linear() -> None:
    """Edge list is a single linear chain from entry → end with no branching."""
    cfg = load_config("chain")
    out: dict[str, list[str]] = {}
    for e in cfg["edges"]:
        out.setdefault(e["from"], []).append(e["to"])

    # Every non-end node has exactly one outgoing edge (out-degree 1).
    for src, targets in out.items():
        assert len(targets) == 1, f"node '{src}' has out-degree {len(targets)}, expected 1"

    # Walk the chain from entry; every node except `end` should appear.
    chain = [cfg["entry"]]
    while chain[-1] in out:
        chain.append(out[chain[-1]][0])
    assert chain == ["locator", "patcher", "reviewer", "finalizer"]
    assert chain[-1] == cfg["end"]


# ── dynamic state class ───────────────────────────────────────────────────────

def test_build_state_class_emits_producer_slots_plus_runtime_inputs() -> None:
    cfg = load_config("chain")
    agents = _build_agents(cfg)
    cls = build_state_class(cfg, agents)
    keys = set(cls.__annotations__.keys())
    # RUNTIME_INPUTS:
    assert {"instance", "workspace_path", "issue_text", "errors", "thinking"}.issubset(keys)
    # One slot per agent node, named by node id:
    assert {"locator", "patcher", "reviewer", "finalizer"}.issubset(keys)
    # The legacy `final_patch` runtime slot is gone — the runner reads
    # `state[cfg.end]` instead.
    assert "final_patch" not in keys


def test_build_initial_state_seeds_class_output_defaults() -> None:
    cfg = load_config("chain")
    agents = _build_agents(cfg)
    state = build_initial_state(
        cfg,
        agents,
        {"instance": {"id": "x"}, "workspace_path": "/tmp", "issue_text": "foo"},
    )
    assert state["instance"] == {"id": "x"}
    assert state["workspace_path"] == "/tmp"
    assert state["issue_text"] == "foo"
    assert state["errors"] == []
    assert state["thinking"] == ""
    # Per-agent slots seeded from each class's OUTPUT_DEFAULT. PatcherAgent
    # now emits a str (the workspace diff) into its producer slot via
    # `_producer_value`, so its OUTPUT_DEFAULT is "" — see patcher.py.
    assert state["locator"] == []
    assert state["patcher"] == ""
    assert state["reviewer"] == {}
    assert state["finalizer"] == ""
