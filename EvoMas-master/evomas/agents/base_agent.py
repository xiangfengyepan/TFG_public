import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

from langchain_core.messages import BaseMessage
from langchain_ollama import ChatOllama

from evomas.config.loader import AgentConfig, agent_config_from_block
from evomas.models.langchain_ollama_model import build_chat_ollama, llm_invoke

if TYPE_CHECKING:
    from evomas.mcp.server import MCPServer


class BaseAgent(ABC):
    name: ClassVar[str] = "base_agent"

    # Per-type defaults consulted when the JSON block omits the matching field.
    # Subclasses (the SWE-bench taxonomy bases under `agents/types/`) set these
    # so an agent can be declared with just `class: <type>` and inherit a
    # working prompt + tool whitelist.
    DEFAULT_SYSTEM: ClassVar[str] = ""
    DEFAULT_USER: ClassVar[str] = ""
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = ()
    # Per-type Ollama hyperparameter defaults. Layered under the JSON block
    # before AgentConfig is built, so `class: "Patcher"` inherits patcher-
    # tuned knobs without the JSON having to re-declare them. Empty by default
    # — `BaseAgentType` ships the canonical Ollama Modelfile defaults.
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {}

    # ── Edge-driven state contract ──────────────────────────────────────
    # Under the linear-chain workflow model, every agent writes its output
    # into a single state slot keyed by its node id (`state[self.name]`),
    # and consumers read their immediate predecessor's slot via
    # `state[self.predecessor_name]`. `OUTPUT_TYPE` is the static type of
    # what this class produces; `state_factory.build_state_class` uses it
    # to generate a typed TypedDict slot per agent in the graph.
    # `OUTPUT_DEFAULT` (optional) seeds the slot in `build_initial_state`
    # so consumers never trip on a missing key. Subclasses override both.
    OUTPUT_TYPE: ClassVar[Any] = Any
    OUTPUT_DEFAULT: ClassVar[Any] = None

    # Injected by `graph_builder` once the topology is wired: the upstream
    # node that feeds this one. `None` for the entry node. Multi-upstream
    # agents either bundle the data in their predecessor's output or read
    # additional upstream slots explicitly by node id.
    predecessor_name: str | None = None

    def __init__(
        self,
        config_block: dict[str, Any] | None = None,
        node_name: str | None = None,
    ) -> None:
        from evomas.mcp.server import get_server

        block: dict[str, Any] = config_block or {}
        self.config_block: dict[str, Any] = block
        # Layer the type's hyperparameter defaults under the JSON-block values
        # so a config that omits e.g. `num_ctx` falls through to whatever the
        # type considers a sensible starter, while still letting the JSON
        # override any individual knob.
        merged_for_config = {**type(self).DEFAULT_CONFIG, **block}
        self.config: AgentConfig = agent_config_from_block(merged_for_config)
        # Merge JSON-supplied prompts under the class-level defaults so a block
        # can leave any slot blank and inherit a sensible starter.
        block_prompts: dict[str, str] = block.get("prompts") or {}
        self.prompts: dict[str, str] = {
            "system": block_prompts.get("system") or type(self).DEFAULT_SYSTEM,
            "user":   block_prompts.get("user")   or type(self).DEFAULT_USER,
            **{k: v for k, v in block_prompts.items() if k not in {"system", "user"}},
        }
        # Allow the runner to override the agent's node name per-instance so a
        # single config-driven class (e.g. `LLMToolAgent`) can back several
        # graph nodes that differ only in prompts/tools.
        if node_name:
            self.name = node_name  # type: ignore[misc]
        self.logger: logging.Logger = logging.getLogger(f"evomas.agents.{self.name}")
        self.mcp: MCPServer = get_server()
        # Per-agent tool policy. When `tools` is absent from the config block (e.g.
        # legacy callers / tests instantiating an agent directly), behavior is
        # permissive: any registered MCP tool can be called. When `tools` is
        # present (even as []) the list acts as a whitelist, and each entry's
        # `params` dict supplies defaults that the call site can still override.
        self.tool_policy: dict[str, dict[str, Any]] | None = None
        # The JSON's `tools` field, when present, is the authoritative whitelist
        # (even an empty list disables tools). When absent, fall back to the
        # type's `DEFAULT_TOOLS` so a config block can rely on the type base.
        if "tools" in block:
            policy: dict[str, dict[str, Any]] = {}
            for entry in block.get("tools") or []:
                tname = entry.get("name") if isinstance(entry, dict) else None
                if not tname:
                    continue
                params = entry.get("params") if isinstance(entry, dict) else None
                policy[tname] = dict(params) if isinstance(params, dict) else {}
            self.tool_policy = policy
        elif type(self).DEFAULT_TOOLS:
            self.tool_policy = {name: {} for name in type(self).DEFAULT_TOOLS}
        self._thinking: str = ""
        self._on_think: Callable[[str], None] | None = None
        self._on_tool: Callable[[str, dict, Any], None] | None = None
        # Cumulative LLM token usage across every `_invoke()` call this
        # agent makes during a single graph run. The runner / API worker
        # reads it after the graph completes to surface per-instance
        # totals in the prediction JSONL and the Results page.
        self._tokens: dict[str, int] = {"input": 0, "output": 0, "total": 0}

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.tool_policy is not None and name not in self.tool_policy:
            allowed = sorted(self.tool_policy)
            raise PermissionError(
                f"agent '{self.name}' is not allowed to call tool '{name}' "
                f"(allowed: {allowed or '<none>'})"
            )
        # Merge configured defaults under the call-site arguments.
        merged: dict[str, Any] = {}
        if self.tool_policy is not None:
            merged.update(self.tool_policy.get(name) or {})
        merged.update(arguments or {})
        result = self.mcp.call(name, merged)
        if self._on_tool:
            self._on_tool(name, merged, result)
        return result

    def make_llm(self, **overrides: Any) -> ChatOllama:
        return build_chat_ollama(self.config, **overrides)

    def _invoke(self, llm: ChatOllama, messages: list[BaseMessage]) -> Any:
        """Stream the LLM response, logging thinking tokens in real-time."""
        response, self._thinking, usage = llm_invoke(
            llm, messages, agent_name=self.name, on_think=self._on_think
        )
        # Accumulate cumulative token counts so the runner / API worker
        # can report a single in/out/total for the instance.
        self._tokens["input"]  += int(usage.get("input", 0))
        self._tokens["output"] += int(usage.get("output", 0))
        self._tokens["total"]  += int(usage.get("total", 0))
        return response

    @abstractmethod
    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Process state and return a state delta dict (LangGraph node convention)."""
