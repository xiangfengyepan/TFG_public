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


def instance_memberships(instances_path: Path) -> dict[str, list[tuple[str, str]]]:
    """`instance_id -> [(subset, split), …]`. An id can appear under
    multiple pairs (lite/dev AND full/dev after both subsets refresh)."""
    out: dict[str, list[tuple[str, str]]] = {}
    if not instances_path.exists():
        return out
    for raw in instances_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        iid = obj.get("instance_id")
        if not isinstance(iid, str) or not iid:
            continue
        pair = (obj.get("subset") or "lite", obj.get("split") or "dev")
        memberships = out.setdefault(iid, [])
        if pair not in memberships:
            memberships.append(pair)
    return out


def instance_origin_lookup(instances_path: Path) -> dict[str, tuple[str, str]]:
    """First (subset, split) per id — for callers that need one canonical pair."""
    mems = instance_memberships(instances_path)
    return {iid: pairs[0] for iid, pairs in mems.items()}


def load_instance_rows(
    instance_ids: set[str] | list[str],
    instances_path: Path,
) -> dict[str, dict[str, Any]]:
    """`instance_id -> full row` for every match (eval worker sidecar)."""
    wanted = set(instance_ids)
    out: dict[str, dict[str, Any]] = {}
    if not wanted or not instances_path.exists():
        return out
    with instances_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = obj.get("instance_id")
            if iid in wanted:
                out[iid] = obj
                if len(out) == len(wanted):
                    break
    return out
