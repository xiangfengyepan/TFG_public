from abc import ABC, abstractmethod
from typing import Callable


class BaseTool(ABC):
    """
    The blueprint for all custom tools.
    """

    memory = "512m"
    cpus = 1
    image = "swe-bench"
    shell = "bash"

    @abstractmethod
    def get_tool_call(self) -> Callable:
        """
        Returns the specific method that Ollama will read and execute.
        Subclasses must implement this.
        """
        pass
