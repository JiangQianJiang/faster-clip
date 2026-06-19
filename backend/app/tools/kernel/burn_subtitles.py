"""Kernel tool: burn subtitles into a video file."""

import os
import subprocess

from app.tools import register
from app.tools.base import Tool, ToolResult


class BurnSubtitles(Tool):
    name = "burn_subtitles"
    description = "Burn (hard-code) subtitles into a video file using ffmpeg. Produces a new video file with subtitles rendered into the frames."
    parameters = {
        "type": "object",
        "properties": {
            "video_path": {"type": "string", "description": "Path to source video"},
            "srt_path": {"type": "string", "description": "Path to SRT subtitle file"},
            "output_path": {
                "type": "string",
                "description": "Path for output video with burned subtitles",
            },
            "preset": {
                "type": "string",
                "description": "Optional subtitle style preset name (e.g. douyin, minimal)",
            },
            "overrides": {
                "type": "object",
                "description": "Optional preset parameter overrides (font_size, font_color, etc.)",
            },
        },
        "required": ["video_path", "srt_path", "output_path"],
    }

    async def execute(
        self,
        video_path: str,
        srt_path: str,
        output_path: str,
        preset: str | None = None,
        overrides: dict | None = None,
    ) -> ToolResult:
        try:
            if not os.path.isfile(video_path):
                return ToolResult(
                    success=False,
                    error="Video not found",
                    user_message="视频文件不存在",
                )
            if not os.path.isfile(srt_path):
                return ToolResult(
                    success=False, error="SRT not found", user_message="字幕文件不存在"
                )

            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            if preset:
                from app.services.subtitle_style import build_force_style

                style = build_force_style(preset, overrides)
                vf = f"subtitles={srt_path}:force_style={style}"
            else:
                vf = (
                    f"subtitles={srt_path}:force_style='FontSize=18,"
                    f"PrimaryColour=&HFFFFFF,OutlineColour=&H000000'"
                )
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "22",
                "-c:a",
                "aac",
                output_path,
            ]

            from app.config import settings

            ffmpeg_timeout = settings.ffmpeg_timeout_seconds
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=ffmpeg_timeout
            )

            if result.returncode != 0:
                stderr = (
                    result.stderr[-300:] if result.stderr else "ffmpeg 返回非零退出码"
                )
                return ToolResult(
                    success=False, error=stderr, user_message="字幕烧录失败"
                )

            return ToolResult(
                success=True,
                data={"output_path": output_path},
                user_message="字幕烧录完成",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, error="ffmpeg timed out", user_message="字幕烧录超时"
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), user_message=f"字幕烧录异常: {e}"
            )


_burn_subtitles = BurnSubtitles()
register(_burn_subtitles)
