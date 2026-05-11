import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from evomas.agents.types.localizator import LocalizatorAgent
from evomas.exceptions.errors import LocalizationError
from evomas.utils.bm25 import tokenize

_FILES_BLOCK_RE: re.Pattern[str] = re.compile(r"<files>(.*?)</files>", re.DOTALL | re.IGNORECASE)


class LocalizeAgent(LocalizatorAgent):
    name = "localize_agent"

    MAX_FILES: int = 2
    SEARCH_TOP_K: int = 10
    FILE_LIST_SAMPLE: int = 80

    # Edge-driven output: a short list of repo-relative file paths most
    # likely to contain the bug. Consumed by `PatchAgent` via the
    # `state[predecessor_name]` lookup, where `predecessor_name == "localize_agent"`.
    OUTPUT_TYPE = list[str]
    OUTPUT_DEFAULT: list[str] = []

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        repo: str = state["workspace_path"]
        issue: str = state["issue_text"]
        if not repo or not Path(repo).is_dir():
            raise LocalizationError(f"workspace not found: {repo}")

        keywords = self._extract_keywords(issue)
        self.logger.info("localize keywords: %s", keywords[:15])

        hits = self._call_tool("search_code", {"query": " ".join(keywords), "directory": repo, "top_k": self.SEARCH_TOP_K})
        if not hits:
            self.logger.warning("no BM25 hits; falling back to file listing")
        all_files = self._call_tool("list_files", {"directory": repo, "extension": "*.py"})
        sample = all_files[: self.FILE_LIST_SAMPLE]

        search_block = self._format_hits(hits) or "(no hits)"
        file_list = "\n".join(sample) or "(empty)"

        llm = self.make_llm()
        prompt = self.prompts["user"].format(
            issue=issue[:6000],
            n_hits=len(hits),
            search_results=search_block,
            file_list=file_list,
        )
        self.logger.info("localize prompt: %d chars | hits=%d | files_sample=%d",
                         len(prompt), len(hits), len(sample))
        response = self._invoke(
            llm, [SystemMessage(content=self.prompts["system"]), HumanMessage(content=prompt)]
        )
        raw: str = self._content(response)
        self.logger.info("localize raw response (%d chars): %s", len(raw), raw[:300].replace("\n", " "))
        files = self._parse_files(raw)

        repo_path = Path(repo)
        valid: list[str] = []
        for f in files:
            f = f.strip().lstrip("/").strip()
            if not f:
                continue
            if (repo_path / f).is_file():
                if f not in valid:
                    valid.append(f)
            if len(valid) >= self.MAX_FILES:
                break

        if not valid and hits:
            valid = [hits[0]["path"]]

        if not valid:
            self.logger.error("localize produced no valid files")
        else:
            self.logger.info("localize selected: %s", valid)

        # Edge-driven output: write into our own producer slot keyed by
        # node id. PatchAgent (the linear successor) reads it via
        # `state[self.predecessor_name]`.
        return {self.name: valid, "thinking": self._thinking}

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

    @staticmethod
    def _format_hits(hits: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for h in hits:
            lines.append(f"- {h['path']} (score={h['score']})")
            lines.append(f"  snippet:\n  {h['snippet'].replace(chr(10), chr(10) + '  ')}")
        return "\n".join(lines)

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        STOP = {
            "the", "and", "for", "with", "this", "that", "from", "have", "has", "had",
            "are", "but", "not", "you", "all", "can", "will", "what", "when", "which",
            "use", "using", "into", "out", "should", "would", "could", "issue", "bug",
            "fix", "fixes", "fixed", "test", "tests", "code", "function", "method",
            "class", "module", "import", "return", "returns", "raise", "raises", "error",
            "errors", "exception", "exceptions", "true", "false", "none", "self", "cls",
            "def", "if", "else", "elif", "try", "except", "finally", "for", "while",
            "in", "is", "as", "of", "to", "a", "an",
        }
        toks = tokenize(text)
        seen: set[str] = set()
        out: list[str] = []
        for t in toks:
            if t in STOP or len(t) < 3 or t.isdigit():
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= 20:
                break
        return out

    @staticmethod
    def _parse_files(raw: str) -> list[str]:
        match = _FILES_BLOCK_RE.search(raw)
        block = match.group(1) if match else raw
        candidates: list[str] = []
        for line in block.splitlines():
            line = line.strip().lstrip("-*").strip()
            line = re.sub(r"^\d+[.)]\s*", "", line)
            line = line.strip("`'\" ")
            if not line:
                continue
            if " " in line and not line.endswith(".py"):
                tokens = [t for t in line.split() if t.endswith(".py")]
                if tokens:
                    line = tokens[0]
                else:
                    continue
            if line.endswith(".py") or "/" in line:
                candidates.append(line)
        return candidates
