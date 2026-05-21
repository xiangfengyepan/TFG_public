"""Unit tests for the `evomas` CLI surface (`evomas/cli.py`).

What's covered for every subcommand:

  * `--help` renders (catches accidental import-time breakage).
  * Missing required options produce a typer "Missing option" error.
  * Optional / boolean flags forward correctly to the underlying script.

The downstream scripts and the actual subprocesses are NEVER executed —
we monkeypatch `_run_script` / `_run_shell_script` / `subprocess.run`
in the `evomas.cli` namespace and assert on the captured args. The CLI's
job is to forward arguments correctly; the scripts have their own tests.
"""

from __future__ import annotations

from typing import Callable

import pytest
import typer
from typer.testing import CliRunner

from evomas import cli as cli_mod

# ─── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    """Typer CliRunner. Recent typer/click merge stderr into stdout, so
    `_missing_option` inspects `result.output` rather than `result.stderr`."""
    return CliRunner()


@pytest.fixture
def stub_runners(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Replace `_run_script` and `_run_shell_script` in `evomas.cli` with
    capturing stubs. Returns a dict each test can assert on:

        captured["script"][-1] == ("instances.py", ["--subset", "lite", ...])
        captured["shell"][-1]  == ("start_frontend", [])

    Both stubs return 0 so the CLI exits cleanly (typer reads the exit
    code via `typer.Exit(...)`)."""
    captured: dict[str, list] = {"script": [], "shell": []}

    def fake_run_script(name: str, args: list[str]) -> int:
        captured["script"].append((name, args))
        return 0

    def fake_run_shell(name: str, args: list[str]) -> int:
        captured["shell"].append((name, args))
        return 0

    monkeypatch.setattr(cli_mod, "_run_script", fake_run_script)
    monkeypatch.setattr(cli_mod, "_run_shell_script", fake_run_shell)
    return captured


