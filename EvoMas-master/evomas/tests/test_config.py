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

def test_list_configs_includes_star() -> None:
    # Loader returns filename stems; the star topology now ships as
    # `evomas/config/evo-star.json` so the stem is `evo-star`.
    assert "evo-star" in list_configs()


def test_load_unknown_config_raises() -> None:
    with pytest.raises(ConfigError):
        load_config("does_not_exist")


def test_evo_star_top_level_shape() -> None:
    cfg = load_config("evo-star")
    # `id` is the human-facing identifier carried in the JSON itself; the
    # on-disk filename stem is the routing key used by `load_config`.
    assert cfg["id"] == "evo-star"
    # Linear chain: localize → patch → validate → ensembler.
    assert cfg["entry"] == "localize_agent"
    assert cfg["end"] == "ensembler_agent"
    assert isinstance(cfg["edges"], list) and cfg["edges"]
    assert isinstance(cfg["agents"], dict)
    assert set(cfg["agents"]) == {
        "localize_agent",
        "patch_agent",
        "validate_agent",
        "ensembler_agent",
    }


# ── per-agent model knobs ─────────────────────────────────────────────────────

@pytest.mark.parametrize("agent_name", [
    "localize_agent",
    "patch_agent",
    "validate_agent",
    "ensembler_agent",
])
def test_agent_config_extracts_valid_knobs(agent_name: str) -> None:
    cfg = load_config("evo-star")
    block = cfg["agents"][agent_name]
    knobs = agent_config_from_block(block)
    assert isinstance(knobs, AgentConfig)
    assert knobs.model == "qwen3.5:9b"
    assert 0.0 <= knobs.temperature <= 1.0
    assert knobs.num_ctx > 0


# ── prompts present where expected ────────────────────────────────────────────

@pytest.mark.parametrize("agent_name", ["localize_agent", "patch_agent", "validate_agent"])
def test_llm_agents_have_prompts(agent_name: str) -> None:
    cfg = load_config("evo-star")
    prompts = cfg["agents"][agent_name].get("prompts") or {}
    assert prompts.get("system"), f"{agent_name} missing system prompt"
    assert prompts.get("user"), f"{agent_name} missing user prompt"


# ── topology shape ────────────────────────────────────────────────────────────

def test_evo_star_is_linear_chain() -> None:
    """Edge list is a single linear chain from entry → end with no branching."""
    cfg = load_config("evo-star")
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
    assert chain == ["localize_agent", "patch_agent", "validate_agent", "ensembler_agent"]
    assert chain[-1] == cfg["end"]


# ── dynamic state class ───────────────────────────────────────────────────────

def test_build_state_class_emits_producer_slots_plus_runtime_inputs() -> None:
    cfg = load_config("evo-star")
    agents = _build_agents(cfg)
    cls = build_state_class(cfg, agents)
    keys = set(cls.__annotations__.keys())
    # RUNTIME_INPUTS:
    assert {"instance", "workspace_path", "issue_text", "errors", "thinking"}.issubset(keys)
    # One slot per agent node, named by node id:
    assert {"localize_agent", "patch_agent", "validate_agent", "ensembler_agent"}.issubset(keys)
    # The legacy `final_patch` runtime slot is gone — the runner reads
    # `state[cfg.end]` instead.
    assert "final_patch" not in keys


def test_build_initial_state_seeds_class_output_defaults() -> None:
    cfg = load_config("evo-star")
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
    # Per-agent slots seeded from each class's OUTPUT_DEFAULT.
    assert state["localize_agent"] == []
    assert state["patch_agent"] == []
    assert state["validate_agent"] == {}
    assert state["ensembler_agent"] == ""
