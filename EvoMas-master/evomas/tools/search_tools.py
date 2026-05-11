from pathlib import Path
from typing import TypedDict

from langchain_core.tools import tool

from evomas.tools.repo_tools import list_files_impl
from evomas.utils.bm25 import BM25, tokenize


class CodeMatch(TypedDict):
    path: str
    score: float
    snippet: str


def _snippet(text: str, query_terms: list[str], context: int = 2, max_lines: int = 8) -> str:
    lines = text.splitlines()
    qset = set(query_terms)
    hits: list[int] = []
    for i, line in enumerate(lines):
        toks = set(tokenize(line))
        if toks & qset:
            hits.append(i)
    if not hits:
        return "\n".join(lines[:max_lines])
    start = max(0, hits[0] - context)
    end = min(len(lines), hits[0] + context + 1)
    block = lines[start:end]
    if len(block) > max_lines:
        block = block[:max_lines]
    return "\n".join(f"{start + i + 1}: {line}" for i, line in enumerate(block))


def search_code_impl(query: str, directory: str, top_k: int = 10) -> list[CodeMatch]:
    base = Path(directory)
    if not base.is_dir():
        raise FileNotFoundError(f"directory not found: {directory}")

    rel_paths: list[str] = list_files_impl(directory, "*.py")
    docs: list[list[str]] = []
    contents: list[str] = []
    abs_paths: list[Path] = []
    for rp in rel_paths:
        ap = base / rp
        try:
            text = ap.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        contents.append(text)
        abs_paths.append(ap)
        docs.append(tokenize(text))

    if not docs:
        return []

    bm25 = BM25()
    bm25.fit(docs)
    q_tokens = tokenize(query)
    if not q_tokens:
        return []

    ranked = bm25.rank(q_tokens, top_k=top_k)
    results: list[CodeMatch] = []
    for idx, score in ranked:
        rel = str(abs_paths[idx].relative_to(base))
        snippet = _snippet(contents[idx], q_tokens)
        results.append({"path": rel, "score": round(score, 3), "snippet": snippet})
    return results


@tool
def search_code(query: str, directory: str, top_k: int = 10) -> list[CodeMatch]:
    """BM25 keyword search across .py files in a directory.

    Args:
        query: free-form natural-language query (function names, error messages, identifiers).
        directory: absolute path to the repo root to search.
        top_k: number of results to return.

    Returns a list of {path, score, snippet} entries ordered by relevance.
    """
    return search_code_impl(query, directory, top_k)
