import json
import re
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from evomas.exceptions.errors import ConfigError

_THIS_DIR: Path = Path(__file__).resolve().parent
PREDEFINED_DIR: Path = _THIS_DIR / "predefined"
LOADED_DIR: Path = _THIS_DIR / "loaded"
AGENT_TYPES_DIR: Path = _THIS_DIR / "agent_types"

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


# ─── Variant resolution ─────────────────────────────────────────────────────
# Agent blocks may set `variant: "<RepoId>:<AgentName>"` to pull `prompts` and
# `tools` from `evomas/config/agent_types/<RepoId>.json` instead of inlining
# them. Inline `prompts` / `tools` on the block always take precedence; the
# catalog only fills in what's missing.
_JINJA_INCLUDE_RE: re.Pattern[str] = re.compile(
    r"<\s*\w+\s*>\s*\{%[^%]+%\}\s*<\s*/\s*\w+\s*>",
)


def _strip_jinja_includes(text: str) -> str:
    """Drop Jinja `{% include ... %}` blocks wrapped in XML-style tags (e.g.
    the OpenHands catalog's `<SECURITY_RISK_ASSESSMENT>{% include … %}
    </SECURITY_RISK_ASSESSMENT>`). EvoMas doesn't run a Jinja preprocessor,
    so these would otherwise reach the LLM verbatim."""
    if not isinstance(text, str):
        return text
    return _JINJA_INCLUDE_RE.sub("", text)


def _load_variant_catalog(repo_id: str) -> dict[str, Any] | None:
    """Read `evomas/config/agent_types/<repo_id>.json` and return the parsed
    dict. Returns None when the file doesn't exist (caller decides what to
    do with the miss). Catalog files use the repo id verbatim as the filename
    stem — see `scripts/import_agent_types.py`."""
    path = AGENT_TYPES_DIR / f"{repo_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def resolve_variant_block(block: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `block` with `prompts` and `tools` filled from the
    variant catalog when missing. Pass-through if `block.variant` isn't set,
    can't be parsed, or the catalog lookup misses.

    Precedence: inline `block["prompts"]` / `block["tools"]` win. The catalog
    only fills keys that the block omitted entirely (an empty inline value
    like `"tools": []` is honored — the block explicitly opted out).
    """
    variant = block.get("variant")
    if not variant or ":" not in str(variant):
        return block
    repo_id, agent_name = str(variant).split(":", 1)
    catalog = _load_variant_catalog(repo_id)
    if catalog is None:
        return block
    target = next(
        (a for a in (catalog.get("agents") or []) if a.get("name") == agent_name),
        None,
    )
    if target is None:
        return block

    resolved: dict[str, Any] = dict(block)
    if "prompts" not in resolved:
        cat_prompts = target.get("prompts") or {}
        cleaned = {
            k: _strip_jinja_includes(v) if isinstance(v, str) else v
            for k, v in cat_prompts.items()
        }
        if any(cleaned.values()):
            resolved["prompts"] = cleaned
    if "tools" not in resolved:
        cat_tools = target.get("tools") or []
        if cat_tools:
            # Catalog entries carry `{name, source_url}`; the block shape
            # expects `{name, params}`. Drop source_url, default params={}.
            resolved["tools"] = [
                {"name": str(t["name"]), "params": {}}
                for t in cat_tools if t.get("name")
            ]
    return resolved
