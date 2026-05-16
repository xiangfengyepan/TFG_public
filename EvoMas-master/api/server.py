"""FastAPI server for EvoMas frontend."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request as _urllib
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

# Module-level logger. The per-run text log gets attached as an extra
# handler in worker() below; this logger feeds it.
logger = logging.getLogger(__name__)

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

# Results root is overridable via `RESULTS_DIR` in evomas/.env. Relative
# values are resolved against the repo root (BASE_DIR), so users can write
# either `RESULTS_DIR=results` or `RESULTS_DIR=/some/absolute/path` without
# having to know the server's cwd.
_results_env = os.getenv("RESULTS_DIR", "").strip()
if _results_env:
    _results_path = Path(_results_env).expanduser()
    RESULTS_DIR = _results_path if _results_path.is_absolute() else (BASE_DIR / _results_path)
else:
    RESULTS_DIR = BASE_DIR / "results"
PREDICTIONS_DIR = RESULTS_DIR / "predictions"
# User-facing Python `logging` text log per run. The Results page surfaces
# this and its parent dir is the target of the "reveal logs folder" button.
PREDICTION_TEXT_LOGS_DIR = PREDICTIONS_DIR / "logs"
# Snapshot of the resolved config used for a run. Lets the Results page hand
# the user the exact JSON that produced a given prediction even after the
# source config has been renamed/deleted.
PREDICTION_CONFIGS_DIR = PREDICTIONS_DIR / "configs"
# Internal NDJSON SSE-event log per run — used by the Inference page to
# rehydrate the central log panel after a page reload. NOT shown to the
# user on the Results page.
INFERENCE_INTERNAL_LOGS_DIR = BASE_DIR / "evomas" / "logs" / "inference_logs"
EVALUATION_DIR = RESULTS_DIR / "evaluations"

# One-time migration from the old singular folder name. Existing on-disk runs
# stay browseable on the Results page; new runs land under the renamed dir.
_legacy_eval = RESULTS_DIR / "evaluation"
if _legacy_eval.exists() and not EVALUATION_DIR.exists():
    _legacy_eval.rename(EVALUATION_DIR)

# Migrate the previous NDJSON log location (results/predictions/logs/) to the
# new internal home if any old runs are still on disk. Only moves NDJSON
# files (text logs are written directly to the new results/predictions/logs/
# location going forward, so the legacy contents migrating away clears the
# folder for the new content).
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


def _to_wsl(path: str) -> str:
    """Convert a Windows absolute path to a WSL /mnt/<drive>/... path."""
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = f"/mnt/{p[0].lower()}{p[2:]}"
    return p

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="EvoMas API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Models ───────────────────────────────────────────────────────────────────
class InferenceRequest(BaseModel):
    # Single-instance form (legacy) — used when `instance_ids` is omitted.
    instance_id: str | None = None
    # Multi-instance form — frontend sends a list when the user ticks several
    # rows. Worker runs them sequentially and frames each with `instance_start`/
    # `instance_done` events on the same SSE stream.
    instance_ids: list[str] | None = None
    # Either a config name (resolved to evomas/config/<name>.json) OR an inline
    # unified-config dict — used by the topology page's "Save to session" flow
    # so edits don't need to be exported to disk before running inference.
    config: str | dict[str, Any] = ""

class EvaluationRequest(BaseModel):
    predictions_path: str
    max_workers: int = 4
    # `split` and `run_id` are auto-detected from the prediction file when
    # omitted. The frontend's evaluation page no longer collects them; older
    # callers can still override either.
    split: str | None = None
    run_id: str | None = None

# ─── Ollama helpers ───────────────────────────────────────────────────────────
def _ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").strip().strip("\"'")


# Cache for remote provider model lists. Google/OpenAI APIs both rate-limit
# `models.list` modestly; refresh once per TTL so the Topology page picker
# isn't paying a round-trip on every reload.
_REMOTE_MODELS_TTL_S = 300
_remote_models_cache: dict[str, tuple[float, list[str]]] = {}


def _ollama_models() -> list[str]:
    try:
        url = f"{_ollama_base_url()}/api/tags"
        with _urllib.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return sorted(f"ollama/{m['name']}" for m in data.get("models", []))
    except Exception:
        return []


def _cached_remote(provider: str, fetch) -> list[str]:
    import time
    now = time.time()
    hit = _remote_models_cache.get(provider)
    if hit and (now - hit[0]) < _REMOTE_MODELS_TTL_S:
        return hit[1]
    try:
        models = fetch()
    except Exception:  # noqa: BLE001
        models = []
    _remote_models_cache[provider] = (now, models)
    return models


def _gemini_models() -> list[str]:
    """Live list from generativelanguage.googleapis.com. Filters to models
    that support `generateContent` and excludes obvious non-chat shapes
    (TTS, image-only, audio, robotics, deep-research)."""
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        return []
    def fetch() -> list[str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        with _urllib.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        bad = ("-tts", "-image", "lyria", "robotics", "deep-research", "computer-use", "nano-banana", "gemma")
        out: list[str] = []
        for m in data.get("models", []):
            name = m.get("name", "")
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            bare = name.split("/", 1)[1] if name.startswith("models/") else name
            if any(b in bare for b in bad):
                continue
            out.append(f"gemini/{bare}")
        return sorted(out)
    return _cached_remote("gemini", fetch)


def _openai_models() -> list[str]:
    """Live list from OpenAI's `/v1/models` (or the configured proxy via
    `OPENAI_BASE_URL`). Filters to chat-capable model ids by name pattern
    since the response doesn't carry a `chat` flag."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return []
    def fetch() -> list[str]:
        base = (os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1").rstrip("/")
        req = _urllib.Request(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        with _urllib.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        good_prefix = ("gpt-", "o1", "o3", "o4", "chatgpt-")
        bad = ("-tts", "-realtime", "-audio", "whisper", "-embedding", "dall-e", "tts-", "babbage", "davinci", "moderation", "-image")
        out: list[str] = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if not mid.startswith(good_prefix):
                continue
            if any(b in mid for b in bad):
                continue
            out.append(f"openai/{mid}")
        return sorted(out)
    return _cached_remote("openai", fetch)


@app.get("/api/models")
def list_models() -> list[str]:
    """Return prefixed model ids (`<provider>/<model>`) for every configured
    LLM provider. Ollama is always probed; Gemini and OpenAI lists are only
    fetched when their API keys are present."""
    return _ollama_models() + _gemini_models() + _openai_models()


# ─── Unified Config Endpoints ────────────────────────────────────────────────
# Configs split into two roots:
#   evomas/config/predefined/   — read-only, ships with the framework
#   evomas/config/loaded/       — user-imported configs (writable)
#
# Loader (`evomas/config/loader.py`) searches both, so `--config <stem>` works
# uniformly. The Topology page uses the `source` field below to render two
# sections in the left panel.

# Required top-level keys in any imported config. Their values may be empty
# (`""`, `[]`, `{}`, `null`) but the keys themselves must be present.
_REQUIRED_CONFIG_KEYS = ("id", "entry", "end", "edges", "agents")


def _scan_config_dir(base: Path, source: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not base.is_dir():
        return out
    for p in sorted(base.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        out.append({
            "stem": p.stem,
            "id": str(data.get("id") or p.stem),
            "description": str(data.get("description") or ""),
            "source": source,
        })
    return out


def _resolve_config_path(name: str) -> Path | None:
    """Return the on-disk path of a config by stem, searching predefined → loaded."""
    for base in (PREDEFINED_CONFIG_DIR, LOADED_CONFIG_DIR):
        p = base / f"{name}.json"
        if p.is_file():
            return p
    return None


def _validate_loaded_config(data: dict, expected_stem: str) -> None:
    """Reject configs missing one of the four required keys, or whose `id`
    doesn't match the filename stem (per the topology UX rule)."""
    missing = [k for k in _REQUIRED_CONFIG_KEYS if k not in data]
    if missing:
        raise HTTPException(400, f"config is missing required keys: {missing}")
    if str(data.get("id") or "") != expected_stem:
        raise HTTPException(
            400,
            f"config 'id' must match filename stem (id={data.get('id')!r}, "
            f"stem={expected_stem!r})",
        )


@app.get("/api/configs")
def list_configs() -> list[dict[str, str]]:
    """List configs from both predefined/ and loaded/ subdirs.

    Each entry has:
      - `stem`: filename stem, used as the routing key (URL param, --config arg)
      - `id`: human-facing identifier from the JSON's top-level `id` field
      - `description`: top-level description (may be empty)
      - `source`: `"predefined"` or `"loaded"` so the UI can split them.
    """
    return _scan_config_dir(PREDEFINED_CONFIG_DIR, "predefined") + _scan_config_dir(LOADED_CONFIG_DIR, "loaded")


@app.get("/api/configs/{name}")
def get_config(name: str) -> dict:
    """Return the unified config JSON for the given name."""
    path = _resolve_config_path(name)
    if path is None:
        raise HTTPException(404, f"Config '{name}' not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"Failed to parse {path.name}: {exc}") from exc


class LoadedConfigPayload(BaseModel):
    """Payload for POST /api/configs/loaded — full config JSON + replace flag."""
    name: str           # filename stem; must equal `data["id"]`
    data: dict[str, Any]
    replace: bool = False


@app.post("/api/configs/loaded")
def save_loaded_config(payload: LoadedConfigPayload) -> dict[str, Any]:
    """Persist a user-loaded config under evomas/config/loaded/<name>.json.

    Validation:
      - Required top-level keys (`id`, `entry`, `edges`, `agents`).
      - `id` must equal `name` (the filename stem).
      - If a config with the same stem already exists in EITHER root, the
        client must set `replace=True` to overwrite. Predefined configs
        cannot be replaced — the request is rejected.
    """
    if "/" in payload.name or "\\" in payload.name or not payload.name:
        raise HTTPException(400, "invalid config name")
    _validate_loaded_config(payload.data, payload.name)

    target = LOADED_CONFIG_DIR / f"{payload.name}.json"
    predefined = PREDEFINED_CONFIG_DIR / f"{payload.name}.json"
    if predefined.is_file():
        raise HTTPException(409, f"a predefined config already uses id '{payload.name}'")
    if target.is_file() and not payload.replace:
        raise HTTPException(409, f"a loaded config already uses id '{payload.name}'")
    LOADED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload.data, indent=2), encoding="utf-8")
    return {"ok": True, "stem": payload.name, "path": str(target)}


class RenameConfigPayload(BaseModel):
    new_name: str


@app.patch("/api/configs/loaded/{name}")
def rename_loaded_config(name: str, payload: RenameConfigPayload) -> dict[str, Any]:
    """Rename a loaded config (file + JSON `id` field). Predefined configs
    are read-only and cannot be renamed."""
    new_name = payload.new_name.strip()
    if "/" in new_name or "\\" in new_name or not new_name:
        raise HTTPException(400, "invalid new_name")
    if new_name == name:
        return {"ok": True, "stem": name}

    src = LOADED_CONFIG_DIR / f"{name}.json"
    if not src.is_file():
        raise HTTPException(404, f"loaded config '{name}' not found")
    if (PREDEFINED_CONFIG_DIR / f"{new_name}.json").is_file():
        raise HTTPException(409, f"a predefined config already uses id '{new_name}'")
    dst = LOADED_CONFIG_DIR / f"{new_name}.json"
    if dst.is_file():
        raise HTTPException(409, f"a loaded config already uses id '{new_name}'")

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"failed to parse {src.name}: {exc}") from exc
    data["id"] = new_name
    dst.write_text(json.dumps(data, indent=2), encoding="utf-8")
    src.unlink()
    return {"ok": True, "stem": new_name, "path": str(dst)}


@app.delete("/api/configs/loaded/{name}")
def delete_loaded_config(name: str) -> dict[str, Any]:
    """Remove a loaded config from disk. Predefined configs cannot be deleted."""
    target = LOADED_CONFIG_DIR / f"{name}.json"
    if not target.is_file():
        raise HTTPException(404, f"loaded config '{name}' not found")
    target.unlink()
    return {"ok": True, "stem": name}

# ─── Instances Endpoints ──────────────────────────────────────────────────────
@app.get("/api/instances/count")
def count_instances() -> dict:
    if not INSTANCES_PATH.exists():
        return {"count": 0}
    count = sum(1 for line in INSTANCES_PATH.open(encoding="utf-8") if line.strip())
    return {"count": count}

@app.post("/api/instances/refresh-all")
def refresh_all_instances(limit: int | None = None) -> dict:
    """Pull every SWE-bench (subset, split) pair we know about, skipping any
    combination the upstream dataset doesn't ship (e.g. SWE-bench_Verified has
    no dev split). Heavy operation — Full alone is ~2000 instances per split.
    """
    from scripts.generate_swebench_instances import build_instances
    # Per the SWE-bench HuggingFace dataset cards:
    #   - SWE-bench (Full):   train, dev, test
    #   - SWE-bench_Lite:     dev, test
    #   - SWE-bench_Verified: test only
    combos = [
        ("lite", "dev"), ("lite", "test"),
        ("full", "dev"), ("full", "test"), ("full", "train"),
        ("verified", "test"),
    ]
    results: dict[str, Any] = {}
    total = 0
    for subset, split in combos:
        try:
            count = build_instances(
                split, str(INSTANCES_PATH), limit,
                subset=subset, append=True,
            )
            results[f"{subset}/{split}"] = {"count": count}
            total += count
        except Exception as exc:
            results[f"{subset}/{split}"] = {"error": str(exc)}
    return {"total": total, "results": results}


@app.post("/api/instances/refresh")
def refresh_instances(
    split: str = "dev",
    limit: int | None = None,
    subset: str = "lite",
    append: bool = True,
) -> dict:
    """Regenerate `swebench_instances.jsonl` for ONE (subset, split) pair.

    Synchronous — returns the new instance count. Other (subset, split) pairs
    already in the file are preserved when `append=True` (the default), so the
    UI can incrementally pull Lite, Full, Verified into the same picker.
    """
    if split not in {"dev", "test", "train"}:
        raise HTTPException(400, f"split must be 'dev' | 'test' | 'train' (got {split!r})")
    if subset not in {"lite", "full", "verified"}:
        raise HTTPException(400, f"subset must be 'lite' | 'full' | 'verified' (got {subset!r})")
    from scripts.generate_swebench_instances import build_instances
    try:
        count = build_instances(
            split, str(INSTANCES_PATH), limit,
            subset=subset, append=append,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"count": count, "subset": subset, "split": split, "path": str(INSTANCES_PATH)}


class AddCustomInstanceRequest(BaseModel):
    repo: str
    problem_statement: str
    base_commit: str | None = None


_CUSTOM_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@app.post("/api/instances/custom")
def add_custom_instance(req: AddCustomInstanceRequest) -> dict:
    """Append a user-provided GitHub repo to `swebench_instances.jsonl` so it
    can be selected on the Inference page just like a SWE-bench row. Marked
    with `subset="custom"` / `split="custom"` so the evaluation worker can
    skip it (the SWE-bench harness needs test_patch / FAIL_TO_PASS, which a
    free-form repo doesn't carry)."""
    repo = req.repo.strip()
    # Strip the common URL-flavored prefixes so the user can paste either
    # `owner/name` or a full https://github.com/owner/name(.git)? link.
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
    if repo.endswith(".git"):
        repo = repo[:-4]
    repo = repo.rstrip("/")
    if not _CUSTOM_REPO_RE.match(repo):
        raise HTTPException(400, f"repo must be owner/name (got {req.repo!r})")
    problem = (req.problem_statement or "").strip()
    if not problem:
        raise HTTPException(400, "problem_statement is required")

    # Resolve base_commit. If the user gave one, take it verbatim (no remote
    # round-trip — `git clone` will still fail at run time if it's bogus).
    # Otherwise resolve HEAD via `git ls-remote` so the prediction has a
    # stable SHA to reproduce against later.
    base_commit = (req.base_commit or "").strip()
    if not base_commit:
        # Force git into non-interactive mode -- on Windows, hitting a private
        # or non-existent repo otherwise opens Git Credential Manager's GUI
        # prompt, which deadlocks the subprocess (the timeout fires but the
        # GUI window stays modal until the user closes it manually).
        env = {**os.environ,
               "GIT_TERMINAL_PROMPT": "0",
               "GCM_INTERACTIVE": "Never",
               "GIT_ASKPASS": "echo"}
        try:
            out = subprocess.run(
                ["git", "ls-remote", f"https://github.com/{repo}", "HEAD"],
                capture_output=True, text=True, timeout=10, check=True,
                stdin=subprocess.DEVNULL, env=env,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            stderr = getattr(exc, "stderr", "") or str(exc)
            raise HTTPException(502, f"failed to resolve HEAD for {repo}: {stderr[:300]}") from exc
        first = (out.stdout or "").split("\n", 1)[0].strip()
        base_commit = first.split("\t", 1)[0].strip()
        if not re.match(r"^[0-9a-f]{7,40}$", base_commit):
            raise HTTPException(502, f"could not parse HEAD SHA from `git ls-remote` output: {out.stdout[:200]!r}")
    if not re.match(r"^[0-9a-f]{4,40}$", base_commit):
        raise HTTPException(400, f"base_commit doesn't look like a git SHA: {base_commit!r}")

    owner, name = repo.split("/", 1)
    instance_id = f"custom-{owner}-{name}-{base_commit[:7]}"

    # Idempotent: if we've already recorded this exact (repo, base_commit)
    # pair, surface the existing row so the frontend can just select it.
    if INSTANCES_PATH.exists():
        with INSTANCES_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("instance_id") == instance_id:
                    return {
                        "instance_id": instance_id,
                        "repo": repo,
                        "base_commit": base_commit,
                        "duplicate": True,
                    }

    # Field order matches the SWE-bench JSONL rows (`repo` first, then
    # `instance_id`, then `base_commit`, ...) so the file stays uniform when
    # viewed line-by-line.
    row = {
        "repo": repo,
        "instance_id": instance_id,
        "base_commit": base_commit,
        "problem_statement": problem,
        "hints_text": "",
        "subset": "custom",
        "split": "custom",
    }
    # Ensure trailing newline on existing content so the append lands on a
    # fresh line even if the file was hand-edited without one.
    if INSTANCES_PATH.exists() and INSTANCES_PATH.stat().st_size > 0:
        existing = INSTANCES_PATH.read_bytes()
        if not existing.endswith(b"\n"):
            with INSTANCES_PATH.open("ab") as fh:
                fh.write(b"\n")
    with INSTANCES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": base_commit,
        "duplicate": False,
    }


@app.get("/api/instances")
def list_instances(skip: int = 0, limit: int = 0) -> list[dict]:
    """List instances. `limit=0` means unlimited (return everything past skip)."""
    if not INSTANCES_PATH.exists():
        return []
    results: list[dict] = []
    seen = 0
    with INSTANCES_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            seen += 1
            if seen <= skip:
                continue
            if limit > 0 and len(results) >= limit:
                break
            try:
                obj = json.loads(line)
                results.append({
                    "instance_id": obj.get("instance_id", ""),
                    "repo": obj.get("repo", ""),
                    "problem_statement": (obj.get("problem_statement") or "")[:300],
                    # Default to lite/dev for legacy lines written before the
                    # nested instance picker landed.
                    "subset": obj.get("subset", "lite"),
                    "split": obj.get("split", "dev"),
                })
            except json.JSONDecodeError:
                pass
    return results

# ─── Health (used by the frontend's top-right API indicator) ─────────────────
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ─── MCP tools (read-only) ────────────────────────────────────────────────────
@app.get("/api/tools")
def list_tools() -> list[dict[str, Any]]:
    """Return the registered MCP tool catalog (name, description, inputSchema)."""
    from evomas.mcp.server import MCPServer
    return MCPServer().registry.list()


# ─── Agent types (read-only) ──────────────────────────────────────────────────
@app.get("/api/agent-types")
def list_agent_types_endpoint() -> list[dict[str, Any]]:
    """Return the SWE-bench agent-type catalog (label, color, description).

    Each type also carries a `variants` array: the EvoMas built-in first,
    then every CSV-derived alternative from `evomas/config/agent_types/`.
    The Topology page renders one chip+dropdown per type and uses the
    variants list to populate the dropdown.
    """
    from evomas.agents.types import list_agent_types
    from evomas.agents.types.variants import list_variants
    catalog = list_agent_types()
    variants_by_type = list_variants()
    for t in catalog:
        t["variants"] = variants_by_type.get(t["type"], [])
    return catalog


@app.get("/api/agent-variants")
def list_agent_variants_endpoint() -> dict[str, list[dict[str, Any]]]:
    """Return agent variants grouped by canonical AGENT_TYPE.

    Same data the `/api/agent-types` response embeds under each type's
    `variants` field, but flat -- handy for callers that only need the
    catalog and not the per-type defaults / colors. The built-in EvoMas
    variant is always FIRST inside each bucket; the Topology page treats
    that as the default selection for the chip+dropdown widget.
    """
    from evomas.agents.types.variants import list_variants
    return list_variants()


# ─── Predictions list ─────────────────────────────────────────────────────────
@app.get("/api/predictions")
def list_predictions() -> list[str]:
    files = sorted(PREDICTIONS_DIR.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)
    return [str(p) for p in files]


def _load_instance_rows(instance_ids: set[str] | list[str]) -> dict[str, dict]:
    """Return `instance_id -> full row` for every match in INSTANCES_PATH.

    Used by the evaluation worker to feed `scripts/apply_and_test.py` a
    sidecar instances file containing only the rows it needs (in particular
    the `repo` + `base_commit` for each custom prediction). One linear scan
    of the JSONL is fine -- custom groups are typically tiny (<10 rows).
    """
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


def _instance_origin_lookup() -> dict[str, tuple[str, str]]:
    """`instance_id -> (subset, split)` from the local SWE-bench cache.

    Returns the FIRST membership per instance_id — used by callers (eval
    partitioning, prediction inspection) that just need a single canonical
    (subset, split) pair to drive the harness. For all-memberships use
    `_instance_memberships()` instead.
    """
    mems = _instance_memberships()
    return {iid: pairs[0] for iid, pairs in mems.items()}


def _instance_memberships() -> dict[str, list[tuple[str, str]]]:
    """`instance_id -> [(subset, split), …]` covering every membership the
    local SWE-bench cache records for the id.

    The same instance can appear once per (subset, split) it belongs to —
    e.g. a Lite/dev instance shows up as both `lite/dev` AND `full/dev` after
    the user has refreshed both subsets. This lets the Results page render
    every applicable group without a hardcoded "Lite ⊆ Full" assumption.
    """
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


@app.get("/api/predictions/inspect")
def inspect_prediction(path: str) -> dict[str, Any]:
    """Return the (subset, split, instance_ids) groups detected in a prediction file.

    Each line is consulted in this order for its `(subset, split)`:
      1. The line's own `subset` / `split` fields (set by the inference
         worker when it wrote the line).
      2. The local `swebench_instances.jsonl` cache, looked up by instance_id.
      3. Default fallback `("lite", "dev")`.
    """
    p = _safe_under(PREDICTIONS_DIR, path)
    if not p.is_file():
        raise HTTPException(404, "prediction file not found")

    origin = _instance_origin_lookup()
    text = p.read_text(encoding="utf-8")

    groups: dict[tuple[str, str], list[str]] = {}
    total = 0
    for raw in text.splitlines():
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
        total += 1

        subset = obj.get("subset")
        split = obj.get("split")
        if not subset or not split:
            cached = origin.get(iid)
            if cached:
                subset = subset or cached[0]
                split = split or cached[1]
        subset = subset or "lite"
        split = split or "dev"

        groups.setdefault((subset, split), []).append(iid)

    # Pull a canonical `<config>-<UID>` segment out of the filename, if any.
    m = _PRED_KEY_RE.match(p.name)
    run_id_base = m.group(1) if m else p.stem

    return {
        "path": str(p),
        "name": p.name,
        "run_id_base": run_id_base,
        "total": total,
        "groups": [
            {"subset": s, "split": sp, "instance_ids": ids}
            for (s, sp), ids in groups.items()
        ],
    }


# ─── Results browser (read-only) ──────────────────────────────────────────────
def _scan_predictions() -> dict[str, list[dict[str, Any]]]:
    """Group every prediction JSONL line by its `instance_id`.

    A single file can hold multiple instances (one line each), as written by
    the multi-instance inference worker. Each line emits its own entry so the
    UI can list per-instance runs even when several share a file.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for p in PREDICTIONS_DIR.glob("*.jsonl"):
        try:
            text = p.read_text(encoding="utf-8")
            mtime = p.stat().st_mtime
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = obj.get("instance_id")
            if not isinstance(iid, str) or not iid:
                continue
            out.setdefault(iid, []).append({
                "path": str(p),
                "name": p.name,
                "instance_id": iid,
                "run_id": obj.get("run_id"),
                "mtime": mtime,
            })
    for files in out.values():
        files.sort(key=lambda f: f["mtime"], reverse=True)
    return out


def _scan_evaluations() -> dict[str, list[dict[str, Any]]]:
    """Group all per-instance evaluation directories by instance_id.

    Layout: results/evaluations/logs/run_evaluation/<run_id>/<model>/<instance_id>/
    """
    out: dict[str, list[dict[str, Any]]] = {}
    base = EVALUATION_DIR / "logs" / "run_evaluation"
    if not base.is_dir():
        return out
    for run_dir in base.iterdir():
        if not run_dir.is_dir():
            continue
        for model_dir in run_dir.iterdir():
            if not model_dir.is_dir():
                continue
            for inst_dir in model_dir.iterdir():
                if not inst_dir.is_dir():
                    continue
                iid = inst_dir.name
                out.setdefault(iid, []).append({
                    "run_id": run_dir.name,
                    "model": model_dir.name,
                    "dir": str(inst_dir),
                    "mtime": inst_dir.stat().st_mtime,
                })
    for entries in out.values():
        entries.sort(key=lambda e: e["mtime"], reverse=True)
    return out


_TS_RE = re.compile(r"-(\d{14})(?:\.|$)")
_PRED_KEY_RE = re.compile(r"^prediction-(.+)\.jsonl$")
_EVAL_KEY_RE = re.compile(r"^evaluation-(.+)$")


def _key_of_pred(pred: dict[str, Any]) -> str | None:
    """Return the pairing key embedded in a prediction filename.

    New layout (`prediction-<config>-<UID>.jsonl`) → `<config>-<UID>`.
    Legacy layout (`<instance_id>-<TS>.jsonl`) → `<TS>`.
    Prefers the explicit `run_id` recorded inside the JSONL line when present.
    """
    rid = pred.get("run_id")
    if isinstance(rid, str) and rid:
        return rid
    name = pred.get("name", "")
    m = _PRED_KEY_RE.match(name)
    if m:
        return m.group(1)
    m = _TS_RE.search(name)
    return m.group(1) if m else None


def _key_of_eval(ev: dict[str, Any]) -> str | None:
    """Return the pairing key embedded in an evaluation directory's run_id.

    New layout (`evaluation-<config>-<UID>`) → `<config>-<UID>`.
    Legacy layout (`evomas-<split>-<TS>`) → `<TS>`.
    """
    run_id = ev.get("run_id", "")
    m = _EVAL_KEY_RE.match(run_id)
    if m:
        return m.group(1)
    m = _TS_RE.search(run_id)
    return m.group(1) if m else None


def _pair_runs(
    preds: list[dict[str, Any]],
    evals: list[dict[str, Any]],
    instance_id: str,
) -> list[dict[str, Any]]:
    """Pair predictions and evaluations on a shared `<config>-<UID>` (or
    legacy timestamp) key.

    Each prediction becomes a `run` entry; an evaluation whose `run_id` ends
    with the matching key is attached. Evaluations without a matching
    prediction are emitted as run entries with `prediction = None` so they
    remain visible in the UI's single-dropdown listing.
    """
    runs: list[dict[str, Any]] = []
    used_eval_dirs: set[str] = set()

    for pred in preds:
        key = _key_of_pred(pred)
        match = next(
            (e for e in evals if key is not None and _key_of_eval(e) == key),
            None,
        )
        if match:
            used_eval_dirs.add(match["dir"])
        runs.append({
            "run_id": key or pred.get("name", ""),
            "key": key,
            "prediction": pred,
            "evaluation": match,
            "mtime": pred.get("mtime", 0),
        })

    for ev in evals:
        if ev["dir"] in used_eval_dirs:
            continue
        key = _key_of_eval(ev)
        runs.append({
            "run_id": ev.get("run_id") or "",
            "key": key,
            "prediction": None,
            "evaluation": ev,
            "mtime": ev.get("mtime", 0),
        })

    runs.sort(key=lambda r: r.get("mtime", 0), reverse=True)
    return runs


def _expand_hierarchy(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Expand cache memberships through the SWE-bench dataset hierarchy.

      Lite/<split>      ⊆  Full/<split>   →  every Lite row implies a Full row.
      Verified/test     ⊆  Full/test      →  every Verified row implies Full/test.

    Used so an instance recorded only as `lite/dev` in the cache still shows
    up under `full/dev` on the Results page, even when the user hasn't done
    a Full refresh. The reverse direction is NOT expanded — a `full/dev`
    record could come from anywhere in Full and we can't tell from the cache
    alone whether it's part of Lite.
    """
    expanded = list(pairs)
    seen = set(pairs)
    for subset, split in pairs:
        if subset in ("lite", "verified"):
            parent = ("full", split)
            if parent not in seen:
                expanded.append(parent)
                seen.add(parent)
    return expanded


@app.get("/api/results/instances")
def list_result_instances() -> list[dict[str, Any]]:
    """List every instance_id with its prediction/evaluation runs paired up.

    A `run` is a (prediction, evaluation) pair sharing the same trailing
    `-YYYYMMDDHHMMSS` timestamp, so the Results page can render both panels
    from one dropdown selection. Predictions without a matching evaluation
    still appear (with `evaluation: null`) so the empty-state panel can hint
    at running an evaluation.

    Each instance carries:
      - `subset` / `split`: the canonical (first) membership — kept for
        backwards-compat with callers that want a single tag.
      - `memberships`: every (subset, split) the instance belongs to in the
        local cache, expanded through the dataset hierarchy (Lite/Verified
        rows imply a matching Full row). The Results page renders the
        instance under EVERY membership when grouping by subset/split.
    """
    preds = _scan_predictions()
    evals = _scan_evaluations()
    mems = _instance_memberships()
    ids = sorted(set(preds) | set(evals))

    out: list[dict[str, Any]] = []
    for iid in ids:
        raw_pairs = mems.get(iid) or [("lite", "dev")]
        pairs = _expand_hierarchy(raw_pairs)
        out.append({
            "instance_id": iid,
            "subset": pairs[0][0],
            "split":  pairs[0][1],
            "memberships": [{"subset": s, "split": sp} for s, sp in pairs],
            "predictions": preds.get(iid, []),
            "evaluations": evals.get(iid, []),
            "runs": _pair_runs(preds.get(iid, []), evals.get(iid, []), iid),
        })
    return out


def _safe_under(root: Path, candidate: str) -> Path:
    """Resolve `candidate` and ensure it stays inside `root`."""
    p = Path(candidate).resolve()
    root_r = root.resolve()
    if root_r not in p.parents and p != root_r:
        raise HTTPException(403, "path is outside the allowed directory")
    return p


@app.get("/api/results/prediction")
def get_prediction(path: str, instance_id: str | None = None) -> dict[str, Any]:
    """Return one parsed JSONL line of a prediction file.

    If `instance_id` is provided, the line whose `instance_id` matches is
    returned (multi-instance files keep one line per instance). Otherwise the
    first non-empty line wins.
    """
    p = _safe_under(PREDICTIONS_DIR, path)
    if not p.is_file():
        raise HTTPException(404, "prediction file not found")
    text = p.read_text(encoding="utf-8")
    obj: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if instance_id is None:
            obj = parsed
            break
        if parsed.get("instance_id") == instance_id:
            obj = parsed
            break
    return {"path": str(p), "name": p.name, "raw": text, "data": obj}


@app.get("/api/results/prediction/log")
def get_prediction_log(path: str) -> dict[str, Any]:
    """Return the user-facing Python `logging` text transcript for a prediction.

    The inference worker attaches a file handler at run start that captures
    every `logger.info(...)` etc. emitted by the agents and pipes them into
    `results/predictions/logs/prediction-<run_id>.log` with the standard
    `<timestamp> - <LEVEL> - <message>` format (same shape as old_logs/).

    `path` is the absolute path of the corresponding prediction `.jsonl`."""
    p = _safe_under(PREDICTIONS_DIR, path)
    if not p.is_file():
        raise HTTPException(404, "prediction file not found")
    log_path = PREDICTION_TEXT_LOGS_DIR / (p.stem + ".log")
    if not log_path.is_file():
        # Older predictions written before the text-log writer landed have no
        # transcript — return an empty body so the UI can show an empty state.
        return {"path": str(log_path), "name": log_path.name, "exists": False, "raw": ""}
    return {
        "path": str(log_path),
        "name": log_path.name,
        "exists": True,
        "raw": log_path.read_text(encoding="utf-8", errors="replace"),
    }


@app.get("/api/results/prediction/ndjson")
def get_prediction_ndjson(path: str) -> dict[str, Any]:
    """Return the internal NDJSON SSE event log for a completed prediction.

    The inference worker writes every `put()` event to a sibling file under
    `INFERENCE_INTERNAL_LOGS_DIR` (`evomas/logs/inference_logs/prediction-
    <run_id>.log`) alongside emitting them on the SSE stream — this lets the
    Results page modal replay the run as agent cards + hand-off chips with
    full fidelity (tool result previews, hand-off payloads, final patch).

    `path` is the absolute path of the prediction `.jsonl` — same convention
    as `/api/results/prediction/log` so callers can derive both endpoints
    from one row in the predictions table.
    """
    p = _safe_under(PREDICTIONS_DIR, path)
    if not p.is_file():
        raise HTTPException(404, "prediction file not found")
    ndjson_path = INFERENCE_INTERNAL_LOGS_DIR / (p.stem + ".log")
    if not ndjson_path.is_file():
        # Older predictions written before the NDJSON sink existed — return
        # exists=False so the modal can render an empty/error state.
        return {"path": str(ndjson_path), "name": ndjson_path.name, "exists": False, "raw": ""}
    return {
        "path": str(ndjson_path),
        "name": ndjson_path.name,
        "exists": True,
        "raw": ndjson_path.read_text(encoding="utf-8", errors="replace"),
    }


@app.get("/api/results/prediction/config")
def get_prediction_config(path: str) -> dict[str, Any]:
    """Return the snapshot of the unified-config JSON used to produce a
    prediction file. Snapshots live at `results/predictions/configs/<stem>.json`
    and are written by the inference worker at run start so the user can grab
    the exact config that produced a run (even after the source has been
    renamed or deleted)."""
    p = _safe_under(PREDICTIONS_DIR, path)
    if not p.is_file():
        raise HTTPException(404, "prediction file not found")
    cfg_path = PREDICTION_CONFIGS_DIR / (p.stem + ".json")
    if not cfg_path.is_file():
        return {"path": str(cfg_path), "name": cfg_path.name, "exists": False, "raw": ""}
    return {
        "path": str(cfg_path),
        "name": cfg_path.name,
        "exists": True,
        "raw": cfg_path.read_text(encoding="utf-8", errors="replace"),
    }


@app.get("/api/results/evaluation")
def get_evaluation(dir: str) -> dict[str, Any]:
    """Return the parsed report.json + patch.diff for a per-instance evaluation dir."""
    base = (EVALUATION_DIR / "logs" / "run_evaluation").resolve()
    d = _safe_under(base, dir)
    if not d.is_dir():
        raise HTTPException(404, "evaluation directory not found")
    report: dict[str, Any] = {}
    report_path = d / "report.json"
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report = {}
    patch = ""
    patch_path = d / "patch.diff"
    if patch_path.is_file():
        patch = patch_path.read_text(encoding="utf-8", errors="replace")
    # `dir` = .../logs/run_evaluation/<run_id>/<model>/<instance_id>
    # Surface the run-level dir + cross-model summary so the Results page can
    # offer "reveal in file explorer" buttons without re-deriving paths.
    run_dir = d.parent.parent
    model = d.parent.name
    run_id = run_dir.name
    summary_path = EVALUATION_DIR / f"{model}.{run_id}.json"
    return {
        "dir": str(d),
        "report": report,
        "patch": patch,
        "files": sorted(p.name for p in d.iterdir() if p.is_file()),
        "run_dir": str(run_dir),
        "summary_path": str(summary_path) if summary_path.is_file() else "",
    }


@app.post("/api/results/reveal")
def reveal_in_explorer(payload: dict[str, str]) -> dict[str, Any]:
    """Open the OS file explorer at the given path. Files get highlighted in
    their parent folder; directories open in place. Restricted to paths under
    `results/` so an attacker can't reveal arbitrary system files via the
    frontend."""
    path = payload.get("path") or ""
    if not path:
        raise HTTPException(400, "path is required")
    p = _safe_under(RESULTS_DIR, path)
    if not p.exists():
        raise HTTPException(404, f"path not found: {path}")
    if sys.platform.startswith("win"):
        if p.is_dir():
            subprocess.Popen(["explorer", str(p)])
        else:
            # /select,<file> opens the parent folder with the file highlighted.
            subprocess.Popen(["explorer", f"/select,{p}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p) if p.is_dir() else str(p.parent)])
    return {"ok": True, "path": str(p)}


@app.get("/api/results/evaluation/zip")
def get_evaluation_zip(dir: str) -> Response:
    """Bundle a per-instance evaluation into a zip and return it.

    Layout produced inside the archive:
      logs/<run_instance.log, test_output.txt, eval.sh, report.json, patch.diff>
      evomas.<run_id>.json   ← the top-level evaluation summary, if it exists.
    """
    base = (EVALUATION_DIR / "logs" / "run_evaluation").resolve()
    d = _safe_under(base, dir)
    if not d.is_dir():
        raise HTTPException(404, "evaluation directory not found")

    # `dir` = .../run_evaluation/<run_id>/<model>/<instance_id>
    run_id = d.parent.parent.name        # e.g. "evomas-dev-20260505144947"
    model = d.parent.name                 # e.g. "evomas"
    instance_id = d.name

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(d.iterdir()):
            if f.is_file():
                zf.write(f, arcname=f"logs/{f.name}")
        # Top-level summary file, named `<model>.<run_id>.json`.
        summary = EVALUATION_DIR / f"{model}.{run_id}.json"
        if summary.is_file():
            zf.write(summary, arcname=summary.name)
    buf.seek(0)

    archive_name = f"{instance_id}-{run_id}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{archive_name}"'},
    )


@app.get("/api/results/evaluation/log")
def get_evaluation_log(dir: str, name: str = "run_instance.log") -> dict[str, Any]:
    """Return the contents of a log file inside the evaluation dir.

    `name` defaults to `run_instance.log`; pass `test_output.txt` for the test log.
    """
    if name not in {"run_instance.log", "test_output.txt", "eval.sh", "patch.diff", "report.json"}:
        raise HTTPException(400, f"log '{name}' not allowed")
    base = (EVALUATION_DIR / "logs" / "run_evaluation").resolve()
    d = _safe_under(base, dir)
    f = d / name
    if not f.is_file():
        raise HTTPException(404, f"log not found: {name}")
    return {"name": name, "content": f.read_text(encoding="utf-8", errors="replace")}

# ─── Inference Endpoint ───────────────────────────────────────────────────────
_cancel_flags: dict[str, bool] = {}

# Set by the inference worker on start, cleared on done/error/cancel. The
# Inference page polls `/api/inference/active` on load to discover an
# in-flight run and rebuild its UI from the .log transcript on disk.
_active_run: dict[str, Any] | None = None


def _safe_serialize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items() if k not in ("instance",)}
    if isinstance(obj, list):
        return [_safe_serialize(i) for i in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


@app.post("/api/inference/run")
async def run_inference(req: InferenceRequest):
    # Normalize the instance list. The legacy single-instance form is still
    # accepted; multi-instance runs go through the same SSE stream and emit
    # `instance_start` / `instance_done` frames around each iteration.
    ids: list[str] = []
    if req.instance_ids:
        ids = [i for i in req.instance_ids if i]
    elif req.instance_id:
        ids = [req.instance_id]
    if not ids:
        raise HTTPException(400, "Provide `instance_id` or `instance_ids`")

    # Resolve every id against the on-disk SWE-bench JSONL up front so we can
    # 404 fast before kicking off any LLM work.
    by_id: dict[str, dict] = {}
    if INSTANCES_PATH.exists():
        with INSTANCES_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line.strip())
                    iid = obj.get("instance_id")
                    if iid in ids and iid not in by_id:
                        by_id[iid] = obj
                except json.JSONDecodeError:
                    pass
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise HTTPException(404, f"Instance(s) not found: {missing}")

    # Cancel flag is set per-id; cancel API targets any one of them.
    for iid in ids:
        _cancel_flags[iid] = False

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    # The .log writers are opened once the run_id is known (inside the worker).
    # `put()` mirrors every SSE event into log_state["fh"] (NDJSON, internal,
    # used for resume-on-reload). text_log_state["handler"] holds the Python
    # `logging` FileHandler that captures user-facing text-format messages
    # into results/predictions/logs/.
    log_state: dict[str, Any] = {"fh": None}
    text_log_state: dict[str, Any] = {"handler": None}

    def put(data: dict) -> None:
        loop.call_soon_threadsafe(q.put_nowait, data)
        fh = log_state.get("fh")
        if fh is not None:
            try:
                fh.write(json.dumps(data, default=str) + "\n")
                fh.flush()
            except (OSError, ValueError):
                pass

    def worker() -> None:
        global _active_run
        try:
            from evomas.config.loader import load_config
            from evomas.core.workflow.graph_builder import build_graph
            from evomas.core.workflow.runner import _build_agents
            from evomas.core.workflow.state_factory import (
                build_initial_state,
                build_state_class,
            )
            from evomas.tools.patch_tools import generate_diff_impl
            from evomas.utils.workspace import clone_workspace

            if isinstance(req.config, dict):
                put({"type": "status", "message": "Using inline session config…"})
                cfg = req.config
                # Inline session config — derive a stable name from its `id`.
                config_name = str(cfg.get("id") or "session")
            else:
                put({"type": "status", "message": f"Loading config '{req.config}'…"})
                cfg = load_config(req.config)
                config_name = str(req.config)

            # One run = one shared random UID, used for the prediction filename
            # AND the evaluation directory (`evaluation-<config>-<UID>`). Short
            # hex is plenty unique for local results browsing.
            run_uid = uuid.uuid4().hex[:8]
            run_id = f"{config_name}-{run_uid}"
            stem = f"prediction-{run_id}"
            # Surface the run_id to the UI immediately so the "Running …" chip
            # can show the prediction key while the chain is still streaming;
            # the same key lands on instance_done later for the final record.
            put({
                "type": "run_id",
                "run_id": run_id,
                "output_path": str(PREDICTIONS_DIR / f"{stem}.jsonl"),
            })
            # Re-create the dirs at request time — module-level `mkdir` only
            # runs at boot, so a user wiping `results/` between restarts must
            # not break the next inference run.
            PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
            PREDICTION_TEXT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            PREDICTION_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
            INFERENCE_INTERNAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            output_path = str(PREDICTIONS_DIR / f"{stem}.jsonl")
            text_log_path = str(PREDICTION_TEXT_LOGS_DIR / f"{stem}.log")
            internal_log_path = str(INFERENCE_INTERNAL_LOGS_DIR / f"{stem}.log")
            config_snapshot_path = str(PREDICTION_CONFIGS_DIR / f"{stem}.json")
            # Truncate any leftover prediction file with the same name.
            Path(output_path).write_text("", encoding="utf-8")
            # Snapshot the resolved config so the Results page can hand the
            # user back the exact JSON that produced this run.
            Path(config_snapshot_path).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            # Internal NDJSON SSE-event log — used by the Inference page for
            # resume-on-reload, not surfaced on the Results page. `put()`
            # mirrors each event into it; closed in the finally below.
            log_state["fh"] = open(internal_log_path, "w", encoding="utf-8", buffering=1)

            # User-facing Python `logging` text log — captures every
            # `logger.info(...)` etc. that agents emit during the run, in the
            # same `<timestamp> - <LEVEL> - <message>` shape as old_logs/.
            # Detached in the finally below so log lines from an earlier run
            # don't bleed into the next one's file.
            import logging as _logging
            _root_logger = _logging.getLogger()
            _text_log_handler = _logging.FileHandler(text_log_path, mode="w", encoding="utf-8")
            _text_log_handler.setFormatter(_logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            ))
            _text_log_handler.setLevel(_logging.INFO)
            if _root_logger.level > _logging.INFO or _root_logger.level == 0:
                _root_logger.setLevel(_logging.INFO)
            _root_logger.addHandler(_text_log_handler)
            text_log_state["handler"] = _text_log_handler

            # Publish active-run state so a page reload can rehydrate the UI
            # by reading the internal log file.
            _active_run = {
                "run_id": run_id,
                "config_label": str(config_name),
                "instance_ids": list(ids),
                "log_path": internal_log_path,
                "started_at": int(datetime.now().timestamp() * 1000),
            }

            # ─── Helpers shared across the per-instance loop ────────────
            def _make_think_cb(agent_name: str) -> Any:
                def _cb(chunk: str) -> None:
                    put({"type": "thinking_chunk", "agent": agent_name, "chunk": chunk})
                return _cb

            def _make_response_cb(agent_name: str) -> Any:
                """Fires once per `_invoke()` call with the full LLM response
                text. Emitted to the UI as a single `response` SSE event so
                the chip shows the response as a finished block rather than
                streaming it token-by-token."""
                def _cb(text: str) -> None:
                    put({"type": "response", "agent": agent_name, "content": text})
                return _cb

            def _result_preview(tool: str, result: Any) -> str:
                if isinstance(result, list):
                    return f"{len(result)} items"
                if isinstance(result, dict):
                    if "ok" in result or "applied" in result:
                        ok = result.get("ok", result.get("applied", "?"))
                        return f"ok={ok}"
                    return str(result)[:80]
                return str(result)[:80]

            _PATH_KEYS = {"path", "file_path", "directory", "repo_path"}

            def _args_preview(tool: str, args: dict) -> str:
                skip = {"patch_str", "with_line_numbers", "max_chars"}
                parts = []
                for k, v in args.items():
                    if k in skip:
                        continue
                    val = str(v)
                    if k in _PATH_KEYS and len(val) > 35:
                        parts_path = val.replace("\\", "/").rstrip("/").split("/")
                        val = "…/" + "/".join(parts_path[-2:])
                    else:
                        val = val[:40]
                    parts.append(f"{k}={val}")
                return ", ".join(parts)

            def _make_tool_cb(agent_name: str) -> Any:
                def _cb(tool: str, args: dict, result: Any) -> None:
                    put({
                        "type": "tool_call",
                        "agent": agent_name,
                        "tool": tool,
                        "args_preview": _args_preview(tool, args),
                        "result_preview": _result_preview(tool, result),
                    })
                return _cb

            # ─── Per-instance loop (sequential) ─────────────────────────
            for idx, iid in enumerate(ids):
                if any(_cancel_flags.get(x) for x in ids):
                    put({"type": "cancelled"})
                    return

                instance = by_id[iid]
                instance_started_at = int(datetime.now().timestamp() * 1000)
                put({"type": "instance_start", "instance_id": iid, "index": idx, "total": len(ids)})

                put({"type": "status", "message": f"Cloning workspace for {iid}…"})
                workspace = clone_workspace(
                    instance["instance_id"],
                    instance["repo"],
                    instance["base_commit"],
                )

                issue_parts: list[str] = []
                if instance.get("problem_statement"):
                    issue_parts.append(instance["problem_statement"])
                if instance.get("hints_text"):
                    issue_parts.append("\n## Hints\n" + instance["hints_text"])
                issue_text = "\n".join(issue_parts).strip()

                # Order matters: build_state_class needs the agent instances
                # so it can read each class's `OUTPUT_TYPE` ClassVar.
                agents = _build_agents(cfg)

                for agent_name, agent in agents.items():
                    agent._on_think = _make_think_cb(agent_name)
                    agent._on_response = _make_response_cb(agent_name)
                    agent._on_tool = _make_tool_cb(agent_name)

                state_cls = build_state_class(cfg, agents)
                graph = build_graph(cfg, agents, state_cls)

                initial_state = build_initial_state(
                    cfg,
                    agents,
                    {
                        "instance": instance,
                        "workspace_path": str(workspace.path),
                        "issue_text": issue_text,
                    },
                )

                put({"type": "start", "instance_id": iid, "config": req.config})

                # Pre-compute predecessor map so `agent_input` events on first
                # observation of each agent can list what state it received from
                # earlier nodes. Edges are directed `from -> to`.
                predecessors: dict[str, list[str]] = {}
                # Mirror of `predecessors` keyed by source — used to emit one
                # `handoff` SSE event per outgoing edge after an agent runs,
                # so the inference page can render a chip per (from, to) pair.
                successors: dict[str, list[str]] = {}
                for edge in (cfg.get("edges") or []):
                    if isinstance(edge, dict):
                        src = str(edge.get("from") or "")
                        dst = str(edge.get("to") or "")
                        predecessors.setdefault(dst, []).append(src)
                        successors.setdefault(src, []).append(dst)

                def _preview(val: Any) -> Any:
                    """Same 600-char truncation rule as the delta path below."""
                    if isinstance(val, str):
                        return val[:600] + "\n…(truncated)" if len(val) > 600 else val
                    if isinstance(val, list) and val and all(isinstance(x, str) for x in val):
                        return [
                            (x[:600] + "\n…(truncated)" if len(x) > 600 else x)
                            for x in val
                        ]
                    return val

                accumulated: dict[str, Any] = {}
                seen_agents: set[str] = set()
                for chunk in graph.stream(initial_state, config={"recursion_limit": 75}):
                    if any(_cancel_flags.get(x) for x in ids):
                        put({"type": "cancelled"})
                        return
                    for agent_name, delta in chunk.items():
                        if agent_name.startswith("__") or delta is None:
                            continue
                        if agent_name not in seen_agents:
                            # First observation of this agent — surface what
                            # predecessors put into state before its first
                            # iteration ran.
                            inputs: dict[str, Any] = {}
                            for pred in predecessors.get(agent_name, []):
                                if pred and pred in accumulated:
                                    inputs[pred] = _safe_serialize(_preview(accumulated[pred]))
                            put({
                                "type": "agent_input",
                                "agent": agent_name,
                                "inputs": inputs,
                            })
                            seen_agents.add(agent_name)
                        accumulated.update(delta)
                        safe_delta = _safe_serialize(delta)
                        # Truncate any long patch strings inside list-valued
                        # slots — the producer-keyed convention means the
                        # field name varies per topology (e.g. `patch_agent`
                        # for evo-star, `patcher` for star), so we can't
                        # hardcode a single key like before.
                        for k, v in list(safe_delta.items()):
                            if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                                safe_delta[k] = [
                                    (x[:600] + "\n…(truncated)" if len(x) > 600 else x)
                                    for x in v
                                ]
                        put({"type": "agent_event", "agent": agent_name, "delta": safe_delta})
                        # One `handoff` event per outgoing edge so the
                        # inference page can render a chip between this
                        # agent's card and each downstream agent's card.
                        # The canonical producer slot is `delta[agent_name]`
                        # per the edge-driven IO contract; fall back to the
                        # whole delta when the agent wrote elsewhere.
                        targets_for_node = successors.get(agent_name, [])
                        if targets_for_node:
                            from evomas.utils.handoff import (
                                preview_payload as _preview_payload,
                                summarize_payload as _summarize_payload,
                            )
                            raw_primary = delta.get(agent_name, delta)
                            handoff_summary = _summarize_payload(raw_primary)
                            handoff_preview = _preview_payload(raw_primary)
                            handoff_keys = sorted(delta.keys())
                            handoff_ts = datetime.now().isoformat()
                            for _tgt in targets_for_node:
                                put({
                                    "type": "handoff",
                                    "from": agent_name,
                                    "to": _tgt,
                                    "keys": handoff_keys,
                                    "summary": handoff_summary,
                                    "preview": handoff_preview,
                                    "timestamp": handoff_ts,
                                })

                # Edge-driven output contract: the model_patch is whatever the
                # `end` node wrote into its producer slot. Fall back to the
                # workspace git diff for type-driven topologies whose agents
                # don't explicitly write a final-patch slot.
                end_field = cfg.get("end")
                end_key: str = (
                    end_field if isinstance(end_field, str)
                    else (end_field[-1] if end_field else "")
                )
                final_patch: str = str(accumulated.get(end_key) or "")
                if not final_patch.strip():
                    final_patch = generate_diff_impl(str(workspace.path)) or ""

                # Sum per-agent token counts (each agent accumulated its
                # own across multiple `_invoke()` calls during the graph
                # run). Logged for visibility and persisted on the
                # prediction record so the Results page can surface it.
                tokens_in = sum(int(a._tokens.get("input", 0))  for a in agents.values())
                tokens_out = sum(int(a._tokens.get("output", 0)) for a in agents.values())
                tokens_total = sum(int(a._tokens.get("total", 0))  for a in agents.values())
                logger.info(
                    "[%s] tokens in=%d out=%d total=%d (per-agent: %s)",
                    iid, tokens_in, tokens_out, tokens_total,
                    {n: a._tokens for n, a in agents.items()},
                )
                # Surface per-agent token counts so each chip in the UI can
                # show its own in/out/total footer. The graph stream doesn't
                # expose per-agent "done" events, so we emit these after the
                # chain finishes — fine since the values are accumulated
                # across iterations anyway.
                for agent_name, agent in agents.items():
                    put({
                        "type": "agent_tokens",
                        "agent": agent_name,
                        "input":  int(agent._tokens.get("input", 0)),
                        "output": int(agent._tokens.get("output", 0)),
                        "total":  int(agent._tokens.get("total", 0)),
                    })

                pred = {
                    "instance_id": iid,
                    "model_patch": final_patch,
                    "model_name_or_path": "evomas",
                    "run_id": run_id,
                    # LLM token usage summed across every agent's calls for
                    # this instance. {"input": prompt+context, "output":
                    # generated, "total": in+out}. Source: each agent's
                    # `_tokens` dict, populated by `BaseAgent._invoke`.
                    "tokens": {"input": tokens_in, "output": tokens_out, "total": tokens_total},
                    # Forward the instance's source subset/split so the
                    # Evaluation page can partition by (subset, split) and run
                    # the harness against the right HuggingFace dataset.
                    "subset": instance.get("subset", "lite"),
                    "split":  instance.get("split", "dev"),
                    # Per-instance timing (epoch ms) — surfaced on the Results
                    # prediction panel as Time of inference / End of inference.
                    "started_at": instance_started_at,
                    "ended_at": int(datetime.now().timestamp() * 1000),
                }
                # Append (one JSONL line per instance) into the shared run file.
                with open(output_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(pred) + "\n")

                put({
                    "type": "instance_done",
                    "instance_id": iid,
                    "index": idx,
                    "total": len(ids),
                    "output_path": output_path,
                    "run_id": run_id,
                    "patch": final_patch,
                })

            # Final batch-level frame so the UI can flip to "all done".
            put({
                "type": "done",
                "instance_ids": ids,
                "output_path": output_path,
                "run_id": run_id,
            })

        except Exception as exc:
            import traceback as _tb
            put({"type": "error", "message": str(exc), "traceback": _tb.format_exc()})
        finally:
            fh = log_state.get("fh")
            if fh is not None:
                try:
                    fh.close()
                except OSError:
                    pass
            handler = text_log_state.get("handler")
            if handler is not None:
                try:
                    import logging as _logging
                    _logging.getLogger().removeHandler(handler)
                    handler.close()
                except (OSError, ValueError):
                    pass
            _active_run = None
            loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=600.0)
            except asyncio.TimeoutError:
                yield 'data: {"type":"error","message":"Timeout waiting for response"}\n\n'
                break
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/inference/cancel/{instance_id}")
def cancel_inference(instance_id: str) -> dict:
    _cancel_flags[instance_id] = True
    return {"ok": True}


