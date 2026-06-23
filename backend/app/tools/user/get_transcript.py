"""User tool: get transcript with validation."""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")


class GetTranscript(Tool):
    name = "get_transcript"
    description = (
        "Retrieve transcript segments with optional pagination. "
        "Use offset/limit to avoid loading too many segments at once."
    )
    user_facing = True
    requires_state = ["transcript_ready"]
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "offset": {
                "type": "integer",
                "description": "Zero-based start index for pagination",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Max segments to return (omit for all)",
                "default": 0,
            },
        },
        "required": ["task_id"],
    }

    async def execute(
        self,
        task_id: str,
        offset: int = 0,
        limit: int = 0,
    ) -> ToolResult:
        transcript_path = OUTPUT_DIR / task_id / "transcript.json"
        if not os.path.isfile(transcript_path):
            return ToolResult(
                success=False,
                error="Transcript not available",
                user_message="字幕文件暂不可用，请先提取字幕",
            )

        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                error="Transcript file corrupted",
                user_message="字幕文件格式错误",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"读取字幕失败: {e}",
            )

        from app.services.transcript_validator import validate_transcript

        valid_segments, _warnings = validate_transcript(segments)

        total = len(valid_segments)

        # Apply pagination
        if limit > 0 and offset >= 0:
            paginated = valid_segments[offset : offset + limit]
            next_offset = offset + limit if offset + limit < total else None
        else:
            paginated = valid_segments
            next_offset = None

        return ToolResult(
            success=True,
            data={
                "total": total,
                "offset": offset,
                "limit": limit if limit > 0 else total,
                "next_offset": next_offset,
                "segment_count": len(paginated),
                "segments": paginated,
            },
            user_message=(
                f"字幕共 {total} 条"
                + (f"（返回 {len(paginated)} 条，offset={offset}）" if limit > 0 else "")
            ),
        )


_get_transcript = GetTranscript()
register(_get_transcript)
