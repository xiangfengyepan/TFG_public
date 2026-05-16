"""OpenHands tool re-implementations.

Schemas mirror the upstream OpenHands tool definitions
(`openhands/agenthub/codeact_agent/tools/*` and
`openhands/agenthub/readonly_agent/tools/*`); descriptions are kept verbatim
where possible. Implementations are lightweight Python equivalents that work
inside the EvoMas workspace (subprocess + filesystem only — no IPython kernel,
no Playwright, no security_risk plumbing).
"""

from evomas.tools.openhands.tools import (
    OPENHANDS_TOOLS,
    bash,
    condensation_request,
    edit_file,
    execute_bash,
    execute_ipython_cell,
    finish,
    glob_,
    grep,
    str_replace_editor,
    think,
    view,
)
from evomas.tools.openhands.loc_tools import (
    LOC_TOOLS,
    explore_tree_structure,
    get_entity_contents,
    search_code_snippets,
)
from evomas.tools.openhands.aliases import (
    OPENHANDS_ALIAS_TOOLS,
    browser,
    ipython,
    llm_based_edit,
)

__all__ = [
    "OPENHANDS_TOOLS",
    "LOC_TOOLS",
    "OPENHANDS_ALIAS_TOOLS",
    "browser",
    "ipython",
    "llm_based_edit",
    "think",
    "str_replace_editor",
    "execute_ipython_cell",
    "edit_file",
    "condensation_request",
    "finish",
    "execute_bash",
    "bash",
    "grep",
    "glob_",
    "view",
    "get_entity_contents",
    "search_code_snippets",
    "explore_tree_structure",
]