@app.get("/api/inference/active")
def inference_active() -> dict[str, Any]:
    """Snapshot of the in-flight inference run, or `{active: false}` when
    nothing is running. Used by the Inference page on reload to rehydrate
    its UI from the on-disk .log transcript."""
    if _active_run is None:
        return {"active": False}
    return {"active": True, **_active_run}


@app.get("/api/inference/log-tail")
def inference_log_tail(path: str, offset: int = 0) -> dict[str, Any]:
    """Return bytes of the prediction log starting at `offset`, plus the new
    end-of-file offset and whether the run is still in flight. The Inference
    page polls this while a run is active to stream newly-appended events
    into the live UI without holding open an SSE connection."""
    p = _safe_under(INFERENCE_INTERNAL_LOGS_DIR, path)
    if not p.is_file():
        raise HTTPException(404, "log file not found")
    size = p.stat().st_size
    if offset > size:
        offset = 0  # log was truncated/replaced; restart from the top
    with p.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    is_running = _active_run is not None and Path(_active_run["log_path"]) == p
    return {
        "raw": chunk.decode("utf-8", errors="replace"),
        "offset": offset + len(chunk),
        "is_running": is_running,
    }


# ─── Evaluation Endpoint ──────────────────────────────────────────────────────
_eval_procs: dict[str, Any] = {}


