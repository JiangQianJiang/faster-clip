"""User tool: export clips to MP4."""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")


class ExportClips(Tool):
    name = "export_clips"
    description = "Export one or more clips to MP4 files. Can optionally burn subtitles into the video."
    user_facing = True
    requires_state = ["clips_ready"]
    produces_state = "exported"
    requires_checkpoint = True
    fatal_on_failure = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "clip_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Which clips to export (by zero-based index). Empty = export all.",
            },
            "burn_subtitle": {
                "type": "boolean",
                "description": "Whether to burn subtitles into the exported videos",
                "default": False,
            },
        },
        "required": ["task_id"],
    }

    async def execute(
        self,
        task_id: str,
        clip_indices: list[int] | None = None,
        burn_subtitle: bool = False,
    ) -> ToolResult:
        from app.models.task import get_task, update_task_status

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False, error="Task not found", user_message="任务不存在"
            )

        # Guard: reject mutations while task is processing, unless in ai_exporting stage
        if (
            task.get("status") in ("pending", "queued", "processing")
            and task.get("stage") != "ai_exporting"
        ):
            return ToolResult(
                success=False,
                error="Cannot export while task is processing",
                user_message="任务处理中，请等待完成后再试",
            )

        try:
            clips = json.loads(task.get("clips_json") or "[]")
        except json.JSONDecodeError:
            clips = []

        if not clips:
            return ToolResult(
                success=False,
                error="No clips to export",
                user_message="没有可导出的片段",
            )

        video_path = task.get("video_path", "")
        if not video_path or not os.path.isfile(video_path):
            return ToolResult(
                success=False,
                error="Video file not found",
                user_message="原始视频文件不存在",
            )

        # Validate and deduplicate clip indices
        if clip_indices:
            seen = set()
            selected_indices = []
            for i in clip_indices:
                if not isinstance(i, int) or i < 0 or i >= len(clips):
                    continue
                if clips[i].get("status") == "failed":
                    continue
                if i in seen:
                    continue
                seen.add(i)
                selected_indices.append(i)
        else:
            selected_indices = [
                i for i, c in enumerate(clips) if c.get("status") != "failed"
            ]

        if not selected_indices:
            return ToolResult(
                success=False,
                error="No valid clips selected",
                user_message="没有可导出的有效片段",
            )

        # Set processing before enqueue to avoid race with worker completion
        update_task_status(task_id, "processing", stage="ai_exporting")

        # Enqueue Celery task — ffmpeg runs in worker, not FastAPI
        from app.worker.celery_app import export_clips_task

        try:
            export_clips_task.apply_async(
                kwargs={
                    "task_id": task_id,
                    "clip_indices": selected_indices,
                    "burn_subtitle": burn_subtitle,
                },
                task_id=f"export_{task_id}",
            )
        except Exception as e:
            update_task_status(
                task_id, "error", failed_stage="ai_exporting", error_message=str(e)
            )
            return ToolResult(
                success=False, error=str(e), user_message=f"导出任务入队失败: {e}"
            )

        return ToolResult(
            success=True,
            data={"enqueued": True, "clip_count": len(selected_indices)},
            user_message=f"导出任务已启动，共 {len(selected_indices)} 个片段。完成后可在经典模式查看和下载。",
        )


_export_clips = ExportClips()
register(_export_clips)
