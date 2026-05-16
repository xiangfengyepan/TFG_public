import logging
import os
from typing import Any

from evomas.agents.base_agent import BaseAgent
from evomas.agents.llm_tool_agent import LLMToolAgent
from evomas.agents.types import TYPE_REGISTRY
from evomas.config.loader import load_config, resolve_variant_block
from evomas.core.workflow.graph_builder import build_graph
from evomas.core.workflow.state_factory import build_initial_state, build_state_class
from evomas.exceptions.errors import ConfigError, EvomasError, OllamaMemoryError
from evomas.tools.patch_tools import generate_diff_impl
from evomas.utils.workspace import clone_workspace

logger = logging.getLogger(__name__)

# Per-node revisit budget. The total LangGraph super-step budget is
# `DEFAULT_MAX_REVISITS * len(agents)`, so each node can participate in up
# to this many super-steps before `GraphRecursionError` fires. Override via
# the `EVOMAS_GRAPH_MAX_REVISITS` env var.
DEFAULT_MAX_REVISITS: int = 2


def _max_revisits() -> int:
    raw = os.getenv("EVOMAS_GRAPH_MAX_REVISITS", "").strip()
    if not raw:
        return DEFAULT_MAX_REVISITS
    try:
        v = int(raw)
    except ValueError:
        logger.warning(
            "EVOMAS_GRAPH_MAX_REVISITS=%r is not an int; using default %d",
            raw, DEFAULT_MAX_REVISITS,
        )
        return DEFAULT_MAX_REVISITS
    return max(1, v)

AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    # Generic config-driven agent (function-calling LLM loop or plan-driven router).
    # Used by openhands.json for every node — prompts, tools, and routing live in
    # the JSON block, no per-node Python required.
    "LLMToolAgent": LLMToolAgent,
    # Per-type bases registered under their human-readable type name so a JSON
    # block can spell `"class": "Locator"` etc. and skip hand-coding.
    **TYPE_REGISTRY,
}


def _build_agents(config: dict[str, Any]) -> dict[str, BaseAgent]:
    agents: dict[str, BaseAgent] = {}
    for name, block in (config.get("agents") or {}).items():
        # Pull `prompts` + `tools` from the variant catalog when the block
        # sets `variant: "<RepoId>:<AgentName>"` and doesn't inline them.
        # Inline values always win.
        block = resolve_variant_block(block)
        cls_name = block.get("class")
        if not cls_name:
            raise ConfigError(f"agent '{name}' missing required 'class' field")
        cls = AGENT_REGISTRY.get(cls_name)
        if cls is None:
            raise ConfigError(
                f"agent '{name}': unknown class '{cls_name}' "
                f"(known: {sorted(AGENT_REGISTRY)})"
            )
        agents[name] = cls(block, node_name=name)
    return agents


def _compose_issue(instance: dict[str, Any]) -> str:
    parts: list[str] = []
    if instance.get("problem_statement"):
        parts.append(str(instance["problem_statement"]))
    hints = instance.get("hints_text")
    if hints:
        parts.append("\n## Hints\n" + str(hints))
    return "\n".join(parts).strip()


def _maybe_weave_op(fn):
    try:
        import weave  # type: ignore

        return weave.op()(fn)
    except Exception:
        return fn


def _run_impl(instance: dict[str, Any], config: str = "") -> str:
    """Run the EvoMas workflow for a single SWE-bench instance.

    `config` is either a name (resolved against `evomas/config/<name>.json`) or a
    path to a unified config JSON.
    """
    instance_id: str = instance["instance_id"]
    repo: str = instance["repo"]
    base_commit: str = instance["base_commit"]

    logger.info("=== running %s with config=%s ===", instance_id, config)
    cfg = load_config(config)

    workspace = clone_workspace(instance_id, repo, base_commit)
    issue_text = _compose_issue(instance)

    # Order matters: state_factory needs the agent instances to read each
    # class's `OUTPUT_TYPE` / `OUTPUT_DEFAULT` ClassVars.
    agents = _build_agents(cfg)
    state_cls = build_state_class(cfg, agents)
    graph = build_graph(cfg, agents, state_cls)

    initial_state = build_initial_state(
        cfg,
        agents,
        {
            "instance": instance,
            "workspace_path": str(workspace.path),
            "issue_text": issue_text,
        },
    )

    max_revisits = _max_revisits()
    recursion_limit = max_revisits * max(1, len(agents))
    invoke_config: dict[str, Any] = {"recursion_limit": recursion_limit}
    logger.info(
        "graph runtime: %d agents x %d max revisits => recursion_limit=%d",
        len(agents), max_revisits, recursion_limit,
    )
    try:
        final_state = graph.invoke(initial_state, config=invoke_config)
    except OllamaMemoryError:
        raise  # preserve the specific type so callers can handle it
    except Exception as exc:
        logger.exception("graph execution failed for %s: %s", instance_id, exc)
        raise EvomasError(f"graph failure for {instance_id}: {exc}") from exc

    # Read the predicted patch from the end node's producer slot. `cfg.end`
    # may be a single name or a list — when a list, the last entry wins
    # (terminal-most node by convention).
    end_field: Any = cfg.get("end")
    end_key: str = (
        end_field if isinstance(end_field, str)
        else (end_field[-1] if end_field else "")
    )
    final_patch: str = str(final_state.get(end_key) or "")
    if not final_patch.strip():
        logger.warning(
            "%s produced empty patch in state[%r]; falling back to git diff",
            instance_id, end_key,
        )
        final_patch = generate_diff_impl(str(workspace.path)) or ""

    # Per-instance token report. Each agent accumulates its own counts in
    # `BaseAgent._tokens` across every `_invoke()` call; sum them here so
    # the CLI run-log line is comparable to what the API worker writes.
    tokens_in    = sum(int(a._tokens.get("input", 0))  for a in agents.values())
    tokens_out   = sum(int(a._tokens.get("output", 0)) for a in agents.values())
    tokens_total = sum(int(a._tokens.get("total", 0))  for a in agents.values())
    logger.info(
        "=== %s done: %d-char patch | tokens in=%d out=%d total=%d ===",
        instance_id, len(final_patch), tokens_in, tokens_out, tokens_total,
    )
    return final_patch


run = _maybe_weave_op(_run_impl)
