"""Tool base classes — pure Python, no HTTP dependency."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Standard return value for all tool executions.

    Attributes:
        success: Whether the tool completed successfully.
        data: Result data on success (arbitrary JSON-serializable value).
        error: Error description on failure (human-readable).
        user_message: Chinese-language summary for display to the user.
    """

    success: bool
    data: Any = None
    error: str | None = None
    user_message: str = ""


class Tool:
    """Base class for all tools — both user-facing and kernel.

    Attributes:
        name: Unique tool identifier (snake_case, e.g. "run_asr").
        description: English description for the LLM (used in tool-calling).
        user_facing: True for tools the user can invoke directly via conversation.
        parameters: JSON Schema dict describing the tool's input parameters.
    """

    name: str = ""
    description: str = ""
    user_facing: bool = False
    parameters: dict[str, Any] = {}

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given parameters.

        Subclasses MUST override this. Exceptions are caught by the caller
        (ChatService) and must not propagate through this interface.
        """
        raise NotImplementedError
