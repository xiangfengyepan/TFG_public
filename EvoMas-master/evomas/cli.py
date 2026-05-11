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
import subprocess
import sys
from pathlib import Path

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


def _run_powershell(ps1_name: str, extra_args: list[str]) -> int:
    """Subprocess one of the `scripts/` PowerShell entry points. Windows-only
    by design - the project targets Windows and the start_*.ps1 scripts use
    Windows paths and PowerShell built-ins."""
    ps1_path = REPO_ROOT / "scripts" / ps1_name
    if not ps1_path.is_file():
        typer.echo(f"script not found: {ps1_path}", err=True)
        return 1
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(ps1_path), *extra_args],
        cwd=REPO_ROOT,
    ).returncode


# ─── ollama subcommands ───────────────────────────────────────────────────────
@ollama_app.command("pull")
def ollama_pull(
    model: str = typer.Argument(..., help="Model tag, e.g. `qwen3.5:9b`."),
) -> None:
    """Pull a model on the configured Ollama server."""
    raise typer.Exit(subprocess.run(["ollama", "pull", model], env=_ollama_host_env()).returncode)


@ollama_app.command("list")
def ollama_list() -> None:
    """List models available on the configured Ollama server."""
    raise typer.Exit(subprocess.run(["ollama", "list"], env=_ollama_host_env()).returncode)


@ollama_app.command("serve")
def ollama_serve(
    cpu_only: bool = typer.Option(
        False, "--cpu-only",
        help="Disable GPU acceleration by exporting OLLAMA_NO_CUDA=1 before serving "
             "- mirrors the legacy `ollama_cpu_only.ps1` behaviour.",
    ),
) -> None:
    """Start the Ollama server bound to the configured host."""
    env = _ollama_host_env()
    if cpu_only:
        env["OLLAMA_NO_CUDA"] = "1"
    raise typer.Exit(subprocess.run(["ollama", "serve"], env=env).returncode)


# ─── run subcommands ──────────────────────────────────────────────────────────
# Each command forwards every extra arg verbatim to the underlying script so
# adding a new flag upstream doesn't need a corresponding CLI patch.
_FORWARD_CTX = {"allow_extra_args": True, "ignore_unknown_options": True}


@run_app.command("instances", context_settings=_FORWARD_CTX)
def run_instances(ctx: typer.Context) -> None:
    """Generate the SWE-bench instances JSONL.

    Wraps `scripts/generate_swebench_instances.py`. Pulls a slice of the
    HuggingFace dataset and writes it as JSONL for the prediction step.

    Arguments (all optional, forwarded verbatim):
      --subset {lite,full,verified}   SWE-bench subset to pull. (default: lite)
      --split  {dev,test}             Dataset split.            (default: dev)
      --output PATH                   Output JSONL path.        (default: swebench_instances.jsonl)
      --limit  N                      Smoke-test: keep only the first N instances.
      --append                        Keep existing lines for other (subset, split) pairs in the output file.

    Example:
        evomas run instances --subset lite --split dev --limit 5
    """
    raise typer.Exit(_run_script("generate_swebench_instances.py", ctx.args))


@run_app.command("prediction", context_settings=_FORWARD_CTX)
def run_prediction(ctx: typer.Context) -> None:
    """Generate EvoMas predictions for the instances JSONL.

    Wraps `scripts/generate_evomas_predictions.py`. Runs the configured
    LangGraph topology against each instance and emits one model_patch
    per line into the predictions JSONL.

    Arguments (all optional, forwarded verbatim):
      --instances PATH    Path to the JSONL produced by `evomas run instances`.
                          (default: swebench_instances.jsonl)
      --output    PATH    Output predictions JSONL.
                          (default: evomas_predictions.jsonl)
      --config    NAME    Unified config to run. Either a stem resolved against
                          `evomas/config/<stem>.json` (e.g. `evo-star`, `star`,
                          `openhands`) or an explicit path to a config JSON.
                          (default: "" -- falls through to the topology's own default)
      --limit     N       Smoke-test: process only the first N instances.

    Example:
        evomas run prediction --instances swebench_instances.jsonl --config evo-star
    """
    raise typer.Exit(_run_script("generate_evomas_predictions.py", ctx.args))


@run_app.command("evaluation", context_settings=_FORWARD_CTX)
def run_evaluation(ctx: typer.Context) -> None:
    """Run SWE-bench evaluation on a predictions JSONL.

    Wraps `scripts/run_swebench_evaluation.py`. Drives the upstream
    SWE-bench harness via Docker; one container per instance per worker.
    Run from WSL with the SWE-bench venv active.

    Arguments (all optional, forwarded verbatim):
      --predictions PATH                Path to the predictions JSONL.
                                        (default: evomas_predictions.jsonl)
      --split   {dev,test,train}        Dataset split.                  (default: dev)
      --subset  {lite,full,verified}    SWE-bench subset to score against. (default: lite)
      --max-workers N                   Parallel harness workers.       (default: 8)
      --run-id  NAME                    Override the auto-generated `evomas-<split>-<date>` run id.
      --report-dir PATH                 Where the harness writes reports. (default: harness default)

    Requires Docker Desktop.
    """
    raise typer.Exit(_run_script("run_swebench_evaluation.py", ctx.args))


# ─── server entry points ──────────────────────────────────────────────────────
@app.command()
def web() -> None:
    """Start the Angular frontend dev server (`start_frontend.ps1`)."""
    raise typer.Exit(_run_powershell("start_frontend.ps1", []))


@app.command()
def api() -> None:
    """Start the FastAPI backend (`start_api.ps1`)."""
    raise typer.Exit(_run_powershell("start_api.ps1", []))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
