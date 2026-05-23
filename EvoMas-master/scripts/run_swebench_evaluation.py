import argparse
import importlib.util
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
SWEBENCH_VENV = REPO_ROOT / "SWE-bench" / "venv"


def _swebench_python() -> str:
    """Pick a python that can import `swebench.harness`: active interpreter, then `<repo>/SWE-bench/venv/`."""
    if importlib.util.find_spec("swebench") is not None:
        return sys.executable
    win_py = SWEBENCH_VENV / "Scripts" / "python.exe"
    if win_py.exists():
        return str(win_py)
    posix_py = SWEBENCH_VENV / "bin" / "python"
    if posix_py.exists() and os.name != "nt":
        return str(posix_py)
    return sys.executable


def _remove_stale_containers(run_id: str) -> None:
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=sweb.eval.", "--format", "{{.Names}}"],
        capture_output=True, text=True
    )
    containers = [c for c in result.stdout.splitlines() if run_id in c]
    if not containers:
        return
    logger.info("Removing %d stale containers from previous run...", len(containers))
    subprocess.run(["docker", "rm", "-f"] + containers, capture_output=True)
    logger.info("Stale containers removed.")


def _purge_stale_reports(run_id: str, report_dir: str | None) -> None:
    """Delete per-instance report.json so the harness re-runs (it hardcodes
    exclude_completed=True; same run_id otherwise logs "already run")."""
    base = Path(report_dir or ".") / "logs" / "run_evaluation" / run_id
    if not base.is_dir():
        return
    nuked = 0
    for p in base.rglob("report.json"):
        try:
            p.unlink()
            nuked += 1
        except OSError:
            pass
    if nuked:
        logger.info("Purged %d stale report.json files under %s", nuked, base)


SUBSET_DATASETS: dict[str, str] = {
    "lite":     "SWE-bench/SWE-bench_Lite",
    "full":     "SWE-bench/SWE-bench",
    "verified": "SWE-bench/SWE-bench_Verified",
}


def run_evaluation(
    predictions_path: str,
    run_id: str,
    split: str,
    max_workers: int = 8,
    report_dir: str | None = None,
    subset: str = "lite",
    force: bool = True,
    cache_level: str = "env",
    force_rebuild: bool = False,
) -> int:
    """Return the harness subprocess exit code (127 = couldn't spawn it)."""
    _remove_stale_containers(run_id)
    if force:
        _purge_stale_reports(run_id, report_dir)
    dataset = SUBSET_DATASETS.get(subset, SUBSET_DATASETS["lite"])
    python_bin = _swebench_python()
    # SWE-bench writes `logs/run_evaluation/<run_id>/` relative to the
    # subprocess cwd (not --report_dir, which only places the top-level
    # JSON). Resolve --predictions to absolute then chdir into report_dir
    # so every artifact lands under it.
    abs_predictions = str(Path(predictions_path).resolve())
    cwd: str | None = None
    abs_report_dir: str | None = None
    if report_dir:
        abs_report_dir = str(Path(report_dir).resolve())
        Path(abs_report_dir).mkdir(parents=True, exist_ok=True)
        cwd = abs_report_dir
    cmd = [
        python_bin,
        "-m",
        "swebench.harness.run_evaluation",
        "--predictions_path", abs_predictions,
        "--max_workers", str(max_workers),
        "--run_id", run_id,
        "--dataset_name", dataset,
        "--split", split,
        "--cache_level", cache_level,
    ]
    if force_rebuild:
        cmd += ["--force_rebuild", "True"]
    if abs_report_dir:
        cmd += ["--report_dir", abs_report_dir]
    logger.info(
        "Running evaluation with %d workers on %s (run_id=%s, dataset=%s, split=%s, force=%s, cache_level=%s, force_rebuild=%s, python=%s, cwd=%s)",
        max_workers, abs_predictions, run_id, dataset, split, force, cache_level, force_rebuild, python_bin, cwd,
    )
    try:
        proc = subprocess.run(cmd, cwd=cwd, check=False)
        return proc.returncode
    except OSError as e:
        # WinError 193: resolved python is a POSIX ELF (WSL venv invoked
        # from Windows). Install swebench into the host-native venv.
        logger.error("Failed to execute the SWE-bench harness (%s).", e)
        return 127


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the SWE-bench Docker harness on a predictions JSONL. "
            "On Windows, invoke via WSL (`swebench` is POSIX-only)."
        )
    )
    parser.add_argument(
        "--predictions",
        default="evomas_predictions.jsonl",
        help="Path to the JSONL predictions file",
    )
    parser.add_argument("--split", choices=["dev", "test", "train"], default="dev")
    parser.add_argument(
        "--subset", choices=list(SUBSET_DATASETS), default="lite",
        help="SWE-bench subset to evaluate against (lite | full | verified)",
    )
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override run_id (default: evomas-<split>-<date>)",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory to write evaluation reports (default: harness default)",
    )
    parser.add_argument(
        "--no-force",
        dest="force",
        action="store_false",
        help=(
            "Disable forced re-evaluation. By default the script deletes any "
            "existing per-instance report.json under "
            "<report_dir>/logs/run_evaluation/<run_id>/ so SWE-bench doesn't "
            "skip the instance with 'already run' (run_evaluation.py:455). "
            "Pass --no-force to keep the harness default skip-on-cached "
            "behaviour."
        ),
    )
    parser.set_defaults(force=True)
    parser.add_argument(
        "--cache-level",
        choices=["none", "base", "env", "instance"],
        default="env",
        help=(
            "SWE-bench --cache_level pass-through. 'none' wipes every image "
            "(slowest, fully clean); 'env' (default) keeps the environment "
            "image but rebuilds the instance image so the new patch is "
            "always applied to a fresh container."
        ),
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help=(
            "Pass --force_rebuild True to the harness so every docker image "
            "(base, env, instance) is rebuilt from scratch. Use when an "
            "earlier eval left a corrupted image."
        ),
    )
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = args.run_id or f"evomas-{args.split}-{ts}"
    logger.info(
        "Running evaluation on %s/%s (run_id=%s)", args.subset, args.split, run_id,
    )
    rc = run_evaluation(
        args.predictions, run_id, args.split, args.max_workers,
        args.report_dir, args.subset,
        force=args.force,
        cache_level=args.cache_level,
        force_rebuild=args.force_rebuild,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
