"""Remote SWE-bench evaluation via `sb-cli`.

Submits a predictions JSONL to the hosted SWE-bench leaderboards
(https://www.swebench.com/sb-cli/) instead of running the Docker-based
harness locally. Use this when:

  - Docker / WSL isn't available on the host.
  - You're preparing a leaderboard submission and want the official
    grader (the local harness and the remote scorer differ on edge
    cases — only the remote result counts for the leaderboard).
  - You need the resolved/unresolved split scored against the test
    split that's not publicly available (only `swe-bench_lite` /
    `swe-bench_verified` / `swe-bench-m` test splits work; full SWE-bench
    has no test split on the hosted API).

Requirements:
  - `sb-cli` installed; this script prefers the venv at
    `<repo>/sb-cli/venv/bin/sb-cli` and falls back to whatever
    `sb-cli` is on PATH.
  - `SWEBENCH_API_KEY` env var set. Generate via
    `sb-cli gen-api-key your@email.com` and verify with the code
    you receive by email.

The script converts the project's local JSONL (one prediction per
line) into the JSON-list format the hosted API consumes, submits the
batch, and (by default) waits for the run to be scored + downloads
the report.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
SB_CLI_VENV = REPO_ROOT / "sb-cli" / "venv"

# Map evomas's subset names (the same vocabulary the local script uses)
# to sb-cli's dataset slugs. The hosted API doesn't carry the full
# SWE-bench set, so `full` is intentionally absent — we fail loudly
# instead of silently picking a different subset.
SUBSET_TO_SB_DATASET: dict[str, str] = {
    "lite":       "swe-bench_lite",
    "verified":   "swe-bench_verified",
    "multimodal": "swe-bench-m",
}


def _sb_cli_executable() -> str:
    """Locate the sb-cli entry-point.

    Resolution order (each step is a fallback for the previous):
      1. `shutil.which('sb-cli')` — picks up sb-cli installed into the
         currently-active virtualenv (e.g. the user did
         `pip install sb-cli` in their evomas venv) or on PATH. This is
         the safest because the binary is guaranteed to match the host
         OS — on Windows it's `Scripts\\sb-cli.exe`, on POSIX it's
         `bin/sb-cli`.
      2. The Windows entry-point under `<repo>/sb-cli/venv/Scripts/`.
      3. The POSIX entry-point under `<repo>/sb-cli/venv/bin/`. This
         only works when the script runs in the same OS that built the
         venv — a Linux-layout venv (the common case after cloning
         sb-cli and running its setup under WSL) cannot be executed
         from Windows-side Python and will raise WinError 193.
      4. Bare `'sb-cli'` so subprocess.run gets a usable string even
         if everything else fails (and surfaces a clear FileNotFoundError)."""
    on_path = shutil.which("sb-cli")
    if on_path:
        return on_path
    win_exe = SB_CLI_VENV / "Scripts" / "sb-cli.exe"
    if win_exe.exists():
        return str(win_exe)
    posix_bin = SB_CLI_VENV / "bin" / "sb-cli"
    if posix_bin.exists() and os.name != "nt":
        # Skip on Windows: the bin/sb-cli file is a POSIX shebang script
        # and CreateProcess won't run it (WinError 193).
        return str(posix_bin)
    return "sb-cli"


def jsonl_to_json_list(predictions_jsonl: Path, out_json: Path) -> int:
    """Convert one-prediction-per-line JSONL to the JSON-list shape the
    hosted API accepts (see sb-cli README "Predictions File Format").
    Each record must already carry `instance_id`, `model_patch`, and
    `model_name_or_path` — that's the schema the local harness uses
    too, so no field rewriting is needed."""
    records: list[dict] = []
    with predictions_jsonl.open(encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"{predictions_jsonl}:{ln} is not valid JSON: {e}") from e
            if not isinstance(rec, dict) or "instance_id" not in rec:
                raise ValueError(
                    f"{predictions_jsonl}:{ln} missing required 'instance_id' field"
                )
            records.append(rec)
    out_json.write_text(json.dumps(records), encoding="utf-8")
    return len(records)


def run_remote_evaluation(
    predictions_path: str,
    run_id: str,
    subset: str,
    split: str,
    output_dir: str | None = None,
    overwrite: bool = False,
    gen_report: bool = True,
    instance_ids: str | None = None,
) -> int:
    pred_path = Path(predictions_path)
    if not pred_path.is_file():
        logger.error("predictions file not found: %s", pred_path)
        return 2
    if pred_path.stat().st_size == 0:
        logger.error(
            "predictions file is empty (0 bytes): %s\n"
            "Re-run `evomas run prediction --instances <instances.jsonl> "
            "--output %s --config <name>` to produce predictions before "
            "submitting.",
            pred_path, pred_path.name,
        )
        return 2

    if not os.environ.get("SWEBENCH_API_KEY"):
        logger.error(
            "SWEBENCH_API_KEY is not set. Generate one with "
            "`sb-cli gen-api-key your@email` and export it before running."
        )
        return 2

    dataset = SUBSET_TO_SB_DATASET.get(subset)
    if dataset is None:
        logger.error(
            "subset '%s' has no sb-cli equivalent. Pick one of: %s.",
            subset, sorted(SUBSET_TO_SB_DATASET),
        )
        return 2

    # sb-cli's `submit` reads a JSON file, not JSONL. Convert into a
    # temp file we delete on exit so the working tree stays clean
    # regardless of submission outcome. `mkstemp` returns (fd, path) AND
    # leaves the OS-level file descriptor open — on Windows that turns
    # the later `unlink()` into ERROR_SHARING_VIOLATION (WinError 32),
    # because the file is "in use" by our own process. Close the fd
    # immediately; we only need the path so jsonl_to_json_list can
    # reopen it in text mode.
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="evomas-preds-")
    os.close(fd)
    tmp_json = Path(tmp_path)
    try:
        n = jsonl_to_json_list(pred_path, tmp_json)
        if n == 0:
            # File has bytes but every line stripped to empty — malformed
            # JSONL (e.g. all blank lines).
            logger.error(
                "no JSON records in %s (file has %d bytes but every line "
                "stripped to empty). Re-generate predictions and try again.",
                pred_path, pred_path.stat().st_size,
            )
            return 2
        logger.info(
            "Converted %d predictions from %s → %s (sb-cli JSON list).",
            n, pred_path.name, tmp_json.name,
        )

        sb_cli = _sb_cli_executable()
        cmd: list[str] = [
            sb_cli, "submit", dataset, split,
            "--predictions_path", str(tmp_json),
            "--run_id", run_id,
            "--gen_report", "1" if gen_report else "0",
            "--overwrite", "1" if overwrite else "0",
        ]
        if output_dir:
            cmd += ["--output_dir", output_dir]
        if instance_ids:
            cmd += ["--instance_ids", instance_ids]

        logger.info(
            "Submitting to sb-cli: subset=%s split=%s run_id=%s instances=%d "
            "(gen_report=%s, overwrite=%s)",
            dataset, split, run_id, n, gen_report, overwrite,
        )
        try:
            result = subprocess.run(cmd)
        except OSError as e:
            # WinError 193 = "%1 is not a valid Win32 application". Fires
            # when sb-cli resolved to a POSIX shebang script (the case if
            # the user cloned sb-cli/ and built its venv under WSL but is
            # invoking from Windows-side Python). The fix is to install
            # sb-cli into the host-native venv — a one-liner — so the
            # Scripts/sb-cli.exe entry-point exists.
            logger.error(
                "Failed to execute sb-cli (%s). Install sb-cli into the "
                "active evomas venv so a native Windows entry-point "
                "exists:\n  pip install sb-cli",
                e,
            )
            return 2
        if result.returncode != 0:
            logger.error("sb-cli submit returned non-zero exit code %d", result.returncode)
        return result.returncode
    finally:
        tmp_json.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Submit EvoMas predictions to the hosted SWE-bench leaderboards "
            "via sb-cli, as an alternative to the local Docker harness."
        )
    )
    parser.add_argument(
        "--predictions",
        default="evomas_predictions.jsonl",
        help="Path to the JSONL predictions file.",
    )
    parser.add_argument(
        "--subset", choices=list(SUBSET_TO_SB_DATASET), default="lite",
        help="SWE-bench subset (lite | verified | multimodal). 'full' has "
             "no hosted API split.",
    )
    parser.add_argument(
        "--split", choices=["dev", "test"], default="dev",
        help="Dataset split. 'test' is only available on lite / verified / "
             "multimodal subsets.",
    )
    parser.add_argument(
        "--run-id", default=None,
        help="Submission run-id (default: evomas-<split>-<timestamp>). "
             "Must be unique per (subset, split) unless --overwrite is set.",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Where sb-cli writes the downloaded report (default: "
             "sb-cli-reports in the cwd).",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite an existing run-id's report on the server.",
    )
    parser.add_argument(
        "--no-gen-report", dest="gen_report", action="store_false",
        help="Skip the report-fetch step after submission — useful when "
             "submitting in batches and downloading reports later.",
    )
    parser.add_argument(
        "--instance-ids", default=None,
        help="Comma-separated subset of instance_ids to submit (default: all).",
    )
    parser.set_defaults(gen_report=True)
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = args.run_id or f"evomas-{args.split}-{ts}"
    logger.info("Remote evaluation on %s/%s (run_id=%s)", args.subset, args.split, run_id)
    return run_remote_evaluation(
        args.predictions, run_id, args.subset, args.split,
        args.output_dir, args.overwrite, args.gen_report, args.instance_ids,
    )


if __name__ == "__main__":
    sys.exit(main())
