from app.src.tools.base_tool import BaseTool
from app.src.tools.tool_registry import ToolRegistry

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional
from langchain_core.tools import tool

class CommandApprovalDecision:
    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


class TerminalTool(BaseTool):
    _approval_callback = None
    _allowlist_file = None

    @classmethod
    def set_approval_callback(cls, callback):
        """
        Registers an optional callback used by GUI frontends.
        Callback signature: (command: str) -> str decision
        """
        cls._approval_callback = callback

    @classmethod
    def _project_root(cls) -> Path:
        return Path(__file__).resolve().parents[3]

    @classmethod
    def _default_allowlist_file(cls) -> Path:
        return cls._project_root() / "app" / "terminal_allowlist.json"

    @classmethod
    def _get_allowlist_file(cls) -> Path:
        if cls._allowlist_file:
            return Path(cls._allowlist_file)
        env_path = os.getenv("TERMINAL_TOOL_ALLOWLIST_FILE", "").strip()
        if env_path:
            return Path(env_path).expanduser().resolve()
        return cls._default_allowlist_file()

    @classmethod
    def _load_allowlist(cls) -> set[str]:
        path = cls._get_allowlist_file()
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(item).strip() for item in data if str(item).strip()}
        except Exception:
            return set()
        return set()

    @classmethod
    def _save_allowlist(cls, allowlist: set[str]) -> None:
        path = cls._get_allowlist_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = sorted(allowlist)
        path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")

    @classmethod
    def _cli_prompt_decision(cls, command: str) -> str:
        print("\n[TerminalTool] Command requires approval for:")
        print(f"  {command}")
        print("Choose: [y] allow once, [a] allow and add to allowlist, [N] deny")
        answer = input("> ").strip().lower()
        if answer in ["a", "allow", "add", "allowlist"]:
            return CommandApprovalDecision.ALLOW_ALWAYS
        if answer in ["y", "yes"]:
            return CommandApprovalDecision.ALLOW_ONCE
        return CommandApprovalDecision.DENY

    @classmethod
    def _approve_command(cls, command: str) -> bool:
        normalized = command.strip()
        allowlist = cls._load_allowlist()
        if normalized in allowlist:
            return True

        decision = None
        if callable(cls._approval_callback):
            try:
                decision = cls._approval_callback(normalized)
            except Exception:
                decision = None
        if not decision:
            decision = cls._cli_prompt_decision(normalized)

        if decision == CommandApprovalDecision.ALLOW_ALWAYS:
            allowlist.add(normalized)
            cls._save_allowlist(allowlist)
            return True
        return decision == CommandApprovalDecision.ALLOW_ONCE

    def get_tool_call(self) -> Callable:
        return self.terminal_tool

    @ToolRegistry.tool("terminal_tool")
    @tool
    def terminal_tool(command: str) -> str:
        """
        Executes a bash command in the terminal.
        Use this to run commands like 'ls', 'pwd', 'mkdir', or to execute scripts.
        
        Args:
            command: The bash command to execute.
        """
        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                return output if output else "OK"
            else:
                error = result.stderr.strip() or result.stdout.strip()
                return f"Error ({result.returncode}): {error}"
                
        except subprocess.TimeoutExpired:
            return "Error: Command execution timed out after 30 seconds."
        except Exception as e:
            return f"Unexpected error executing command: {e}"

    def terminal_tool_2(self, command: str) -> str:
        """
        Executes a command inside a Docker sandbox.
        """
        if not self._approve_command(command):
            return "Denied: Command not approved by user."

        try:
            docker_cmd = [
                "docker",
                "run",
                "--rm",
                "-i",
                f"--memory={self.memory}",
                f"--cpus={self.cpus}",
                "--network=none",
                f"{self.image}",
                f"{self.shell}",
                "-c",
                command,
            ]

            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                return output if output else "OK"
            else:
                error = result.stderr.strip() or result.stdout.strip()
                return f"Error ({result.returncode}): {error}"

        except subprocess.TimeoutExpired:
            return "Error: Timeout (30s)"
        except Exception as e:
            return f"System Error: {str(e)}"
