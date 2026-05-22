"""Evaluation-page endpoints: scan / inspect prediction JSONLs, run
them through the SWE-bench harness (or `apply_and_test.py` for custom
repos), and stream results back as SSE."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.common import (
    BASE_DIR,
    EVALUATION_DIR,
    INSTANCES_PATH,
    PREDICTIONS_DIR,
    SWEBENCH_VENV_PYTHON,
    safe_under,
)
from evomas.utils.instances import instance_origin_lookup, load_instance_rows
from evomas.utils.paths import to_wsl
from evomas.utils.predictions import derive_run_id_base, partition_predictions

router = APIRouter()


# ─── Prediction listing / inspection ─────────────────────────────────────────
_PRED_KEY_RE_LOCAL = re.compile(r"^prediction-(.+)\.jsonl$")


class EvaluationRequest(BaseModel):
    predictions_path: str
    max_workers: int = 4
    # Both auto-detected from the prediction file when omitted.
    split: str | None = None
    run_id: str | None = None


@router.get("/api/predictions")
def list_predictions() -> list[str]:
    files = sorted(PREDICTIONS_DIR.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)
    return [str(p) for p in files]


@router.get("/api/predictions/inspect")
def inspect_prediction(path: str) -> dict[str, Any]:
    """`{groups: [{subset, split, instance_ids}], total, ...}` for a
    prediction file. Resolution order per line: row's own subset/split,
    then the instances cache, then `("lite", "dev")`."""
    p = safe_under(PREDICTIONS_DIR, path)
    if not p.is_file():
        raise HTTPException(404, "prediction file not found")

    origin = instance_origin_lookup(INSTANCES_PATH)
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

    m = _PRED_KEY_RE_LOCAL.match(p.name)
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


# ─── Run / cancel evaluation ──────────────────────────────────────────────────
_eval_procs: dict[str, Any] = {}


@router.post("/api/evaluation/run")
async def run_evaluation(req: EvaluationRequest):
    pred_path = Path(req.predictions_path)
    if not pred_path.is_file():
        raise HTTPException(404, f"Predictions file not found: {req.predictions_path}")

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    key = req.predictions_path

    # Partition by (subset, split) so a multi-instance file is scored
    # against every dataset its rows came from. Custom-repo rows go to
    # `apply_and_test.py` since the SWE-bench harness needs test_patch.
    groups = partition_predictions(pred_path, INSTANCES_PATH)
    skipped_custom = groups.pop(("custom", "custom"), [])
    base = req.run_id or f"evaluation-{derive_run_id_base(pred_path)}"

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
                put({"type": "done", "returncode": 0})
                return

            return_codes: list[int] = []
            for (subset, split), lines in groups.items():
                group_path = tmp_dir / f"{pred_path.stem}__{subset}_{split}.jsonl"
                group_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                group_run_id = f"{base}-{subset}-{split}" if len(groups) > 1 else base
                effective_split = req.split or split

                put({"type": "group_start", "subset": subset, "split": split,
                     "run_id": group_run_id, "count": len(lines)})

                cmd = [
                    "wsl",
                    to_wsl(str(SWEBENCH_VENV_PYTHON)),
                    to_wsl(str(BASE_DIR / "scripts" / "run_swebench_evaluation.py")),
                    "--predictions", to_wsl(str(group_path)),
                    "--subset", subset,
                    "--split", effective_split,
                    "--max-workers", str(req.max_workers),
                    "--run-id", group_run_id,
                    "--report-dir", to_wsl(str(EVALUATION_DIR)),
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
                assert proc.stdout is not None
                for line in iter(proc.stdout.readline, ""):
                    put({"type": "log", "message": line.rstrip()})
                proc.wait()
                return_codes.append(proc.returncode)
                put({"type": "group_done", "subset": subset, "split": split,
                     "run_id": group_run_id, "returncode": proc.returncode})

            # Custom group: native clone + apply + pytest. Runs after the
            # harness groups so SSE order matches the frontend's render.
            if skipped_custom:
                custom_run_id = (
                    f"{base}-custom-custom" if groups else base
                )
                custom_iids: list[str] = []
                for raw in skipped_custom:
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    iid = obj.get("instance_id")
                    if iid:
                        custom_iids.append(iid)
                rows = load_instance_rows(custom_iids, INSTANCES_PATH)

                model_name = "evomas-custom"
                try:
                    first = json.loads(skipped_custom[0])
                    cand = first.get("model_name_or_path") or first.get("model")
                    if isinstance(cand, str) and cand.strip():
                        model_name = cand.strip()
                except json.JSONDecodeError:
                    pass

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
                assert proc.stdout is not None
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


@router.post("/api/evaluation/cancel")
async def cancel_evaluation(predictions_path: str) -> dict:
    proc = _eval_procs.get(predictions_path)
    if proc:
        proc.terminate()
        return {"ok": True}
    return {"ok": False, "message": "No running evaluation found"}
