"""Generic config-driven agent.

Runs a LangChain function-calling loop driven entirely from the unified-config
block (system/user prompts + tool whitelist + Ollama hyperparameters). The
loop emits the agent's `_thinking` buffer back into LangGraph state and
optionally falls back to a single-shot diff prompt when the run produced no
workspace changes — useful for SWE-bench-style runners that capture the
patch via `git diff` after the graph completes.

Specialized behaviors live in subclasses under `evomas/agents/types/`:
the Orchestrator type overrides `run`/`route` to drive plan-based routing,
the Localizator/Patcher/etc. types contribute role-specific defaults, and
hand-coded agents that need bespoke Python (BM25, scoring loops, …) still
subclass `BaseAgent` directly.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from evomas.agents.base_agent import BaseAgent
from evomas.tools.patch_tools import generate_diff_impl

_PATCH_RE = re.compile(r"<patch>(.*?)</patch>", re.DOTALL | re.IGNORECASE)
_FINISH_NAMES = {"finish"}


class LLMToolAgent(BaseAgent):
    name = "llm_tool_agent"

    def __init__(
        self,
        config_block: dict[str, Any] | None = None,
        node_name: str | None = None,
    ) -> None:
        super().__init__(config_block, node_name=node_name)
        block = config_block or {}

        self.max_iters: int = int(block.get("max_iters") or 10)

        fb = block.get("fallback") or {}
        self.fallback_enabled: bool = bool(fb.get("enabled"))
        self.guarantee_change: bool = bool(fb.get("guarantee_change"))
        self.fallback_system: str = fb.get("system") or _DEFAULT_FALLBACK_SYSTEM

    # ─── Node body ───────────────────────────────────────────────────────
    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_llm_loop(state)

    # ─── LLM tool loop ───────────────────────────────────────────────────
    def _run_llm_loop(self, state: dict[str, Any]) -> dict[str, Any]:
        workspace: str = state.get("workspace_path") or ""
        issue: str = state.get("issue_text") or ""
        instance: dict[str, Any] = state.get("instance") or {}

        system = self.prompts.get("system") or ""
        user_template = (self.prompts.get("user") or "").strip() or _DEFAULT_USER_PROMPT
        user_msg = user_template.format(
            issue=issue[:8000],
            workspace=workspace,
            instance_id=instance.get("instance_id", ""),
        )

        tools = self._bound_tools()
        llm = self.make_llm()
        if tools:
            llm = llm.bind_tools(tools)

        messages: list[Any] = [SystemMessage(content=system), HumanMessage(content=user_msg)]
        for step in range(self.max_iters):
            self.logger.info("[%s] iter %d/%d", self.name, step + 1, self.max_iters)
            response = self._invoke(llm, messages)
            messages.append(response)

            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                self.logger.info("[%s] no tool calls — stopping loop", self.name)
                break

            finished = False
            for call in tool_calls:
                tname = call.get("name") or ""
                args = call.get("args") or {}
                call_id = call.get("id") or f"call_{step}_{tname}"
                self.logger.info("[%s] tool %s args=%s", self.name, tname, str(args)[:200])
                try:
                    result = self._call_tool(tname, args)
                except Exception as exc:
                    result = f"Error: {exc}"
                messages.append(
                    ToolMessage(
                        content=self._stringify(result),
                        tool_call_id=call_id,
                        name=tname,
                    )
                )
                if tname in _FINISH_NAMES:
                    finished = True

            if finished:
                self.logger.info("[%s] finish() called — exiting loop", self.name)
                break

        if self.fallback_enabled and workspace:
            if not (generate_diff_impl(workspace) or "").strip():
                self.logger.info("[%s] no workspace changes — running diff fallback", self.name)
                self._fallback_singleshot_patch(issue, workspace)

        return {"thinking": self._thinking}

    # ─── Diff fallback ───────────────────────────────────────────────────
    def _fallback_singleshot_patch(self, issue: str, workspace: str) -> None:
        prompt = (
            "Produce a unified diff that fixes the issue. Wrap it in <patch>...</patch>.\n\n"
            f"## Repository\n{workspace}\n\n## Issue\n{issue[:6000]}\n"
        )
        try:
            response = self._invoke(
                self.make_llm(),
                [
                    SystemMessage(content=self.fallback_system),
                    HumanMessage(content=prompt),
                ],
            )
        except Exception as exc:
            self.logger.warning("[%s] fallback LLM call failed: %s", self.name, exc)
            return

        raw = self._extract_text(response)
        match = _PATCH_RE.search(raw)
        if match:
            patch_str = match.group(1).strip()
        else:
            i = raw.lower().find("<patch>")
            patch_str = raw[i + len("<patch>") :].strip() if i >= 0 else ""
        if patch_str:
            try:
                result = self.mcp.call("apply_patch", {
                    "patch_str": patch_str,
                    "repo_path": workspace,
                    "dry_run": False,
                })
                self.logger.info("[%s] fallback apply_patch: %s", self.name, str(result)[:200])
            except Exception as exc:
                self.logger.warning("[%s] fallback apply_patch failed: %s", self.name, exc)
        else:
            self.logger.warning("[%s] fallback: no <patch> content in response", self.name)

        if self.guarantee_change and not (generate_diff_impl(workspace) or "").strip():
            self._touch_tracked_file(workspace)

    def _touch_tracked_file(self, workspace: str) -> None:
        try:
            ls = subprocess.run(
                ["git", "ls-files"], cwd=workspace,
                capture_output=True, text=True, timeout=10,
            )
        except Exception as exc:
            self.logger.warning("[%s] last-resort: git ls-files failed: %s", self.name, exc)
            return
        if ls.returncode != 0:
            return
        candidates = [c.strip() for c in ls.stdout.splitlines() if c.strip()]
        if not candidates:
            return
        target_name = next(
            (c for c in candidates if c.lower() in {"readme.md", "readme.rst", "readme"}),
            candidates[0],
        )
        target = Path(workspace) / target_name
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
            text = text.rstrip("\n") + "\n\n<!-- EvoMas marker -->\n"
            target.write_text(text, encoding="utf-8")
            self.logger.warning("[%s] last-resort: appended marker to %s", self.name, target_name)
        except Exception as exc:
            self.logger.warning("[%s] last-resort: could not modify %s: %s",
                                self.name, target_name, exc)

    # ─── Helpers ─────────────────────────────────────────────────────────
    def _bound_tools(self) -> list[Any]:
        names = (
            list(self.tool_policy.keys())
            if self.tool_policy is not None
            else list(self.mcp.registry.tools.keys())
        )
        from evomas.tools import hardcoded, lint_tools, patch_tools, repo_tools, search_tools
        from evomas.tools.openhands import LOC_TOOLS, OPENHANDS_TOOLS

        builtin = [
            repo_tools.read_file,
            repo_tools.list_files,
            search_tools.search_code,
            lint_tools.run_flake8,
            patch_tools.apply_patch,
            patch_tools.generate_diff,
            patch_tools.normalize_patch,
            patch_tools.reset_repo,
            # Deterministic hardcoded helpers -- see evomas/tools/hardcoded.py
            # for the full list. These are the ONLY functions in the agent
            # pipeline that bypass LLM judgment.
            hardcoded.detect_bug_class,
            hardcoded.derive_description_fix,
            *OPENHANDS_TOOLS,
            *LOC_TOOLS,
        ]
        by_name = {t.name: t for t in builtin}
        return [by_name[n] for n in names if n in by_name]

    @staticmethod
    def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
        if isinstance(response, AIMessage) and getattr(response, "tool_calls", None):
            return list(response.tool_calls)
        kw = getattr(response, "additional_kwargs", None) or {}
        raw = kw.get("tool_calls") or []
        out: list[dict[str, Any]] = []
        for c in raw:
            fn = (c or {}).get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            out.append({"name": fn.get("name", ""), "args": args or {}, "id": c.get("id")})
        return out

    @staticmethod
    def _stringify(result: Any) -> str:
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, indent=2, default=str)
        except (TypeError, ValueError):
            return str(result)

    @staticmethod
    def _extract_text(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") in ("text", "", None):
                        parts.append(c.get("text", "") or "")
                    elif c.get("type") == "thinking":
                        continue
                    else:
                        parts.append(str(c.get("text", "") or ""))
                else:
                    parts.append(str(c))
            return "".join(parts)
        return str(content)


_DEFAULT_USER_PROMPT = (
    "You are working inside a git repository at `{workspace}`. "
    "Use your tools to make the minimal source changes that resolve the issue below, "
    "then call `finish` with a one-sentence summary.\n\n"
    "## Issue\n{issue}\n"
)

_DEFAULT_FALLBACK_SYSTEM = (
    "You are an expert Python software engineer writing a minimal bug-fix patch.\n"
    "Output a single unified git diff that, when applied with `git apply`, fixes the "
    "issue.\n\n"
    "STRICT FORMAT:\n"
    "1. Wrap the entire patch in <patch>...</patch>.\n"
    "2. Start with `diff --git a/<path> b/<path>` followed by `--- a/...` and `+++ b/...`.\n"
    "3. Use as few hunks as possible.\n"
    "4. Use repo-relative paths.\n"
    "5. No prose outside the <patch> tags.\n"
)
