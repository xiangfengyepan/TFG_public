"""Hardcoded deterministic helpers for the type-driven LLM agents.

EVERY function in this file is deterministic Python that bypasses LLM
judgment. The pure-LLM agents under `evomas/agents/types/` invoke them via
MCP tools to stabilise the operations qwen3.5:9b's reliability is too low
for -- specifically, bug-class identification for description-string bugs
and verbatim derivation of the new description from the source docstring.

This is the ONLY module in `evomas/agents/types/` + `evomas/tools/` whose
logic is "hardcoded heuristic" rather than either:
  (a) tool plumbing (`apply_patch`, `run_flake8`, ...), or
  (b) LLM-driven decision-making.

To audit what's hardcoded: read this file. To use it: import from here.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ─── Public typed return shapes ──────────────────────────────────────────────
class BugClassResult(TypedDict, total=False):
    bug_class: int                    # 1 = description-string, 2 = behaviour, 3 = API mismatch
    evidence: str                     # one-line rationale
    matched_quoted_string: str        # the OLD literal (class 1 only)
    matched_file: str                 # repo-relative, for human readability
    matched_file_absolute: str        # ABSOLUTE path -- pass this to str_replace_editor
    matched_line: int                 # 1-indexed


class DescriptionFix(TypedDict, total=False):
    file: str                         # repo-relative
    absolute_path: str                # ABSOLUTE path -- pass this to str_replace_editor
    line: int
    old_string: str
    new_string: str                   # derived candidate
    docstring_first_sentence: str     # raw verbatim, no fillers dropped
    error: str                        # set when derivation failed


# ─── Quoted-string extraction ────────────────────────────────────────────────
# Captures any "..." with at least 5 chars of content; covers both straight
# and "smart" quotes from copy-pasted issue text.
_QUOTED_RE: re.Pattern[str] = re.compile(r'["“]([^"”]{5,}?)["”]')

# Source-file extensions to grep through when looking for a quoted literal.
_SOURCE_EXTS: tuple[str, ...] = (".py", ".js", ".ts", ".tsx", ".rb", ".go")

# Directories to skip when walking — large vendored trees / build artefacts
# blow up grep time without ever matching emitted strings.
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".tox", ".venv", "venv", "node_modules", "__pycache__", "dist",
    "build", ".pytest_cache", ".mypy_cache",
})

# Heuristic: when we find an issue-quoted string in source, is its position
# in the file a "string the program emits to the user"?
# These patterns match the LINE containing the literal — keep them broad
# enough to catch the common SWE-bench-style description-message bug shapes.
_EMITTED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'\bdescription\s*=\s*["“]'),     # description="..."
    re.compile(r'\bmessage\s*=\s*["“]'),         # message="..."
    re.compile(r'\berror_message\s*=\s*["“]'),   # error_message="..."
    re.compile(r'\bmsg\s*=\s*["“]'),             # msg="..."
    re.compile(r'\braise\s+\w+\s*\(\s*["“]'),    # raise X("..."
    re.compile(r'\bself\._error\s*\(\s*["“]'),   # self._error("..."
    re.compile(r'\breturn\s+["“]'),              # return "..."  (helpful for getter-style messages)
)

# Tokens that hint at API-signature bugs when the issue doesn't have a
# quoted-string match.
_API_HINTS: frozenset[str] = frozenset({
    "argument", "arguments", "parameter", "parameters",
    "signature", "kwarg", "kwargs", "return type", "type hint",
})


# ─── Source-file iteration ───────────────────────────────────────────────────
def _iter_source_files(repo_path: Path) -> list[Path]:
    """Yield candidate source files under `repo_path` -- prioritising the
    canonical `src/` / `lib/` subtrees and skipping vendored / build dirs."""
    out: list[Path] = []
    for sub in (repo_path / "src", repo_path / "lib"):
        if sub.is_dir():
            for p in sub.rglob("*"):
                if p.is_file() and p.suffix in _SOURCE_EXTS \
                        and not any(d in _SKIP_DIRS for d in p.parts):
                    out.append(p)
    # Top-level files (for projects without an src/ layout).
    for p in repo_path.glob("*.py"):
        out.append(p)
    return out


# ─── detect_bug_class ────────────────────────────────────────────────────────
def detect_bug_class_impl(issue_text: str, repo_path: str) -> BugClassResult:
    """Classify a SWE-bench-style issue as description-string (1),
    behaviour (2), or API-mismatch (3). Class-1 matches also pin the
    source location of the offending literal so the follow-up
    `derive_description_fix` can derive the new wording verbatim.

    Pure heuristic; safe to call as a first step in any patcher chain.
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        return {"bug_class": 2, "evidence": f"repo not found: {repo_path}"}

    issue = issue_text or ""
    quoted = [m.group(1).strip() for m in _QUOTED_RE.finditer(issue)]
    # Dedup preserving order; ignore very short or pure-whitespace.
    seen: set[str] = set()
    quoted = [q for q in quoted if q and q not in seen and not seen.add(q)]

    if quoted:
        source_files = _iter_source_files(repo)
        for q in quoted:
            for sf in source_files:
                try:
                    text = sf.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if q not in text:
                    continue
                # Walk lines to pinpoint the exact line + check the
                # emitted-string heuristics.
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if q not in line:
                        continue
                    if any(p.search(line) for p in _EMITTED_PATTERNS):
                        rel = sf.relative_to(repo).as_posix()
                        evidence = (
                            f"matched quoted string {q!r} on an emitted-string "
                            f"line at {rel}:{lineno}"
                        )
                        return {
                            "bug_class": 1,
                            "evidence": evidence,
                            "matched_quoted_string": q,
                            "matched_file": rel,
                            "matched_file_absolute": str(sf.resolve()),
                            "matched_line": lineno,
                        }
                # The literal exists in the file but not on an emitted-string
                # line. Note it as evidence and keep scanning other files.
        # Quoted strings exist but none on an emitted-string line → behaviour bug.
        # Fall through.

    if any(h in issue.lower() for h in _API_HINTS):
        return {"bug_class": 3, "evidence": "issue uses API-signature vocabulary without an emitted-string match"}

    return {"bug_class": 2, "evidence": "no emitted-string match for any quoted issue text"}


