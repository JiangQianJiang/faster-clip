"""Clip endpoints: download, thumbnail, subtitles, delete."""

import json
import os
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api._common import OUTPUT_DIR
from app.models.task import (
    ensure_clips_have_ids,
    get_task,
    update_task_if_version,
    update_task_status,
)
from app.services.subtitle import get_clip_subtitle_segments

router = APIRouter(prefix="/api/tasks", tags=["clips"])


@router.get("/{task_id}/clips/{clip_index}/download")
async def download_clip(task_id: str, clip_index: str):
    try:
        idx = int(clip_index)
    except (ValueError, TypeError):
        raise HTTPException(400, detail="无效的片段索引")

    if idx < 0:
        raise HTTPException(400, detail="无效的片段索引")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    try:
        clips = json.loads(task.get("clips_json") or "[]")
    except json.JSONDecodeError:
        clips = []

    if idx >= len(clips):
        raise HTTPException(404, detail="片段不存在")

    clip = clips[idx]
    if clip.get("status") == "failed":
        raise HTTPException(404, detail="该片段导出失败，无法下载")

    filepath = clip.get("filepath", "")
    if not filepath:
        raise HTTPException(404, detail="片段文件不存在")

    abs_filepath = os.path.abspath(filepath)
    task_output_root = os.path.abspath(str(OUTPUT_DIR / task_id))
    if (
        not abs_filepath.startswith(task_output_root + os.sep)
        and abs_filepath != task_output_root
    ):
        raise HTTPException(400, detail="无效的片段路径")

    if not os.path.isfile(abs_filepath):
        raise HTTPException(404, detail="片段文件不存在")

    filename = os.path.basename(abs_filepath)
    return FileResponse(
        path=abs_filepath,
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{task_id}/clips/{clip_index}/thumbnail")
async def thumbnail_clip(task_id: str, clip_index: str):
    try:
        idx = int(clip_index)
    except (ValueError, TypeError):
        raise HTTPException(400, detail="无效的片段索引")

    if idx < 0:
        raise HTTPException(400, detail="无效的片段索引")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    try:
        clips = json.loads(task.get("clips_json") or "[]")
    except json.JSONDecodeError:
        clips = []

    if idx >= len(clips):
        raise HTTPException(404, detail="片段不存在")

    clip = clips[idx]
    thumb_path = clip.get("thumbnail_path", "")
    if not thumb_path:
        raise HTTPException(404, detail="缩略图不存在")

    abs_path = os.path.abspath(thumb_path)
    task_output_root = os.path.abspath(str(OUTPUT_DIR / task_id))
    if (
        not abs_path.startswith(task_output_root + os.sep)
        and abs_path != task_output_root
    ):
        raise HTTPException(400, detail="无效的缩略图路径")

    if not os.path.isfile(abs_path):
        raise HTTPException(404, detail="缩略图文件不存在")

    return FileResponse(path=abs_path, media_type="image/jpeg")



@router.get("/{task_id}/clips/{clip_index}/subtitles")
async def download_clip_subtitles(task_id: str, clip_index: str, format: str = "srt"):
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid task_id")

    try:
        idx = int(clip_index)
    except (ValueError, TypeError):
        raise HTTPException(400, detail="无效的片段索引")

    if idx < 0:
        raise HTTPException(400, detail="无效的片段索引")

    supported = {"srt", "vtt", "ass"}
    if format not in supported:
        raise HTTPException(
            400, detail=f"不支持的字幕格式: {format}，支持: srt, vtt, ass"
        )

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    try:
        clips = json.loads(task.get("clips_json") or "[]")
    except json.JSONDecodeError:
        clips = []

    if idx >= len(clips):
        raise HTTPException(404, detail="片段不存在")

    clip = clips[idx]
    if clip.get("status") == "failed":
        raise HTTPException(404, detail="该片段导出失败，字幕不可用")

    sub_path = OUTPUT_DIR / task_id / f"clip_{idx:03d}.{format}"
    abs_path = os.path.abspath(str(sub_path))
    task_output_root = os.path.abspath(str(OUTPUT_DIR / task_id))
    if (
        not abs_path.startswith(task_output_root + os.sep)
        and abs_path != task_output_root
    ):
        raise HTTPException(400, detail="无效的字幕路径")

    transcript_path = str(OUTPUT_DIR / task_id / "transcript.json")
    if not os.path.isfile(abs_path):
        # Sidecar missing — (re)generate from transcript with line-breaker.
        if not os.path.isfile(transcript_path):
            raise HTTPException(404, detail="字幕文件不存在")
        try:
            with open(transcript_path, encoding="utf-8") as f:
                all_segments = json.load(f)
            window_start = clip.get("export_start_time_s", 0)
            window_end = clip.get("export_end_time_s", 0)
            filtered = get_clip_subtitle_segments(
                all_segments, window_start, window_end
            )
            from app.services.line_breaker import break_lines, split_segments

            filtered = split_segments(filtered)
            for seg in filtered:
                seg["text"] = break_lines(seg["text"])
            from app.services.subtitle import (
                segments_to_ass,
                segments_to_srt,
                segments_to_vtt,
            )

            formatters = {
                "srt": segments_to_srt,
                "vtt": segments_to_vtt,
                "ass": segments_to_ass,
            }
            content = formatters[format](filtered)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            raise HTTPException(404, detail="字幕文件不存在")

    media_types = {"srt": "text/plain", "vtt": "text/plain", "ass": "text/x-ssa"}
    filename = f"clip_{idx:03d}.{format}"
    return FileResponse(
        path=abs_path,
        media_type=media_types.get(format, "text/plain"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{task_id}/clips/{clip_index}/subtitles/json")
async def get_clip_subtitles_json(task_id: str, clip_index: str):
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid task_id")

    try:
        idx = int(clip_index)
    except (ValueError, TypeError):
        raise HTTPException(400, detail="无效的片段索引")

    if idx < 0:
        raise HTTPException(400, detail="无效的片段索引")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    try:
        clips = json.loads(task.get("clips_json") or "[]")
    except json.JSONDecodeError:
        clips = []

    if idx >= len(clips):
        raise HTTPException(404, detail="片段不存在")

    clip = clips[idx]
    if clip.get("status") == "failed":
        raise HTTPException(404, detail="该片段导出失败，字幕不可用")

    transcript_path = OUTPUT_DIR / task_id / "transcript.json"
    if not os.path.isfile(transcript_path):
        return {
            "clip_index": idx,
            "start_time_s": clip.get("export_start_time_s", 0),
            "end_time_s": clip.get("export_end_time_s", 0),
            "segments": [],
        }

    try:
        with open(transcript_path, encoding="utf-8") as f:
            segments = json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(500, detail="字幕文件格式错误")

    window_start = clip.get("export_start_time_s", 0)
    window_end = clip.get("export_end_time_s", 0)
    filtered = get_clip_subtitle_segments(segments, window_start, window_end)

    return {
        "clip_index": idx,
        "start_time_s": window_start,
        "end_time_s": window_end,
        "segments": filtered,
    }


@router.delete("/{task_id}/clips/{clip_index}")
async def delete_clip_endpoint(task_id: str, clip_index: str):
    """Delete a single clip by index (classic mode). Returns the updated clip list."""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid task_id")

    try:
        idx = int(clip_index)
    except (ValueError, TypeError):
        raise HTTPException(400, detail="无效的片段索引")

    if idx < 0:
        raise HTTPException(400, detail="无效的片段索引")

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    if task.get("status") in ("queued", "processing"):
        raise HTTPException(409, detail="任务处理中，无法删除片段，请等待完成")

    try:
        clips = json.loads(task.get("clips_json") or "[]")
    except json.JSONDecodeError:
        clips = []

    if idx >= len(clips):
        raise HTTPException(404, detail="片段不存在")

    clip = clips.pop(idx)

    # Backfill clip_ids and use conditional update BEFORE any cleanup
    clips_json = ensure_clips_have_ids(json.dumps(clips, ensure_ascii=False))
    current_version = task.get("version", 0)
    result = update_task_if_version(
        task_id,
        expected_version=current_version,
        clips_json=clips_json,
    )
    if result is None:
        task_r = get_task(task_id)
        cv = task_r.get("version", 0) if task_r else 0
        raise HTTPException(
            409,
            detail=f"片段已被其他客户端修改（版本: {cv}），请刷新后重试",
        )

    # CAS succeeded — now safe to clean up files
    from app.tools.user.delete_clip import _cleanup_clip_files

    _cleanup_clip_files(task_id, clip, clip_index=idx)

    return {"deleted": clip, "clips": json.loads(clips_json or "[]")}
