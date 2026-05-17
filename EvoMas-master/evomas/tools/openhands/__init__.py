"""OpenHands tool re-implementations — one per file under the
upstream-aligned tool names.

Each module exposes a single `@tool`-decorated function whose name
matches the upstream OpenHands tool identifier (e.g. `BrowserTool`,
`CmdRunTool`, …) so prompts referencing those names continue to
resolve. Implementations are EvoMas-authored Python wrappers — they
share a small `_helpers` module for output truncation, file viewing,
edit-undo, and bash dispatch.
"""

from evomas.tools.openhands.BrowserTool import BrowserTool
from evomas.tools.openhands.CmdRunTool import CmdRunTool
from evomas.tools.openhands.CondensationRequestTool import CondensationRequestTool
from evomas.tools.openhands.FinishTool import FinishTool
from evomas.tools.openhands.GlobTool import GlobTool
from evomas.tools.openhands.GrepTool import GrepTool
from evomas.tools.openhands.IPythonTool import IPythonTool
from evomas.tools.openhands.LLMBasedFileEditTool import LLMBasedFileEditTool
from evomas.tools.openhands.StrReplaceEditorTool import StrReplaceEditorTool
from evomas.tools.openhands.ThinkTool import ThinkTool
from evomas.tools.openhands.ViewTool import ViewTool

from evomas.tools.openhands.loc_tools import (
    LOC_TOOLS,
    explore_tree_structure,
    get_entity_contents,
    search_code_snippets,
)

OPENHANDS_TOOLS = (
    BrowserTool,
    CmdRunTool,
    CondensationRequestTool,
    FinishTool,
    GlobTool,
    GrepTool,
    IPythonTool,
    LLMBasedFileEditTool,
    StrReplaceEditorTool,
    ThinkTool,
    ViewTool,
)

__all__ = [
    "OPENHANDS_TOOLS",
    "LOC_TOOLS",
    "BrowserTool",
    "CmdRunTool",
    "CondensationRequestTool",
    "FinishTool",
    "GlobTool",
    "GrepTool",
    "IPythonTool",
    "LLMBasedFileEditTool",
    "StrReplaceEditorTool",
    "ThinkTool",
    "ViewTool",
    "explore_tree_structure",
    "get_entity_contents",
    "search_code_snippets",
]
