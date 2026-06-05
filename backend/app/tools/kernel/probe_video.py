"""Kernel tool: probe video file metadata."""

from app.tools import register
from app.tools.base import Tool, ToolResult


class ProbeVideo(Tool):
    name = "probe_video"
    description = "Probe a video file to get metadata: duration, codec, resolution, FPS, subtitle streams. Use the task_id to probe the task's video."
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task UUID (auto-resolves video_path from DB)",
            },
        },
        "required": ["task_id"],
    }

    async def execute(self, task_id: str = "") -> ToolResult:
        if not task_id:
            return ToolResult(
                success=False,
                error="task_id is required",
                user_message="需要提供 task_id",
            )

        from app.models.task import get_task

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False,
                error="Task not found",
                user_message="任务不存在",
            )
        video_path = task.get("video_path", "")
        if not video_path:
            return ToolResult(
                success=False,
                error="No video associated with this task",
                user_message="该任务无关联视频文件",
            )
        try:
            from app.services.ffprobe import FFprobeError, probe

            info = probe(video_path)
            return ToolResult(
                success=True,
                data={
                    "duration_s": info.duration,
                    "width": info.width,
                    "height": info.height,
                    "codec": info.codec,
                    "container": info.container,
                    "has_video": info.has_video,
                    "subtitle_streams": info.subtitle_streams,
                    "fps": info.fps,
                    "fps_mode": info.fps_mode,
                },
                user_message=f"视频时长 {info.duration:.0f} 秒, "
                f"{info.width}x{info.height}, "
                f"字幕流: {len(info.subtitle_streams)} 个",
            )
        except FFprobeError as e:
            return ToolResult(success=False, error=str(e), user_message=str(e))
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"视频探测失败: {e}",
            )


_probe_video = ProbeVideo()
register(_probe_video)
