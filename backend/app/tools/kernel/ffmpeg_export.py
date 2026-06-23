"""Kernel tool: export a clip using ffmpeg."""

import os
import subprocess

from app.tools import register
from app.tools.base import Tool, ToolResult


class FFmpegExport(Tool):
    name = "ffmpeg_export"
    description = "Export a video clip using ffmpeg. Cuts the segment between start and end times (with buffer), burns subtitles if requested, and generates output."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID for output path resolution",
            },
            "video_path": {
                "type": "string",
                "description": "Absolute path to source video",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory for output files",
            },
            "clip_index": {"type": "integer", "description": "Zero-based clip index"},
            "start_time_s": {
                "type": "number",
                "description": "Clip start time in seconds",
            },
            "end_time_s": {"type": "number", "description": "Clip end time in seconds"},
            "buffer_seconds": {
                "type": "number",
                "description": "Buffer seconds around clip",
                "default": 3,
            },
            "burn_subtitle": {
                "type": "boolean",
                "description": "Whether to burn subtitles into the video",
                "default": False,
            },
            "segments": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Subtitle segments for the clip (needed when burn_subtitle is True)",
            },
            "subtitle_preset": {
                "type": "string",
                "description": "Optional subtitle style preset name (e.g. douyin, minimal)",
            },
            "subtitle_overrides": {
                "type": "object",
                "description": "Optional preset parameter overrides",
            },
        },
        "required": [
            "task_id",
            "video_path",
            "output_dir",
            "clip_index",
            "start_time_s",
            "end_time_s",
        ],
    }

    async def execute(
        self,
        task_id: str,
        video_path: str,
        output_dir: str,
        clip_index: int,
        start_time_s: float,
        end_time_s: float,
        buffer_seconds: float = 3,
        burn_subtitle: bool = False,
        segments: list[dict] | None = None,
        subtitle_preset: str | None = None,
        subtitle_overrides: dict | None = None,
    ) -> ToolResult:
        try:
            if not os.path.isfile(video_path):
                return ToolResult(
                    success=False,
                    error="Video file not found",
                    user_message="视频文件不存在",
                )

            os.makedirs(output_dir, exist_ok=True)
            export_start = max(0, start_time_s - buffer_seconds)
            export_end = end_time_s + buffer_seconds
            duration = export_end - export_start
            output_path = os.path.join(output_dir, f"clip_{clip_index:03d}.mp4")

            from app.config import settings

            ffmpeg_timeout = settings.ffmpeg_timeout_seconds

            if burn_subtitle and segments:
                # Build temporary subtitle filter
                srt_path = os.path.join(output_dir, f"clip_{clip_index:03d}_temp.srt")
                try:
                    from app.services.subtitle import segments_to_srt

                    with open(srt_path, "w", encoding="utf-8") as f:
                        f.write(segments_to_srt(segments))
                except Exception:
                    srt_path = None

                if srt_path and os.path.isfile(srt_path):
                    if subtitle_preset:
                        from app.services.subtitle_style import build_force_style

                        style = build_force_style(subtitle_preset, subtitle_overrides)
                        vf = f"subtitles={srt_path}:force_style={style}"
                    else:
                        vf = (
                            f"subtitles={srt_path}:force_style='FontSize=18,"
                            f"PrimaryColour=&HFFFFFF,OutlineColour=&H000000'"
                        )
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        str(export_start),
                        "-i",
                        video_path,
                        "-t",
                        str(duration),
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
                else:
                    burn_subtitle = False

            if not burn_subtitle:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(export_start),
                    "-i",
                    video_path,
                    "-t",
                    str(duration),
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

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=ffmpeg_timeout)

            # Clean up temp srt
            if burn_subtitle:
                srt_path = os.path.join(output_dir, f"clip_{clip_index:03d}_temp.srt")
                if os.path.isfile(srt_path):
                    os.unlink(srt_path)

            if result.returncode != 0:
                stderr = result.stderr[-300:] if result.stderr else "ffmpeg 返回非零退出码"
                return ToolResult(
                    success=False,
                    error=stderr,
                    user_message=f"片段 {clip_index + 1} 导出失败: ffmpeg 错误",
                )

            if not os.path.isfile(output_path):
                return ToolResult(
                    success=False,
                    error="ffmpeg completed but no output file found",
                    user_message=f"片段 {clip_index + 1} 导出失败: 未生成输出文件",
                )

            return ToolResult(
                success=True,
                data={
                    "filepath": output_path,
                    "start_time_s": start_time_s,
                    "end_time_s": end_time_s,
                    "duration_s": end_time_s - start_time_s,
                    "export_start_time_s": export_start,
                    "export_end_time_s": export_end,
                },
                user_message=f"片段 {clip_index + 1} 导出成功 ({end_time_s - start_time_s:.0f}s)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="ffmpeg timed out",
                user_message=f"片段 {clip_index + 1} 导出超时",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"片段 {clip_index + 1} 导出异常: {e}",
            )


_ffmpeg_export = FFmpegExport()
register(_ffmpeg_export)
