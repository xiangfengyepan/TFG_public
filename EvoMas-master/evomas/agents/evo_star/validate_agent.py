import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from evomas.agents.types.reviewer import ReviewerAgent

_REVIEW_BLOCK_RE: re.Pattern[str] = re.compile(r"<review>(.*?)</review>", re.DOTALL | re.IGNORECASE)
_CHANGED_FILE_RE: re.Pattern[str] = re.compile(r"^\+\+\+\s+b/(.+?)\s*$", re.MULTILINE)


class ValidateAgent(ReviewerAgent):
    name = "validate_agent"

    SCORE_APPLIES: int = 10
    SCORE_FLAKE8: int = 5
    SCORE_REVIEW: int = 3

    # Edge-driven output: bundle `{patches, validations}` so the downstream
    # ensembler can pick from both via a single predecessor-slot lookup.
    # The two parallel lists are index-aligned: `patches[i]` is scored by
    # `validations[i]`.
    OUTPUT_TYPE = dict[str, Any]
    OUTPUT_DEFAULT: dict[str, Any] = {}

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Edge-driven input: predecessor's slot carries `list[str]` of
        # candidate patches (per the patch_agent → validate_agent edge).
        patches: list[str] = state.get(self.predecessor_name or "") or []
        repo: str = state["workspace_path"]
        base_commit: str = state["instance"]["base_commit"]
        issue: str = state["issue_text"]

        results: list[dict[str, Any]] = []
        for idx, patch in enumerate(patches):
            self.logger.info("validating candidate %d (%d chars)", idx, len(patch))
            results.append(self._validate_one(idx, patch, repo, base_commit, issue))

        # Edge-driven output: bundle the patches alongside the per-patch
        # validation results so the ensembler can pick both up via a single
        # predecessor-slot lookup — no implicit two-hop state reads.
        return {
            self.name: {"patches": patches, "validations": results},
            "thinking": self._thinking,
        }

    def _validate_one(
        self,
        idx: int,
        patch: str,
        repo: str,
        base_commit: str,
        issue: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "patch_idx": idx,
            "applies": False,
            "flake8_ok": False,
            "review_pass": False,
            "lint_output": "",
            "review_text": "",
            "score": 0,
        }
        if not patch.strip():
            result["review_text"] = "empty patch"
            return result

        check = self._call_tool("apply_patch", {"patch_str": patch, "repo_path": repo, "dry_run": True})
        result["applies"] = bool(check["ok"])
        if not check["ok"]:
            self.logger.info("candidate %d: does not apply - %s", idx, check["output"][:200])
            result["review_text"] = f"does not apply: {check['output'][:300]}"
            return result
        self.logger.info("candidate %d: patch applies ok", idx)

        applied = self._call_tool("apply_patch", {"patch_str": patch, "repo_path": repo, "dry_run": False})
        if not applied["applied"]:
            self.logger.warning("candidate %d: apply failed after dry-run pass", idx)
            result["review_text"] = f"apply failed after dry-run pass: {applied['output'][:300]}"
            return result

        try:
            changed = _CHANGED_FILE_RE.findall(patch)
            self.logger.info("candidate %d: changed files: %s", idx, changed)
            lint_lines: list[str] = []
            lint_ok = True
            for cf in changed:
                cp = Path(repo) / cf
                if not (cp.is_file() and cf.endswith(".py")):
                    continue
                lint = self._call_tool("run_flake8", {"file_path": str(cp)})
                self.logger.info("candidate %d: flake8 %s -> %s", idx, cf,
                                 "ok" if lint["ok"] else lint["output"][:150])
                if not lint["ok"]:
                    lint_ok = False
                    lint_lines.append(f"{cf}:\n{lint['output']}")
            result["flake8_ok"] = lint_ok
            result["lint_output"] = "\n".join(lint_lines) or "no python files changed"

            try:
                review = self._llm_review(issue, patch, result)
                result["review_pass"] = review["pass"]
                result["review_text"] = review["text"]
                self.logger.info("candidate %d: review -> %s | %s",
                                 idx, "PASS" if review["pass"] else "FAIL",
                                 review["text"][:150].replace("\n", " "))
            except Exception as exc:
                self.logger.warning("candidate %d: review LLM failed: %s", idx, exc)
                result["review_text"] = f"review error: {exc}"
        finally:
            self._call_tool("reset_repo", {"repo_path": repo, "base_commit": base_commit})

        score = 0
        if result["applies"]:
            score += self.SCORE_APPLIES
        if result["flake8_ok"]:
            score += self.SCORE_FLAKE8
        if result["review_pass"]:
            score += self.SCORE_REVIEW
        result["score"] = score
        self.logger.info("candidate %d: score=%d (applies=%s flake8=%s review=%s)",
                         idx, score, result["applies"], result["flake8_ok"], result["review_pass"])
        return result

    def _llm_review(self, issue: str, patch: str, partial: dict[str, Any]) -> dict[str, Any]:
        llm = self.make_llm()
        prompt = self.prompts["user"].format(
            issue=issue[:5000],
            patch=patch[:8000],
            applies=partial["applies"],
            flake8_ok=partial["flake8_ok"],
            flake8_output=partial.get("lint_output", "")[:1500],
        )
        response = self._invoke(
            llm, [SystemMessage(content=self.prompts["system"]), HumanMessage(content=prompt)]
        )
        raw = self._content(response)
        match = _REVIEW_BLOCK_RE.search(raw)
        if match:
            block = match.group(1).strip()
        else:
            idx = raw.lower().find("<review>")
            block = raw[idx + len("<review>"):].strip() if idx >= 0 else raw.strip()
        first_line = block.splitlines()[0].strip().upper() if block else ""
        passes = first_line.startswith("PASS")
        return {"pass": passes, "text": block[:600]}

    @staticmethod
    def _content(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    parts.append(c.get("text", ""))
                else:
                    parts.append(str(c))
            return "".join(parts)
        return str(content)