def _partition_predictions(path: Path) -> dict[tuple[str, str], list[str]]:
    """Group the JSONL lines of `path` by (subset, split).

    Resolution priority per line — same logic as `/api/predictions/inspect`:
      1. The line's own `subset` / `split` fields.
      2. Fallback to the local `swebench_instances.jsonl` cache, looked up by
         instance_id (rescues old prediction files written before the inference
         worker started forwarding subset/split).
      3. Default ("lite", "dev").
    """
    origin = _instance_origin_lookup()
    out: dict[tuple[str, str], list[str]] = {}
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        subset = obj.get("subset")
        split = obj.get("split")
        if not subset or not split:
            cached = origin.get(obj.get("instance_id") or "")
            if cached:
                subset = subset or cached[0]
                split = split or cached[1]
        subset = subset or "lite"
        split = split or "dev"
        out.setdefault((subset, split), []).append(raw)
    return out


def _derive_run_id_base(pred_path: Path) -> str:
    """Pull the `<config>-<UID>` segment out of a `prediction-<X>.jsonl` name,
    or fall back to a timestamp."""
    m = re.match(r"^prediction-(.+)\.jsonl$", pred_path.name)
    if m:
        return m.group(1)
    return f"adhoc-{datetime.now().strftime('%Y%m%d%H%M%S')}"


