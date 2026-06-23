"""User tool: query export progress for clips."""

import json

from app.tools import register
from app.tools.base import Tool, ToolResult


class GetExportProgress(Tool):
    name = "get_export_progress"
    description = (
        "Query the export progress of clips. Returns per-clip status "
        "(pending, success, failed) and any error messages. "
        "Use after export_clips to check results."
    )
    user_facing = True
    requires_state = ["exporting", "exported"]
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
        },
        "required": ["task_id"],
    }

    async def execute(self, task_id: str) -> ToolResult:
        from app.models.task import get_task

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False,
                error="Task not found",
                user_message="任务不存在",
            )

        try:
            clips = json.loads(task.get("clips_json") or "[]")
        except json.JSONDecodeError:
            clips = []

        if not clips:
            return ToolResult(
                success=True,
                data={"clips": [], "summary": "无片段"},
                user_message="没有可查询的片段",
            )

        statuses = [c.get("status", "pending") for c in clips]
        pending_count = statuses.count("pending")
        success_count = statuses.count("success")
        failed_count = statuses.count("failed")

        clip_statuses = []
        for i, c in enumerate(clips):
            entry = {
                "index": i,
                "start_time_s": c.get("start_time_s"),
                "end_time_s": c.get("end_time_s"),
                "reason": c.get("reason", ""),
                "status": c.get("status", "pending"),
            }
            if c.get("status") == "failed":
                entry["error"] = c.get("error", "导出失败")
            if c.get("filepath"):
                entry["filepath"] = c.get("filepath")
            clip_statuses.append(entry)

        if pending_count > 0:
            summary = (
                f"导出进行中: {success_count} 成功, {failed_count} 失败, {pending_count} 待处理"
            )
        elif failed_count > 0:
            summary = f"导出完成: {success_count} 成功, {failed_count} 失败"
        else:
            summary = f"全部导出成功: {success_count} 个片段"

        return ToolResult(
            success=True,
            data={
                "clips": clip_statuses,
                "total": len(clips),
                "success_count": success_count,
                "failed_count": failed_count,
                "pending_count": pending_count,
                "summary": summary,
            },
            user_message=summary,
        )


_get_export_progress = GetExportProgress()
register(_get_export_progress)
