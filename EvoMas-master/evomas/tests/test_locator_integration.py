"""Integration test: run ONLY the locator agent on `sqlfluff__sqlfluff-1625`
with real Ollama + real tools + real workspace, and surface exactly what the
producer-slot would hand off to the next node in the chain.

Why this exists
---------------
Run `chain-25986f4a` finished with `[locator] -> [patcher] payload=str(0 B)`
— the locator ran for 3 iterations (search → read → final iter with no tool
calls), the model emitted ALL its output via the thinking channel instead of
`.content`, the fallback summary call did the same, and the patcher received
an empty upstream slot. `test_locator_agent.py` covers the loop's exit paths
with a mocked LLM, but it can't catch this real-world `think:true` swallow.

This integration test plugs into the real Ollama, runs the production
`LocatorAgent` against the cached `sqlfluff__sqlfluff-1625` workspace, and
asserts the producer-slot is non-empty. Run with `-s` to see the actual
content printed. Honors two opt-in env vars:

  * `EVOMAS_RUN_INTEGRATION=1` — set by `evomas test --integration` and
    `scripts/run_tests.py --integration`; flips on every integration
    test in the suite.
  * `EVOMAS_RUN_LOCATOR_INTEGRATION=1` — narrower opt-in for running
    JUST the locator test without the rest of the integration matrix.

    evomas test --backend-only --integration -- evomas/tests/test_locator_integration.py -v -s
    EVOMAS_RUN_LOCATOR_INTEGRATION=1 pytest evomas/tests/test_locator_integration.py -v -s

Skipped by default (no Ollama, no instance file, no workspace permissions)
so the regular `pytest evomas/tests/` still finishes in ~20 seconds.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evomas.agents.types.locator import LocatorAgent
from evomas.config.loader import load_config
from evomas.utils.workspace import clone_workspace, get_workspace_root


_INSTANCE_ID = "sqlfluff__sqlfluff-1625"
_INSTANCES_FILE = Path(__file__).resolve().parents[2] / "swebench_instances.jsonl"


def _load_instance(instance_id: str) -> dict:
    """Read `swebench_instances.jsonl` and return the row matching
    `instance_id`. Skips the test cleanly if either the file or the row is
    missing — common when running against a freshly-cloned repo."""
    if not _INSTANCES_FILE.is_file():
        pytest.skip(f"swebench_instances.jsonl missing at {_INSTANCES_FILE}")
    with _INSTANCES_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("instance_id") == instance_id:
                return row
    pytest.skip(f"instance {instance_id!r} not in {_INSTANCES_FILE}")


def _opt_in_enabled() -> bool:
    """True when either the global integration switch or the locator-specific
    switch is on. Lets `evomas test --integration` (which sets
    EVOMAS_RUN_INTEGRATION=1) pick this test up alongside the rest of the
    integration matrix, while still allowing a narrow opt-in via
    EVOMAS_RUN_LOCATOR_INTEGRATION=1 for someone debugging just this test."""
    return (
        os.environ.get("EVOMAS_RUN_INTEGRATION") == "1"
        or os.environ.get("EVOMAS_RUN_LOCATOR_INTEGRATION") == "1"
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not _opt_in_enabled(),
    reason="opt-in via EVOMAS_RUN_INTEGRATION=1 (or EVOMAS_RUN_LOCATOR_INTEGRATION=1) — slow: ~2 min on qwen3.5:9b",
)
def test_locator_only_on_sqlfluff_1625(ollama_required: None, caplog) -> None:
    """End-to-end: load the SWE-bench row → ensure workspace exists → build a
    real `LocatorAgent` from `chain.json`'s locator block → run a single
    `agent.run(state)` → assert the producer-slot is non-empty and print what
    would be handed off to the patcher.

    This test directly catches the `chain-25986f4a` regression where the
    locator emitted only thinking-channel tokens, leaving `state["locator"]`
    empty and the patcher with nothing to read from `## Upstream (locator)`.
    """
    instance = _load_instance(_INSTANCE_ID)

    # Cloning the workspace fans out subprocess(git) calls — wrap so a
    # broken git env / no network skips cleanly instead of erroring out.
    try:
        workspace = clone_workspace(
            instance["instance_id"], instance["repo"], instance["base_commit"],
        )
    except Exception as exc:
        pytest.skip(f"could not clone/reuse workspace: {exc}")

    # Build the locator from the SAME config the chain run uses. `chain.json`
    # is the authoritative source — pulling the block here keeps the test
    # locked to whatever hyperparameters production uses.
    cfg = load_config("chain")
    locator_block = cfg["agents"]["locator"]
    agent = LocatorAgent(config_block=locator_block)

    # State the LangGraph runtime would seed for the entry node. No
    # predecessor (locator is the entry), so no `{predecessor}` to inject.
    state = {
        "issue_text": instance.get("problem_statement", ""),
        "workspace_path": str(workspace.path),
        "instance": {"instance_id": instance["instance_id"]},
    }

    delta = agent.run(state)

    # The producer-slot is what gets handed off to `state[self.name]` and
    # subsequently read by `patcher` via its `predecessor_name="locator"`.
    producer = delta.get("locator", "")
    print(f"\n=== LOCATOR PRODUCER SLOT ({len(producer)} chars) ===")
    print(producer)
    print(f"=== END (delta keys: {sorted(delta.keys())}) ===")

    # The bug from `chain-25986f4a` was a 0-byte slot. Any non-empty output
    # passes — we don't pin the exact format because the model varies; the
    # important regression is "did the locator hand SOMETHING off".
    assert producer, (
        "Locator produced an empty producer slot — the patcher would receive "
        "'payload=str(0 B)' just like chain-25986f4a. Check the agent's "
        "think:true behaviour: when qwen3.5:9b emits everything as thinking "
        "and nothing as .content, _final_response_text stays empty and the "
        "summary fallback can hit the same wall."
    )
