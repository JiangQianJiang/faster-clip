"""User tool: delete clips and clean up exported files."""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")


def _cleanup_sidecar_files(task_id: str, clip_index: int) -> list[str]:
    """Remove subtitle sidecar files for a clip index. Returns paths removed."""
    task_output_dir = os.path.realpath(OUTPUT_DIR / task_id)
    removed = []
    for ext in ("srt", "vtt", "ass"):
        sidecar = os.path.join(
            str(OUTPUT_DIR / task_id), f"clip_{clip_index:03d}.{ext}"
        )
        real = os.path.realpath(sidecar)
        if not real.startswith(task_output_dir + os.sep) and real != task_output_dir:
            continue
        if os.path.isfile(real):
            try:
                os.unlink(real)
                removed.append(sidecar)
            except OSError:
                pass
    return removed


def _cleanup_clip_files(
    task_id: str, clip: dict, clip_index: int | None = None
) -> list[str]:
    """Delete exported files for a clip, only within the task output directory.

    Cleans up MP4, thumbnail, and subtitle sidecar files (SRT/VTT/ASS).
    Returns list of paths successfully removed.
    """
    task_output_dir = os.path.realpath(OUTPUT_DIR / task_id)
    removed = []

    # Primary files: MP4 and thumbnail
    for key in ("filepath", "thumbnail_path"):
        path = clip.get(key, "")
        if not path:
            continue
        real = os.path.realpath(path)
        if not real.startswith(task_output_dir + os.sep) and real != task_output_dir:
            continue
        if os.path.isfile(real):
            try:
                os.unlink(real)
                removed.append(path)
            except OSError:
                pass

    # Subtitle sidecars for this clip index
    if clip_index is not None:
        for ext in ("srt", "vtt", "ass"):
            sidecar = os.path.join(
                str(OUTPUT_DIR / task_id), f"clip_{clip_index:03d}.{ext}"
            )
            real = os.path.realpath(sidecar)
            if (
                not real.startswith(task_output_dir + os.sep)
                and real != task_output_dir
            ):
                continue
            if os.path.isfile(real):
                try:
                    os.unlink(real)
                    removed.append(sidecar)
                except OSError:
                    pass

    return removed


class DeleteClip(Tool):
    name = "delete_clip"
    description = (
        "Delete one or more clips by index. Also removes exported MP4 and "
        "thumbnail files from disk. Use when the user wants to remove unwanted clips. "
        "The LLM should translate conditions (e.g. 'score < 5') into indices."
    )
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "clip_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Zero-based indices of clips to delete",
            },
        },
        "required": ["task_id", "clip_indices"],
    }

    async def execute(
        self,
        task_id: str,
        clip_indices: list[int],
    ) -> ToolResult:
        from app.models.task import get_task, update_task_status

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
                error="Cannot delete clips while task is processing",
                user_message="任务处理中，无法删除片段，请等待完成",
            )

        try:
            clips = json.loads(task.get("clips_json") or "[]")
        except json.JSONDecodeError:
            clips = []

        if not clips:
            return ToolResult(
                success=False,
                error="No clips to delete",
                user_message="没有可删除的片段",
            )

        # Sort indices descending so we can pop without shifting
        valid_indices: list[int] = []
        skipped: list[int] = []
        for i in sorted(set(clip_indices), reverse=True):
            if 0 <= i < len(clips):
                valid_indices.append(i)
            else:
                skipped.append(i)

        if not valid_indices:
            return ToolResult(
                success=False,
                error="All indices out of range",
                user_message="所有索引均超出范围",
            )

        removed_clips = []
        files_removed = []
        for i in valid_indices:
            clip = clips.pop(i)
            removed_clips.append(clip)
            files_removed.extend(_cleanup_clip_files(task_id, clip, clip_index=i))
            # Invalidate sidecars for all clips that shifted after this deletion
            for shifted_idx in range(i, len(clips)):
                files_removed.extend(_cleanup_sidecar_files(task_id, shifted_idx))
            # After popping, remaining clips from index i onward have shifted up.
            # Their stored filepaths still point to old indices. Clear export state
            # so a re-export produces correct filenames matching their new positions.
            for shifted in range(i, len(clips)):
                for key in (
                    "filepath",
                    "thumbnail_path",
                    "export_start_time_s",
                    "export_end_time_s",
                ):
                    clips[shifted].pop(key, None)
                if clips[shifted].get("status") == "success":
                    clips[shifted]["status"] = "pending"

        update_task_status(
            task_id,
            task["status"],
            clips_json=json.dumps(clips, ensure_ascii=False),
        )

        msg = f"已删除 {len(removed_clips)} 个片段"
        if files_removed:
            msg += f"，清理了 {len(files_removed)} 个文件"
        if skipped:
            msg += f"，跳过 {len(skipped)} 个无效索引"

        return ToolResult(
            success=True,
            data={
                "deleted": len(removed_clips),
                "remaining": len(clips),
                "skipped_indices": skipped,
                "files_removed": len(files_removed),
            },
            user_message=msg,
        )


_delete_clip = DeleteClip()
register(_delete_clip)
