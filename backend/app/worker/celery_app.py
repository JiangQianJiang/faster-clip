import logging
import os
import shutil
import time as time_mod

from celery import Celery, signals
from celery.schedules import crontab

from app.config import settings
from app.logging_config import install_log_filter, setup_json_logging
from app.utils import utcnow_iso

_logger = logging.getLogger("app.celery")

celery_app = Celery(
    "live-clipper",
    broker=settings.redis_url,
    backend=None,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    worker_concurrency=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=60,
    task_max_retries=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "cleanup-expired-tasks": {
            "task": "app.worker.celery_app.cleanup_expired_tasks",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)


@signals.task_failure.connect
def on_task_failure(**kwargs):
    """Reset task_id context on any unhandled task exception."""
    from app.logging_config import _task_id_var as _tv

    try:
        _tv.set(None)
    except Exception:
        pass


@signals.worker_ready.connect
def on_worker_ready(**kwargs):
    from app.config import _validate_startup_config

    _validate_startup_config()
    install_log_filter()
    setup_json_logging()


@celery_app.task(bind=True, max_retries=1, name="app.worker.celery_app.process_video_task")
def process_video_task(
    self,
    task_id: str,
    video_path: str,
    config: dict,
    llm_api_key: str,
    asr_api_key: str,
):
    from app.crypto import decrypt_api_key
    from app.logging_config import _task_id_var
    from app.models.task import update_task_status

    token = _task_id_var.set(task_id)
    try:
        start = time_mod.monotonic()
        _logger.info(
            "task.lifecycle",
            extra={
                "task_id": task_id,
                "status": "started",
                "task_name": "process_video_task",
            },
        )

        _llm_key = decrypt_api_key(llm_api_key)
        _asr_key = decrypt_api_key(asr_api_key)

        if not update_task_status(task_id, "processing", started_at=utcnow_iso()):
            return

        _run_pipeline(task_id, video_path, config, _llm_key, _asr_key)
        _logger.info(
            "task.lifecycle",
            extra={
                "task_id": task_id,
                "status": "done",
                "duration_ms": round((time_mod.monotonic() - start) * 1000, 1),
            },
        )
    except Exception as e:
        _logger.error(
            "task.lifecycle",
            extra={
                "task_id": task_id,
                "status": "error",
                "duration_ms": round((time_mod.monotonic() - start) * 1000, 1),
                "error": str(e)[:200],
            },
        )
        stage = getattr(e, "stage", None)
        retryable = getattr(e, "retryable", True)
        if not retryable:
            kwargs = {"error_message": str(e)[:1000]}
            if stage:
                kwargs["failed_stage"] = stage
            update_task_status(task_id, "error", **kwargs)
        else:
            if self.request.retries >= self.max_retries:
                kwargs = {"error_message": str(e)[:1000]}
                if stage:
                    kwargs["failed_stage"] = stage
                update_task_status(task_id, "error", **kwargs)
            else:
                try:
                    raise self.retry(exc=e)
                except self.MaxRetriesExceededError:
                    kwargs = {"error_message": str(e)[:1000]}
                    if stage:
                        kwargs["failed_stage"] = stage
                    update_task_status(task_id, "error", **kwargs)
    finally:
        _task_id_var.reset(token)
        try:
            del _llm_key
            del _asr_key
        except Exception:
            pass


def _run_pipeline(task_id, video_path, config, llm_api_key, asr_api_key):
    from app.worker.pipeline import run as run_pipeline

    run_pipeline(task_id, video_path, config, llm_api_key, asr_api_key)


@celery_app.task(name="app.worker.celery_app.cleanup_expired_tasks")
def cleanup_expired_tasks():
    from app.models.task import delete_task, get_expired_tasks

    retention = settings.retention_days
    logger = logging.getLogger("cleanup")

    try:
        tasks = get_expired_tasks(retention)
    except Exception as e:
        logger.error(f"清理任务查询失败: {e}")
        return

    for task in tasks:
        tid = task["id"]
        video_dir = os.path.join("data", "videos", tid)
        output_dir = os.path.join("data", "output", tid)
        both_cleared = True
        for d in (video_dir, output_dir):
            if os.path.isdir(d):
                try:
                    shutil.rmtree(d)
                except PermissionError:
                    logger.error(f"清理目录 {d} 时权限不足，跳过")
                    both_cleared = False
                except Exception as e:
                    logger.error(f"清理目录 {d} 失败: {e}")
                    both_cleared = False
        if both_cleared:
            delete_task(tid)
            logger.info(f"已清理过期任务: {tid}")
        else:
            logger.warning(f"任务 {tid} 部分目录清理失败，保留数据库记录")


@celery_app.task(
    name="app.worker.celery_app.export_clips_task",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    acks_late=True,
)
def export_clips_task(
    self,
    task_id: str,
    clip_indices: list[int] | None = None,
    burn_subtitle: bool = False,
):
    """Celery task: export clips via ffmpeg (runs in worker, not FastAPI)."""
    import json
    import os

    from app.logging_config import _task_id_var
    from app.models.task import ensure_clips_have_ids, get_task, update_task_status

    token = _task_id_var.set(task_id)
    start = time_mod.monotonic()
    _logger.info(
        "task.lifecycle",
        extra={
            "task_id": task_id,
            "status": "started",
            "task_name": "export_clips_task",
        },
    )

    task = get_task(task_id)
    if task is None:
        logging.error("export_clips_task: task %s not found", task_id)
        _task_id_var.reset(token)
        return

    config = json.loads(task.get("config_json") or "{}")
    buffer = config.get("buffer_seconds", 3)
    video_path = task.get("video_path", "")

    try:
        clips = json.loads(task.get("clips_json") or "[]")
    except json.JSONDecodeError:
        clips = []
    clips_json_with_ids = ensure_clips_have_ids(json.dumps(clips, ensure_ascii=False))
    try:
        clips = json.loads(clips_json_with_ids or "[]")
    except json.JSONDecodeError:
        clips = []
    output_dir = os.path.join("data", "output", task_id)

    # Filter clips
    if clip_indices:
        selected = [
            (i, c) for i, c in enumerate(clips) if i in clip_indices and c.get("status") != "failed"
        ]
    else:
        selected = [(i, c) for i, c in enumerate(clips) if c.get("status") != "failed"]

    if not selected:
        update_task_status(
            task_id,
            "error",
            failed_stage="ai_exporting",
            error_message="No valid clips to export",
        )
        _logger.error(
            "task.lifecycle",
            extra={
                "task_id": task_id,
                "status": "error",
                "error": "No valid clips to export",
            },
        )
        _task_id_var.reset(token)
        return

    # Load transcript for subtitle burning
    segments = []
    transcript_path = os.path.join(output_dir, "transcript.json")
    if burn_subtitle and os.path.isfile(transcript_path):
        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
        except Exception:
            pass

    from app.services.ffprobe import FFprobeError, probe
    from app.worker.pipeline import _export_clip

    # Probe video for duration (classic pipeline parity)
    video_duration = 0.0
    try:
        info = probe(video_path)
        video_duration = info.duration
    except FFprobeError as e:
        logging.warning("export_clips_task: ffprobe failed: %s", e)

    max_duration = config.get("clip_max_duration", 120)
    subtitle_style_cfg = config.get("subtitle_style") or {}

    os.makedirs(output_dir, exist_ok=True)
    update_task_status(task_id, "processing", stage="ai_exporting")
    # Count pre-existing successes so a re-export that fails doesn't
    # overwrite an already-successful task with "error"
    success_count = sum(
        1 for _, c in selected if c.get("status") == "success" and c.get("filepath")
    )
    for idx, clip in selected:
        try:
            out = _export_clip(
                video_path,
                output_dir,
                idx,
                clip,
                buffer,
                burn_subtitle,
                segments,
                max_duration=max_duration,
                video_duration=video_duration,
                subtitle_style_cfg=subtitle_style_cfg,
            )
            clip["filepath"] = out.get("video", "")
            clip["thumbnail_path"] = out.get("thumbnail", "")
            clip["export_start_time_s"] = out.get("export_start", clip.get("start_time_s", 0))
            clip["export_end_time_s"] = out.get("export_end", clip.get("end_time_s", 0))
            clip["status"] = "success"
            success_count += 1
        except Exception as e:
            if clip.get("status") != "success":
                clip["status"] = "failed"
            logging.warning("export_clips_task: clip %d failed: %s", idx, e)

    # Re-read clips from DB to avoid overwriting concurrent analysis results.
    # Only patch the export fields (status, filepath, etc.) into whatever is
    # currently stored — do NOT replace the entire clips array.
    from app.models.task import get_task as _re_get_task

    _fresh = _re_get_task(task_id)
    if _fresh is not None:
        try:
            fresh_clips = json.loads(_fresh.get("clips_json") or "[]")
            fresh_json_with_ids = ensure_clips_have_ids(json.dumps(fresh_clips, ensure_ascii=False))
            fresh_clips = json.loads(fresh_json_with_ids or "[]")
            fresh_by_clip_id = {
                str(fc.get("clip_id")): fc
                for fc in fresh_clips
                if isinstance(fc, dict) and fc.get("clip_id")
            }
            # Match exported results back to current clips by stable clip_id,
            # falling back to index for legacy data that cannot be identified.
            for idx, exported in selected:
                clip_id = str(exported.get("clip_id") or "")
                fc = fresh_by_clip_id.get(clip_id) if clip_id else None
                if fc is None and not clip_id and idx < len(fresh_clips):
                    fc = fresh_clips[idx]
                if fc is None:
                    continue
                fc["status"] = exported.get("status", fc.get("status"))
                fc["filepath"] = exported.get("filepath", fc.get("filepath"))
                fc["thumbnail_path"] = exported.get("thumbnail_path", fc.get("thumbnail_path"))
                fc["export_start_time_s"] = exported.get(
                    "export_start_time_s", fc.get("export_start_time_s")
                )
                fc["export_end_time_s"] = exported.get(
                    "export_end_time_s", fc.get("export_end_time_s")
                )
        except json.JSONDecodeError:
            fresh_clips = clips  # fall back to original
        clips = fresh_clips

    # Write manifest.json (classic pipeline parity)
    manifest_path = os.path.join(output_dir, "manifest.json")
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"task_id": task_id, "clips": clips}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning("export_clips_task: failed to write manifest.json: %s", e)

    is_error = success_count == 0 and len(selected) > 0
    new_status = "error" if is_error else "done"
    kwargs = {
        "clips_json": json.dumps(clips, ensure_ascii=False),
        "stage": None,
    }
    if is_error:
        kwargs["error_message"] = "All clip exports failed"
        kwargs["failed_stage"] = "ai_exporting"
    else:
        kwargs["completed_at"] = utcnow_iso()
        kwargs["error_message"] = None
        kwargs["failed_stage"] = None

    update_task_status(task_id, new_status, **kwargs)
    _logger.info(
        "task.lifecycle",
        extra={
            "task_id": task_id,
            "status": new_status,
            "duration_ms": round((time_mod.monotonic() - start) * 1000, 1),
        },
    )
    _task_id_var.reset(token)
