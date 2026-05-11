import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from evomas.agents.types.patcher import PatcherAgent
from evomas.exceptions.errors import PatchGenerationError
from evomas.tools.patch_tools import normalize_patch_impl

_PATCH_BLOCK_RE: re.Pattern[str] = re.compile(r"<patch>(.*?)</patch>", re.DOTALL | re.IGNORECASE)
_FENCED_DIFF_RE: re.Pattern[str] = re.compile(r"```(?:diff)?\s*(diff --git[\s\S]+?)```", re.IGNORECASE)
_PLUS_PATH_RE: re.Pattern[str] = re.compile(r"^\+\+\+\s+b/(.+?)\s*$", re.MULTILINE)


class PatchAgent(PatcherAgent):
    name = "patch_agent"

    NUM_CANDIDATES: int = 3
    MAX_FILE_CHARS: int = 12000
    SEED_POOL: tuple[int, ...] = (42, 1337, 31415, 271828, 2718281)

    # Edge-driven output: the per-candidate patch strings (some may be ""
    # when generation failed). Consumed by `ValidateAgent`.
    OUTPUT_TYPE = list[str]
    OUTPUT_DEFAULT: list[str] = []

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Edge-driven input: read the predecessor's producer slot. For the
        # canonical evo-star chain that's `state["localize_agent"]` → a
        # `list[str]` of candidate file paths.
        files: list[str] = state.get(self.predecessor_name or "") or []
        repo: str = state["workspace_path"]
        if not files:
            raise PatchGenerationError(
                f"no candidate files in upstream slot '{self.predecessor_name}'"
            )

        file_block = self._format_files(repo, files)
        prompt = self.prompts["user"].format(issue=state["issue_text"][:6000], file_contents=file_block)
        messages = [SystemMessage(content=self.prompts["system"]), HumanMessage(content=prompt)]
        self.logger.info("patch prompt: %d chars | files=%s", len(prompt), files)

        patches: list[str] = []
        thinking_parts: list[str] = []
        for i in range(self.NUM_CANDIDATES):
            seed = self.SEED_POOL[i % len(self.SEED_POOL)]
            self.logger.info("generating candidate %d/%d (seed=%d temp=%.1f)",
                             i + 1, self.NUM_CANDIDATES, seed, 0.3 + 0.1 * i)
            try:
                llm = self.make_llm(seed=seed, temperature=0.3 + 0.1 * i)
                response = self._invoke(llm, messages)
                if self._thinking:
                    thinking_parts.append(f"[Candidate {i + 1}]\n{self._thinking}")
                raw = self._content(response)
                patch = self._extract_patch(raw)
                if patch and not self._paths_exist_in_repo(patch, repo):
                    self.logger.warning(
                        "candidate %d: patch references non-existent files - discarding", i
                    )
                    patch = ""
                self.logger.info("candidate %d: %d chars patch | raw preview: %s",
                                 i, len(patch), patch[:200].replace("\n", " "))
                patches.append(patch)
            except Exception as exc:
                self.logger.error("candidate %d failed: %s", i, exc)
                patches.append("")

        return {self.name: patches, "thinking": "\n\n".join(thinking_parts)}

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

    def _format_files(self, repo: str, files: list[str]) -> str:
        repo_path = Path(repo)
        sections: list[str] = []
        budget = self.MAX_FILE_CHARS * max(1, len(files))
        for f in files:
            ap = repo_path / f
            if not ap.is_file():
                continue
            try:
                content = self._call_tool("read_file", {
                    "path": str(ap),
                    "with_line_numbers": True,
                    "max_chars": self.MAX_FILE_CHARS,
                })
            except Exception as exc:
                self.logger.warning("could not read %s: %s", f, exc)
                continue
            sections.append(f"=== {f} ===\n{content}")
            budget -= len(content)
            if budget <= 0:
                break
        return "\n\n".join(sections) if sections else "(no files readable)"

    @staticmethod
    def _extract_patch(raw: str) -> str:
        # Closed <patch>...</patch> block (ideal case)
        match = _PATCH_BLOCK_RE.search(raw)
        if match:
            return PatchAgent._normalize(match.group(1))

        # Unclosed <patch> - model hit context limit before emitting </patch>.
        # Extract whatever diff content follows the opening tag.
        idx = raw.lower().find("<patch>")
        if idx >= 0:
            content = raw[idx + len("<patch>"):]
            diff_idx = content.find("diff --git")
            if diff_idx >= 0:
                return PatchAgent._normalize(content[diff_idx:])
            stripped = content.strip()
            if stripped.startswith("---") or stripped.startswith("diff"):
                return PatchAgent._normalize(content)

        # Fenced code block: ```diff ... ```
        match = _FENCED_DIFF_RE.search(raw)
        if match:
            return PatchAgent._normalize(match.group(1))

        # Bare diff --git anywhere in the response
        idx = raw.find("diff --git")
        if idx >= 0:
            return PatchAgent._normalize(raw[idx:])
        return ""

    @staticmethod
    def _paths_exist_in_repo(patch: str, repo: str) -> bool:
        """Return True only if every +++ b/<path> in the patch exists on disk."""
        repo_path = Path(repo)
        paths = _PLUS_PATH_RE.findall(patch)
        if not paths:
            return False
        return all((repo_path / p.strip()).exists() for p in paths)

    @staticmethod
    def _normalize(patch: str) -> str:
        """Single source of truth lives in `evomas.tools.patch_tools` so the
        same repair pipeline is reachable as the `normalize_patch` MCP tool
        for type-driven agents."""
        return normalize_patch_impl(patch)
