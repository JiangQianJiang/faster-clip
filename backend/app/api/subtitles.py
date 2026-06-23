"""Transcript/subtitle endpoints: export, edit, get."""

import fcntl
import json
import os
import tempfile
import uuid
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.api._common import OUTPUT_DIR
from app.models.task import (
    bump_transcript_version_if_current,
    get_task,
    update_task_status,
)
from app.services.subtitle import (
    generate_clip_subtitles,
    segments_to_ass,
    segments_to_srt,
    segments_to_vtt,
)
from app.services.transcript_validator import (
    validate_transcript,
    validate_transcript_strict,
)

router = APIRouter(prefix="/api/tasks", tags=["subtitles"])


@contextmanager
def _transcript_lock(task_id: str):
    """Per-task file lock serializing transcript writes for a single task."""
    output_dir = OUTPUT_DIR / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = str(output_dir / ".transcript.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@router.get("/{task_id}/transcript/export")
async def export_transcript(task_id: str, format: str = "srt"):
    """Export transcript as subtitle file."""
    supported = {"srt", "vtt", "ass"}
    if format not in supported:
        raise HTTPException(400, detail=f"Unsupported format: {format}")

    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid task_id")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="Task not found")

    transcript_path = OUTPUT_DIR / task_id / "transcript.json"
    if not os.path.isfile(transcript_path):
        raise HTTPException(404, detail="Transcript not available")

    try:
        with open(transcript_path, encoding="utf-8") as f:
            segments = json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(500, detail="Transcript file corrupted")

    formatters = {
        "srt": (segments_to_srt, "text/plain"),
        "vtt": (segments_to_vtt, "text/plain"),
    }
    func, media_type = formatters.get(format, (segments_to_ass, "text/x-ssa"))
    content = func(segments)

    filename = f"transcript_{task_id}.{format}"
    export_path = OUTPUT_DIR / task_id / filename
    export_path.parent.mkdir(parents=True, exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(content)
    return FileResponse(
        path=str(export_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.patch("/{task_id}/transcript")
async def patch_transcript(task_id: str, body: dict):
    """Replace a transcript with a complete edited segment array."""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="无效的 task_id 格式")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    if task.get("status") in ("queued", "processing"):
        raise HTTPException(409, detail="任务处理中，无法修改字幕，请等待完成")

    segments = body.get("segments")
    after_save = body.get("after_save", "none")

    if after_save not in (
        "none",
        "save_only",
        "regenerate_clip_subtitles",
        "reanalyze",
    ):
        raise HTTPException(
            400,
            detail="after_save must be one of: none, save_only, regenerate_clip_subtitles, reanalyze",
        )
    if segments is None:
        raise HTTPException(400, detail="缺少 segments 字段")

    if not isinstance(segments, list):
        raise HTTPException(400, detail="segments 必须是数组")

    # Incoming segments may have been edited — clear confidence only for
    # rows the client marks as modified (confidence absent or explicitly
    # null).  Unmodified rows retain their original confidence value.
    for seg in segments:
        if isinstance(seg, dict):
            if seg.get("confidence") is not None:
                # Client preserved a non-null confidence — trust it.
                continue
            seg["confidence"] = None

    transcript_path = OUTPUT_DIR / task_id / "transcript.json"
    if not os.path.isfile(transcript_path):
        raise HTTPException(404, detail="字幕文件不存在，无法编辑")

    try:
        with open(transcript_path, encoding="utf-8") as f:
            json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(500, detail="字幕文件格式错误")

    # Strict validation: reject invalid segments
    error = validate_transcript_strict(segments)
    if error:
        raise HTTPException(422, detail=error)

    # Version-based optimistic lock: require base_transcript_version
    base_version = body.get("base_transcript_version")
    if base_version is None:
        raise HTTPException(422, detail="缺少 base_transcript_version 字段，请先获取最新字幕")
    if not isinstance(base_version, int) or base_version < 0:
        raise HTTPException(422, detail="base_transcript_version 必须是非负整数")

    resolved_llm_api_key = ""
    resolved_asr_api_key = ""
    if after_save == "reanalyze":
        from app.config import settings

        resolved_llm_api_key = (
            (settings.llm_api_key or "").strip()
            or str(body.get("llm_api_key") or "").strip()
        )
        resolved_asr_api_key = (
            (settings.asr_api_key or "").strip()
            or str(body.get("asr_api_key") or "").strip()
        )
        if not resolved_llm_api_key:
            raise HTTPException(
                422,
                detail="服务端未配置 LLM API Key，请在 setting 文件中配置 llm.api_key。",
            )

    from app.utils import utcnow_iso

    now_iso = utcnow_iso()
    output_dir = OUTPUT_DIR / task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # SERIALIZE: per-task lock ensures no concurrent transcript writes
    with _transcript_lock(task_id):
        # Re-read version under lock to prevent TOCTOU
        task_current = get_task(task_id)
        current_version = task_current.get("transcript_version", 0) if task_current else 0
        if current_version != base_version:
            raise HTTPException(
                409,
                detail=f"字幕已被其他客户端修改（当前版本: {current_version}），请刷新后重试",
            )

        # Phase 1: Prepare temp file (no side effects yet)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(output_dir), prefix="transcript_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            os.unlink(tmp_path)
            raise HTTPException(500, detail="保存字幕文件失败")

        # Phase 2: DB CAS while still under lock
        updated = bump_transcript_version_if_current(
            task_id,
            expected_transcript_version=base_version,
            modified_at=now_iso,
            subtitle_segment_count=len(segments),
            transcript_source="manual_edit",
        )

        if not updated:
            os.unlink(tmp_path)
            task_r = get_task(task_id)
            cv = task_r.get("transcript_version", 0) if task_r else 0
            return JSONResponse(
                status_code=409,
                content={
                    "code": "VERSION_CONFLICT",
                    "detail": "字幕已被其他客户端修改，请刷新后重试",
                    "current_version": cv,
                },
            )

        # Phase 3: CAS succeeded — atomically swap file, fsync directory
        try:
            os.replace(tmp_path, transcript_path)
            dir_fd = os.open(str(output_dir), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Rollback: restore previous DB state since file write failed
            os.unlink(tmp_path)
            update_task_status(
                task_id,
                task["status"],
                subtitle_segment_count=task.get("subtitle_segment_count"),
                transcript_source=task.get("transcript_source"),
                transcript_modified_at=task.get("transcript_modified_at"),
            )
            raise HTTPException(500, detail="字幕文件写入失败，数据库状态已回滚，请重试")

    # Post-save actions
    follow_up_status = None
    follow_up_error = None

    if after_save == "regenerate_clip_subtitles":
        try:
            clips = json.loads(task.get("clips_json") or "[]")
        except json.JSONDecodeError:
            clips = []
        for i, clip in enumerate(clips):
            if clip.get("status") == "failed":
                continue
            window_start = clip.get(
                "export_start_time_s", clip.get("start_time_s", 0.0)
            )
            window_end = clip.get("export_end_time_s", clip.get("end_time_s", 0.0))
            generate_clip_subtitles(
                segments,
                float(window_start),
                float(window_end),
                str(output_dir),
                i,
            )

    if after_save == "reanalyze":
        from app.crypto import encrypt_api_key
        from app.worker.celery_app import process_video_task

        video_path = task.get("video_path") or ""
        if not video_path or not os.path.isfile(video_path):
            follow_up_status = "failed"
            follow_up_error = "原始视频不存在，无法重新分析"
        else:
            config = json.loads(task.get("config_json") or "{}")
            task_kwargs = {
                "task_id": task_id,
                "video_path": video_path,
                "config": config,
                "llm_api_key": encrypt_api_key(resolved_llm_api_key),
                "asr_api_key": encrypt_api_key(resolved_asr_api_key),
            }
            try:
                process_video_task.apply_async(kwargs=task_kwargs, task_id=task_id)
                update_task_status(
                    task_id,
                    "queued",
                    stage=None,
                    error_message=None,
                    failed_stage=None,
                    empty_clips_reason=None,
                )
                follow_up_status = "enqueued"
            except Exception:
                follow_up_status = "failed"
                follow_up_error = "重新分析任务入队失败，请稍后重试"

    # Refresh to get updated transcript_version
    task_refreshed = get_task(task_id)
    new_version = task_refreshed.get("transcript_version", base_version + 1) if task_refreshed else base_version + 1

    response = {
        "task_id": task_id,
        "segment_count": len(segments),
        "transcript_version": new_version,
        "transcript_modified_at": now_iso,
        "save_status": "saved",
        "after_save": after_save,
    }

    if follow_up_status:
        response["follow_up_status"] = follow_up_status
        if follow_up_error:
            response["follow_up_error"] = follow_up_error
    elif after_save in ("reanalyze",):
        response["follow_up_status"] = "enqueued"

    return response


@router.get("/{task_id}/transcript")
async def get_transcript(task_id: str):
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="无效的 task_id 格式")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    transcript_path = OUTPUT_DIR / task_id / "transcript.json"
    abs_path = os.path.abspath(str(transcript_path))
    output_root = os.path.abspath(str(OUTPUT_DIR / task_id))

    if not abs_path.startswith(output_root + os.sep) and abs_path != output_root:
        raise HTTPException(400, detail="无效的路径")

    if os.path.isfile(abs_path):
        try:
            with open(abs_path, encoding="utf-8") as f:
                segments = json.load(f)
        except json.JSONDecodeError:
            raise HTTPException(500, detail="字幕文件格式错误")

        valid_segments, _warnings = validate_transcript(segments)

        return {
            "task_id": task_id,
            "available": True,
            "segment_count": len(valid_segments),
            "segments": valid_segments,
            "transcript_version": task.get("transcript_version", 0),
            "transcript_modified_at": task.get("transcript_modified_at"),
        }

    status = task.get("status", "")
    stage = task.get("stage")
    failed_stage = task.get("failed_stage")

    if status in ("pending", "queued"):
        detail = "任务处理尚未开始"
    elif status == "processing" and stage == "extracting_subtitles":
        detail = "字幕提取中，请稍后查看"
    elif status == "error" and failed_stage == "extracting_subtitles":
        detail = f"字幕提取失败: {task.get('error_message', '未知错误')}"
    else:
        detail = "字幕文件暂不可用"

    return {
        "task_id": task_id,
        "available": False,
        "segment_count": 0,
        "segments": [],
        "detail": detail,
        "transcript_modified_at": task.get("transcript_modified_at"),
    }
