"""Kernel tool: merge adjacent transcript segments."""

import json
import os

from app.tools import register
from app.tools.base import Tool, ToolResult


class MergeSegments(Tool):
    name = "merge_segments"
    description = "Merge a range of adjacent transcript segments into one. The merged segment takes the start time of the first and end time of the last."
    parameters = {
        "type": "object",
        "properties": {
            "transcript_path": {
                "type": "string",
                "description": "Path to transcript.json",
            },
            "start_index": {
                "type": "integer",
                "description": "First segment index to merge (inclusive)",
            },
            "end_index": {
                "type": "integer",
                "description": "Last segment index to merge (inclusive)",
            },
        },
        "required": ["transcript_path", "start_index", "end_index"],
    }

    async def execute(
        self,
        transcript_path: str,
        start_index: int,
        end_index: int,
    ) -> ToolResult:
        try:
            if not os.path.isfile(transcript_path):
                return ToolResult(
                    success=False,
                    error="Transcript file not found",
                    user_message="字幕文件不存在",
                )

            if start_index >= end_index:
                return ToolResult(
                    success=False,
                    error="start_index must be less than end_index",
                    user_message="起始索引必须小于结束索引",
                )

            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)

            if start_index < 0 or end_index >= len(segments):
                return ToolResult(
                    success=False,
                    error=f"Index range [{start_index}, {end_index}] out of range",
                    user_message="合并范围超出字幕总数",
                )

            merged_text = " ".join(
                s["text"] for s in segments[start_index : end_index + 1]
            )
            merged = {
                "start_time_s": segments[start_index]["start_time_s"],
                "end_time_s": segments[end_index]["end_time_s"],
                "text": merged_text,
            }

            new_segments = segments[:start_index] + [merged] + segments[end_index + 1 :]
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump(new_segments, f, ensure_ascii=False, indent=2)

            count = end_index - start_index + 1
            return ToolResult(
                success=True,
                data=merged,
                user_message=f"已合并第 {start_index + 1}-{end_index + 1} 条字幕（共 {count} 条）",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"字幕合并失败: {e}",
            )


_merge_segments = MergeSegments()
register(_merge_segments)
