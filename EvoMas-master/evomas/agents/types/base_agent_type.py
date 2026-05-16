"""Base agent — generic catch-all type for agents that don't fit a more specific role."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


class BaseAgentType(LLMToolAgent):
    """Base agent — generic, role-less. Used when none of the specialized
    type bases (Locator, Patcher, …) apply.

    Carries the canonical Ollama Modelfile defaults — no system/user prompt,
    no tool whitelist. Per the upstream docs:
    https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx
    """

    AGENT_TYPE: ClassVar[str] = "Base agent"
    name = "base_agent_type"

    # The role-less base type produces arbitrary outputs — whatever the
    # configured agent's tool loop writes. Slot stays `Any` with no default.
    OUTPUT_TYPE: ClassVar[Any] = Any
    OUTPUT_DEFAULT: ClassVar[Any] = None

    # Empty prompts and no tool whitelist on purpose — Base agent is the
    # "no defaults" type. JSON blocks that pick `class: "Base agent"` are
    # responsible for supplying their own prompt + tools when they need any.
    DEFAULT_SYSTEM: ClassVar[str] = ""
    DEFAULT_USER: ClassVar[str] = ""
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = ()

    # Pure Ollama Modelfile defaults — see linked docs above.
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":    0.8,    # Modelfile default
        "num_ctx":        2048,   # Modelfile default
        "top_k":          40,
        "top_p":          0.9,
        "min_p":          0.0,
        "repeat_penalty": 1.1,
        "repeat_last_n":  64,
        "seed":           0,
        "num_predict":    -1,
        "stop":           [],
    }
