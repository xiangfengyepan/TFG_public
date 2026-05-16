import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict

from langchain_core.tools import tool

from evomas.tools.repo_tools import derive_description_fix_impl
from evomas.tools.search_tools import detect_bug_class_impl

logger = logging.getLogger(__name__)


class PatchResult(TypedDict):
    ok: bool
    output: str
    applied: bool


def _git(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _patch_cmd(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["patch", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def apply_patch_impl(patch_str: str, repo_path: str, dry_run: bool = False) -> PatchResult:
    if not patch_str.strip():
        return {"ok": False, "output": "empty patch", "applied": False}

    content = patch_str if patch_str.endswith("\n") else patch_str + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".diff", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(content)
        patch_path = tf.name

    try:
        # Method 1: git apply --check (strict)
        check = _git(["apply", "--check", patch_path], cwd=repo_path)
        if check.returncode == 0:
            if dry_run:
                return {"ok": True, "output": "patch applies cleanly (dry run)", "applied": False}
            apply = _git(["apply", patch_path], cwd=repo_path)
            return {
                "ok": apply.returncode == 0,
                "output": (apply.stdout + apply.stderr).strip() or "patch applied",
                "applied": apply.returncode == 0,
            }

        git_err = (check.stdout + check.stderr).strip()

        # Method 2: patch --fuzz=5 (more lenient context matching)
        fuzz_args = ["--batch", "--fuzz=5", "-p1", "-i", patch_path]
        if dry_run:
            fuzz_args = ["--dry-run"] + fuzz_args
        fuzz = _patch_cmd(fuzz_args, cwd=repo_path)
        if fuzz.returncode == 0:
            output = (fuzz.stdout + fuzz.stderr).strip() or "patch applied (fuzz)"
            return {"ok": True, "output": output, "applied": not dry_run}

        return {
            "ok": False,
            "output": f"{git_err}\n{(fuzz.stdout + fuzz.stderr).strip()}".strip(),
            "applied": False,
        }
    finally:
        try:
            Path(patch_path).unlink()
        except OSError:
            pass


def generate_diff_impl(repo_path: str, base_commit: str | None = None) -> str:
    args = ["diff", "--no-color"]
    if base_commit:
        args.append(base_commit)
    proc = _git(args, cwd=repo_path)
    if proc.returncode != 0:
        logger.warning("git diff failed: %s", proc.stderr)
        return ""
    return proc.stdout


def reset_repo_impl(repo_path: str, base_commit: str) -> None:
    _git(["reset", "--hard", base_commit], cwd=repo_path)
    _git(["clean", "-fdx"], cwd=repo_path)


# ─── Unified-diff repair helpers (used by `normalize_patch` and by any
# PatcherAgent that wants to normalize before applying). Pure string
# functions, no filesystem side-effects. ────────────────────────────────
def _add_git_header_if_missing(patch: str) -> str:
    """Prepend `diff --git a/<path> b/<path>` when the LLM omitted it.
    `git apply` requires the header; GNU `patch` doesn't. Adding it makes
    the diff compatible with both backends used inside apply_patch."""
    if patch.startswith("diff --git"):
        return patch
    lines = patch.splitlines()
    old_path = new_path = None
    for line in lines[:10]:
        if line.startswith("--- a/") and old_path is None:
            old_path = line[6:].split("\t")[0].strip()
        elif line.startswith("+++ b/") and new_path is None:
            new_path = line[6:].split("\t")[0].strip()
    if old_path and new_path:
        return f"diff --git a/{old_path} b/{new_path}\n{patch}"
    return patch


def _fix_blank_context_lines(patch: str) -> str:
    """Ensure blank context lines inside hunks have a leading space.
    `git apply` rejects patches where context lines inside a hunk are
    completely empty — the unified-diff standard requires a single-space
    prefix for unchanged lines."""
    lines = patch.splitlines(keepends=True)
    result: list[str] = []
    in_hunk = False
    for line in lines:
        if line.startswith("@@"):
            in_hunk = True
        elif line.startswith("diff --git"):
            in_hunk = False
        if in_hunk and line in ("\n", "\r\n", ""):
            line = " \n"
        result.append(line)
    return "".join(result)


_HUNK_HEADER_RE_INNER: re.Pattern[str] = re.compile(
    r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@", re.MULTILINE,
)


def _fix_hunk_headers(patch: str) -> str:
    """Recalculate `@@` hunk headers to match the actual content line counts.
    LLMs frequently write wrong `old_count` / `new_count`; `git apply --check`
    flags this as a corrupt patch even when the content would apply fine."""
    lines = patch.splitlines(keepends=True)
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HUNK_HEADER_RE_INNER.match(line)
        if m:
            old_start = int(m.group(1))
            new_start = int(m.group(2))
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].startswith("@@") and not lines[i].startswith("diff --git"):
                body.append(lines[i])
                i += 1
            old_count = sum(1 for l in body if l and (l[0] in (" ", "-")))
            new_count = sum(1 for l in body if l and (l[0] in (" ", "+")))
            suffix_m = re.match(r"@@[^@]*@@(.*)", line.rstrip("\r\n"))
            suffix = suffix_m.group(1) if suffix_m else ""
            new_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}\n"
            result.append(new_header)
            result.extend(body)
        else:
            result.append(line)
            i += 1
    return "".join(result)


def _filter_noop_hunks(patch: str) -> str:
    """Remove hunks where every removed line equals the corresponding added
    line (whitespace-only flips, trailing-comment churn). Such hunks fail
    `git apply` with context-mismatch and carry no useful fix anyway."""
    lines = patch.splitlines(keepends=True)
    file_header: list[str] = []
    current_hunk: list[str] = []
    meaningful_hunks: list[list[str]] = []

    def _is_meaningful(hunk: list[str]) -> bool:
        removed = [l[1:].rstrip("\r\n") for l in hunk if l.startswith("-")]
        added = [l[1:].rstrip("\r\n") for l in hunk if l.startswith("+")]
        return removed != added

    def _flush_hunk() -> None:
        if current_hunk and _is_meaningful(current_hunk):
            meaningful_hunks.append(list(current_hunk))
        current_hunk.clear()

    in_file = False
    for line in lines:
        if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "):
            _flush_hunk()
            if line.startswith("diff --git"):
                in_file = True
            file_header.append(line)
        elif line.startswith("@@") and in_file:
            _flush_hunk()
            current_hunk.append(line)
        elif in_file and current_hunk:
            current_hunk.append(line)
    _flush_hunk()

    if not meaningful_hunks:
        if not file_header:
            return patch
        return ""

    return "".join(file_header + [l for h in meaningful_hunks for l in h])


def normalize_patch_impl(patch_str: str) -> str:
    """Run every diff-repair pass on a (possibly malformed) unified diff and
    return a `git apply`-compatible string. Empty input → empty output."""
    patch = (patch_str or "").strip("\n\r ")
    if not patch:
        return ""
    patch = _add_git_header_if_missing(patch)
    patch = _fix_blank_context_lines(patch)
    patch = _fix_hunk_headers(patch)
    patch = _filter_noop_hunks(patch)
    if patch and not patch.endswith("\n"):
        patch += "\n"
    return patch


@tool
def apply_patch(patch_str: str, repo_path: str, dry_run: bool = False) -> PatchResult:
    """Apply a unified diff patch to a git repository using `git apply`.

    Args:
        patch_str: unified diff content.
        repo_path: absolute path to the git repo root.
        dry_run: if True, only run `git apply --check` without applying.

    Returns {ok, output, applied}.
    """
    return apply_patch_impl(patch_str, repo_path, dry_run)


@tool
def generate_diff(repo_path: str, base_commit: str | None = None) -> str:
    """Run `git diff` in the given repo against the working tree (or a base commit)."""
    return generate_diff_impl(repo_path, base_commit)


@tool
def reset_repo(repo_path: str, base_commit: str) -> None:
    """Hard-reset the repository to base_commit and remove untracked files."""
    reset_repo_impl(repo_path, base_commit)


@tool
def normalize_patch(patch_str: str) -> str:
    """Repair common LLM-generated unified-diff malformations and return a
    `git apply`-compatible patch string. Idempotent: a well-formed patch is
    returned unchanged. Specifically:
      * adds a `diff --git a/<path> b/<path>` header when missing,
      * recomputes `@@ -old,oldc +new,newc @@` hunk counts from body lines,
      * gives blank context lines inside hunks a leading space,
      * drops hunks where every `-` line equals the matching `+` line.
    Call this right after generating a `<patch>...</patch>` block and before
    `apply_patch`.

    Args:
        patch_str: raw unified diff content (possibly malformed).
    Returns: a normalized diff string, or "" if the input has no diff content.
    """
    return normalize_patch_impl(patch_str)


# ─── End-to-end class-1 description fixer ────────────────────────────────────
# Composes `detect_bug_class` (search_tools) + `derive_description_fix`
# (repo_tools) + `apply_patch` (same module) into a single deterministic call
# the patcher chain invokes first. Lives in patch_tools because the
# downstream operation — building a minimal unified diff and applying it — is
# fundamentally a patch op.

class DescriptionFixApplied(TypedDict, total=False):
    ok: bool                          # True when the patch was applied
    bug_class: int                    # 1 / 2 / 3 from detect_bug_class
    evidence: str                     # detect_bug_class evidence (always)
    file: str                         # repo-relative, class 1 only
    line: int                         # 1-indexed, class 1 only
    old_string: str                   # the literal removed
    new_string: str                   # the literal inserted
    patch: str                        # the unified diff applied
    error: str                        # set when a class-1 path can't complete


def _build_single_line_diff(
    relative_path: str,
    lines: list[str],
    line_index: int,
    old_string: str,
    new_string: str,
    context: int = 3,
) -> str:
    """Build a minimal unified diff that replaces `old_string` with
    `new_string` on `lines[line_index]`. Reads no filesystem; pure string
    construction. The 3-line context above/below matches `git diff` defaults
    so `git apply --check` doesn't reject for fuzzy context."""
    original_line = lines[line_index]
    if old_string not in original_line:
        raise ValueError(f"old_string not found on line {line_index + 1}")
    new_line = original_line.replace(old_string, new_string, 1)
    if new_line == original_line:
        raise ValueError("replacement produced an identical line")

    start = max(0, line_index - context)
    end = min(len(lines), line_index + context + 1)
    pre = lines[start:line_index]
    post = lines[line_index + 1:end]

    hunk_old_count = len(pre) + 1 + len(post)
    hunk_new_count = hunk_old_count  # single-line replacement → counts match
    hunk_start = start + 1  # 1-indexed

    body: list[str] = []
    body.extend(" " + l for l in pre)
    body.append("-" + original_line)
    body.append("+" + new_line)
    body.extend(" " + l for l in post)

    header = (
        f"diff --git a/{relative_path} b/{relative_path}\n"
        f"--- a/{relative_path}\n"
        f"+++ b/{relative_path}\n"
        f"@@ -{hunk_start},{hunk_old_count} +{hunk_start},{hunk_new_count} @@\n"
    )
    return header + "\n".join(body) + "\n"


def apply_description_fix_impl(issue_text: str, repo_path: str) -> DescriptionFixApplied:
    """End-to-end class-1 description-bug fixer.

    Combines `detect_bug_class` + `derive_description_fix` and applies the
    resulting single-line replacement via `apply_patch`. Pure deterministic
    Python — safe to call as the very first step in any patcher chain.

    Returns:
      * On class-1 success: `{ok: True, bug_class: 1, file, line, old_string,
        new_string, patch, evidence}`. The workspace has been modified.
      * On non-class-1 detection: `{ok: False, bug_class: <2|3>, evidence}`.
        The caller (LLM agent) should fall through to a general workflow.
      * On class-1 detection but derivation/apply failure: `{ok: False,
        bug_class: 1, error, evidence}`.
    """
    detection = detect_bug_class_impl(issue_text, repo_path)
    bug_class = int(detection.get("bug_class", 0) or 0)
    evidence = str(detection.get("evidence", ""))
    if bug_class != 1:
        return {"ok": False, "bug_class": bug_class, "evidence": evidence}

    matched_file = str(detection.get("matched_file", ""))
    matched_quoted = str(detection.get("matched_quoted_string", ""))
    if not matched_file or not matched_quoted:
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": "class-1 detection missing matched_file or matched_quoted_string",
        }

    fix = derive_description_fix_impl(repo_path, matched_file, matched_quoted)
    if fix.get("error"):
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": f"derive_description_fix failed: {fix['error']}",
        }

    new_string = str(fix.get("new_string", ""))
    line_no = int(fix.get("line", 0) or 0)
    if not new_string or line_no < 1:
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": "derive_description_fix returned an unusable result",
        }

    abs_file = Path(repo_path) / matched_file
    if not abs_file.is_file():
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": f"matched_file not found at expected path: {abs_file}",
        }
    try:
        text = abs_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": f"read failed: {exc}",
        }
    lines = text.splitlines()
    line_index = line_no - 1
    if not (0 <= line_index < len(lines)):
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": f"derived line {line_no} out of range (file has {len(lines)} lines)",
        }

    try:
        patch_str = _build_single_line_diff(
            relative_path=matched_file,
            lines=lines,
            line_index=line_index,
            old_string=matched_quoted,
            new_string=new_string,
        )
    except ValueError as exc:
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": f"diff construction failed: {exc}",
        }

    apply = apply_patch_impl(patch_str, repo_path)
    if not apply.get("ok"):
        return {
            "ok": False, "bug_class": 1, "evidence": evidence,
            "error": f"apply_patch failed: {apply.get('output', '')[:300]}",
            "patch": patch_str,
        }

    logger.info("[apply_description_fix] applied %s:%d %r -> %r",
                matched_file, line_no, matched_quoted, new_string)
    return {
        "ok": True,
        "bug_class": 1,
        "evidence": evidence,
        "file": matched_file,
        "line": line_no,
        "old_string": matched_quoted,
        "new_string": new_string,
        "patch": patch_str,
    }


@tool
def apply_description_fix(issue_text: str, repo_path: str) -> dict:
    """Deterministic end-to-end fixer for class-1 description / error-message
    bugs. Detects the bug class, derives the verbatim replacement from the
    source docstring, builds a minimal unified diff, and applies it to the
    workspace via `apply_patch` — all without LLM judgment.

    Use this as the FIRST tool call on every SWE-bench-style task:
      * If it returns `ok=True`: the fix is already applied. Stop emitting
        further tool calls — your job is done.
      * If it returns `ok=False`: this is a class-2 behaviour bug or a
        class-3 API mismatch. Fall through to the general repair workflow:
        read the relevant file with `read_file`, write a unified diff
        manually, and apply it via `apply_patch`.

    Args:
        issue_text: the SWE-bench issue / problem statement.
        repo_path:  absolute path to the cloned workspace root.

    Returns: `{ok, bug_class, evidence, ...}` — see `apply_description_fix_impl`
        for the full shape.
    """
    return apply_description_fix_impl(issue_text, repo_path)
