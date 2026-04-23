from __future__ import annotations

from typing import Any, Dict, List

import json
from app.src.agents.base_agent import BaseAgent
from paths import ISSUE_PRIORITIZER_AGENT_JSON

class IssuePrioritizerAgent(BaseAgent):
    """
    Prioritizes and trims detected issues before patch generation.
    """
    def __init__(self):
        with open(ISSUE_PRIORITIZER_AGENT_JSON, "r") as f:
            self.hyperparameters = json.load(f)
        super().__init__()

    _SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

    def run(self, state: dict) -> dict:
        issues = state.get("issues") or []
        if not isinstance(issues, list):
            return {"issues": []}

        normalized: List[Dict[str, Any]] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            file_path = issue.get("file_path")
            desc = issue.get("description")
            if not isinstance(file_path, str) or not file_path:
                continue
            if not isinstance(desc, str) or not desc:
                continue
            normalized.append(issue)

        # Deduplicate by file path + description and rank by severity/confidence.
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for issue in normalized:
            key = (issue.get("file_path", ""), issue.get("description", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(issue)

        def issue_key(item: Dict[str, Any]) -> tuple:
            sev = str(item.get("severity", "low")).lower()
            conf = item.get("confidence", 0.0)
            try:
                conf_f = float(conf)
            except Exception:
                conf_f = 0.0
            return (self._SEVERITY_RANK.get(sev, 2), -conf_f)

        deduped.sort(key=issue_key)
        prioritized = deduped[:8]

        return {
            "issues": prioritized,
            "issues_prioritized_count": len(prioritized),
        }

