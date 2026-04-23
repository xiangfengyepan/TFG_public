from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.src.agents.base_agent import BaseAgent
from app.src.tools.code_tools import read_files_batch_tool
from pydantic import BaseModel, Field
from paths import BUG_DETECTOR_AGENT_JSON


class DetectedIssue(BaseModel):
    file_path: str = Field(
        description="Path to the file within the repository that likely contains a bug."
    )
    description: str = Field(description="What could be wrong and why it might fail.")
    evidence: str = Field(
        description="Relevant excerpt or concrete symptom description."
    )
    severity: Literal["low", "medium", "high"] = Field(
        description="Severity/impact estimate."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="How confident the agent is about this issue."
    )


class BugDetectionResponse(BaseModel):
    issues: List[DetectedIssue]
    needs_more_context: bool = Field(default=False)
    additional_search_request: str = Field(default="")
    summary: str = Field(default="")


# TODO check
class BugDetectorAgent(BaseAgent):
    """
    Analyzes the scanned repository tree and code snippets to detect possible bugs.
    """

    def __init__(self):
        with open(BUG_DETECTOR_AGENT_JSON, "r") as f:
            self.hyperparameters = json.load(f)
        super().__init__()

    SUPPORTED_SOURCE_EXTS: Tuple[str, ...] = (
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".java",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".sql",
    )

    KEYWORDS: List[str] = [
        "TODO",
        "FIXME",
        "NotImplementedError",
        "pass  #",
        "except Exception",
        "except:",
        "raise ",
        "assert False",
        "eval(",
        "exec(",
        "KeyError",
        "IndexError",
    ]

    @staticmethod
    def _iter_tree_files(
        node: Dict[str, Any], *, prefix: str = ""
    ) -> List[Tuple[str, Dict[str, Any]]]:
        if node.get("type") == "file":
            return [(prefix + node.get("name", ""), node)]
        results: List[Tuple[str, Dict[str, Any]]] = []
        for child in node.get("children", []) or []:
            child_name = child.get("name", "")
            child_prefix = prefix + ("" if prefix == "" else "/") + child_name
            if child.get("type") == "file":
                results.append((child_prefix, child))
            else:
                results.extend(
                    BugDetectorAgent._iter_tree_files(child, prefix=child_prefix)
                )
        return results

    def _score_snippet(self, snippet: str) -> int:
        score = 0
        lowered = snippet.lower()
        for kw in self.KEYWORDS:
            if kw.lower() in lowered:
                score += 2
        # Small bonus for tests/files.
        # TODO check
        if "tests" in lowered[:200] or "test_" in lowered:
            score += 1
        return score

    # TODO check
    def _fallback_issues(
        self, file_contents: List[Dict[str, str]], max_issues: int = 8
    ) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        for item in file_contents:
            content = item.get("content", "")
            file_path = item.get("file_path", "")
            for kw in self.KEYWORDS:
                if kw in content:
                    issues.append(
                        {
                            "file_path": file_path,
                            "description": f"Suspicious pattern '{kw}' found; verify this code path for correctness and error handling.",
                            "evidence": f"Keyword '{kw}' present in snippet.",
                            "severity": (
                                "medium" if kw in ("KeyError", "IndexError") else "low"
                            ),
                            "confidence": 0.35,
                        }
                    )
                    if len(issues) >= max_issues:
                        return issues
        return issues

    def run(self, state: dict) -> dict:
        repo_tree = state.get("repo_tree")
        if not repo_tree:
            return {"issues": [], "bug_detector_error": "Missing repo_tree in state."}

        # Prefer pre-collected snippets when available.
        # TODO refactor
        existing_snippets = state.get("repo_snippets") or []
        snippets: List[Dict[str, str]] = []
        for item in existing_snippets:
            if not isinstance(item, dict):
                continue
            fp = item.get("file_path")
            content = item.get("content", "")
            if isinstance(fp, str) and isinstance(content, str) and content.strip():
                snippets.append({"file_path": fp, "content": content})
        
        # TODO this will not happen since there is a context collector agent
        if not snippets:
            tree_files = self._iter_tree_files(repo_tree)
            file_paths = [p for p, _ in tree_files]

            # Select candidate files: only supported source extensions.
            candidate_paths = [
                p for p in file_paths if Path(p).suffix in self.SUPPORTED_SOURCE_EXTS
            ]
            # TODO check
            candidate_paths = candidate_paths[:40]

            # Read snippets through tool abstraction.
            content_map = read_files_batch_tool(
                paths=candidate_paths, max_bytes_per_file=8000
            )
            for rel_path, content in content_map.items():
                if isinstance(content, str) and content.strip():
                    snippets.append({"file_path": rel_path, "content": content})

        # Rank snippets by likelihood of containing problems.
        snippets.sort(key=lambda s: self._score_snippet(s["content"]), reverse=True)
        # TODO check
        snippets = snippets[:12]

        # Build model prompt.
        user_instructions = (
            "You are fixing bugs in a repository using automated program repair.\n"
            "Analyze the provided repository snippets and detect potential bugs or failing areas.\n\n"
            "Return ONLY valid JSON that matches the required schema.\n\n"
            "Important: focus on issues that could cause runtime failures, incorrect behavior, or failing tests.\n\n"
            f"Repository snippets (truncated):\n{snippets}\n"
        )

        messages = self.build_messages(
            state,
            user_instructions,
            include_state_keys=[
                "task_description",
                "repo_scan_meta",
                "repo_tree",
                "repo_snippets_count",
            ],
        )

        raw_text: Optional[str] = None
        try:
            response = self.model.chat(
                messages=messages,
                response_format=BugDetectionResponse,
                **self.hyperparameters,
            )
            raw_text = self.parse_text_output(
                getattr(response.message, "content", "") if response else ""
            )
            parsed = self.extract_json(raw_text) if raw_text else None
            if isinstance(parsed, dict) and "issues" in parsed:
                issues = parsed.get("issues", [])
                return {
                    "issues": issues,
                    "bug_detection_raw": raw_text,
                }
        except Exception:
            # Model call should not break the pipeline.
            pass
        
        # TODO this should not happen
        # Fallback to heuristic-based issues.
        issues = self._fallback_issues(snippets)
        return {
            "issues": issues,
            "bug_detection_raw": raw_text or "",
            "bug_detector_fallback": True,
        }
