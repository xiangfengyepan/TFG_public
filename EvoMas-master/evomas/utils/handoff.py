"""Payload shape descriptions for inter-agent hand-offs.

Used by `graph_builder._wrap()` to emit one INFO line per outgoing edge
after a node runs, and by `api/server.py`'s SSE streaming loop to fill
the `summary` / `preview` fields of the `handoff` event the inference
page renders as a chip.

Size is computed via `len(str(value))` rather than JSON serialization
because state slots routinely hold non-JSON values (TypedDicts with Path
objects, exceptions, dataclasses), and a stringified representation is
also what the user sees in the preview modal — same unit, no surprise."""
from __future__ import annotations

from typing import Any


def _format_bytes(n: int) -> str:
    """Render an approximate size with a unit suffix. The leading `~` is
    handled by the caller so this function stays pure size→text."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def summarize_payload(value: Any) -> str:
    """Return a short, log-safe shape description for a state-slot value.

    Examples:
        None          → "None"
        42            → "int(42)"
        True          → "bool(True)"
        "hello"       → "str(5 B)"
        ["a", "b"]    → "list(2 items, ~12 B)"
        {"k": "v"}    → "dict(1 keys, ~10 B)"
        b"bytes"      → "bytes(5 B)"

    Never serializes the full value; never raises on exotic types — falls
    back to the type name + repr length."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        # Check bool before int — bools are ints in Python and the int
        # branch would render `int(True)` which reads as a typo.
        return f"bool({value})"
    if isinstance(value, int):
        return f"int({value})"
    if isinstance(value, float):
        return f"float({value})"
    if isinstance(value, str):
        return f"str({_format_bytes(len(value))})"
    if isinstance(value, bytes):
        return f"bytes({_format_bytes(len(value))})"
    if isinstance(value, (list, tuple)):
        kind = "list" if isinstance(value, list) else "tuple"
        approx = len(str(value))
        return f"{kind}({len(value)} items, ~{_format_bytes(approx)})"
    if isinstance(value, dict):
        approx = len(str(value))
        return f"dict({len(value)} keys, ~{_format_bytes(approx)})"
    if isinstance(value, set):
        approx = len(str(value))
        return f"set({len(value)} items, ~{_format_bytes(approx)})"
    # Fallback: type name + stringified-length size. Never raises.
    type_name = type(value).__name__
    try:
        size = len(str(value))
    except Exception:
        return f"{type_name}(?)"
    return f"{type_name}(~{_format_bytes(size)})"


def preview_payload(value: Any, max_chars: int = 16384) -> str:
    """Coerce `value` to a string and truncate to `max_chars`. Used in the
    SSE event payload so the inference page modal can render the full
    content without bloating every chip event with megabytes of state.

    A truncated preview is suffixed with `... (N more chars)` so the user
    knows it isn't the entire payload."""
    try:
        text = str(value)
    except Exception as exc:
        return f"<unrenderable: {type(value).__name__}: {exc}>"
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... ({len(text) - max_chars} more chars)"
