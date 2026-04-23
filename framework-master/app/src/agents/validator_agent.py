from __future__ import annotations

import json
import ast
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from app.src.agents.base_agent import BaseAgent
from pydantic import BaseModel, Field
from paths import VALIDATOR_AGENT_JSON


class ValidationReport(BaseModel):
    bug_solved: bool = Field(
        description="Whether the proposed patch is likely to solve the reported bug(s)."
    )
    manual_review_needed: bool = Field(
        description="Whether a human should review the patch."
    )
    justification: str = Field(description="Reasoning supporting the decision.")
    residual_issues: List[str] = Field(
        default_factory=list, description="Remaining problems if any."
    )
    static_check_results: Dict[str, str] = Field(
        default_factory=dict,
        description="Map from file_path to static check status (e.g., 'OK', or an error message).",
    )


class ValidatorAgent(BaseAgent):
    """
    Validates patch correctness using basic static checks and model re-analysis.
    """

    def __init__(self):
        with open(VALIDATOR_AGENT_JSON, "r") as f:
            self.hyperparameters = json.load(f)
        super().__init__()

    def _static_validate_python(self, rel_path: str, content: str) -> str:
        """
        Returns 'OK' or an error message for python syntax checks.
        """
        try:
            ast.parse(content)
            return "OK"
        except SyntaxError as e:
            return f"SyntaxError: {e.msg} (line {e.lineno})"
        except Exception as e:
            return f"StaticCheckError: {str(e)}"

    def run(self, state: dict) -> dict:
        issues = state.get("issues") or []
        patches = state.get("patches") or []
        if not patches:
            return {
                "validation": {
                    "bug_solved": False,
                    "manual_review_needed": True,
                    "justification": "No patches were generated/applied, so the bug status cannot be improved automatically.",
                    "residual_issues": [
                        issue.get("description", "Unknown issue")
                        for issue in issues[:3]
                    ],
                    "static_check_results": {},
                }
            }

        repo_root = self.get_repo_root()

        static_results: Dict[str, str] = {}
        for patch in patches:
            rel_path = patch.get("file_path")
            if not rel_path:
                continue
            new_content = patch.get("new_content")
            if not isinstance(new_content, str):
                # Re-read if model output didn't include content for some reason.
                try:
                    # TODO use tool read
                    new_content = (repo_root / rel_path).read_text(
                        encoding="utf-8", errors="ignore"
                    )
                except Exception:
                    new_content = ""

            if Path(rel_path).suffix == ".py":
                static_results[rel_path] = self._static_validate_python(
                    rel_path, new_content
                )

        # Heuristic flags: low-confidence patches or syntax errors => manual review.
        manual_review = any(
            float(p.get("confidence", 1.0)) < 0.6
            for p in patches
            if isinstance(p, dict) and p.get("confidence") is not None
        )
        manual_review = manual_review or any(
            status != "OK" for status in static_results.values()
        )

        # Model re-analysis (structured output).
        user_instructions = (
            "You are validating a proposed automated program repair patch.\n"
            "Given:\n"
            "1) detected issues,\n"
            "2) applied patches (updated file contents),\n"
            "3) static check results,\n"
            "decide if the bug is likely solved.\n\n"
            "Return ONLY valid JSON matching the schema.\n\n"
            f"Issues (may be truncated): {issues}\n\n"
            f"Patches: {patches}\n\n"
            f"Static check results: {static_results}\n\n"
            "Constraints:\n"
            "- If any Python file has syntax errors, set bug_solved=false and manual_review_needed=true.\n"
            "- Otherwise, base your answer on whether the changes directly address the issue evidence."
        )

        messages = self.build_messages(
            state,
            user_instructions,
            include_state_keys=["task_description", "repo_tree", "issues", "patches"],
        )

        raw_text: str = ""
        try:
            response = self.model.chat(
                messages=messages, response_format=ValidationReport
            )
            raw_text = self.parse_text_output(
                getattr(response.message, "content", "") if response else ""
            )
            parsed = self.extract_json(raw_text) if raw_text else None
            if isinstance(parsed, dict):
                parsed["static_check_results"] = (
                    parsed.get("static_check_results") or static_results
                )
                # Ensure constraints are enforced.
                if any(status != "OK" for status in static_results.values()):
                    parsed["bug_solved"] = False
                    parsed["manual_review_needed"] = True
                if "manual_review_needed" not in parsed:
                    parsed["manual_review_needed"] = manual_review
                return {"validation": parsed, "validator_raw": raw_text}
        except Exception:
            pass

        # Fallback: static check-based decision.
        has_syntax_errors = any(status != "OK" for status in static_results.values())
        import json

        print(json.dumps(self.model.chat_history, indent=2))
        return {
            "validation": {
                "bug_solved": (not has_syntax_errors) and (len(issues) == 0),
                "manual_review_needed": True,
                "justification": "Model validation failed; used fallback heuristic based on static checks.",
                "residual_issues": [
                    i.get("description", "Unknown issue") for i in issues[:3]
                ],
                "static_check_results": static_results,
            }
        }
