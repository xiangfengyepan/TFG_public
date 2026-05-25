import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.tools import BaseTool

from evomas.tools.repo.augment_swebench_agent import AUGMENT_SWEBENCH_AGENT_TOOLS
from evomas.tools.repo.auto_code_rover import AUTO_CODE_ROVER_TOOLS
from evomas.tools.repo.claude_coder import CLAUDE_CODER_TOOLS
from evomas.tools.repo.composio import COMPOSIO_TOOLS
from evomas.tools.repo.debug_gym import DEBUG_GYM_TOOLS
from evomas.tools.repo.joycode_agent import JOYCODE_AGENT_TOOLS
from evomas.tools.repo.lingma_swe_gpt import LINGMA_SWE_GPT_TOOLS
from evomas.tools.lint_tools import run_flake8
from evomas.tools.repo.openhands import LOC_TOOLS, OPENHANDS_TOOLS
from evomas.tools.patch_tools import (
    apply_description_fix,
    apply_patch,
    generate_diff,
    normalize_patch,
    reset_repo,
)
from evomas.tools.repo.patchwork import PATCHWORK_TOOLS
from evomas.tools.repo_tools import derive_description_fix, list_files, read_file
from evomas.tools.search_tools import detect_bug_class, search_code
from evomas.tools.test_runner import run_tests
from evomas.tools.repo.suna import SUNA_TOOLS
from evomas.tools.repo.swe_agent import SWE_AGENT_TOOLS
from evomas.tools.repo.trae_agent import TRAE_AGENT_TOOLS

logger = logging.getLogger(__name__)


@dataclass
class ToolDescriptor:
    name: str
    description: str
    schema: dict[str, Any]
    invoke: Callable[[dict[str, Any]], Any]


@dataclass
class ToolRegistry:
    tools: dict[str, ToolDescriptor] = field(default_factory=dict)

    def register(self, tool: BaseTool) -> None:
        descriptor = _descriptor_from_tool(tool)
        self.tools[descriptor.name] = descriptor

    def unregister(self, name: str) -> None:
        """Remove a tool by name; no-op when not registered."""
        self.tools.pop(name, None)

    def list(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "inputSchema": t.schema}
            for t in self.tools.values()
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.tools:
            raise KeyError(f"unknown tool: {name}")
        logger.info("mcp.call %s args=%s", name, arguments)
        return self.tools[name].invoke(arguments or {})


def _descriptor_from_tool(tool: BaseTool) -> ToolDescriptor:
    name: str = tool.name
    description: str = (tool.description or "").strip()
    schema = _extract_schema(tool)

    def invoke(arguments: dict[str, Any]) -> Any:
        return tool.invoke(arguments)

    return ToolDescriptor(name=name, description=description, schema=schema, invoke=invoke)


def _extract_schema(tool: BaseTool) -> dict[str, Any]:
    try:
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            return args_schema.model_json_schema()
    except Exception as exc:
        logger.debug("could not extract pydantic schema for %s: %s", tool.name, exc)
    sig = inspect.signature(getattr(tool, "func", tool))  # pyright: ignore[reportArgumentType]
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in sig.parameters.values():
        if param.name in {"self", "cls"}:
            continue
        properties[param.name] = {"type": "string"}
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
    return {"type": "object", "properties": properties, "required": required}


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    # Core tools used by every topology.
    for tool in (read_file, list_files, search_code, run_flake8, apply_patch,
                 generate_diff, normalize_patch, reset_repo,
                 detect_bug_class, derive_description_fix, apply_description_fix,
                 run_tests):
        registry.register(tool)
    # Repo-variant bundles. Duplicate names across bundles are
    # last-registered-wins; bundles avoid collisions by re-exporting
    # canonicals instead of duplicating (see TOOL_AUDIT.md).
    for bundle in (
        OPENHANDS_TOOLS,
        LOC_TOOLS,
        AUTO_CODE_ROVER_TOOLS,
        AUGMENT_SWEBENCH_AGENT_TOOLS,
        CLAUDE_CODER_TOOLS,
        COMPOSIO_TOOLS,
        DEBUG_GYM_TOOLS,
        JOYCODE_AGENT_TOOLS,
        LINGMA_SWE_GPT_TOOLS,
        PATCHWORK_TOOLS,
        SUNA_TOOLS,
        SWE_AGENT_TOOLS,
        TRAE_AGENT_TOOLS,
    ):
        for tool in bundle:
            registry.register(tool)
    return registry


class MCPServer:
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry: ToolRegistry = registry or default_registry()

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        return self.registry.call(name, arguments)

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        method = message.get("method")
        params: dict[str, Any] = message.get("params") or {}
        msg_id = message.get("id")
        try:
            if method == "tools/list":
                return self._ok(msg_id, {"tools": self.registry.list()})
            if method == "tools/call":
                name = params.get("name") or ""
                arguments = params.get("arguments") or {}
                result = self.registry.call(name, arguments)
                return self._ok(msg_id, {"content": result})
            return self._error(msg_id, -32601, f"method not found: {method}")
        except KeyError as exc:
            return self._error(msg_id, -32602, str(exc))
        except Exception as exc:
            logger.exception("mcp server error: %s", exc)
            return self._error(msg_id, -32000, str(exc))

    @staticmethod
    def _ok(msg_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }


_server: MCPServer | None = None


def get_server() -> MCPServer:
    global _server
    if _server is None:
        _server = MCPServer()
    return _server


_TOOL_REPO_OWNER_CACHE: dict[str, str] | None = None


def tool_repo_owner_map() -> dict[str, str]:
    """`tool_name -> owner` map. The owner is the `evomas/tools/<repo>/`
    folder the tool was registered from, or `"evomas"` for the top-level
    `evomas/tools/*.py` helpers (apply_patch, read_file, search_code, …).

    Cached at module level so repeated calls don't re-walk the bundles.
    Used by the topology page's `/api/tools` endpoint to group the
    Add-tool dropdown by owner; could just as well be used by a CLI
    `evomas tools list --owner X` in the future.
    """
    global _TOOL_REPO_OWNER_CACHE
    if _TOOL_REPO_OWNER_CACHE is not None:
        return _TOOL_REPO_OWNER_CACHE
    bundles: list[tuple[str, Any]] = [
        ("augment_swebench_agent", AUGMENT_SWEBENCH_AGENT_TOOLS),
        ("auto_code_rover",        AUTO_CODE_ROVER_TOOLS),
        ("claude_coder",           CLAUDE_CODER_TOOLS),
        ("composio",               COMPOSIO_TOOLS),
        ("debug_gym",              DEBUG_GYM_TOOLS),
        ("joycode_agent",          JOYCODE_AGENT_TOOLS),
        ("lingma_swe_gpt",         LINGMA_SWE_GPT_TOOLS),
        # OpenHands ships two bundles under one folder; share the owner.
        ("openhands",              OPENHANDS_TOOLS),
        ("openhands",              LOC_TOOLS),
        ("patchwork",              PATCHWORK_TOOLS),
        ("suna",                   SUNA_TOOLS),
        ("swe_agent",              SWE_AGENT_TOOLS),
        ("trae_agent",             TRAE_AGENT_TOOLS),
    ]
    out: dict[str, str] = {}
    for owner, bundle in bundles:
        for tool in bundle:
            name = getattr(tool, "name", None)
            if not name:
                continue
            # First-seen owner wins (handles cross-bundle re-exports).
            out.setdefault(name, owner)
    _TOOL_REPO_OWNER_CACHE = out
    return out
