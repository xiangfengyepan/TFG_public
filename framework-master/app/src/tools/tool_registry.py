from __future__ import annotations

from paths import FRAMEWORK_BASE_DIR

import json
import os
import subprocess
from typing import Any, Callable, Dict, Mapping

import pkgutil
import importlib
import app.src.tools as tools_package


class ToolRegistry:
    tools: Dict[str, Callable] = {}

    @classmethod
    def validate_environment(cls):
        if not os.getenv("DOCKER_IMAGE"):
            raise ValueError("DOCKER_IMAGE is not set")

        if not os.getenv("TARGET_ROOT_DIR"):
            raise ValueError("TARGET_ROOT_DIR is not set")
    @classmethod
    def check_docker_running(cls):
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise RuntimeError("Docker is not running or not accessible")
        except FileNotFoundError:
            raise RuntimeError("Docker is not installed")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker check timed out")

    @classmethod
    def _register(cls, name: str, func: Callable):
        if name in cls.tools:
            raise ValueError(f"Tool '{name}' already registered")

        cls.tools[name] = func

    @classmethod
    def tool(cls, name: str):
        def decorator(func: Callable):
            cls._register(name, func)
            return func

        return decorator

    @classmethod
    def execute(cls, name: str, args: Mapping[str, Any]):
        # cls.validate_environment()
        # cls._check_docker_running()
        if name not in cls.tools:
            raise ValueError(f"Tool '{name}' not found")

        print(f"[DEBUG]: {name} {args}")
        return cls._execute_in_docker(name, args)

    @classmethod
    def _run_local_fallback(cls, name: str, args: Mapping[str, Any]):
        # TODO hangle when docker not work
        print("error")
        return cls.tools[name].invoke(args)


    @classmethod
    def load_all_tools(cls):
        for module_info in pkgutil.iter_modules(tools_package.__path__):
            module_name = module_info.name
            importlib.import_module(f"app.src.tools.{module_name}")

    @classmethod
    def _execute_in_docker(cls, name: str, args: Mapping[str, Any]):
        payload = json.dumps({"name": name, "args": dict(args)}, ensure_ascii=True)
        script = (
            "import json, os\n"
            "from app.src.tools.tool_registry import ToolRegistry\n"
            "ToolRegistry.load_all_tools()\n"
            "payload = json.loads(os.environ.get('TOOL_REGISTRY_PAYLOAD', '{}'))\n"
            "tool_name = payload.get('name')\n"
            "tool_args = payload.get('args', {})\n"
            "if tool_name not in ToolRegistry.tools:\n"
            "    raise ValueError(f\"Tool '{tool_name}' not found in container\")\n"
            "result = ToolRegistry.tools[tool_name].invoke(tool_args)\n"
            "print(json.dumps({'ok': True, 'result': result}, default=str))\n"
        )
        # TODO check

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network=none",
            "--cpus=1",
            "--memory=512m",
            "-e",
            "TARGET_ROOT_DIR=/workspace",
            "-e",
            f"TOOL_REGISTRY_PAYLOAD={payload}",
            "-v",
            f"{os.getenv("TARGET_ROOT_DIR")}:/workspace",
            "-v",
            f"{FRAMEWORK_BASE_DIR}:/framework",
            "-w",
            "/workspace",
            os.getenv("DOCKER_IMAGE"),
            "python",
            "-c",
            script,
        ]

        try:
            # TODO timeout
            timeout = 60
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            err = (result.stderr or "").strip()
            out = (result.stdout or "").strip()

            if not out or result.returncode != 0:
                return err if err else out

            try:
                parsed = json.loads(out.splitlines()[-1])
                if isinstance(parsed, dict) and parsed.get("ok"):
                    return parsed.get("result")
            except json.JSONDecodeError:
                return f"Error decoding output. Raw output:\n{out}\nErrors:\n{err}"
        except subprocess.TimeoutExpired:
            return f"Error: Tool execution exceeded the {timeout}-second time limit."
        except Exception as e:
            return f"Unexpected error executing in Docker: {e}"
