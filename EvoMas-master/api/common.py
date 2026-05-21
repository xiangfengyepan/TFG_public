"""Cross-router shared state for the EvoMas FastAPI server.

Routers under `api/routers/` import path constants, the shared logger,
path-safety helpers (`safe_under`, `to_wsl`), and the cross-router
instance-cache lookups (`instance_*`) from this module. `api/server.py`
is the FastAPI entrypoint and the only file that imports the routers.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import HTTPException

# The inference worker attaches a per-run text-log FileHandler to this
# logger so agent code's `logger.info(...)` ends up in the .log transcript.
logger = logging.getLogger("api")


# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / "evomas" / ".env", override=False)
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

CONFIG_DIR = BASE_DIR / "evomas" / "config"
PREDEFINED_CONFIG_DIR = CONFIG_DIR / "predefined"
LOADED_CONFIG_DIR = CONFIG_DIR / "loaded"
PREDEFINED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOADED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
INSTANCES_PATH = BASE_DIR / "swebench_instances.jsonl"

# Results root is overridable via RESULTS_DIR in evomas/.env (relative
# values resolved against BASE_DIR).
_results_env = os.getenv("RESULTS_DIR", "").strip()
if _results_env:
    _results_path = Path(_results_env).expanduser()
    RESULTS_DIR = _results_path if _results_path.is_absolute() else (BASE_DIR / _results_path)
else:
    RESULTS_DIR = BASE_DIR / "results"
PREDICTIONS_DIR = RESULTS_DIR / "predictions"
# Per-run user-facing text log; Results page surfaces it.
PREDICTION_TEXT_LOGS_DIR = PREDICTIONS_DIR / "logs"
# Snapshot of the config used for each run (survives source-config edits).
PREDICTION_CONFIGS_DIR = PREDICTIONS_DIR / "configs"
# Internal NDJSON SSE-event log per run; powers Inference-page reload-resume.
INFERENCE_INTERNAL_LOGS_DIR = BASE_DIR / "evomas" / "logs" / "inference_logs"
EVALUATION_DIR = RESULTS_DIR / "evaluations"

# Migrate legacy singular folder name; old runs stay browseable.
_legacy_eval = RESULTS_DIR / "evaluation"
if _legacy_eval.exists() and not EVALUATION_DIR.exists():
    _legacy_eval.rename(EVALUATION_DIR)

# Migrate the previous NDJSON-log location (was alongside text logs).
_legacy_internal_logs = PREDICTIONS_DIR / "logs"
if _legacy_internal_logs.is_dir() and not INFERENCE_INTERNAL_LOGS_DIR.exists():
    INFERENCE_INTERNAL_LOGS_DIR.parent.mkdir(parents=True, exist_ok=True)
    _legacy_internal_logs.rename(INFERENCE_INTERNAL_LOGS_DIR)

PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
PREDICTION_TEXT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
PREDICTION_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
INFERENCE_INTERNAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
SWEBENCH_VENV_PYTHON = BASE_DIR / "SWE-bench" / "venv" / "bin" / "python"


# ─── Path helpers ────────────────────────────────────────────────────────────
def to_wsl(path: str) -> str:
    """Windows absolute path → WSL `/mnt/<drive>/...`."""
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = f"/mnt/{p[0].lower()}{p[2:]}"
    return p


def safe_under(root: Path, candidate: str) -> Path:
    """Resolve `candidate` and assert it stays under `root` — path-traversal guard."""
    p = Path(candidate).resolve()
    root_r = root.resolve()
    if root_r not in p.parents and p != root_r:
        raise HTTPException(403, "path is outside the allowed directory")
    return p


# ─── Instance-cache lookups ──────────────────────────────────────────────────
# Helpers reading swebench_instances.jsonl, shared across routers.

def instance_memberships() -> dict[str, list[tuple[str, str]]]:
    """`instance_id -> [(subset, split), …]`. An id can appear under
    multiple pairs (lite/dev AND full/dev after both subsets refresh)."""
    out: dict[str, list[tuple[str, str]]] = {}
    if not INSTANCES_PATH.exists():
        return out
    for raw in INSTANCES_PATH.read_text(encoding="utf-8").splitlines():
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


def instance_origin_lookup() -> dict[str, tuple[str, str]]:
    """First (subset, split) per id — for callers that need one canonical pair."""
    mems = instance_memberships()
    return {iid: pairs[0] for iid, pairs in mems.items()}


def load_instance_rows(instance_ids: set[str] | list[str]) -> dict[str, dict[str, Any]]:
    """`instance_id -> full row` for every match (eval worker sidecar)."""
    wanted = set(instance_ids)
    out: dict[str, dict] = {}
    if not wanted or not INSTANCES_PATH.exists():
        return out
    with INSTANCES_PATH.open(encoding="utf-8") as fh:
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