@app.post("/api/evaluation/run")
async def run_evaluation(req: EvaluationRequest):
    pred_path = Path(req.predictions_path)
    if not pred_path.is_file():
        raise HTTPException(404, f"Predictions file not found: {req.predictions_path}")

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    key = req.predictions_path

    # Partition predictions by (subset, split) so a single multi-instance
    # prediction file produced by the inference page is evaluated correctly
    # against every dataset its instances came from.
    groups = _partition_predictions(pred_path)
    # Custom-repo predictions can't be scored by the SWE-bench harness — they
    # don't carry `test_patch` / `FAIL_TO_PASS` / `PASS_TO_PASS`. Pull them
    # out of the groups dict so the harness only sees real SWE-bench rows.
    skipped_custom = groups.pop(("custom", "custom"), [])
    base = req.run_id or f"evaluation-{_derive_run_id_base(pred_path)}"

    def put(data: dict) -> None:
        loop.call_soon_threadsafe(q.put_nowait, data)

    def worker() -> None:
        try:
            EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
            tmp_dir = EVALUATION_DIR / "_tmp_predictions"
            tmp_dir.mkdir(parents=True, exist_ok=True)

            put({"type": "log", "message": (
                f"Detected {len(groups)} (subset, split) group(s) in {pred_path.name}: "
                + ", ".join(f"{s}/{sp}={len(v)}" for (s, sp), v in groups.items())
            )})
            if skipped_custom:
                put({"type": "log", "message": (
                    f"Detected {len(skipped_custom)} custom-repo prediction(s) -- "
                    f"will score them by cloning + applying patch + running pytest after "
                    f"the SWE-bench group(s)."
                )})
            if not groups and not skipped_custom:
                # Nothing to evaluate -- exit cleanly so the frontend
                # doesn't hang on an empty stream.
                put({"type": "done", "returncode": 0})
                return

            return_codes: list[int] = []
            for (subset, split), lines in groups.items():
                # Per-group prediction sidecar so the harness only sees its split.
                group_path = tmp_dir / f"{pred_path.stem}__{subset}_{split}.jsonl"
                group_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                # Per-group run_id (unique under logs/run_evaluation/).
                group_run_id = f"{base}-{subset}-{split}" if len(groups) > 1 else base
                # Honor an explicit override only when there's exactly one group.
                effective_split = req.split or split

                put({"type": "group_start", "subset": subset, "split": split,
                     "run_id": group_run_id, "count": len(lines)})

                cmd = [
                    "wsl",
                    _to_wsl(str(SWEBENCH_VENV_PYTHON)),
                    _to_wsl(str(BASE_DIR / "scripts" / "run_swebench_evaluation.py")),
                    "--predictions", _to_wsl(str(group_path)),
                    "--subset", subset,
                    "--split", effective_split,
                    "--max-workers", str(req.max_workers),
                    "--run-id", group_run_id,
                    "--report-dir", _to_wsl(str(EVALUATION_DIR)),
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=str(EVALUATION_DIR),
                    encoding="utf-8",
                    errors="replace",
                )
                _eval_procs[key] = proc
                for line in iter(proc.stdout.readline, ""):
                    put({"type": "log", "message": line.rstrip()})
                proc.wait()
                return_codes.append(proc.returncode)
                put({"type": "group_done", "subset": subset, "split": split,
                     "run_id": group_run_id, "returncode": proc.returncode})

            # Custom group: clone + apply patch + pytest, native (no WSL).
            # Run after the SWE-bench harness groups so the SSE order matches
            # what the frontend already shows for mixed prediction files.
            if skipped_custom:
                custom_run_id = (
                    f"{base}-custom-custom" if groups else base
                )
                # Resolve repo + base_commit for each custom prediction by
                # looking up the instance row in swebench_instances.jsonl.
                custom_iids: list[str] = []
                for raw in skipped_custom:
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    iid = obj.get("instance_id")
                    if iid:
                        custom_iids.append(iid)
                rows = _load_instance_rows(custom_iids)

                model_name = "evomas-custom"
                try:
                    first = json.loads(skipped_custom[0])
                    cand = first.get("model_name_or_path") or first.get("model")
                    if isinstance(cand, str) and cand.strip():
                        model_name = cand.strip()
                except json.JSONDecodeError:
                    pass

                # Per-group sidecars.
                custom_pred_path = tmp_dir / f"{pred_path.stem}__custom_custom.jsonl"
                custom_pred_path.write_text("\n".join(skipped_custom) + "\n", encoding="utf-8")
                custom_inst_path = tmp_dir / f"{pred_path.stem}__custom_custom_instances.jsonl"
                custom_inst_path.write_text(
                    "\n".join(json.dumps(r, ensure_ascii=False) for r in rows.values()) + "\n",
                    encoding="utf-8",
                )

                put({"type": "group_start", "subset": "custom", "split": "custom",
                     "run_id": custom_run_id, "count": len(skipped_custom)})

                cmd = [
                    sys.executable,
                    str(BASE_DIR / "scripts" / "apply_and_test.py"),
                    "--instances",   str(custom_inst_path),
                    "--predictions", str(custom_pred_path),
                    "--report-dir",  str(EVALUATION_DIR),
                    "--run-id",      custom_run_id,
                    "--model",       model_name,
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=str(BASE_DIR),
                    encoding="utf-8",
                    errors="replace",
                )
                _eval_procs[key] = proc
                for line in iter(proc.stdout.readline, ""):
                    put({"type": "log", "message": line.rstrip()})
                proc.wait()
                return_codes.append(proc.returncode)
                put({"type": "group_done", "subset": "custom", "split": "custom",
                     "run_id": custom_run_id, "returncode": proc.returncode})

            put({"type": "done", "returncode": max(return_codes) if return_codes else 0})
        except Exception as exc:
            put({"type": "error", "message": str(exc)})
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=3600.0)
            except asyncio.TimeoutError:
                yield 'data: {"type":"error","message":"Evaluation timeout"}\n\n'
                break
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/evaluation/cancel")
async def cancel_evaluation(predictions_path: str) -> dict:
    proc = _eval_procs.get(predictions_path)
    if proc:
        proc.terminate()
        return {"ok": True}
    return {"ok": False, "message": "No running evaluation found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
