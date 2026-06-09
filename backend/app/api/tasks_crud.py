"""Task CRUD endpoints: create, list, get, delete, status, video."""

import json
import logging
import os
import shutil
import tempfile
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api._common import (
    OUTPUT_DIR,
    SUBTITLE_MAX_SIZE,
    VIDEOS_DIR,
    _cleanup_task,
    _ensure_task_video_path,
    _media_info_for_task,
)
from app.config import settings
from app.models.task import (
    create_task,
    delete_task,
    get_task,
    init_db,
    list_tasks,
    update_task_status,
)
from app.services.ffprobe import (
    CorruptedVideo,
    DurationTooLong,
    FFprobeError,
    FormatNotSupported,
    NoVideoStream,
    probe,
)
from app.services.subtitle import (
    SUPPORTED_IMPORT_FORMATS,
    parse_subtitle_bytes,
    save_raw_transcript,
    save_transcript,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _validate_config(
    llm_base_url: str,
    llm_model: str,
    clip_min_duration: int,
    clip_max_duration: int,
    buffer_seconds: int,
    asr_base_url: str = "",
) -> None:
    try:
        parsed = urlparse(llm_base_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("无效的 URL")
    except Exception:
        raise HTTPException(422, detail="llm_base_url 不是有效的 URL")

    if not llm_model or not llm_model.strip():
        raise HTTPException(422, detail="llm_model 不能为空")

    if asr_base_url:
        try:
            parsed = urlparse(asr_base_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("无效的 URL")
        except Exception:
            raise HTTPException(422, detail="asr_base_url 不是有效的 URL")

    if clip_min_duration <= 0:
        raise HTTPException(422, detail="clip_min_duration 必须为正数")

    if clip_max_duration <= 0:
        raise HTTPException(422, detail="clip_max_duration 必须为正数")

    if clip_max_duration < clip_min_duration:
        raise HTTPException(422, detail="clip_max_duration 不能小于 clip_min_duration")

    if buffer_seconds < 0:
        raise HTTPException(422, detail="buffer_seconds 不能为负数")


@router.post("", status_code=201)
async def create_task_endpoint(
    file: UploadFile = File(...),
    llm_base_url: str = Form(...),
    llm_model: str = Form(...),
    llm_api_key: str = Form(...),
    asr_api_key: str = Form(""),
    asr_base_url: str = Form(""),
    asr_model: str = Form("qwen3-asr-flash-filetrans"),
    asr_provider: str = Form(""),
    clip_min_duration: int = Form(30),
    clip_max_duration: int = Form(120),
    buffer_seconds: int = Form(3),
    burn_subtitle: bool = Form(False),
    subtitle_file: UploadFile | None = File(None),
):
    _validate_config(
        llm_base_url,
        llm_model,
        clip_min_duration,
        clip_max_duration,
        buffer_seconds,
        asr_base_url,
    )

    if not file.filename:
        raise HTTPException(400, detail="未选择文件")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("mp4", "mov", "mkv", "avi", "webm", "m4v", "flv"):
        raise HTTPException(
            400,
            detail=f"不支持的视频格式: .{ext}，支持: mp4, mov, mkv, avi, webm, m4v, flv",
        )

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            chunk_size = 8 * 1024 * 1024
            total = 0
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_upload_size_bytes:
                    os.unlink(tmp.name)
                    raise HTTPException(413, detail="文件大小超过 2GB 限制")
                tmp.write(chunk)
            tmp_path = tmp.name
    except HTTPException:
        raise
    except OSError as e:
        if getattr(e, "errno", 0) == 28:
            raise HTTPException(507, detail="磁盘空间不足，无法保存上传文件")
        raise HTTPException(500, detail="文件保存失败")
    except Exception:
        raise HTTPException(500, detail="文件保存失败")

    try:
        info = probe(tmp_path)
    except FormatNotSupported as e:
        os.unlink(tmp_path)
        raise HTTPException(400, detail=str(e))
    except NoVideoStream as e:
        os.unlink(tmp_path)
        raise HTTPException(400, detail=str(e))
    except DurationTooLong as e:
        os.unlink(tmp_path)
        raise HTTPException(400, detail=str(e))
    except CorruptedVideo as e:
        os.unlink(tmp_path)
        raise HTTPException(400, detail=str(e))
    except FFprobeError as e:
        os.unlink(tmp_path)
        raise HTTPException(500, detail=str(e))

    try:
        init_db()
    except Exception:
        os.unlink(tmp_path)
        raise HTTPException(500, detail="数据库初始化失败")

    config = {
        "llm_base_url": llm_base_url,
        "llm_model": llm_model,
        "asr_base_url": asr_base_url,
        "asr_model": asr_model,
        "asr_provider": asr_provider,
        "clip_min_duration": clip_min_duration,
        "clip_max_duration": clip_max_duration,
        "buffer_seconds": buffer_seconds,
        "burn_subtitle": burn_subtitle,
    }

    try:
        task_id = create_task(
            video_path="",
            video_filename=file.filename or "unknown",
            config=config,
        )
    except Exception:
        os.unlink(tmp_path)
        raise HTTPException(500, detail="任务创建失败")

    video_dir = VIDEOS_DIR / task_id
    try:
        video_dir.mkdir(parents=True, exist_ok=True)
        dest = video_dir / f"original.{ext}"
        shutil.move(tmp_path, str(dest))
    except OSError as e:
        _cleanup_task(task_id, video_dir)
        if getattr(e, "errno", 0) == 28:
            raise HTTPException(507, detail="磁盘空间不足，无法保存视频文件")
        raise HTTPException(500, detail="视频文件保存失败")

    try:
        update_task_status(
            task_id,
            "pending",
            video_path=str(dest),
            media_info_json=json.dumps(
                {
                    "duration": info.duration,
                    "width": info.width,
                    "height": info.height,
                    "codec": info.codec,
                    "container": info.container,
                    "fps": info.fps,
                    "fps_mode": info.fps_mode,
                }
            ),
        )
    except Exception:
        _cleanup_task(task_id, video_dir)
        raise HTTPException(500, detail="任务状态更新失败")

    # Subtitle import handling
    import_info = None
    if subtitle_file and subtitle_file.filename:
        sub_ext = (
            subtitle_file.filename.rsplit(".", 1)[-1].lower()
            if "." in subtitle_file.filename
            else ""
        )
        if sub_ext not in SUPPORTED_IMPORT_FORMATS:
            _cleanup_task(task_id, video_dir)
            raise HTTPException(
                400, detail=f"不支持的字幕格式: .{sub_ext}，支持: srt, vtt, ass"
            )

        sub_content = await subtitle_file.read()
        if len(sub_content) > SUBTITLE_MAX_SIZE:
            _cleanup_task(task_id, video_dir)
            raise HTTPException(413, detail="字幕文件大小超过 5MB 限制")

        try:
            segments, warnings = parse_subtitle_bytes(sub_content, sub_ext)
        except ValueError as e:
            _cleanup_task(task_id, video_dir)
            raise HTTPException(400, detail=str(e))

        if not segments:
            _cleanup_task(task_id, video_dir)
            raise HTTPException(400, detail="No valid segments found")

        # Save original subtitle file
        orig_path = video_dir / f"uploaded_subtitle.{sub_ext}"
        with open(orig_path, "wb") as f:
            f.write(sub_content)

        # Save normalized transcript
        output_dir = OUTPUT_DIR / task_id
        save_raw_transcript(segments, str(output_dir))
        save_transcript(segments, str(output_dir))

        from app.utils import utcnow_iso

        now_iso = utcnow_iso()
        update_task_status(
            task_id,
            "pending",
            subtitle_segment_count=len(segments),
            transcript_source="subtitle_import",
            transcript_modified_at=now_iso,
            media_info_json=json.dumps(
                {
                    "duration": info.duration,
                    "width": info.width,
                    "height": info.height,
                    "codec": info.codec,
                    "container": info.container,
                    "fps": info.fps,
                    "fps_mode": info.fps_mode,
                }
            ),
        )

        import_info = {
            "imported_count": len(segments),
            "skipped_count": len(warnings),
            "warnings": warnings,
        }

    from app.crypto import encrypt_api_key
    from app.worker.celery_app import process_video_task

    task_kwargs = {
        "task_id": task_id,
        "video_path": str(dest),
        "config": config,
        "llm_api_key": encrypt_api_key(llm_api_key),
        "asr_api_key": encrypt_api_key(asr_api_key),
    }
    try:
        process_video_task.apply_async(kwargs=task_kwargs, task_id=task_id)
    except Exception:
        _cleanup_task(task_id, video_dir)
        shutil.rmtree(str(OUTPUT_DIR / task_id), ignore_errors=True)
        raise HTTPException(500, detail="任务队列失败，请重试")

    try:
        update_task_status(task_id, "queued")
    except Exception:
        _cleanup_task(task_id, video_dir)
        shutil.rmtree(str(OUTPUT_DIR / task_id), ignore_errors=True)
        raise HTTPException(500, detail="任务入队状态更新失败")

    result = {"task_id": task_id}
    if import_info:
        result.update(import_info)
    return result


@router.get("")
async def list_tasks_endpoint(limit: int = 20, after: str | None = None):
    init_db()
    if limit < 1:
        raise HTTPException(422, detail="limit 必须大于 0")
    if limit > 100:
        raise HTTPException(422, detail="limit 不能超过 100")
    tasks = list_tasks(limit, after=after)
    return [
        {
            "task_id": t["id"],
            "status": t["status"],
            "stage": t.get("stage"),
            "video_filename": t.get("video_filename"),
            "subtitle_segment_count": t.get("subtitle_segment_count"),
            "clips_count": len(json.loads(t.get("clips_json") or "[]")),
            "error_message": t.get("error_message"),
            "failed_stage": t.get("failed_stage"),
            "empty_clips_reason": t.get("empty_clips_reason"),
            "created_at": t.get("created_at"),
            "updated_at": t.get("updated_at"),
            "started_at": t.get("started_at"),
            "completed_at": t.get("completed_at"),
            "transcript_source": t.get("transcript_source"),
        }
        for t in tasks
    ]


@router.delete("/{task_id}", status_code=204)
async def delete_task_endpoint(task_id: str):
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid task_id")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="Task not found")

    from app.worker.celery_app import celery_app

    status = task.get("status", "")
    if status in ("pending", "queued"):
        celery_app.control.revoke(task_id, terminate=False)
        try:
            celery_app.control.revoke(f"export_{task_id}", terminate=True)
        except Exception:
            pass
    elif status == "processing":
        celery_app.control.revoke(task_id, terminate=True)
        try:
            celery_app.control.revoke(f"export_{task_id}", terminate=True)
        except Exception:
            pass

    cleanup_ok = True

    video_dir = VIDEOS_DIR / task_id
    if video_dir.exists():
        try:
            shutil.rmtree(str(video_dir))
        except OSError as e:
            logging.warning("Failed to delete video dir %s: %s", video_dir, e)
            cleanup_ok = False

    output_dir = OUTPUT_DIR / task_id
    if output_dir.exists():
        try:
            shutil.rmtree(str(output_dir))
        except OSError as e:
            logging.warning("Failed to delete output dir %s: %s", output_dir, e)
            cleanup_ok = False

    if cleanup_ok:
        delete_task(task_id)
        return None

    logging.warning(
        "File cleanup incomplete for task %s, keeping DB row for scheduled cleanup",
        task_id,
    )
    raise HTTPException(500, detail="File cleanup failed, task preserved for retry")


@router.get("/{task_id}")
async def get_task_endpoint(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    resp = {
        "task_id": task["id"],
        "status": task["status"],
        "stage": task.get("stage"),
        "video_filename": task.get("video_filename"),
        "config": json.loads(task.get("config_json") or "{}"),
        "subtitle_segment_count": task.get("subtitle_segment_count"),
        "clips": json.loads(task.get("clips_json") or "[]"),
        "error_message": task.get("error_message"),
        "failed_stage": task.get("failed_stage"),
        "empty_clips_reason": task.get("empty_clips_reason"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "started_at": task.get("started_at"),
        "completed_at": task.get("completed_at"),
        "transcript_source": task.get("transcript_source"),
        "transcript_modified_at": task.get("transcript_modified_at"),
        "chat_history_json": task.get("chat_history_json"),
        "chat_updated_at": task.get("chat_updated_at"),
        "media_info": _media_info_for_task(task),
    }

    clips = resp["clips"]
    for i, clip in enumerate(clips):
        clip["download_url"] = f"/api/tasks/{task['id']}/clips/{i}/download"
        if clip.get("thumbnail_path"):
            clip["thumbnail_url"] = f"/api/tasks/{task['id']}/clips/{i}/thumbnail"

    return resp


@router.get("/{task_id}/status")
async def get_task_status_endpoint(task_id: str):
    """Lightweight status endpoint for polling — no ffprobe, no JSON parsing."""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid task_id")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    return {
        "task_id": task["id"],
        "status": task["status"],
        "stage": task.get("stage"),
        "error_message": task.get("error_message"),
        "failed_stage": task.get("failed_stage"),
        "empty_clips_reason": task.get("empty_clips_reason"),
        "subtitle_segment_count": task.get("subtitle_segment_count"),
        "video_filename": task.get("video_filename"),
        "updated_at": task.get("updated_at"),
    }


@router.get("/{task_id}/video")
async def get_task_video(task_id: str):
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid task_id")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    video_path = task.get("video_path") or ""
    abs_path = _ensure_task_video_path(task_id, video_path)

    if not video_path.lower().endswith(".mp4"):
        preview_path = os.path.join(os.path.dirname(abs_path), "preview.mp4")
        if os.path.isfile(preview_path):
            return FileResponse(path=preview_path, media_type="video/mp4")

    return FileResponse(path=abs_path, media_type="video/mp4")