@pytest.fixture
def stub_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replace `subprocess.run` in the `evomas.cli` namespace so the
    ollama subcommands don't actually shell out to the `ollama` binary.
    Returns a list of (argv, env) tuples populated on each call."""
    calls: list[tuple] = []

    class _FakeCompleted:
        returncode = 0

    def fake_run(cmd: list[str], env: dict | None = None, **_kw) -> _FakeCompleted:
        calls.append((cmd, env))
        return _FakeCompleted()

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    return calls


# ─── helpers ──────────────────────────────────────────────────────────────────


def _invoke(runner: CliRunner, args: list[str]):
    """Wrapper that asserts the CLI didn't crash with an exception
    (typer's CliRunner swallows them by default but surfaces via
    `result.exception`)."""
    result = runner.invoke(cli_mod.app, args, catch_exceptions=False)
    return result


def _missing_option(result, name: str) -> bool:
    """True if typer reported `Missing option '<name>'` in the runner's
    combined output stream."""
    return f"Missing option '{name}'" in (result.output or "")


def _last_forward(captured: dict[str, list], key: str = "script") -> tuple[str, list[str]]:
    assert captured[key], f"no {key} call captured"
    return captured[key][-1]


# ─── top-level: help, version-ish smoke ───────────────────────────────────────


def test_top_level_help_renders(runner: CliRunner) -> None:
    """`evomas --help` must not raise and must list the registered
    sub-apps + commands."""
    result = _invoke(runner, ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    assert "run" in out
    assert "ollama" in out
    assert "apply" in out
    assert "test" in out
    assert "web" in out
    assert "api" in out


@pytest.mark.parametrize("subcmd", [
    ["ollama", "--help"],
    ["run", "--help"],
    ["run", "instances", "--help"],
    ["run", "prediction", "--help"],
    ["run", "evaluation", "--help"],
    ["apply", "--help"],
    ["test", "--help"],
])
def test_every_help_renders(runner: CliRunner, subcmd: list[str]) -> None:
    result = _invoke(runner, subcmd)
    assert result.exit_code == 0, f"help failed for {subcmd}: {result.stdout}"


# ─── ollama subcommands ───────────────────────────────────────────────────────


def test_ollama_pull_invokes_ollama_binary(
    runner: CliRunner, stub_subprocess: list[tuple],
) -> None:
    """`evomas ollama pull <model>` calls `ollama pull <model>`."""
    result = _invoke(runner, ["ollama", "pull", "qwen3.5:9b"])
    assert result.exit_code == 0
    assert stub_subprocess, "subprocess.run was not called"
    cmd, _env = stub_subprocess[-1]
    assert cmd == ["ollama", "pull", "qwen3.5:9b"]


def test_ollama_pull_requires_model_argument(runner: CliRunner) -> None:
    """`ollama pull` with no model is an error (positional arg required)."""
    result = _invoke(runner, ["ollama", "pull"])
    assert result.exit_code != 0


def test_ollama_list_invokes_ollama_binary(
    runner: CliRunner, stub_subprocess: list[tuple],
) -> None:
    result = _invoke(runner, ["ollama", "list"])
    assert result.exit_code == 0
    cmd, _env = stub_subprocess[-1]
    assert cmd == ["ollama", "list"]


def test_ollama_serve_default(
    runner: CliRunner, stub_subprocess: list[tuple],
) -> None:
    """Without `--cpu-only`, the env passed to `ollama serve` must NOT
    carry `OLLAMA_NO_CUDA`."""
    result = _invoke(runner, ["ollama", "serve"])
    assert result.exit_code == 0
    cmd, env = stub_subprocess[-1]
    assert cmd == ["ollama", "serve"]
    assert env is None or "OLLAMA_NO_CUDA" not in env


def test_ollama_serve_cpu_only_sets_env(
    runner: CliRunner, stub_subprocess: list[tuple],
) -> None:
    """With `--cpu-only`, the env passed to `ollama serve` carries
    `OLLAMA_NO_CUDA=1`."""
    result = _invoke(runner, ["ollama", "serve", "--cpu-only"])
    assert result.exit_code == 0
    cmd, env = stub_subprocess[-1]
    assert cmd == ["ollama", "serve"]
    assert env is not None and env.get("OLLAMA_NO_CUDA") == "1"


def test_ollama_passthrough_forwards_args_after_double_dash(
    runner: CliRunner, stub_subprocess: list[tuple],
) -> None:
    """`evomas ollama -- rm qwen3:8b` should forward `rm qwen3:8b` to the
    `ollama` binary. The `--` separator stops typer/click from
    interpreting `rm` as an unknown subcommand and routes the trailing
    args through the group-level callback instead."""
    result = _invoke(runner, ["ollama", "--", "rm", "qwen3:8b"])
    assert result.exit_code == 0
    cmd, _env = stub_subprocess[-1]
    assert cmd == ["ollama", "rm", "qwen3:8b"]


def test_ollama_passthrough_forwards_arbitrary_subcommand(
    runner: CliRunner, stub_subprocess: list[tuple],
) -> None:
    """Pass-through works for any ollama verb, not just `rm` — e.g.
    `show` or `ps` (which evomas doesn't wrap explicitly). Verifies
    the callback is genuinely generic."""
    result = _invoke(runner, ["ollama", "--", "show", "qwen3:8b"])
    assert result.exit_code == 0
    cmd, _env = stub_subprocess[-1]
    assert cmd == ["ollama", "show", "qwen3:8b"]


# ─── run instances ────────────────────────────────────────────────────────────


def test_run_instances_requires_subset(runner: CliRunner) -> None:
    result = _invoke(runner, ["run", "instances"])
    assert result.exit_code != 0
    assert _missing_option(result, "--subset")


def test_run_instances_requires_split(runner: CliRunner) -> None:
    result = _invoke(runner, ["run", "instances", "--subset", "lite"])
    assert result.exit_code != 0
    assert _missing_option(result, "--split")


def test_run_instances_requires_output(runner: CliRunner) -> None:
    result = _invoke(
        runner, ["run", "instances", "--subset", "lite", "--split", "dev"],
    )
    assert result.exit_code != 0
    assert _missing_option(result, "--output")


def test_run_instances_forwards_required(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """Required trio forwards as-is to the wrapped script."""
    result = _invoke(
        runner,
        ["run", "instances", "--subset", "lite", "--split", "dev",
         "--output", "i.jsonl"],
    )
    assert result.exit_code == 0
    name, args = _last_forward(stub_runners)
    assert name == "generate_swebench_instances.py"
    assert args[:6] == ["--subset", "lite", "--split", "dev", "--output", "i.jsonl"]


def test_run_instances_forwards_optional_flags(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """`--limit`, `--append`, and the custom-repo group must all flow
    into the wrapped script's argv."""
    result = _invoke(
        runner,
        [
            "run", "instances",
            "--subset", "lite", "--split", "dev", "--output", "i.jsonl",
            "--limit", "3", "--append",
            "--custom-repo", "owner/name",
            "--custom-problem", "fix things",
            "--custom-base-commit", "deadbeef",
            "--custom-instance-id", "custom-x",
        ],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert "--limit" in args and "3" in args
    assert "--append" in args
    assert "--custom-repo" in args and "owner/name" in args
    assert "--custom-problem" in args and "fix things" in args
    assert "--custom-base-commit" in args and "deadbeef" in args
    assert "--custom-instance-id" in args and "custom-x" in args


def test_run_instances_passes_through_unknown_args(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """Unknown extra args (via `_FORWARD_CTX`) reach the script verbatim
    — this is the documented escape hatch for upstream flag additions."""
    result = _invoke(
        runner,
        [
            "run", "instances",
            "--subset", "lite", "--split", "dev", "--output", "i.jsonl",
            "--some-future-flag", "yes",
        ],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert "--some-future-flag" in args and "yes" in args


# ─── run prediction ───────────────────────────────────────────────────────────


def test_run_prediction_requires_instances(runner: CliRunner) -> None:
    result = _invoke(runner, ["run", "prediction"])
    assert result.exit_code != 0
    assert _missing_option(result, "--instances")


def test_run_prediction_requires_output(runner: CliRunner) -> None:
    result = _invoke(runner, ["run", "prediction", "--instances", "i.jsonl"])
    assert result.exit_code != 0
    assert _missing_option(result, "--output")


def test_run_prediction_requires_config(runner: CliRunner) -> None:
    result = _invoke(
        runner,
        ["run", "prediction", "--instances", "i.jsonl", "--output", "p.jsonl"],
    )
    assert result.exit_code != 0
    assert _missing_option(result, "--config")


def test_run_prediction_forwards_required(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    result = _invoke(
        runner,
        ["run", "prediction",
         "--instances", "i.jsonl", "--output", "p.jsonl", "--config", "chain"],
    )
    assert result.exit_code == 0
    name, args = _last_forward(stub_runners)
    assert name == "generate_evomas_predictions.py"
    assert args[:6] == [
        "--instances", "i.jsonl", "--output", "p.jsonl", "--config", "chain",
    ]


def test_run_prediction_forwards_limit(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    result = _invoke(
        runner,
        ["run", "prediction",
         "--instances", "i.jsonl", "--output", "p.jsonl", "--config", "chain",
         "--limit", "5"],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert "--limit" in args and "5" in args


# ─── run evaluation ───────────────────────────────────────────────────────────


def test_run_evaluation_requires_predictions(runner: CliRunner) -> None:
    result = _invoke(runner, ["run", "evaluation"])
    assert result.exit_code != 0
    assert _missing_option(result, "--predictions")


def test_run_evaluation_requires_split(runner: CliRunner) -> None:
    result = _invoke(
        runner, ["run", "evaluation", "--predictions", "p.jsonl"],
    )
    assert result.exit_code != 0
    assert _missing_option(result, "--split")


def test_run_evaluation_requires_subset(runner: CliRunner) -> None:
    result = _invoke(
        runner,
        ["run", "evaluation", "--predictions", "p.jsonl", "--split", "dev"],
    )
    assert result.exit_code != 0
    assert _missing_option(result, "--subset")


def test_run_evaluation_local_default(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """Without `--remote`, the LOCAL script wraps the harness."""
    result = _invoke(
        runner,
        ["run", "evaluation",
         "--predictions", "p.jsonl", "--split", "dev", "--subset", "lite"],
    )
    assert result.exit_code == 0
    name, args = _last_forward(stub_runners)
    assert name == "run_swebench_evaluation.py"
    # Local path always forwards --max-workers (8 by default).
    assert "--max-workers" in args
    assert "8" in args


def test_run_evaluation_remote_routes_to_remote_script(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """With `--remote`, the sb-cli wrapper script is invoked and the
    local-only `--max-workers` is dropped."""
    result = _invoke(
        runner,
        ["run", "evaluation", "--remote",
         "--predictions", "p.jsonl", "--split", "dev", "--subset", "lite"],
    )
    assert result.exit_code == 0
    name, args = _last_forward(stub_runners)
    assert name == "run_swebench_evaluation_remote.py"
    assert "--max-workers" not in args


def test_run_evaluation_remote_translates_report_dir(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """`--report-dir` is renamed to sb-cli's `--output-dir` on the
    remote path."""
    result = _invoke(
        runner,
        ["run", "evaluation", "--remote",
         "--predictions", "p.jsonl", "--split", "dev", "--subset", "lite",
         "--report-dir", "out"],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert "--output-dir" in args and "out" in args
    assert "--report-dir" not in args


def test_run_evaluation_local_keeps_report_dir(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """`--report-dir` stays as `--report-dir` on the local path (the
    harness reads that flag name)."""
    result = _invoke(
        runner,
        ["run", "evaluation",
         "--predictions", "p.jsonl", "--split", "dev", "--subset", "lite",
         "--report-dir", "out"],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert "--report-dir" in args and "out" in args


def test_run_evaluation_run_id_forwarded_on_both_paths(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """`--run-id` is honoured by both local and remote."""
    for extra in [[], ["--remote"]]:
        result = _invoke(
            runner,
            ["run", "evaluation", *extra,
             "--predictions", "p.jsonl", "--split", "dev", "--subset", "lite",
             "--run-id", "my-run"],
        )
        assert result.exit_code == 0, f"failed on extra={extra}"
        _, args = _last_forward(stub_runners)
        assert "--run-id" in args and "my-run" in args


def test_run_evaluation_max_workers_overridden(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """`--max-workers` flows through the local path with the user's value."""
    result = _invoke(
        runner,
        ["run", "evaluation",
         "--predictions", "p.jsonl", "--split", "dev", "--subset", "lite",
         "--max-workers", "4"],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    i = args.index("--max-workers")
    assert args[i + 1] == "4"


# ─── apply ────────────────────────────────────────────────────────────────────


def test_apply_requires_predictions(runner: CliRunner) -> None:
    result = _invoke(runner, ["apply"])
    assert result.exit_code != 0
    assert _missing_option(result, "--predictions")


def test_apply_requires_instances(runner: CliRunner) -> None:
    result = _invoke(runner, ["apply", "--predictions", "p.jsonl"])
    assert result.exit_code != 0
    assert _missing_option(result, "--instances")


def test_apply_forwards_required(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    result = _invoke(
        runner,
        ["apply", "--predictions", "p.jsonl", "--instances", "i.jsonl"],
    )
    assert result.exit_code == 0
    name, args = _last_forward(stub_runners)
    assert name == "apply_and_test.py"
    assert args[:4] == ["--predictions", "p.jsonl", "--instances", "i.jsonl"]


def test_apply_forwards_optional_flags(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    result = _invoke(
        runner,
        [
            "apply", "--predictions", "p.jsonl", "--instances", "i.jsonl",
            "--instance-id", "x__y-42",
            "--keep",
            "--report-dir", "out",
            "--run-id", "r1",
            "--model", "evomas-test",
        ],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert "--instance-id" in args and "x__y-42" in args
    assert "--keep" in args
    assert "--report-dir" in args and "out" in args
    assert "--run-id" in args and "r1" in args
    assert "--model" in args and "evomas-test" in args


# ─── server entry points ──────────────────────────────────────────────────────


def test_web_invokes_start_frontend(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    result = _invoke(runner, ["web"])
    assert result.exit_code == 0
    assert stub_runners["shell"], "shell script was not invoked"
    name, args = stub_runners["shell"][-1]
    assert name == "start_frontend"
    assert args == []


def test_api_invokes_start_api(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    result = _invoke(runner, ["api"])
    assert result.exit_code == 0
    name, args = stub_runners["shell"][-1]
    assert name == "start_api"
    assert args == []


# ─── test runner ──────────────────────────────────────────────────────────────


def test_test_command_default(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """`evomas test` with no flags runs the full suite (no exclusions)."""
    result = _invoke(runner, ["test"])
    assert result.exit_code == 0
    name, args = _last_forward(stub_runners)
    assert name == "run_tests.py"
    assert args == []


@pytest.mark.parametrize("flag", ["--backend-only", "--frontend-only", "--integration"])
def test_test_command_forwards_flag(
    runner: CliRunner, stub_runners: dict[str, list], flag: str,
) -> None:
    result = _invoke(runner, ["test", flag])
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert flag in args


def test_test_command_mutual_exclusion(runner: CliRunner) -> None:
    """`--backend-only` + `--frontend-only` together is a usage error."""
    result = _invoke(runner, ["test", "--backend-only", "--frontend-only"])
    assert result.exit_code != 0


def test_test_command_forwards_extra_args(
    runner: CliRunner, stub_runners: dict[str, list],
) -> None:
    """Args after `--` reach the script verbatim (pytest filter style)."""
    result = _invoke(
        runner, ["test", "--backend-only", "--", "-k", "apply_description_fix"],
    )
    assert result.exit_code == 0
    _, args = _last_forward(stub_runners)
    assert "-k" in args and "apply_description_fix" in args
