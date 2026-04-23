from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.src.models.ollama_model import OllamaWrapper, MessageRoleEnum
from langchain_core.output_parsers import StrOutputParser


class BaseAgent:
    """
    Shared base class for APR agents.

    Responsibilities:
    - Centralize model calls through `models/ollama_model.py`
    - Provide consistent task context for every model prompt
    - Provide safe JSON parsing helpers for model outputs
    """

    TASK_SYSTEM_PROMPT = (
        "You are fixing bugs in a repository using automated program repair."
    )

    def __init__(self) -> None:
        self.model = OllamaWrapper()

    @staticmethod
    def get_repo_root() -> Path:
        """
        Resolve repository root in a robust way.
        Priority:
        1) TARGET_ROOT_DIR env var, if valid
        2) Walk up from this file until a .git directory is found
        3) Fallback to project root by known layout (.../framework)
        """
        root_dir = os.getenv("TARGET_ROOT_DIR")
        if root_dir:
            p = Path(root_dir).resolve()
            if p.exists():
                return p

        # TODO change if no .env
        # current = Path(__file__).resolve()
        # for parent in [current.parent, *current.parents]:
        #     if (parent / ".git").exists():
        #         return parent

        # # app/src/agents/base_agent.py -> parents[3] is repo root in this project
        # return current.parents[3]

    def run(self, state: dict) -> dict:  # pragma: no cover (interface)
        raise NotImplementedError

    # TODO check
    @staticmethod
    def _truncate_for_prompt(text: str, max_chars: int = 12000) -> str:
        if len(text) <= max_chars:
            return text
        # TODO warning
        return text[: max_chars - 20] + "\n...<TRUNCATED>..."

    @classmethod
    def _format_state_for_prompt(
        cls, state: dict, keys: Optional[List[str]] = None
    ) -> str:
        if keys is None:
            keys = list(state.keys())

        selected: Dict[str, Any] = {k: state.get(k) for k in keys if k in state}
        try:
            serialized = json.dumps(selected, indent=2, default=str)
        except Exception:
            serialized = str(selected)
        return cls._truncate_for_prompt(serialized)

    def build_messages(
        self,
        state: dict,
        user_instructions: str,
        *,
        include_state_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """
        Build an Ollama-compatible message list.
        """
        state_context = self._format_state_for_prompt(state, include_state_keys)
        user_content = user_instructions
        user_content += "\n\nTask context:\n" + self.TASK_SYSTEM_PROMPT
        if state_context.strip():
            user_content += (
                "\n\nPrevious state/context (may be truncated):\n" + state_context
            )

        return [
            {"role": MessageRoleEnum.system, "content": self.TASK_SYSTEM_PROMPT},
            {"role": MessageRoleEnum.user, "content": user_content},
        ]

    @staticmethod
    def parse_text_output(raw_text: str) -> str:
        """
        Normalize model text output via LangChain parser primitives.
        """
        parser = StrOutputParser()
        return parser.invoke(raw_text or "")

    @staticmethod
    def extract_json(text: str) -> Optional[Any]:
        """
        Best-effort JSON extraction from a model response.
        """
        if not text:
            return None

        # Try direct parse first.
        try:
            return json.loads(text)
        except Exception:
            pass

        # Best-effort: find the first JSON object and parse it.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None
