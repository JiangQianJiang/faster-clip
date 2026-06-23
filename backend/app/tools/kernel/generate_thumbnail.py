"""Kernel tool: generate a thumbnail from a video at a given time."""

import os
import subprocess

from app.tools import register
from app.tools.base import Tool, ToolResult


class GenerateThumbnail(Tool):
    name = "generate_thumbnail"
    description = "Generate a JPEG thumbnail image from a video at a specified timestamp."
    parameters = {
        "type": "object",
        "properties": {
            "video_path": {"type": "string", "description": "Path to source video"},
            "output_path": {
                "type": "string",
                "description": "Path for output JPEG thumbnail",
            },
            "time_s": {
                "type": "number",
                "description": "Timestamp in seconds to capture the frame",
            },
        },
        "required": ["video_path", "output_path", "time_s"],
    }

    async def execute(
        self,
        video_path: str,
        output_path: str,
        time_s: float,
    ) -> ToolResult:
        try:
            if not os.path.isfile(video_path):
                return ToolResult(
                    success=False,
                    error="Video not found",
                    user_message="视频文件不存在",
                )

            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(time_s),
                "-i",
                video_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
                output_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0 or not os.path.isfile(output_path):
                return ToolResult(
                    success=False,
                    error="Thumbnail generation failed",
                    user_message="缩略图生成失败",
                )

            return ToolResult(
                success=True,
                data={"thumbnail_path": output_path, "captured_at_s": time_s},
                user_message=f"缩略图已生成 (时间点: {time_s:.1f}s)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="Thumbnail generation timed out",
                user_message="缩略图生成超时",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), user_message=f"缩略图生成异常: {e}")


_generate_thumbnail = GenerateThumbnail()
register(_generate_thumbnail)
