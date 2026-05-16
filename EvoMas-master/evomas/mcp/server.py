import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.tools import BaseTool

from evomas.tools.augment_swebench_agent import AUGMENT_SWEBENCH_AGENT_TOOLS
from evomas.tools.auto_code_rover import AUTO_CODE_ROVER_TOOLS
from evomas.tools.claude_coder import CLAUDE_CODER_TOOLS
from evomas.tools.composio import COMPOSIO_TOOLS
from evomas.tools.debug_gym import DEBUG_GYM_TOOLS
from evomas.tools.joycode_agent import JOYCODE_AGENT_TOOLS
from evomas.tools.lingma_swe_gpt import LINGMA_SWE_GPT_TOOLS
from evomas.tools.lint_tools import run_flake8
from evomas.tools.openhands import LOC_TOOLS, OPENHANDS_ALIAS_TOOLS, OPENHANDS_TOOLS
from evomas.tools.patch_tools import (
    apply_description_fix,
    apply_patch,
    generate_diff,
    normalize_patch,
    reset_repo,
)
from evomas.tools.patchwork import PATCHWORK_TOOLS
from evomas.tools.repo_tools import derive_description_fix, list_files, read_file
from evomas.tools.search_tools import detect_bug_class, search_code
from evomas.tools.suna import SUNA_TOOLS
from evomas.tools.swe_agent import SWE_AGENT_TOOLS
from evomas.tools.trae_agent import TRAE_AGENT_TOOLS

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
        """Remove a tool by name; no-op when the name isn't registered.
        Used by the per-inference runtime tool fetcher to clean up tools it
        added at the start of an inference run."""
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
    sig = inspect.signature(getattr(tool, "func", tool))
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
    for tool in (read_file, list_files, search_code, run_flake8, apply_patch,
                 generate_diff, normalize_patch, reset_repo,
                 detect_bug_class, derive_description_fix, apply_description_fix):
        registry.register(tool)
    # OpenHands-shape tools (used by the openhands.json topology). Registering
    # them globally keeps the MCP catalog uniform; per-agent allow-lists in the
    # unified config still gate which tools each agent can call.
    for tool in (*OPENHANDS_TOOLS, *LOC_TOOLS, *OPENHANDS_ALIAS_TOOLS):
        registry.register(tool)
    # Repo-variant tools (one bundle per `evomas/tools/<repo>/` package). Each
    # bundle is a tuple of LangChain `@tool` callables — see the per-repo
    # `__init__.py` for the list. Duplicate names across bundles are fine:
    # last-registered wins, and same name = same intended semantics.
    for bundle in (
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
