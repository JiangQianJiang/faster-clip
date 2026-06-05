"""Kernel tool: update a single transcript segment."""

import json
import os

from app.tools import register
from app.tools.base import Tool, ToolResult


class UpdateSegment(Tool):
    name = "update_segment"
    description = "Update a single transcript segment's text or timing by index."
    parameters = {
        "type": "object",
        "properties": {
            "transcript_path": {
                "type": "string",
                "description": "Path to transcript.json",
            },
            "index": {
                "type": "integer",
                "description": "Zero-based segment index to update",
            },
            "text": {
                "type": "string",
                "description": "New text for the segment (optional)",
            },
            "start_time_s": {
                "type": "number",
                "description": "New start time in seconds (optional)",
            },
            "end_time_s": {
                "type": "number",
                "description": "New end time in seconds (optional)",
            },
        },
        "required": ["transcript_path", "index"],
    }

    async def execute(
        self,
        transcript_path: str,
        index: int,
        text: str | None = None,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
    ) -> ToolResult:
        try:
            if not os.path.isfile(transcript_path):
                return ToolResult(
                    success=False,
                    error="Transcript file not found",
                    user_message="字幕文件不存在",
                )

            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)

            if index < 0 or index >= len(segments):
                return ToolResult(
                    success=False,
                    error=f"Index {index} out of range (0-{len(segments) - 1})",
                    user_message=f"段落索引 {index + 1} 超出范围",
                )

            old = segments[index]
            if text is not None:
                old["text"] = text
            if start_time_s is not None:
                old["start_time_s"] = start_time_s
            if end_time_s is not None:
                old["end_time_s"] = end_time_s

            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)

            return ToolResult(
                success=True,
                data=old,
                user_message=f"已更新第 {index + 1} 条字幕",
            )
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                error="Transcript file is not valid JSON",
                user_message="字幕文件格式损坏",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"字幕更新失败: {e}",
            )


_update_segment = UpdateSegment()
register(_update_segment)
