# Tools and prompts: where they come from

This page explains how each tool implementation and each agent prompt
in EvoMas was extracted from its upstream project — i.e. whether the
code or text is a behavior-faithful re-implementation, a paraphrase, or
a verbatim import. It complements [REPO_CATALOG.md](REPO_CATALOG.md),
which focuses on licenses.

## Methodology

### Tools — re-implementation, never direct copy

Every Python tool body under `evomas/tools/<repo>/` is **written from
scratch** by the EvoMas authors. This rule holds across all 12 repos
that contribute tools, regardless of upstream license. The pattern:

1. The catalog JSON at `evomas/config/agent_types/<repo>.json` lists
   each tool with a `source_url` pointing to a specific line in the
   upstream project (commit-pinned).
2. EvoMas authors read the upstream code at that line to understand
   what the tool *does* — its inputs, outputs, side effects.
3. They write a fresh Python implementation that produces the same
   observable behavior, integrated into EvoMas's MCP server and the
   LangChain `@tool` decorator.
4. The **filename and exported symbol name** are kept aligned with
   the upstream identifier (e.g. `StrReplaceEditorTool.py`,
   `EnvironmentTool.py`, `search_class.py`) so the catalog dropdown
   in the Topology UI reads cleanly. Names are interface labels, not
   copyrightable expression.
5. No upstream function bodies are copied. The local clones at
   `…/SWE_bench/repos/` are reference material for the survey step,
   not source for any committed line.

This is why even AGPL- and source-available-licensed upstream tools
(claude-coder, patchwork, auto-code-rover, suna) can be safely
referenced — EvoMas redistributes only behavior, not code.

### Prompts — currently imported verbatim, flagged for permissive vs restrictive

Each `<repo>.json` carries per-agent `prompts.{system, user, proxy, route}`
strings. These were imported **verbatim** from upstream source files by
the CSV ingester that built the initial catalog. The status today:

- **Permissive-license repos** (MIT, Apache-2.0, BSD) — the verbatim
  import is allowed by the upstream license, subject to attribution.
  EvoMas keeps the upstream wording so the agent behavior matches the
  original paper / project; paraphrasing would risk changing the
  evaluated agent's behavior unintentionally.
- **Restrictive-license repos** (AGPL, source-available, no-LICENSE) —
  the verbatim import does *not* have a redistribution grant. Four
  repos are in this bucket: `Lingma-SWE-GPT`, `auto-code-rover`,
  `claude-coder`, `patchwork`. The plan is to paraphrase these
  prompts (same agent role and instruction shape, fresh wording) so
  they no longer depend on the upstream's literal text. This work is
  pending — see the "Restrictive-license prompts" section below.

The Topology UI surfaces every prompt slot in the inspector's
**Prompts** section, where you can edit them — saved edits override the
upstream-derived defaults.

### Topology and orchestration — EvoMas-authored

LangGraph topology assembly, MCP server, the SWE-bench evaluation
harness, and the Angular frontend are all original work. The five
predefined topology shapes (chain, tree, star, hybrid, cycle) were
designed in EvoMas; they take inspiration from patterns observed
across the upstream projects but share no code with any of them.

## EvoMas core tools

These tools live at the top level of `evomas/tools/` (not under any
`<repo>/` subfolder) and are registered for every topology regardless
of the agent-variant catalog in use. They cover workspace I/O, the
patch lifecycle, and bug-class diagnostics.

| Tool | Module | What it does |
|------|--------|--------------|
| `read_file` | `repo_tools.py` | Read a file from the working repo at a given path. |
| `list_files` | `repo_tools.py` | List files under a directory (filtered, recursive). |
| `derive_description_fix` | `repo_tools.py` | Locate the docstring / description block tied to a symbol so a patcher can rewrite it. |
| `search_code` | `search_tools.py` | Grep-style search across the repo with file/line context. |
| `detect_bug_class` | `search_tools.py` | Heuristic classifier for the issue (logic bug, docstring fix, off-by-one, etc.). |
| `run_flake8` | `lint_tools.py` | Run `flake8` against the working tree and return parsed diagnostics. |
| `apply_patch` | `patch_tools.py` | Apply a unified diff to the working tree. |
| `generate_diff` | `patch_tools.py` | Produce a unified diff between the working tree and HEAD. |
| `normalize_patch` | `patch_tools.py` | Canonicalize whitespace / context so a patch round-trips cleanly. |
| `reset_repo` | `patch_tools.py` | `git checkout -- .` style hard reset to the last committed state. |
| `apply_description_fix` | `patch_tools.py` | Apply a one-shot description/docstring rewrite without touching code. |

All eleven are EvoMas-authored — they don't correspond to any single
upstream project. They're written to mirror the operations every
SWE-bench coding agent needs, distilled across the upstream set.

## Per-repo tools

Twelve repos contribute tool bundles. Each row lists the tool symbols
that ship under `evomas/tools/<repo>/`.