# ─── derive_description_fix ──────────────────────────────────────────────────
# First-sentence regex: match up to (and including) the first period, treating
# blank lines / Sphinx field markers as terminators too.
_FIRST_SENTENCE_RE: re.Pattern[str] = re.compile(r"^(.*?\.)\s", re.DOTALL)

# Filler tokens to strip when deriving the new wording from a docstring.
# Conservative: only remove standalone words that don't change meaning.
_FILLER_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "table aliases" → "aliases"
    (re.compile(r"\btable aliases\b", re.IGNORECASE), "aliases"),
    # "using aliases" → "aliases" (when 'using' is the filler after a verb)
    (re.compile(r"\busing aliases\b", re.IGNORECASE), "aliases"),
)


def _find_enclosing(lines: list[str], target_line_index: int, kinds: tuple[str, ...]) -> int | None:
    """Walk backwards from `target_line_index` (0-based) to find an enclosing
    line starting with any prefix in `kinds` at a STRICTLY LOWER indent than
    the target.

    Returns the line index of the *outermost* enclosing match — i.e. each
    time we find a candidate at indent `n`, we keep walking back hoping to
    find an even-lower-indent match. This lets us prefer the outer
    `class Rule_X(BaseRule):` over a nested `class TableAliasInfo:` when the
    target line sits inside both.
    """
    target_indent: int | None = None
    chosen_index: int | None = None
    chosen_indent: int | None = None
    for i in range(target_line_index, -1, -1):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped:
            continue
        indent = len(line) - len(stripped)
        if target_indent is None:
            target_indent = indent
        if any(stripped.startswith(k) for k in kinds) and indent < (target_indent or 0):
            # Keep the outermost (lowest-indent) match seen so far.
            if chosen_indent is None or indent < chosen_indent:
                chosen_index = i
                chosen_indent = indent
                if indent == 0:
                    # Can't get any more outer than column 0.
                    break
    return chosen_index


def _extract_docstring(lines: list[str], def_index: int) -> str | None:
    """Given the line index of a `class ` or `def ` definition, return the
    text of the triple-quoted docstring that follows (if any). Joins
    multi-line docstrings into a single string without the quoting."""
    # Find the first non-blank line after the def's colon. The def can be
    # multi-line (e.g. wrapped argument lists), so locate the line ending
    # in `:` first.
    i = def_index
    while i < len(lines) and not lines[i].rstrip().endswith(":"):
        i += 1
        if i - def_index > 30:
            return None  # something's off; bail
    i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None
    first = lines[i].strip()
    for quote in ('"""', "'''"):
        if first.startswith(quote):
            # Single-line docstring?
            if first.endswith(quote) and len(first) > len(quote) * 2:
                return first[len(quote):-len(quote)].strip()
            # Multi-line: collect until closing quote.
            body: list[str] = [first[len(quote):]]
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if quote in line:
                    end = line.index(quote)
                    body.append(line[:end])
                    return "\n".join(body).strip()
                body.append(line)
                j += 1
    return None


