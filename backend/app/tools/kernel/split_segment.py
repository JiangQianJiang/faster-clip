"""Kernel tool: split a transcript segment into two."""

import json
import os

from app.tools import register
from app.tools.base import Tool, ToolResult


class SplitSegment(Tool):
    name = "split_segment"
    description = "Split a transcript segment at a given time point, creating two segments. The first part keeps the original start time, the second part gets the new end time."
    parameters = {
        "type": "object",
        "properties": {
            "transcript_path": {
                "type": "string",
                "description": "Path to transcript.json",
            },
            "index": {"type": "integer", "description": "Segment index to split"},
            "split_time_s": {
                "type": "number",
                "description": "Time in seconds where the split occurs",
            },
        },
        "required": ["transcript_path", "index", "split_time_s"],
    }

    async def execute(
        self,
        transcript_path: str,
        index: int,
        split_time_s: float,
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
                    error=f"Index {index} out of range",
                    user_message=f"段落索引 {index + 1} 超出范围",
                )

            seg = segments[index]
            if split_time_s <= seg["start_time_s"] or split_time_s >= seg["end_time_s"]:
                return ToolResult(
                    success=False,
                    error=f"Split time {split_time_s}s not within segment [{seg['start_time_s']}s, {seg['end_time_s']}s]",
                    user_message="分割时间点不在段落时间范围内",
                )

            first = {
                "start_time_s": seg["start_time_s"],
                "end_time_s": split_time_s,
                "text": seg["text"],
            }
            second = {
                "start_time_s": split_time_s,
                "end_time_s": seg["end_time_s"],
                "text": seg["text"],
            }

            new_segments = segments[:index] + [first, second] + segments[index + 1 :]
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump(new_segments, f, ensure_ascii=False, indent=2)

            return ToolResult(
                success=True,
                data={"first": first, "second": second},
                user_message=f"已在 {split_time_s:.1f}s 处拆分第 {index + 1} 条字幕",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"字幕拆分失败: {e}",
            )


_split_segment = SplitSegment()
register(_split_segment)
