from typing import Any, Dict, List, Optional
from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from app.src.tools.tool_registry import ToolRegistry
from app.src.models.ollama_model import OllamaModelEnum


# TODO
class ToolBaseAgent:
    def __init__(
        self,
        model_name: str = OllamaModelEnum.QWEN_35_9B,
        temperature: float = 0,
        system_message: str = "You are a helpful AI assistant.",
        custom_tools: Optional[List[Any]] = None,
    ):
        self.llm = ChatOllama(
            model=model_name,
            temperature=temperature,
        )

        self.tools = (
            custom_tools
            if custom_tools is not None
            else list(ToolRegistry.tools.values())
        )

        self.prompt = self._get_prompt_template(system_message)

        self.agent = create_tool_calling_agent(self.llm, self.tools, self.prompt)

        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=10,
        )

    def _get_prompt_template(self, system_message: str) -> ChatPromptTemplate:
        """Defines the structure of the prompt for all agents."""
        return ChatPromptTemplate.from_messages(
            [
                ("system", system_message),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

    def run(self, user_input: str) -> str:
        """Standard entry point for running tasks."""
        try:
            response = self.agent_executor.invoke({"input": user_input})
            return response.get("output", "Agent failed to produce an output.")
        except Exception as e:
            return f"Execution Error: {str(e)}"
