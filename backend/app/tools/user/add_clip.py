"""User tool: add a clip by time range (bypasses LLM analysis)."""

import json
import os

from app.tools import register
from app.tools.base import Tool, ToolResult


class AddClip(Tool):
    name = "add_clip"
    description = (
        "Create a clip directly from a time range, bypassing LLM analysis. "
        "Use this when the user specifies exact times (e.g. 'cut 0:01 to 5:00'). "
        "Overlaps with existing clips are allowed."
    )
    user_facing = True
    requires_state = ["transcript_ready"]
    produces_state = "clips_ready"
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "start_time_s": {
                "type": "number",
                "description": "Clip start time in seconds",
            },
            "end_time_s": {"type": "number", "description": "Clip end time in seconds"},
        },
        "required": ["task_id", "start_time_s", "end_time_s"],
    }

    async def execute(
        self,
        task_id: str,
        start_time_s: float,
        end_time_s: float,
    ) -> ToolResult:
        from app.models.task import get_task, update_task_status

        if start_time_s < 0 or end_time_s < 0:
            return ToolResult(
                success=False,
                error="Negative time values are not allowed",
                user_message="时间不能为负数",
            )

        if start_time_s >= end_time_s:
            return ToolResult(
                success=False,
                error="start_time_s must be less than end_time_s",
                user_message="开始时间必须小于结束时间",
            )

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False,
                error="Task not found",
                user_message="任务不存在",
            )

        # Guard: reject mutations while task is processing (any stage)
        if task.get("status") in ("queued", "processing"):
            return ToolResult(
                success=False,
                error="Cannot add clips while task is processing",
                user_message="任务处理中，无法添加片段，请等待完成",
            )

        try:
            clips = json.loads(task.get("clips_json") or "[]")
        except json.JSONDecodeError:
            clips = []

        # Validate bounds against task configuration and video duration
        config = json.loads(task.get("config_json") or "{}")
        max_dur = config.get("clip_max_duration", 120)
        dur = end_time_s - start_time_s
        if dur > max_dur:
            end_time_s = start_time_s + max_dur

        # Clamp to video duration if available
        video_path = task.get("video_path", "")
        if video_path and os.path.isfile(video_path):
            try:
                from app.services.ffprobe import probe

                info = probe(video_path)
                if start_time_s >= info.duration:
                    return ToolResult(
                        success=False,
                        error="start_time_s is beyond video duration",
                        user_message=f"开始时间超出视频时长（{info.duration:.0f}s）",
                    )
                if end_time_s > info.duration:
                    end_time_s = info.duration
            except Exception:
                pass

        if start_time_s >= end_time_s:
            return ToolResult(
                success=False,
                error="Invalid time range after bounds validation",
                user_message="时间范围无效",
            )

        new_clip = {
            "start_time_s": start_time_s,
            "end_time_s": end_time_s,
            "score": 0,
            "reason": "手动添加",
            "status": "pending",
        }
        clips.append(new_clip)

        update_task_status(
            task_id,
            task["status"],
            clips_json=json.dumps(clips, ensure_ascii=False),
            empty_clips_reason=None,
        )

        return ToolResult(
            success=True,
            data={"clip": new_clip, "total_clips": len(clips)},
            user_message=f"已添加片段 [{start_time_s:.0f}s-{end_time_s:.0f}s]（手动，共 {len(clips)} 个片段）",
        )


_add_clip = AddClip()
register(_add_clip)
