"""User tool: edit transcript segments."""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")


class EditTranscript(Tool):
    name = "edit_transcript"
    description = "Edit transcript segments: update text, adjust timing, merge, or split. Accepts a list of edit operations to apply atomically."
    user_facing = True
    requires_state = ["transcript_ready"]
    produces_state = "transcript_ready"
    destructive = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {
                            "type": "string",
                            "enum": ["update", "merge", "split"],
                            "description": "Operation type",
                        },
                        "index": {
                            "type": "integer",
                            "description": "Segment index (for update/split)",
                        },
                        "text": {
                            "type": "string",
                            "description": "New text (for update)",
                        },
                        "start_time_s": {
                            "type": "number",
                            "description": "New start time (for update)",
                        },
                        "end_time_s": {
                            "type": "number",
                            "description": "New end time (for update)",
                        },
                        "end_index": {
                            "type": "integer",
                            "description": "End index for merge",
                        },
                        "split_time_s": {
                            "type": "number",
                            "description": "Split time for split op",
                        },
                    },
                    "required": ["op"],
                },
                "description": "List of operations to apply",
            },
        },
        "required": ["task_id", "operations"],
    }

    async def execute(self, task_id: str, operations: list[dict]) -> ToolResult:
        from app.models.task import get_task

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False, error="Task not found", user_message="任务不存在"
            )

        # Guard: reject mutations while task is processing (any stage)
        if task.get("status") in ("pending", "queued", "processing"):
            return ToolResult(
                success=False,
                error="Cannot edit transcript while task is processing",
                user_message="任务处理中，无法编辑字幕，请等待完成",
            )

        transcript_path = OUTPUT_DIR / task_id / "transcript.json"

        if not os.path.isfile(transcript_path):
            return ToolResult(
                success=False,
                error="Transcript not found",
                user_message="字幕文件不存在",
            )

        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
        except Exception as e:
            return ToolResult(success=False, error=str(e), user_message="字幕读取失败")

        messages = []
        for op in operations:
            op_type = op.get("op")
            try:
                if op_type == "update":
                    idx = op.get("index", 0)
                    if idx < 0 or idx >= len(segments):
                        messages.append(f"跳过: 索引 {idx + 1} 超出范围")
                        continue
                    if "text" in op:
                        segments[idx]["text"] = op["text"]
                    if "start_time_s" in op:
                        segments[idx]["start_time_s"] = op["start_time_s"]
                    if "end_time_s" in op:
                        segments[idx]["end_time_s"] = op["end_time_s"]
                    messages.append(f"已更新第 {idx + 1} 条")

                elif op_type == "merge":
                    start = op.get("index", 0)
                    end = op.get("end_index", start + 1)
                    if start < 0 or end >= len(segments) or start >= end:
                        messages.append(f"跳过: 合并范围 [{start + 1}, {end + 1}] 无效")
                        continue
                    merged_text = " ".join(s["text"] for s in segments[start : end + 1])
                    merged = {
                        "start_time_s": segments[start]["start_time_s"],
                        "end_time_s": segments[end]["end_time_s"],
                        "text": merged_text,
                    }
                    segments = segments[:start] + [merged] + segments[end + 1 :]
                    messages.append(f"已合并第 {start + 1}-{end + 1} 条")

                elif op_type == "split":
                    idx = op.get("index", 0)
                    split_at = op.get("split_time_s", 0)
                    if idx < 0 or idx >= len(segments):
                        messages.append(f"跳过: 索引 {idx + 1} 超出范围")
                        continue
                    seg = segments[idx]
                    if split_at <= seg["start_time_s"] or split_at >= seg["end_time_s"]:
                        messages.append("跳过: 分割时间点不在范围内")
                        continue
                    first = {
                        "start_time_s": seg["start_time_s"],
                        "end_time_s": split_at,
                        "text": seg["text"],
                    }
                    second = {
                        "start_time_s": split_at,
                        "end_time_s": seg["end_time_s"],
                        "text": seg["text"],
                    }
                    segments = segments[:idx] + [first, second] + segments[idx + 1 :]
                    messages.append(f"已在 {split_at:.1f}s 处拆分第 {idx + 1} 条")

            except Exception as e:
                messages.append(f"操作失败 ({op_type}): {e}")

        # Persist
        try:
            tmp_path = str(transcript_path) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, transcript_path)
        except Exception as e:
            return ToolResult(success=False, error=str(e), user_message="字幕保存失败")

        # Update DB
        from app.models.task import get_task, update_task_status
        from app.utils import utcnow_iso

        task = get_task(task_id)
        if task:
            now = utcnow_iso()
            update_task_status(
                task_id,
                task["status"],
                subtitle_segment_count=len(segments),
                transcript_source="manual_edit",
                transcript_modified_at=now,
            )

        return ToolResult(
            success=True,
            data={"segment_count": len(segments), "messages": messages},
            user_message="; ".join(messages) if messages else "字幕编辑完成",
        )


_edit_transcript = EditTranscript()
register(_edit_transcript)
