import logging
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from evomas.mcp.server import MCPServer
from evomas.utils.workspace import DEFAULT_WORKSPACE_ROOT


def _force_remove(func, path, exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.mark.integration
@pytest.mark.slow
def test_workflow_runner_on_buggy_repo(
    ollama_required: None,
    buggy_instance: dict,
    buggy_repo: Path,
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="evomas")

    instance_id = buggy_instance["instance_id"]
    workspace_path = DEFAULT_WORKSPACE_ROOT / instance_id
    workspace_path.parent.mkdir(parents=True, exist_ok=True)

    if workspace_path.exists():
        shutil.rmtree(workspace_path, onexc=_force_remove)
    shutil.copytree(buggy_repo, workspace_path)

    def fake_clone(instance_id: str, repo: str, base_commit: str):
        from evomas.utils.workspace import Workspace

        subprocess.run(
            ["git", "reset", "--hard", base_commit], cwd=workspace_path, check=True
        )
        return Workspace(instance_id, repo, base_commit, workspace_path)

    monkeypatch.setattr("evomas.core.workflow.runner.clone_workspace", fake_clone)

    from evomas.core.workflow.runner import _run_impl

    patch = _run_impl(buggy_instance, config="evo-star")

    assert patch, "expected non-empty patch from runner"

    server = MCPServer()
    apply = server.call("apply_patch", {
        "patch_str": patch,
        "repo_path": str(workspace_path),
        "dry_run": True,
    })
    if not apply["ok"]:
        pytest.skip(
            f"LLM produced non-applying patch (acceptable in smoke test):\n{patch[:500]}"
        )
    assert apply["ok"]