| Repo | # | Tools |
|------|---|-------|
| `augment_swebench_agent` | 3 | `CompleteTool`, `SequentialThinkingTool`, `StrReplaceEditorTool` |
| `auto_code_rover` | 1 | `agent_write_patch` (upstream class `PatchAgent`) |
| `claude_coder` | 15 | `executeCommandTool`, `listFilesTool`, `ExploreRepoFolderTool`, `searchFilesTool`, `readFileTool`, `askFollowupQuestionTool`, `attemptCompletionTool`, `webSearchTool`, `urlScreenshotTool`, `devServerTool`, `searchSymbolTool`, `addInterestedFileTool`, `fileEditorTool`, `spawnAgentTool`, `exitAgentTool` |
| `composio` | 4 | `MultiServerMCPClient_mcp`, `MultiServerMCPClient_langchain_agent`, `HostedMCPTool_openai_agents`, `HostedMCPTool_tool_router_mcp` |
| `debug_gym` | 1 | `EnvironmentTool` |
| `joycode_agent` | 3 | `CompleteTool`, `SequentialThinkingTool`, `StrReplaceEditorTool` (re-exported from `augment_swebench_agent` / `openhands` canonicals) |
| `lingma_swe_gpt` | 8 | `search_class`, `search_class_in_file`, `search_method_in_file`, `search_method_in_class`, `search_method`, `search_code`, `search_code_in_file`, `write_patch` |
| `openhands` | 11 | `BrowserTool`, `CmdRunTool`, `CondensationRequestTool`, `FinishTool`, `GlobTool`, `GrepTool`, `IPythonTool`, `LLMBasedFileEditTool`, `StrReplaceEditorTool`, `ThinkTool`, `ViewTool` |
| `patchwork` | 5 | `code_edit_tools`, `csvkit_tool`, `git_tool`, `grep_tool`, `workspace_manifest` |
| `suna` | 1 | `filter_mcp_tools` |
| `swe_agent` | 1 | `list_mcp_tools` |
| `trae_agent` | 6 | `CKGTool`, `JSONEditTool`, `TaskDoneTool`, `CmdRunTool` (re-export), `StrReplaceEditorTool` (re-export), `SequentialThinkingTool` (re-export) |

A few patterns to read this table by:

- **Re-exports** (`joycode_agent`, `trae_agent`) — when two upstream
  projects ship the same tool concept, EvoMas keeps one canonical
  implementation and re-exports it from the other bundle. This avoids
  MCP "last write wins" collisions when both bundles are loaded at
  once.
- **Canonical owners** — `StrReplaceEditorTool` lives in `openhands`;
  `CompleteTool` and `SequentialThinkingTool` in `augment_swebench_agent`;
  `search_code` in the EvoMas core (not `lingma_swe_gpt`).
- **Schema vs. behavior** — for OpenHands, the upstream tool definition
  is a `litellm.ChatCompletionToolParam` schema; the EvoMas counterpart
  is a real Python function with the same name and equivalent
  behavior, not a schema declaration.

## Per-repo prompts

Twenty-two repos contribute prompts. The "Status" column reflects
whether the prompt text can stay as-is or needs paraphrasing.

| Repo | # agents | License | Status |
|------|---------:|---------|--------|
| `aider` | 14 | Apache-2.0 | Verbatim, permitted by upstream license. |
| `augment-swebench-agent` | 1 | MIT | Verbatim, permitted. |
| `auto_code_rover` | 6 | SONAR Source-Available | **Verbatim — needs paraphrase.** |
| `claude-coder` | 1 | AGPL-3.0-or-later | **Verbatim — needs paraphrase.** |
| `composio` | 14 | MIT | Verbatim, permitted. |
| `DARS-Agent` | 2 | Apache-2.0 | Verbatim, permitted. |
| `debug-gym` | 4 | MIT | Verbatim, permitted. |
| `ExpeRepair` | 4 | MIT | Verbatim, permitted. |
| `HyperAgent` | 7 | Apache-2.0 | Verbatim, permitted. |
| `joycode-agent` | 1 | MIT | Verbatim, permitted. |
| `KGCompass` | 3 | MIT | Verbatim, permitted. |
| `Lingma_SWE_GPT` | 6 | No LICENSE | **Verbatim — needs paraphrase.** |
| `Lingxi` | 4 | MIT | Verbatim, permitted. |
| `mini-SWE-agent` | 2 | MIT | Verbatim, permitted. |
| `OpenHands` | 8 | MIT | Verbatim, permitted. |
| `OrcaLoca` | 6 | MIT | Verbatim, permitted. |
| `patchwork` | 15 | AGPL-3.0-only | **Verbatim — needs paraphrase.** |
| `programmer` | 3 | Apache-2.0 | Verbatim, permitted. |
| `R2E-Gym` | 1 | Apache-2.0 | Verbatim, permitted. |
| `SWE_agent` | 9 | MIT | Verbatim, permitted. |
| `trae_agent` | 4 | MIT | Verbatim, permitted. |

Empty/tools-only entries (no prompts in EvoMas's catalog): `suna`.

## Restrictive-license prompts — paraphrase plan

Four repos carry verbatim upstream prompts under licenses that do not
permit redistribution of literal text:

- `Lingma_SWE_GPT` (6 agents) — no LICENSE file at upstream, default
  copyright applies.
- `auto_code_rover` (6 agents) — SONAR Source-Available v1.0 forbids
  competing / commercial use.
- `claude-coder` (1 agent, long prompt) — AGPL-3.0-or-later would
  require EvoMas's whole codebase to flip to AGPL to redistribute.
- `patchwork` (15 agents) — AGPL-3.0-only, same posture.

The intended fix is a **prompt-level paraphrase**: same agent role,
same input/output expectations, same instruction structure, but reworded
so the strings no longer match upstream byte-for-byte. The
re-implementation rule that applies to tool bodies also applies here
to prompt text. This work is pending an explicit go-ahead before any
file changes are made.

## Source-line traceability

Every prompt and every tool in the catalog carries a `source_url` in
its JSON entry, pointing to a specific line in the upstream project at
the exact commit EvoMas pins (the same SHAs listed in
`REPO_CATALOG.md`). Anyone auditing the integration can open that URL
and see what the EvoMas version was modeled after.

For tools, the URL points to the upstream function or class definition
that EvoMas's re-implementation mirrors. For prompts, it points to the
upstream file (often a `prompts.py`, `_constants.py`, or similar)
where the original text lives.
