"""Per-agent context state for the lingma_swe_gpt `manage_N` tool family.

Upstream Lingma's `manage` operation is a single dispatcher that bundles
multiple context-management actions (focus file, context-window contents,
history, etc.). The CSV importer split the URL into 8 distinct tool
names — we honour that split by giving each `manage_N` its own dedicated
operation, all backed by this shared per-agent dict.

State is in-process and reset on import; safe under the single-active-run
backend. Tests use `reset()` to start clean.
"""
from __future__ import annotations

from typing import Any

_DEFAULT: dict[str, Any] = {"focus": "", "context_files": [], "history": []}


def _entry(agent: str) -> dict[str, Any]:
    key = agent or "default"
    if key not in _STATE:
        _STATE[key] = {"focus": "", "context_files": [], "history": []}
    return _STATE[key]


_STATE: dict[str, dict[str, Any]] = {}


def snapshot(agent: str) -> dict[str, Any]:
    """Return a copy of the agent's full state."""
    e = _entry(agent)
    return {"focus": e["focus"], "context_files": list(e["context_files"]), "history": list(e["history"])}


def add_file(agent: str, path: str) -> dict[str, Any]:
    e = _entry(agent)
    if path and path not in e["context_files"]:
        e["context_files"].append(path)
        e["history"].append(f"add_file:{path}")
    return snapshot(agent)


def remove_file(agent: str, path: str) -> dict[str, Any]:
    e = _entry(agent)
    if path in e["context_files"]:
        e["context_files"].remove(path)
        e["history"].append(f"remove_file:{path}")
    return snapshot(agent)


def history(agent: str, n: int = 20) -> list[str]:
    return list(_entry(agent)["history"])[-n:]


def clear_history(agent: str) -> dict[str, Any]:
    e = _entry(agent)
    e["history"] = []
    return snapshot(agent)


def set_focus(agent: str, path: str) -> dict[str, Any]:
    e = _entry(agent)
    e["focus"] = path
    e["history"].append(f"set_focus:{path}")
    return snapshot(agent)


def get_focus(agent: str) -> str:
    return _entry(agent)["focus"]


def reset(agent: str | None = None) -> None:
    """Test hook: wipe one agent's state (or all when `agent` is None)."""
    if agent is None:
        _STATE.clear()
    else:
        _STATE.pop(agent or "default", None)
