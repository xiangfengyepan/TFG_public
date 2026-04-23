try:
    # Legacy workflow agents (may not exist in all repo snapshots).
    from app.src.tests.localize_agent_test import LocalizeAgent
    from app.src.tests.analyze_agent_test import AnalyzeAgent
except Exception:  # pragma: no cover
    LocalizeAgent = None
    AnalyzeAgent = None
from app.src.models.ollama_model import OllamaWrapper
from ollama import ChatResponse

from typing import TypedDict
from langgraph.graph import StateGraph, END


class APRState(TypedDict):
    bug_description: str
    search_query: str  # What the LocalizeAgent should currently search for
    localization_report: str  # Accumulated file contents
    analysis_details: str
    needs_more_context: bool
    iteration_count: int
    response: ChatResponse


def localize_node(state: APRState) -> dict:
    print(
        f"\n--- Entering Node: LOCALIZE (Iteration {state.get('iteration_count', 0)}) ---"
    )

    agent = LocalizeAgent()
    query = state.get("search_query") or state["bug_description"]

    new_report = agent.run(query)

    existing_report = state.get("localization_report", "")
    combined_report = (
        f"{existing_report}\n\n--- Next Search Results ---\n{new_report}"
        if existing_report
        else new_report
    )

    return {"localization_report": combined_report, "response": new_report}


def analyze_node(state: APRState) -> dict:
    print(f"\n--- Entering Node: ANALYZE ---")

    agent = AnalyzeAgent()
    result = agent.run(state["bug_description"], state["localization_report"])

    iteration = state.get("iteration_count", 0) + 1

    return {
        "analysis_details": result.get("analysis_details", ""),
        "needs_more_context": result.get("needs_more_context", False),
        "search_query": result.get("additional_search_request", ""),
        "iteration_count": iteration,
        "response": result,
    }


def should_continue(state: APRState) -> str:
    if state.get("iteration_count", 0) >= 3:
        print("\n[Router] Max iterations reached. Ending workflow.")
        return "end"

    if state.get("needs_more_context"):
        print(
            "\n[Router] AnalyzeAgent needs more context. Looping back to LocalizeAgent."
        )
        return "localize"

    print("\n[Router] Analysis complete. Bug identified (or no more files needed).")
    return "end"


def build_workflow():
    # Switch to the new APR workflow implementation (agents/ -> core/workflow.py).
    # Legacy graph uses missing `tests.localize_agent` / `tests.analyze_agent` in some repo snapshots.
    from app.src.core.workflow import build_workflow as build_apr_workflow

    return build_apr_workflow()


def run_workflow(
    task_description: str = "Fix bugs in the repository that could cause crashes or failing tests.",
):
    app = build_workflow()

    initial_state = {
        "task_description": task_description,
    }

    print("=== Starting LangGraph APR Workflow ===")

    final_state = app.invoke(initial_state)

    print("\n=== Workflow Finished ===")
    if isinstance(final_state, dict) and "validation" in final_state:
        print("\nValidation Report:")
        print(final_state.get("validation"))
    return dict(final_state)


if __name__ == "__main__":
    run_workflow()
