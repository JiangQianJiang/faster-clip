"""Tool registry for AI chat mode.

All tools — both user-facing and kernel — are registered here.
The registry is the single source of truth for tool discovery.
"""

from app.tools.base import Tool
from app.tools.base import ToolResult as ToolResult

_registry: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """Register a tool. Raises ValueError on duplicate name."""
    if tool.name in _registry:
        raise ValueError(f"Tool '{tool.name}' is already registered")
    _registry[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    """Look up a tool by name."""
    return _registry.get(name)


def list_user_tools() -> list[Tool]:
    """Return all user-facing tools."""
    return [t for t in _registry.values() if t.user_facing]


def list_kernel_tool_instances() -> list[Tool]:
    """Return all kernel (internal) tool instances."""
    return [t for t in _registry.values() if not t.user_facing]


def list_kernel_tools() -> list[dict]:
    """Return kernel tool schemas as Anthropic-format dicts.

    Each dict contains: name, description, input_schema.
    """
    return _tools_to_schemas(list_kernel_tool_instances())


def _tools_to_schemas(tools: list[Tool]) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
    ]


def get_tool_schemas(for_user: bool = True) -> list[dict]:
    """Generate Anthropic-format tool schemas for tool calling."""
    tools = list_user_tools() if for_user else list_kernel_tool_instances()
    return _tools_to_schemas(tools)


# Auto-register all kernel tools on import
from app.tools.kernel import probe_video as _  # noqa
from app.tools.kernel import extract_embedded_subtitles as _  # noqa
from app.tools.kernel import run_asr as _  # noqa
from app.tools.kernel import parse_subtitle_file as _  # noqa
from app.tools.kernel import update_segment as _  # noqa
from app.tools.kernel import merge_segments as _  # noqa
from app.tools.kernel import split_segment as _  # noqa
from app.tools.kernel import llm_analyze as _  # noqa
from app.tools.kernel import ffmpeg_export as _  # noqa
from app.tools.kernel import burn_subtitles as _  # noqa
from app.tools.kernel import generate_thumbnail as _  # noqa
from app.tools.kernel import get_task_status as _  # noqa

# Auto-register all user-facing tools on import
from app.tools.user import get_transcript as _  # noqa
from app.tools.user import edit_transcript as _  # noqa
from app.tools.user import analyze_highlights as _  # noqa
from app.tools.user import export_clips as _  # noqa
from app.tools.user import search_transcript as _  # noqa
from app.tools.user import add_clip as _  # noqa
from app.tools.user import refine_clips as _  # noqa
from app.tools.user import delete_clip as _  # noqa

from app.tools.user import apply_subtitle_style as _  # noqa
from app.tools.user import get_export_progress as _  # noqa
from app.tools.user import regenerate_subtitles as _  # noqa
from app.tools.user import run_asr as _  # noqa
