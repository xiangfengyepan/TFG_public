from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.src.agents.repo_scanner_agent import RepoScannerAgent
from app.src.agents.context_collector_agent import ContextCollectorAgent
from app.src.agents.bug_detector_agent import BugDetectorAgent
from app.src.agents.issue_prioritizer_agent import IssuePrioritizerAgent
from app.src.agents.patch_generator_agent import PatchGeneratorAgent
from app.src.agents.validator_agent import ValidatorAgent
from dotenv import load_dotenv

from app.src.utils.json import load_state_from_disk, merge_json_objects, save_state_to_disk
from app.src.tools.tool_registry import ToolRegistry


def run_with_persistence(agent_cls, state: APRState, node_name: str) -> dict:
    print(f"Entering {node_name}")
    STATE_FILE = f"state_{node_name}.json"

    persisted_state = load_state_from_disk(STATE_FILE)
    # merged_state = {**persisted_state, **state}
    merged_state = {**state, **persisted_state}

    agent = agent_cls()
    result = agent.run(dict(merged_state))

    new_state = {**merged_state, **result}

    save_state_to_disk(STATE_FILE, new_state)
    save_state_to_disk("state.json", new_state)
    return result


class APRState(TypedDict, total=False):
    """
    Shared state carried through the LangGraph APR pipeline.
    """

    task_description: str
    repo_tree: Dict[str, Any]
    repo_scan_meta: Dict[str, Any]
    repo_snippets: List[Dict[str, str]]
    repo_snippets_count: int
    issues: List[Dict[str, Any]]
    issues_prioritized_count: int
    patches: List[Dict[str, Any]]
    validation: Dict[str, Any]

    # Debugging / trace fields (optional)
    bug_detection_raw: str
    patch_generation_raw: str
    validator_raw: str


def repo_scanner_node(state: APRState) -> dict:
    return run_with_persistence(RepoScannerAgent, state, "RepoScannerAgent")


def context_collector_node(state: APRState) -> dict:
    return run_with_persistence(ContextCollectorAgent, state, "ContextCollectorAgent")


def bug_detector_node(state: APRState) -> dict:
    return run_with_persistence(BugDetectorAgent, state, "BugDetectorAgent")


def issue_prioritizer_node(state: APRState) -> dict:
    return run_with_persistence(IssuePrioritizerAgent, state, "IssuePrioritizerAgent")


def patch_generator_node(state: APRState) -> dict:
    return run_with_persistence(PatchGeneratorAgent, state, "PatchGeneratorAgent")


def validator_node(state: APRState) -> dict:
    return run_with_persistence(ValidatorAgent, state, "ValidatorAgent")


def build_workflow() -> Any:
    """
    Build and compile the APR LangGraph workflow.
    """
    workflow = StateGraph(APRState)

    workflow.add_node("repo_scanner_agent", repo_scanner_node)
    workflow.add_node("context_collector_agent", context_collector_node)
    workflow.add_node("bug_detector_agent", bug_detector_node)
    workflow.add_node("issue_prioritizer_agent", issue_prioritizer_node)
    workflow.add_node("patch_generator_agent", patch_generator_node)
    workflow.add_node("validator_agent", validator_node)

    workflow.set_entry_point("repo_scanner_agent")
    workflow.add_edge("repo_scanner_agent", "context_collector_agent")
    workflow.add_edge("context_collector_agent", "bug_detector_agent")
    workflow.add_edge("bug_detector_agent", "patch_generator_agent")
    workflow.add_edge("patch_generator_agent", END)
    # workflow.add_edge("validator_agent", END)

    return workflow.compile()


def run_apr(task_description: str) -> Dict[str, Any]:
    """
    Convenience runner for manual execution.
    """

    app = build_workflow()
    initial_state: APRState = {"task_description": task_description}
    final_state = app.invoke(initial_state)
    return dict(final_state)


if __name__ == "__main__":
    try:
        load_dotenv(override=True)

        # TODO move this method to an other class for validating before start
        ToolRegistry.validate_environment()
        ToolRegistry.check_docker_running()

        result = run_apr("Fix bugs that may cause crashes or failing tests.")
        print("=== APR Workflow Result ===")
        print(result.get("validation"))
    except Exception as e:
        print({f"error:{e}"})
