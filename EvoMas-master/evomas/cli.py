"""EvoMas command-line interface.

Wraps every entry point listed in TODO.md's `## CLI` section so users can
drive instance generation, prediction, evaluation, the FastAPI server, the
Angular dev server, and a few Ollama-side conveniences from a single
`evomas <subcommand>` command.

Installed via `pip install -e .` from the repo root; the `[project.scripts]`
table in `pyproject.toml` registers `evomas` against `evomas.cli:main`. The
underlying generate_*/run_* scripts and start_*.ps1 scripts are invoked as
subprocesses with all extra args forwarded verbatim, so adding a new flag
upstream doesn't require touching this CLI.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Load the project's two .env files (evomas/ first, then api/ for overrides)
# so subprocesses inherit OLLAMA_BASE_URL, WANDB_API_KEY, RESULTS_DIR, etc.
# `override=False` matches the FastAPI server's loader and lets a shell
# export win over the file value.
load_dotenv(REPO_ROOT / "evomas" / ".env", override=False)
load_dotenv(REPO_ROOT / "api" / ".env", override=False)

app = typer.Typer(
    no_args_is_help=True,
    help="EvoMas command-line interface - drives instance generation, "
         "prediction, evaluation, and the front-/back-end dev servers.",
    add_completion=False,
)
ollama_app = typer.Typer(
    no_args_is_help=True,
    help="Local LLM lifecycle. All subcommands target the Ollama server "
         "named by `OLLAMA_BASE_URL` in evomas/.env (default: localhost:11434).",
    add_completion=False,
)
run_app = typer.Typer(
    no_args_is_help=True,
    help="Run the SWE-bench pipeline: generate instances -> predict -> evaluate.",
    add_completion=False,
)
app.add_typer(ollama_app, name="ollama")
app.add_typer(run_app, name="run")


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _ollama_host_env() -> dict[str, str]:
    """Return an os.environ copy with `OLLAMA_HOST` set from `OLLAMA_BASE_URL`.

    The Ollama CLI honors `OLLAMA_HOST` for remote targeting; the project's
    .env exposes the URL form (`http://host:port`) so we strip the scheme
    here before handing it to the CLI.
    """
    env = os.environ.copy()
    url = env.get("OLLAMA_BASE_URL", "").strip()
    if url:
        host = url.replace("http://", "").replace("https://", "").rstrip("/")
        env["OLLAMA_HOST"] = host
    return env


def _run_script(script_name: str, extra_args: list[str]) -> int:
    """Subprocess one of the `scripts/` entry points, forwarding extra args."""
    script_path = REPO_ROOT / "scripts" / script_name
    if not script_path.is_file():
        typer.echo(f"script not found: {script_path}", err=True)
        return 1
    return subprocess.run(
        [sys.executable, str(script_path), *extra_args],
        cwd=REPO_ROOT,
    ).returncode


def _run_shell_script(script_stem: str, extra_args: list[str]) -> int:
    """Subprocess a `scripts/` entry point picking the right interpreter
    for the current OS: `.ps1` via PowerShell on Windows, `.sh` via bash
    on Linux/macOS. The two variants are kept in sync (same args, same
    behaviour). `script_stem` is the filename WITHOUT extension, e.g.
    ``"start_api"``."""
    if platform.system() == "Windows":
        script_path = REPO_ROOT / "scripts" / f"{script_stem}.ps1"
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(script_path), *extra_args]
    else:
        script_path = REPO_ROOT / "scripts" / f"{script_stem}.sh"
        cmd = ["bash", str(script_path), *extra_args]
    if not script_path.is_file():
        typer.echo(f"script not found: {script_path}", err=True)
        return 1
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


# ─── ollama subcommands ───────────────────────────────────────────────────────
@ollama_app.command("pull")
def ollama_pull(
    model: str = typer.Argument(..., help="Model tag, e.g. `qwen3.5:9b`."),
) -> None:
    """Pull a model on the configured Ollama server.

    Example:  evomas ollama pull qwen3.5:9b
    """
    raise typer.Exit(subprocess.run(["ollama", "pull", model], env=_ollama_host_env()).returncode)


@ollama_app.command("list")
def ollama_list() -> None:
    """List models available on the configured Ollama server.

    Example:  evomas ollama list
    """
    raise typer.Exit(subprocess.run(["ollama", "list"], env=_ollama_host_env()).returncode)


@ollama_app.command("serve")
def ollama_serve(
    cpu_only: bool = typer.Option(
        False, "--cpu-only",
        help="Disable GPU acceleration by exporting OLLAMA_NO_CUDA=1 before serving "
             "- mirrors the legacy `ollama_cpu_only.ps1` behaviour.",
    ),
) -> None:
    """Start the Ollama server bound to the configured host.

    Example:  evomas ollama serve --cpu-only
    """
    env = _ollama_host_env()
    if cpu_only:
        env["OLLAMA_NO_CUDA"] = "1"
    raise typer.Exit(subprocess.run(["ollama", "serve"], env=env).returncode)


# ─── run subcommands ──────────────────────────────────────────────────────────
# Each command forwards every extra arg verbatim to the underlying script so
# adding a new flag upstream doesn't need a corresponding CLI patch.
_FORWARD_CTX = {"allow_extra_args": True, "ignore_unknown_options": True}


@run_app.command(
    "instances",
    context_settings=_FORWARD_CTX,
    help=(
        "Generate the SWE-bench instances JSONL. Wraps "
        "scripts/generate_swebench_instances.py; pulls a slice of the "
        "HuggingFace dataset and writes it as JSONL for the prediction step."
        " Pass --custom-repo + --custom-problem to append one synthetic "
        "custom-repo row instead of pulling from HuggingFace."
        "\n\nExample:  evomas run instances --subset lite --split dev --limit 5"
        "\nExample:  evomas run instances --custom-repo owner/name --custom-problem \"calc returns difference\""
    ),
)
def run_instances(
    ctx: typer.Context,
    subset: str = typer.Option(
        "lite", "--subset",
        help="SWE-bench subset to pull: lite | full | verified.",
    ),
    split: str = typer.Option(
        "dev", "--split",
        help="Dataset split: dev | test.",
    ),
    output: str = typer.Option(
        "swebench_instances.jsonl", "--output",
        help="Output JSONL path.",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit",
        help="Smoke-test: keep only the first N instances.",
    ),
    append: bool = typer.Option(
        False, "--append",
        help="Keep existing lines for other (subset, split) pairs in the output file.",
    ),
    custom_repo: Optional[str] = typer.Option(
        None, "--custom-repo",
        help=(
            "GitHub 'owner/name' or URL. Switches to custom-repo mode "
            "(skips the HuggingFace pull and appends one synthetic row "
            "with subset='custom'/split='custom')."
        ),
    ),
    custom_problem: Optional[str] = typer.Option(
        None, "--custom-problem",
        help="Problem statement for the custom row. Required with --custom-repo.",
    ),
    custom_base_commit: Optional[str] = typer.Option(
        None, "--custom-base-commit",
        help="Base commit SHA. Defaults to the remote HEAD via `git ls-remote`.",
    ),
    custom_instance_id: Optional[str] = typer.Option(
        None, "--custom-instance-id",
        help="Override the auto-generated `custom-<owner>-<name>-<sha[:7]>` id.",
    ),
) -> None:
    forwarded: list[str] = [
        "--subset", subset, "--split", split, "--output", output,
    ]
    if limit is not None:
        forwarded += ["--limit", str(limit)]
    if append:
        forwarded.append("--append")
    if custom_repo:
        forwarded += ["--custom-repo", custom_repo]
    if custom_problem:
        forwarded += ["--custom-problem", custom_problem]
    if custom_base_commit:
        forwarded += ["--custom-base-commit", custom_base_commit]
    if custom_instance_id:
        forwarded += ["--custom-instance-id", custom_instance_id]
    forwarded.extend(ctx.args)
    raise typer.Exit(_run_script("generate_swebench_instances.py", forwarded))


@run_app.command(
    "prediction",
    context_settings=_FORWARD_CTX,
    help=(
        "Generate EvoMas predictions for the instances JSONL. Wraps "
        "scripts/generate_evomas_predictions.py; runs the configured "
        "LangGraph topology against each instance and emits one "
        "model_patch per line into the predictions JSONL."
        "\n\nExample:  evomas run prediction --instances swebench_instances.jsonl --config chain"
    ),
)
def run_prediction(
    ctx: typer.Context,
    instances: str = typer.Option(
        "swebench_instances.jsonl", "--instances",
        help="Path to the JSONL produced by `evomas run instances`.",
    ),
    output: str = typer.Option(
        "evomas_predictions.jsonl", "--output",
        help="Output predictions JSONL.",
    ),
    config: str = typer.Option(
        "", "--config",
        help=(
            "Unified config to run. Either a stem resolved against "
            "evomas/config/<stem>.json (e.g. 'chain', 'openhands') or an "
            "explicit path to a config JSON. Empty = topology default."
        ),
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit",
        help="Smoke-test: process only the first N instances.",
    ),
) -> None:
    forwarded: list[str] = [
        "--instances", instances, "--output", output,
    ]
    if config:
        forwarded += ["--config", config]
    if limit is not None:
        forwarded += ["--limit", str(limit)]
    forwarded.extend(ctx.args)
    raise typer.Exit(_run_script("generate_evomas_predictions.py", forwarded))


@run_app.command(
    "evaluation",
    context_settings=_FORWARD_CTX,
    help=(
        "Run SWE-bench evaluation on a predictions JSONL. Wraps "
        "scripts/run_swebench_evaluation.py; drives the upstream "
        "SWE-bench harness via Docker (one container per instance per "
        "worker). Run from WSL with the SWE-bench venv active. "
        "Requires Docker Desktop."
        "\n\nExample:  evomas run evaluation --predictions evomas_predictions.jsonl --subset lite --split dev"
    ),
)
def run_evaluation(
    ctx: typer.Context,
    predictions: str = typer.Option(
        "evomas_predictions.jsonl", "--predictions",
        help="Path to the predictions JSONL.",
    ),
    split: str = typer.Option(
        "dev", "--split",
        help="Dataset split: dev | test | train.",
    ),
    subset: str = typer.Option(
        "lite", "--subset",
        help="SWE-bench subset to score against: lite | full | verified.",
    ),
    max_workers: int = typer.Option(
        8, "--max-workers",
        help="Parallel harness workers.",
    ),
    run_id: Optional[str] = typer.Option(
        None, "--run-id",
        help="Override the auto-generated `evomas-<split>-<date>` run id.",
    ),
    report_dir: Optional[str] = typer.Option(
        None, "--report-dir",
        help="Where the harness writes reports (default: harness default).",
    ),
) -> None:
    forwarded: list[str] = [
        "--predictions", predictions, "--split", split, "--subset", subset,
        "--max-workers", str(max_workers),
    ]
    if run_id:
        forwarded += ["--run-id", run_id]
    if report_dir:
        forwarded += ["--report-dir", report_dir]
    forwarded.extend(ctx.args)
    raise typer.Exit(_run_script("run_swebench_evaluation.py", forwarded))


# ─── server entry points ──────────────────────────────────────────────────────
@app.command()
def web() -> None:
    """Start the Angular frontend dev server (scripts/start_frontend.{ps1,sh}).

    Example:  evomas web
    """
    raise typer.Exit(_run_shell_script("start_frontend", []))


@app.command()
def api() -> None:
    """Start the FastAPI backend (scripts/start_api.{ps1,sh}).

    Example:  evomas api
    """
    raise typer.Exit(_run_shell_script("start_api", []))


# ─── apply (re-run pytest against a prediction's patch) ──────────────────────
@app.command(
    "apply",
    context_settings=_FORWARD_CTX,
    help=(
        "Apply a prediction's patch to its repo and run the project's tests. "
        "Wraps scripts/apply_and_test.py. With --instance-id, only the matching "
        "row in both --predictions and --instances is processed."
        "\n\nExample:  evomas apply --predictions evomas_predictions.jsonl --instance-id sqlfluff__sqlfluff-1625"
        "\nExample:  evomas apply --instance-id custom-evomas-buggy-1 --report-dir results/evaluations"
    ),
)
def apply(
    ctx: typer.Context,
    predictions: str = typer.Option(
        "evomas_predictions.jsonl", "--predictions",
        help="Path to the predictions JSONL.",
    ),
    instances: str = typer.Option(
        "swebench_instances.jsonl", "--instances",
        help="Path to the instances metadata JSONL.",
    ),
    instance_id: Optional[str] = typer.Option(
        None, "--instance-id",
        help="When set, narrow the apply+test loop to this single instance_id.",
    ),
    keep: bool = typer.Option(
        False, "--keep",
        help="Keep the patch applied (don't reset workspace after testing).",
    ),
    report_dir: Optional[str] = typer.Option(
        None, "--report-dir",
        help="When set, write SWE-bench-compatible reports under this directory.",
    ),
    run_id: Optional[str] = typer.Option(
        None, "--run-id",
        help="Override the auto-generated `apply-and-test-<ts>` run id.",
    ),
    model: Optional[str] = typer.Option(
        None, "--model",
        help="Model name used in the report path. Default: 'evomas-custom'.",
    ),
) -> None:
    forwarded: list[str] = ["--predictions", predictions, "--instances", instances]
    if instance_id:
        forwarded += ["--instance-id", instance_id]
    if keep:
        forwarded.append("--keep")
    if report_dir:
        forwarded += ["--report-dir", report_dir]
    if run_id:
        forwarded += ["--run-id", run_id]
    if model:
        forwarded += ["--model", model]
    forwarded.extend(ctx.args)
    raise typer.Exit(_run_script("apply_and_test.py", forwarded))


# ─── test runner ──────────────────────────────────────────────────────────────
@app.command(
    "test",
    context_settings=_FORWARD_CTX,
    help=(
        "Run pytest (backend) and ng test (frontend). Extra args after `--` "
        "are forwarded verbatim to the inner runner."
        "\n\nExample:  evomas test --backend-only -- -k apply_description_fix"
        "\nExample:  evomas test --frontend-only --integration -- --include \"src/integration/**\""
    ),
)
def test(
    ctx: typer.Context,
    backend_only: bool = typer.Option(
        False, "--backend-only",
        help="Skip ng test; forward extras to pytest only.",
    ),
    frontend_only: bool = typer.Option(
        False, "--frontend-only",
        help="Skip pytest; forward extras to ng test only.",
    ),
    integration: bool = typer.Option(
        False, "--integration",
        help="Set EVOMAS_RUN_INTEGRATION=1 before running.",
    ),
) -> None:
    if backend_only and frontend_only:
        typer.echo("Cannot use --backend-only and --frontend-only together.", err=True)
        raise typer.Exit(2)
    forwarded: list[str] = []
    if backend_only:
        forwarded.append("--backend-only")
    if frontend_only:
        forwarded.append("--frontend-only")
    if integration:
        forwarded.append("--integration")
    forwarded.extend(ctx.args)
    raise typer.Exit(_run_script("run_tests.py", forwarded))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
