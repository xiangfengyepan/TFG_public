"""EvoMas CLI — single `evomas <subcommand>` entry covering instance
generation, prediction, evaluation, dev servers, notebook export, and
Ollama conveniences. Each subcommand subprocesses a `scripts/` entry
point with extra args forwarded verbatim."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click
import typer
from typer.core import TyperGroup
from dotenv import load_dotenv

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Two .env files (matches the FastAPI server loader) so subprocesses
# inherit OLLAMA_BASE_URL, RESULTS_DIR, etc.
load_dotenv(REPO_ROOT / "evomas" / ".env", override=False)
load_dotenv(REPO_ROOT / "api" / ".env", override=False)

app = typer.Typer(
    no_args_is_help=True,
    help="EvoMas command-line interface - drives instance generation, "
         "prediction, evaluation, notebook export, dev servers, and the "
         "test runner.",
    add_completion=False,
)
class _OllamaPassthroughGroup(TyperGroup):
    """Forwards unrecognised `evomas ollama <args>` to the local
    `ollama` binary so `evomas ollama -- rm qwen3:8b` works without
    wrapping every verb."""

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            # Bare `evomas ollama` still falls through to no_args_is_help.
            if not args:
                raise
            forwarded = list(args)

            def _passthrough() -> None:
                raise typer.Exit(
                    subprocess.run(
                        ["ollama", *forwarded],
                        env=_ollama_host_env(),
                    ).returncode,
                )

            cmd = click.Command(name="<passthrough>", callback=_passthrough, params=[])
            # `[]` so Click doesn't re-parse args; we already have them.
            return cmd.name, cmd, []


ollama_app = typer.Typer(
    no_args_is_help=True,
    cls=_OllamaPassthroughGroup,
    help="Local LLM lifecycle. Subcommands target the Ollama server named "
         "by `OLLAMA_BASE_URL` in evomas/.env (default: localhost:11434)."
         "\n\nUse `evomas ollama -- <args>` to forward arbitrary args to "
         "the `ollama` binary, e.g. `evomas ollama -- rm qwen3:8b`.",
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
    """os.environ copy with `OLLAMA_HOST` derived from `OLLAMA_BASE_URL`
    (the Ollama CLI wants `host:port`, not the full URL)."""
    env = os.environ.copy()
    url = env.get("OLLAMA_BASE_URL", "").strip()
    if url:
        host = url.replace("http://", "").replace("https://", "").rstrip("/")
        env["OLLAMA_HOST"] = host
    return env


def _run_script(script_name: str, extra_args: list[str]) -> int:
    """Subprocess a `scripts/<name>.py` entry point."""
    script_path = REPO_ROOT / "scripts" / script_name
    if not script_path.is_file():
        typer.echo(f"script not found: {script_path}", err=True)
        return 1
    return subprocess.run(
        [sys.executable, str(script_path), *extra_args],
        cwd=REPO_ROOT,
    ).returncode


def _run_shell_script(script_stem: str, extra_args: list[str]) -> int:
    """Subprocess `scripts/<stem>.ps1` on Windows, `scripts/<stem>.sh`
    elsewhere. Both variants are kept in sync."""
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
        help="Disable GPU acceleration by exporting OLLAMA_NO_CUDA=1 before serving.",
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
_FORWARD_CTX = {"allow_extra_args": True, "ignore_unknown_options": True}


@run_app.command(
    "instances",
    context_settings=_FORWARD_CTX,
    help=(
        "Generate the SWE-bench instances JSONL. Pulls a slice of the "
        "HuggingFace dataset and writes it as JSONL for the prediction step. "
        "Pass --custom-repo + --custom-problem to append one synthetic "
        "custom-repo row instead of pulling from HuggingFace."
        "\n\nExample:  evomas run instances --subset lite --split dev --output swebench_instances.jsonl --limit 5"
        "\nExample:  evomas run instances --subset lite --split custom --output swebench_instances.jsonl --custom-repo owner/name --custom-problem \"calc returns difference\""
    ),
)
def run_instances(
    ctx: typer.Context,
    subset: str = typer.Option(
        ..., "--subset",
        help="SWE-bench subset to pull: lite | full | verified.",
    ),
    split: str = typer.Option(
        ..., "--split",
        help="Dataset split: dev | test | train.",
    ),
    output: str = typer.Option(
        ..., "--output",
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
        "Generate EvoMas predictions for the instances JSONL. Runs the "
        "configured LangGraph topology against each instance and emits "
        "one model_patch per line into the predictions JSONL."
        "\n\nExample:  evomas run prediction --instances swebench_instances.jsonl --output evomas_predictions.jsonl --config chain"
    ),
)
def run_prediction(
    ctx: typer.Context,
    instances: str = typer.Option(
        ..., "--instances",
        help="Path to the JSONL produced by `evomas run instances`.",
    ),
    output: str = typer.Option(
        ..., "--output",
        help="Output predictions JSONL.",
    ),
    config: str = typer.Option(
        ..., "--config",
        help=(
            "Config name (resolved against evomas/config/predefined/ then "
            "loaded/) or a path to a JSON file."
        ),
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit",
        help="Smoke-test: process only the first N instances.",
    ),
) -> None:
    forwarded: list[str] = [
        "--instances", instances, "--output", output, "--config", config,
    ]
    if limit is not None:
        forwarded += ["--limit", str(limit)]
    forwarded.extend(ctx.args)
    raise typer.Exit(_run_script("generate_evomas_predictions.py", forwarded))


@run_app.command(
    "evaluation",
    context_settings=_FORWARD_CTX,
    help=(
        "Run SWE-bench evaluation on a predictions JSONL."
        "\n\n  --local  (default) - runs the SWE-bench harness via Docker "
        "(one container per instance per worker; requires Docker Desktop)."
        "\n  --remote - submits to the swebench.com leaderboards via "
        "sb-cli (requires SWEBENCH_API_KEY)."
        "\n\nExample (local):   evomas run evaluation --predictions evomas_predictions.jsonl --subset lite --split dev"
        "\nExample (remote):  evomas run evaluation --remote --predictions evomas_predictions.jsonl --subset lite --split dev"
    ),
)
def run_evaluation(
    ctx: typer.Context,
    predictions: str = typer.Option(
        ..., "--predictions",
        help="Path to the predictions JSONL.",
    ),
    split: str = typer.Option(
        ..., "--split",
        help="Dataset split: dev | test | train. Remote only supports dev/test.",
    ),
    subset: str = typer.Option(
        ..., "--subset",
        help=(
            "SWE-bench subset. Local accepts lite | full | verified. "
            "Remote accepts lite | verified | multimodal (the hosted "
            "API has no 'full' subset)."
        ),
    ),
    max_workers: int = typer.Option(
        8, "--max-workers",
        help="Parallel harness workers (local only - ignored when --remote).",
    ),
    run_id: Optional[str] = typer.Option(
        None, "--run-id",
        help="Override the auto-generated `evomas-<split>-<timestamp>` run id.",
    ),
    report_dir: Optional[str] = typer.Option(
        None, "--report-dir",
        help="Where reports land. Default: `./sb-cli-reports` for --remote.",
    ),
    remote: bool = typer.Option(
        False, "--remote/--local",
        help="Run remotely via sb-cli (--remote) or locally via the Docker harness (--local, default).",
    ),
) -> None:
    if remote:
        # Remote only forwards common args; max-workers is local-only.
        forwarded: list[str] = [
            "--predictions", predictions, "--split", split, "--subset", subset,
        ]
        if run_id:
            forwarded += ["--run-id", run_id]
        if report_dir:
            forwarded += ["--output-dir", report_dir]
        forwarded.extend(ctx.args)
        raise typer.Exit(_run_script("run_swebench_evaluation_remote.py", forwarded))

    forwarded = [
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
    """Start the Angular frontend dev server.

    Example:  evomas web
    """
    raise typer.Exit(_run_shell_script("start_frontend", []))


@app.command()
def api() -> None:
    """Start the FastAPI backend.

    Example:  evomas api
    """
    raise typer.Exit(_run_shell_script("start_api", []))


# ─── apply (re-run pytest against a prediction's patch) ──────────────────────
@app.command(
    "apply",
    context_settings=_FORWARD_CTX,
    help=(
        "Apply a prediction's patch to its repo and run the project's "
        "tests. With --instance-id, only the matching row in both "
        "--predictions and --instances is processed."
        "\n\nExample:  evomas apply --predictions evomas_predictions.jsonl --instances swebench_instances.jsonl --instance-id sqlfluff__sqlfluff-1625"
        "\nExample:  evomas apply --predictions evomas_predictions.jsonl --instances swebench_instances.jsonl --instance-id custom-<owner>-<name>-<short-sha> --report-dir results/evaluations"
    ),
)
def apply(
    ctx: typer.Context,
    predictions: str = typer.Option(
        ..., "--predictions",
        help="Path to the JSONL produced by `evomas run prediction`.",
    ),
    instances: str = typer.Option(
        ..., "--instances",
        help="Path to the JSONL produced by `evomas run instances`.",
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


# ─── notebook export ─────────────────────────────────────────────────────────
@app.command(
    "notebook",
    help=(
        "Export a reproduce-this-run Jupyter notebook (.ipynb) for a "
        "prediction JSONL. Mirrors the Results page's 'Notebook' button. "
        "Best with UI-produced predictions -- they carry a config "
        "snapshot that fills the notebook's CONFIG cell."
        "\n\nExample:  evomas notebook --predictions results/predictions/prediction-<run-id>.jsonl"
        "\nExample:  evomas notebook --predictions results/predictions/prediction-<run-id>.jsonl --output ~/Downloads/reproduce.ipynb"
    ),
)
def notebook(
    predictions: str = typer.Option(
        ..., "--predictions",
        help="Path to the prediction JSONL (the file produced by "
             "`evomas run prediction` or the Inference page).",
    ),
    output: Optional[str] = typer.Option(
        None, "--output",
        help="Where to write the .ipynb. Defaults to "
             "`./<prediction-stem>.ipynb` in the current directory.",
    ),
) -> None:
    # Same builder the API endpoint uses — keeps CLI + UI byte-identical.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from api.routers.results import build_notebook_for_prediction
    pred_path = Path(predictions).resolve()
    try:
        run_id, nb = build_notebook_for_prediction(pred_path)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    out_path = Path(output) if output else Path.cwd() / f"{pred_path.stem}.ipynb"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    typer.echo(f"Wrote reproduce-this-run notebook for {run_id} -> {out_path}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
