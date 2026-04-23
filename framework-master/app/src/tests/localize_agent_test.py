from paths import LOCALIZE_AGENT_JSON

from app.src.models.ollama_model import OllamaWrapper, MessageRoleEnum
from app.src.tools.terminal_tool import TerminalTool
from app.src.models.response_format import FileReport

import json


class LocalizeAgent:
    def __init__(self):
        self.model = OllamaWrapper()
        self.terminal_tool = TerminalTool()
        self.available_tools = [self.terminal_tool.get_tool_call()]

        with open(LOCALIZE_AGENT_JSON, "r") as f:
            self.hyperparameters = json.load(f)

        self.system_prompt = """You are an autonomous File Locator Agent operating in an unknown environment (either Windows/PowerShell or Linux/WSL/Bash). Your sole purpose is to find specific files or file contents within a repository based on the user's request.
        All terminal commands must be valid for the specific shell you are targeting.

        CRITICAL INSTRUCTIONS:
        1. ENVIRONMENT CHECK & INITIAL ACTION: Your very first tool call must be to determine exactly which shell you are operating in. Run `echo $SHELL` to check for a Bash environment, or `$PSVersionTable` to check for a PowerShell environment. Once confirmed, identify your root working directory using `pwd` (Bash) or `Get-Location` (PowerShell).
        2. SEARCH SCOPE & EXCLUSIONS: The repository has multiple levels of nested directories. You must search recursively. Use commands like `find` and `grep` for Bash, or `Get-ChildItem` and `Select-String` for PowerShell. **CRITICAL: You MUST actively exclude common noise directories to prevent system hangs. Do not search inside Python virtual environments (regardless of whether they are named `venv`, `.venv`, `env`, etc.), `node_modules`, `.git`, `__pycache__`, or compiled build/bin folders.** Your search MUST NEVER leave the root folder identified by your initial command. NEVER search global paths (like `~` or `$env:USERPROFILE`).
        3. ZERO INTERACTION: You are 100% autonomous. NEVER ask the user questions, offer options (e.g., "Would you like me to..."), or wait for guidance.
        4. RELENTLESS EXECUTION: DO NOT explain your plan. If a command fails or a file is missing, immediately deduce the next logical search strategy and execute the tool.
        5. MISSION COMPLETE: Once you have successfully located the requested file(s), use the tool to read its content (e.g., `cat` for Bash or `Get-Content` for PowerShell). Your final action is to output the requested file paths and their contents.
        """

    def run(self, task_description: str) -> str:
        """
        Executes the localization loop.
        Returns the final structured output as a JSON string (or parsed dictionary).
        """
        print("\n\033[95m[LocalizeAgent] Starting task...\033[0m")

        response = self.model.chat(
            [
                {"role": MessageRoleEnum.system, "content": self.system_prompt},
                {"role": MessageRoleEnum.user, "content": task_description},
            ],
            tools=self.available_tools,
            stream=True,
            # think=True,
        )

        while response.message and getattr(response.message, "tool_calls", None):
            response = self.model.tool_chat(response.message.tool_calls)

            response = self.model.chat(
                [
                    {
                        "role": MessageRoleEnum.assistant,
                        "content": response.message.content or "",
                    },
                    {
                        "role": MessageRoleEnum.user,
                        "content": "The tool has returned the data above. If the original task is now complete, provide the final solution. If more steps are needed, call the next tool.",
                    },
                ],
                tools=self.available_tools,
                stream=True,
                # think=True,
                **self.hyperparameters,
            )

        print(
            "\n\033[95m[LocalizeAgent] Task complete. Generating FileReport...\033[0m"
        )

        final_response = self.model.chat(
            [
                {
                    "role": MessageRoleEnum.user,
                    "content": response.message.content
                    or "Summarize the files located.",
                }
            ],
            response_format=FileReport,
            think=True,
            stream=False,
            **self.hyperparameters,
        )

        return final_response.message.content

if __name__ == "__main__":
    agent = LocalizeAgent()
    agent.run(task_description="")