import json
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from evomas.exceptions.errors import ConfigError

_THIS_DIR: Path = Path(__file__).resolve().parent
PREDEFINED_DIR: Path = _THIS_DIR / "predefined"
LOADED_DIR: Path = _THIS_DIR / "loaded"

ThinkLevel = Union[bool, Literal["low", "medium", "high"]]


class AgentConfig(BaseModel):
    """Per-agent model knobs extracted from the unified config block."""

    model: str = "qwen3.5:9b"
    think: ThinkLevel = True
    num_ctx: int = 4096
    stream: bool = True
    temperature: float = 0.2
    top_k: int = 40
    top_p: float = 0.9
    min_p: float = 0.0
    repeat_penalty: float = 1.1
    repeat_last_n: int = 64
    seed: int = 0
    num_predict: int = -1
    stop: list[str] = Field(default_factory=list)


AGENT_CONFIG_KEYS: frozenset[str] = frozenset(AgentConfig.model_fields.keys())


def _resolve_path(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.is_file():
        return p
    # Look in predefined/ first, then loaded/, then the legacy flat root.
    for base in (PREDEFINED_DIR, LOADED_DIR, _THIS_DIR):
        candidate = base / f"{name_or_path}.json"
        if candidate.is_file():
            return candidate
    raise ConfigError(f"config not found: {name_or_path}")


def load_config(name_or_path: str) -> dict[str, Any]:
    """Load a unified config JSON. Accepts a name (e.g. 'star') or an absolute/relative file path."""
    path = _resolve_path(name_or_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"failed to parse {path}: {exc}") from exc


def list_configs() -> list[str]:
    """Return the stems of every *.json file shipped under evomas/config/.

    Scans predefined/, loaded/, and the legacy flat root (for backwards
    compatibility with on-disk runs that pre-date the split). Stems must be
    unique across the three roots — the loader assumes one config per name."""
    stems: set[str] = set()
    for base in (PREDEFINED_DIR, LOADED_DIR, _THIS_DIR):
        if base.is_dir():
            stems.update(p.stem for p in base.glob("*.json"))
    return sorted(stems)


def agent_config_from_block(block: dict[str, Any]) -> AgentConfig:
    """Project a unified-config agent block down to the model knobs Pydantic schema."""
    return AgentConfig(**{k: v for k, v in block.items() if k in AGENT_CONFIG_KEYS})
