"""Minimal workflow state validation for chat tool calls."""

import json
from typing import Any

from app.models.task import get_task, update_task_status
from app.tools.base import Tool, ToolResult


class WorkflowRuntime:
    """Small compatibility state machine for phase-one tool gating."""

    _STATE_ORDER = {
        "unknown": 0,
        "uploaded": 1,
        "media_ready": 2,
        "transcript_ready": 3,
        "clips_ready": 4,
        "exporting": 5,
        "exported": 6,
        "error": 99,
    }

    @staticmethod
    def get_task_state(task: dict[str, Any] | None) -> str:
        if not task:
            return "unknown"

        status = str(task.get("status") or "").lower()
        stage = str(task.get("stage") or "").lower()
        if status == "error":
            return "error"
        if "exporting" in status or "exporting" in stage or stage == "ai_exporting":
            return "exporting"

        clips = WorkflowRuntime._load_clips(task.get("clips_json"))
        if (
            "exported" in status
            or "exported" in stage
            or status == "done"
            or stage in {"exported", "export_complete", "completed"}
            or any(clip.get("status") == "success" or clip.get("filepath") for clip in clips)
        ):
            return "exported"
        if clips:
            return "clips_ready"
        if (task.get("subtitle_segment_count") or 0) > 0 or (task.get("transcript_version") or 0) > 0:
            return "transcript_ready"
        if task.get("media_info_json") or task.get("video_path"):
            return "media_ready"
        if status in {"pending", "queued", "processing", "done"}:
            return "uploaded"
        return "unknown"

    def validate_tool_call(self, task: dict[str, Any] | None, tool: Tool | None) -> tuple[bool, str | None]:
        if tool is None:
            return False, "未知工具，无法执行。"
        if task is None:
            return True, None
        required_states = list(getattr(tool, "requires_state", []) or [])
        if not required_states:
            return True, None

        current_state = self.get_task_state(task)
        if self._state_satisfies(current_state, required_states):
            return True, None

        target = required_states[0]
        reason = (
            f"当前任务还没有 {target}，不能执行 {tool.name}。"
            "请先运行 ASR 或导入字幕。"
        )
        return False, reason

    def apply_tool_success(self, task_id: str, tool: Tool | None, result: ToolResult) -> str | None:
        if tool is None or not result.success:
            return None
        produced_state = getattr(tool, "produces_state", None)
        if not produced_state:
            return None

        task = get_task(task_id)
        if task is None:
            return None

        status = task.get("status") or "done"
        if status in {"pending", "queued", "processing", "error"}:
            status = "done"

        if produced_state == "exporting":
            update_task_status(task_id, "processing", stage="ai_exporting")
        elif produced_state == "exported":
            update_task_status(task_id, "done", stage="exported")
        elif produced_state in {"transcript_ready", "clips_ready"}:
            update_task_status(task_id, status, stage=produced_state)
        else:
            update_task_status(task_id, status, stage=produced_state)
        return produced_state

    def apply_tool_failure(self, task_id: str, tool: Tool | None, result: ToolResult) -> None:
        if tool is None or result.success or not getattr(tool, "fatal_on_failure", False):
            return
        error_text = (result.error or "") + (result.user_message or "")
        if "while task is processing" in error_text or "任务处理中" in error_text:
            return
        update_task_status(
            task_id,
            "error",
            failed_stage=tool.name,
            error_message=result.error or result.user_message or f"{tool.name} failed",
        )

    @classmethod
    def _state_satisfies(cls, current_state: str, required_states: list[str]) -> bool:
        if current_state in required_states:
            return True
        current_rank = cls._STATE_ORDER.get(current_state, 0)
        return any(
            current_rank >= cls._STATE_ORDER.get(required_state, 100)
            and required_state not in {"exporting", "uploaded"}
            for required_state in required_states
        )

    @staticmethod
    def _load_clips(clips_json: str | None) -> list[dict]:
        if not clips_json:
            return []
        try:
            clips = json.loads(clips_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return clips if isinstance(clips, list) else []
