"""Topology-page endpoints: unified configs + GitPython-backed history,
MCP tool catalogue, agent-type catalogue, and the Ollama /
remote-provider model dropdown feed. One file because the topology
page consumes them as one surface."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import threading
import urllib.request as _urllib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.common import (
    INFERENCE_INTERNAL_LOGS_DIR,
    LOADED_CONFIG_DIR,
    PREDEFINED_CONFIG_DIR,
    logger,
)

router = APIRouter()


# ─── Ollama helpers ───────────────────────────────────────────────────────────
def _ollama_base_url() -> str:
    import os
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").strip().strip("\"'")


# TTL cache for remote provider model lists — avoid round-tripping the
# Google/OpenAI `models.list` API on every Topology-page reload.
_REMOTE_MODELS_TTL_S = 300
_remote_models_cache: dict[str, tuple[float, list[str]]] = {}


def _ollama_models() -> list[str]:
    """Locally-pulled Ollama models as `["ollama/<name>", ...]`."""
    try:
        url = f"{_ollama_base_url()}/api/tags"
        with _urllib.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return sorted(f"ollama/{m['name']}" for m in data.get("models", []))
    except Exception:
        return []


def _ollama_models_with_pulled() -> list[dict[str, Any]]:
    """Merge locally-pulled Ollama models with the curated catalog so
    the topology dropdown shows every model the user can pick. Pulled
    entries come first (alphabetical), then unpulled catalog entries
    in declared order. The Inference page runs `ollama pull <name>`
    for `pulled: False` entries before the run starts."""
    from api.ollama_catalog import OLLAMA_CATALOG
    pulled = set(_ollama_models())
    out: list[dict[str, Any]] = []
    for name in sorted(pulled):
        out.append({"name": name, "pulled": True})
    seen = set(pulled)
    for name in OLLAMA_CATALOG:
        if name in seen:
            continue
        out.append({"name": name, "pulled": False})
        seen.add(name)
    return out


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
    """Live `generateContent`-capable Gemini models, minus non-chat shapes."""
    import os
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
    """Chat-capable OpenAI models from `/v1/models` (filtered by name)."""
    import os
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


class PullModelRequest(BaseModel):
    model: str


@router.post("/api/models/pull")
async def pull_model(req: PullModelRequest):
    """Stream `ollama pull <model>` progress as SSE.

    Events: `{type: "log", line}` per stdout line, then a terminal
    `{type: "done", code}` (0 = success)."""
    raw = req.model.strip()
    name = raw.removeprefix("ollama/") if raw.startswith("ollama/") else raw
    if not name:
        raise HTTPException(400, "model must be a non-empty string")

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def put(payload: dict | None) -> None:
        loop.call_soon_threadsafe(q.put_nowait, payload)

    def worker() -> None:
        try:
            # utf-8 + errors="replace" avoids cp1252 decode crashes on
            # Windows when Ollama's progress bars contain non-cp1252 glyphs.
            proc = subprocess.Popen(
                ["ollama", "pull", name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            put({"type": "log", "line": "ERROR: `ollama` not on PATH; install Ollama first."})
            put({"type": "done", "code": 127})
            put(None)
            return
        assert proc.stdout is not None
        for line in proc.stdout:
            put({"type": "log", "line": line.rstrip()})
        proc.wait()
        put({"type": "done", "code": proc.returncode})
        put(None)

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=600.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'done', 'code': 124})}\n\n"
                return
            if item is None:
                return
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/models")
def list_models() -> list[dict[str, Any]]:
    """`[{name, pulled}]` — pulled-locally + curated catalog. Pulled
    first (alphabetical), then unpulled in declared order."""
    return _ollama_models_with_pulled()


# ─── Unified Config Endpoints ────────────────────────────────────────────────
# Configs live in two roots — `predefined/` (read-only, shipped) and
# `loaded/` (writable, user-imported). The loader searches both.

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
    """On-disk path of a config by stem — predefined first, then loaded."""
    for base in (PREDEFINED_CONFIG_DIR, LOADED_CONFIG_DIR):
        p = base / f"{name}.json"
        if p.is_file():
            return p
    return None


def _validate_loaded_config(data: dict, expected_stem: str) -> None:
    """Required keys present + `id` matches the filename stem."""
    missing = [k for k in _REQUIRED_CONFIG_KEYS if k not in data]
    if missing:
        raise HTTPException(400, f"config is missing required keys: {missing}")
    if str(data.get("id") or "") != expected_stem:
        raise HTTPException(
            400,
            f"config 'id' must match filename stem (id={data.get('id')!r}, "
            f"stem={expected_stem!r})",
        )


@router.get("/api/configs")
def list_configs() -> list[dict[str, str]]:
    """`[{stem, id, description, source}]` from both config roots."""
    return _scan_config_dir(PREDEFINED_CONFIG_DIR, "predefined") + _scan_config_dir(LOADED_CONFIG_DIR, "loaded")


@router.get("/api/configs/{name}")
def get_config(name: str) -> dict:
    path = _resolve_config_path(name)
    if path is None:
        raise HTTPException(404, f"Config '{name}' not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"Failed to parse {path.name}: {exc}") from exc


class LoadedConfigPayload(BaseModel):
    name: str
    data: dict[str, Any]
    replace: bool = False


@router.post("/api/configs/loaded")
def save_loaded_config(payload: LoadedConfigPayload) -> dict[str, Any]:
    """Persist `loaded/<name>.json`. Rejects overlap with a predefined
    stem; requires `replace=True` to overwrite an existing loaded stem."""
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
    # Best-effort version-control commit; failures don't propagate.
    sha: str | None = None
    try:
        from evomas.config.history import commit_save
        sha = commit_save(payload.name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("config history commit failed for %s: %s", payload.name, exc)
    return {"ok": True, "stem": payload.name, "path": str(target), "sha": sha}


class RenameConfigPayload(BaseModel):
    new_name: str


@router.patch("/api/configs/loaded/{name}")
def rename_loaded_config(name: str, payload: RenameConfigPayload) -> dict[str, Any]:
    """Rename a loaded config (file + `id` field). Predefined are read-only."""
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
    # Two histories, one rename: close the old timeline, start the new.
    try:
        from evomas.config.history import commit_delete, commit_save
        commit_delete(name)
        commit_save(new_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("config history rename commit failed (%s -> %s): %s", name, new_name, exc)
    return {"ok": True, "stem": new_name, "path": str(dst)}


@router.delete("/api/configs/loaded/{name}")
def delete_loaded_config(name: str) -> dict[str, Any]:
    target = LOADED_CONFIG_DIR / f"{name}.json"
    if not target.is_file():
        raise HTTPException(404, f"loaded config '{name}' not found")
    target.unlink()
    try:
        from evomas.config.history import commit_delete
        commit_delete(name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("config history delete commit failed for %s: %s", name, exc)
    return {"ok": True, "stem": name}


# ─── Loaded-config version history (GitPython-backed) ────────────────────────
# History lives in a nested git repo under `evomas/config/loaded/`
# (gitignored at the project root). Every Save writes a commit.

@router.get("/api/configs/loaded/{name}/history")
def list_config_history(name: str) -> dict[str, Any]:
    """Newest-first commits touching `<name>.json`; empty list = no history yet."""
    if "/" in name or "\\" in name or not name:
        raise HTTPException(400, "invalid config name")
    try:
        from evomas.config.history import list_history
        return {"entries": list_history(name)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("history list failed for %s: %s", name, exc)
        raise HTTPException(503, f"history backend unavailable: {exc}") from exc


@router.get("/api/configs/loaded/{name}/history/{sha}")
def get_config_at_sha(name: str, sha: str) -> dict[str, Any]:
    """File contents at `sha` for the history preview pane."""
    if "/" in name or "\\" in name or not name:
        raise HTTPException(400, "invalid config name")
    if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha):
        raise HTTPException(400, "invalid sha")
    try:
        from evomas.config.history import read_at
        content = read_at(name, sha)
        return {"sha": sha, "content": content}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"version not found: {exc}") from exc


@router.delete("/api/configs/loaded/{name}/history/{sha}")
def delete_config_history_entry(name: str, sha: str) -> dict[str, Any]:
    """Drop a single commit from the loaded-configs history.
    Descendants get rebased onto its parent, so their SHAs change —
    older runs pinned to those SHAs will stop matching."""
    if "/" in name or "\\" in name or not name:
        raise HTTPException(400, "invalid config name")
    if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha):
        raise HTTPException(400, "invalid sha")
    try:
        from evomas.config.history import delete_commit
        new_head = delete_commit(sha)
        if new_head is None:
            raise HTTPException(
                409,
                "cannot delete — commit is the root of history (use "
                "the 'clear all history' action instead) or the SHA "
                "is no longer reachable",
            )
        return {"ok": True, "new_head": new_head}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_commit failed for %s: %s", sha, exc)
        raise HTTPException(500, f"delete failed: {exc}") from exc


@router.delete("/api/configs/loaded/history")
def clear_all_config_history() -> dict[str, Any]:
    """Wipe `.git/` under `loaded/` — every config loses its history;
    working-tree files are preserved."""
    try:
        from evomas.config.history import delete_all_history
        delete_all_history()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("clear_all_config_history failed: %s", exc)
        raise HTTPException(500, f"reset failed: {exc}") from exc


@router.get("/api/configs/loaded/{name}/history/{sha}/runs")
def list_runs_for_config_sha(name: str, sha: str) -> dict[str, Any]:
    """Runs whose recorded `config_sha` matches `sha` — drives the
    "N runs" pill in the history sidebar."""
    if "/" in name or "\\" in name or not name:
        raise HTTPException(400, "invalid config name")
    if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha):
        raise HTTPException(400, "invalid sha")
    matches: list[dict[str, Any]] = []
    if INFERENCE_INTERNAL_LOGS_DIR.is_dir():
        # `run_meta` is always the first event — read one line per sidecar.
        for ndjson in INFERENCE_INTERNAL_LOGS_DIR.glob("*.ndjson"):
            try:
                with ndjson.open("r", encoding="utf-8") as f:
                    first = f.readline()
                if not first.strip():
                    continue
                meta = json.loads(first)
                if meta.get("type") != "run_meta":
                    continue
                if meta.get("config_name") != name:
                    continue
                run_sha = meta.get("config_sha") or ""
                if not run_sha:
                    continue
                if run_sha.startswith(sha) or sha.startswith(run_sha):
                    matches.append({
                        "runId": meta.get("run_id") or ndjson.stem.replace("prediction-", ""),
                        "instanceIds": meta.get("instance_ids") or [],
                        "ts": meta.get("ts") or "",
                    })
            except (OSError, json.JSONDecodeError):
                continue
    matches.sort(key=lambda m: m.get("ts") or "", reverse=True)
    return {"matches": matches}


# ─── MCP tools (read-only) ────────────────────────────────────────────────────
_TOOL_REPO_OWNER_CACHE: dict[str, str] | None = None


def _tool_repo_owner_map() -> dict[str, str]:
    """`tool_name -> owner` map built by importing each tool bundle once.
    Tools not in any bundle (top-level `evomas/tools/*.py`) get `"evomas"`."""
    global _TOOL_REPO_OWNER_CACHE
    if _TOOL_REPO_OWNER_CACHE is not None:
        return _TOOL_REPO_OWNER_CACHE
    from evomas.tools.repo.augment_swebench_agent import AUGMENT_SWEBENCH_AGENT_TOOLS
    from evomas.tools.repo.auto_code_rover import AUTO_CODE_ROVER_TOOLS
    from evomas.tools.repo.claude_coder import CLAUDE_CODER_TOOLS
    from evomas.tools.repo.composio import COMPOSIO_TOOLS
    from evomas.tools.repo.debug_gym import DEBUG_GYM_TOOLS
    from evomas.tools.repo.joycode_agent import JOYCODE_AGENT_TOOLS
    from evomas.tools.repo.lingma_swe_gpt import LINGMA_SWE_GPT_TOOLS
    from evomas.tools.repo.openhands import LOC_TOOLS, OPENHANDS_TOOLS
    from evomas.tools.repo.patchwork import PATCHWORK_TOOLS
    from evomas.tools.repo.suna import SUNA_TOOLS
    from evomas.tools.repo.swe_agent import SWE_AGENT_TOOLS
    from evomas.tools.repo.trae_agent import TRAE_AGENT_TOOLS
    # Heterogeneous bundle tuples (each repo declares its own Tool subtype);
    # annotation widens to `tuple[Any, ...]` to unify the union.
    bundles: list[tuple[str, Any]] = [
        ("augment_swebench_agent", AUGMENT_SWEBENCH_AGENT_TOOLS),
        ("auto_code_rover",        AUTO_CODE_ROVER_TOOLS),
        ("claude_coder",           CLAUDE_CODER_TOOLS),
        ("composio",               COMPOSIO_TOOLS),
        ("debug_gym",              DEBUG_GYM_TOOLS),
        ("joycode_agent",          JOYCODE_AGENT_TOOLS),
        ("lingma_swe_gpt",         LINGMA_SWE_GPT_TOOLS),
        # OpenHands ships two bundles under one folder; share the owner.
        ("openhands",              OPENHANDS_TOOLS),
        ("openhands",              LOC_TOOLS),
        ("patchwork",              PATCHWORK_TOOLS),
        ("suna",                   SUNA_TOOLS),
        ("swe_agent",              SWE_AGENT_TOOLS),
        ("trae_agent",             TRAE_AGENT_TOOLS),
    ]
    out: dict[str, str] = {}
    for owner, bundle in bundles:
        for tool in bundle:
            name = getattr(tool, "name", None)
            if not name:
                continue
            # First-seen owner wins (handles cross-bundle re-exports).
            out.setdefault(name, owner)
    _TOOL_REPO_OWNER_CACHE = out
    return out


@router.get("/api/tools")
def list_tools() -> list[dict[str, Any]]:
    """MCP tool catalog: `[{name, description, inputSchema, repo}]`.
    `repo` is the bundle folder or `"evomas"` for top-level helpers."""
    from evomas.mcp.server import MCPServer
    owner_map = _tool_repo_owner_map()
    catalog = MCPServer().registry.list()
    for entry in catalog:
        entry["repo"] = owner_map.get(entry.get("name", ""), "evomas")
    return catalog


# ─── Agent types (read-only) ──────────────────────────────────────────────────
@router.get("/api/agent-types")
def list_agent_types_endpoint() -> list[dict[str, Any]]:
    """Agent-type catalog with a `variants` array per type (EvoMas
    built-in first, then CSV-derived alternatives)."""
    from evomas.agents.types import list_agent_types
    from evomas.agents.types.variants import list_variants
    catalog = list_agent_types()
    variants_by_type = list_variants()
    for t in catalog:
        t["variants"] = variants_by_type.get(t["type"], [])
    return catalog


@router.get("/api/agent-variants")
def list_agent_variants_endpoint() -> dict[str, list[dict[str, Any]]]:
    """Agent variants grouped by AGENT_TYPE; EvoMas built-in is always first."""
    from evomas.agents.types.variants import list_variants
    return list_variants()
