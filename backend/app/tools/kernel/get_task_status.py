"""Kernel tool: get task status and metadata."""

import json

from app.tools import register
from app.tools.base import Tool, ToolResult


class GetTaskStatus(Tool):
    name = "get_task_status"
    description = "Get the current status, stage, and metadata of a task. Use to check progress or verify state before performing operations."
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
        },
        "required": ["task_id"],
    }

    async def execute(self, task_id: str) -> ToolResult:
        try:
            from app.models.task import get_task

            task = get_task(task_id)
            if task is None:
                return ToolResult(
                    success=False,
                    error="Task not found",
                    user_message=f"任务 {task_id[:8]} 不存在",
                )

            config = json.loads(task.get("config_json") or "{}")
            clips = json.loads(task.get("clips_json") or "[]")

            return ToolResult(
                success=True,
                data={
                    "task_id": task["id"],
                    "status": task["status"],
                    "stage": task.get("stage"),
                    "video_filename": task.get("video_filename"),
                    "subtitle_segment_count": task.get("subtitle_segment_count"),
                    "clips_count": len(clips),
                    "transcript_source": task.get("transcript_source"),
                    "transcript_modified_at": task.get("transcript_modified_at"),
                    "error_message": task.get("error_message"),
                    "failed_stage": task.get("failed_stage"),
                },
                user_message=(
                    f"任务状态: {task['status']}"
                    f"{' / ' + task['stage'] if task.get('stage') else ''}"
                    f", 字幕: {task.get('subtitle_segment_count', 0)} 条"
                    f", 片段: {len(clips)} 个"
                ),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"获取任务状态失败: {e}",
            )


_get_task_status = GetTaskStatus()
register(_get_task_status)
