"""Base agent — generic catch-all type for agents that don't fit a more specific role."""
from __future__ import annotations

from typing import Any, ClassVar

from evomas.agents.llm_tool_agent import LLMToolAgent


class BaseAgentType(LLMToolAgent):
    """Base agent — generic, role-less catch-all carrying the canonical Ollama Modelfile defaults; no system/user prompt and no tool whitelist."""

    AGENT_TYPE: ClassVar[str] = "Base agent"
    name = "base_agent_type"

    OUTPUT_TYPE: ClassVar[Any] = Any
    OUTPUT_DEFAULT: ClassVar[Any] = None

    # Empty by design -- Base agent JSON blocks must supply their own prompts
    # and tools when they need any.
    DEFAULT_SYSTEM: ClassVar[str] = ""
    DEFAULT_USER: ClassVar[str] = ""
    DEFAULT_TOOLS: ClassVar[tuple[str, ...]] = ()

    # Pure Ollama Modelfile defaults --
    # https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx
    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "temperature":    0.8,
        "num_ctx":        2048,
        "top_k":          40,
        "top_p":          0.9,
        "min_p":          0.0,
        "repeat_penalty": 1.1,
        "repeat_last_n":  64,
        "seed":           0,
        "num_predict":    -1,
        "stop":           [],
    }
