"""Read a SWE-bench-style instances JSONL into a list of dicts. Lives under
`evomas.utils` so reproduce-this-run notebooks can import it from anywhere."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_instances(
    instances_path: str | Path,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """JSONL → list of dicts."""
    path = Path(instances_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Instances file not found: {instances_path}\n"
            f"Generate it first with: evomas run instances --output {instances_path}"
        )
    instances: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    if limit is not None and limit > 0:
        instances = instances[:limit]
    return instances