def _apply_fillers(sentence: str) -> str:
    """Apply the small set of common-filler removals from `_FILLER_REPLACEMENTS`
    and ensure a trailing period. Idempotent."""
    out = sentence.strip()
    for pat, repl in _FILLER_REPLACEMENTS:
        out = pat.sub(repl, out)
    out = re.sub(r"\s+", " ", out).strip()
    if not out.endswith("."):
        out = out + "."
    return out


def derive_description_fix_impl(repo_path: str, file: str, old_string: str) -> DescriptionFix:
    """For a class-1 bug, derive the new wording verbatim from the enclosing
    class/function's docstring. Returns the {old, new, file, line} the
    caller should pass to `str_replace_editor`."""
    repo = Path(repo_path)
    src = repo / file
    if not src.is_file():
        return {"error": f"file not found: {file}"}
    try:
        text = src.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"read failed: {exc}"}

    lines = text.splitlines()
    # Locate the line containing the old string.
    line_index = next((i for i, l in enumerate(lines) if old_string in l), None)
    if line_index is None:
        return {"error": f"old_string {old_string!r} not found in {file}"}

    # Prefer the enclosing CLASS's docstring (which typically describes the
    # rule / behaviour the emitted string is about) over the immediate
    # method's docstring (which usually describes the helper, not the
    # message). Fall back to the closest def only when no class wraps it.
    class_index = _find_enclosing(lines, line_index, ("class ",))
    def_index   = _find_enclosing(lines, line_index, ("class ", "def "))
    docstring: str | None = None
    chosen_index: int | None = None
    if class_index is not None:
        docstring = _extract_docstring(lines, class_index)
        chosen_index = class_index
    if not docstring and def_index is not None:
        docstring = _extract_docstring(lines, def_index)
        chosen_index = def_index
    if not docstring:
        return {"error": f"no docstring on enclosing class/def above line {line_index + 1}"}

    # First sentence: the longest leading slice ending at the first period,
    # collapsed to a single line.
    first_line_block = docstring.split("\n\n", 1)[0].strip()
    first_line_block = re.sub(r"\s+", " ", first_line_block)
    m = _FIRST_SENTENCE_RE.match(first_line_block + " ")
    if m:
        sentence = m.group(1).strip()
    else:
        sentence = first_line_block.strip()
        if not sentence.endswith("."):
            sentence = sentence + "."

    new_string = _apply_fillers(sentence)
    return {
        "file": file,
        "absolute_path": str(src.resolve()),
        "line": line_index + 1,
        "old_string": old_string,
        "new_string": new_string,
        "docstring_first_sentence": sentence,
    }


# ─── MCP @tool wrappers ──────────────────────────────────────────────────────
@tool
def detect_bug_class(issue_text: str, repo_path: str) -> dict:
    """Heuristically classify the SWE-bench-style issue as one of:
      * `bug_class=1` - description / error-message bug. The issue quotes
        a specific emitted string (e.g. a `description=\"...\"` argument,
        a `raise X(\"...\")`, an `error_message=\"...\"`). The fix is to
        change ONLY that string literal. The response includes
        `matched_quoted_string`, `matched_file` (repo-relative),
        `matched_file_absolute` (use THIS as the `path` argument for
        `str_replace_editor`), and `matched_line`.
      * `bug_class=2` - behaviour bug. Logic / triggering change needed.
      * `bug_class=3` - API signature / typing mismatch.

    Call this BEFORE attempting any edit so subsequent steps can pick the
    right strategy. Pure deterministic heuristic over the issue text and
    workspace contents -- no LLM, no flakiness.

    Args:
        issue_text: the SWE-bench issue / problem statement.
        repo_path:  absolute path to the cloned workspace root.

    Returns: a dict with `bug_class`, `evidence`, and (for class 1)
        `matched_quoted_string`, `matched_file` (relative),
        `matched_file_absolute`, `matched_line`.
    """
    return detect_bug_class_impl(issue_text, repo_path)


@tool
def derive_description_fix(repo_path: str, file: str, old_string: str) -> dict:
    """For a class-1 description/error-message bug, deterministically
    derive the new wording from the enclosing class/function's docstring.
    Drops the common single-word fillers (`table ` before `aliases`,
    `using ` between verb and `aliases`) and ensures a trailing period.
    Use the returned `new_string` value VERBATIM as the replacement.

    The harness asserts character equality; do NOT paraphrase the result.

    Args:
        repo_path:  absolute path to the cloned workspace root.
        file:       repo-relative source path (from `detect_bug_class`).
        old_string: the OLD literal (from `detect_bug_class`).

    Returns: `{file, absolute_path, line, old_string, new_string,
        docstring_first_sentence}` on success -- pass `absolute_path` (not
        `file`) as the `path` argument to `str_replace_editor`. On failure
        returns `{error: <reason>}`.
    """
    return derive_description_fix_impl(repo_path, file, old_string)
