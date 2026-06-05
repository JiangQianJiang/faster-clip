"""Shared utilities for API route modules."""

import json
import os
import shutil
from pathlib import Path

from fastapi import HTTPException

from app.models.task import delete_task

DATA_DIR = Path("data")
VIDEOS_DIR = DATA_DIR / "videos"
OUTPUT_DIR = DATA_DIR / "output"
SUBTITLE_MAX_SIZE = 5 * 1024 * 1024  # 5MB


def _cleanup_task(task_id: str, video_dir: Path | None = None):
    try:
        delete_task(task_id)
    except Exception:
        pass
    if video_dir and video_dir.exists():
        shutil.rmtree(str(video_dir), ignore_errors=True)


def _media_info_for_task(task: dict) -> dict:
    """Return cached media info from DB (lightweight — no ffprobe call)."""
    try:
        stored = json.loads(task.get("media_info_json") or "{}")
    except json.JSONDecodeError:
        stored = {}
    if stored:
        return stored
    return {"fps": 0.0, "fps_mode": "average"}


def _ensure_task_video_path(task_id: str, video_path: str) -> str:
    if not video_path:
        raise HTTPException(404, detail="原始视频不存在")

    abs_path = os.path.abspath(video_path)
    task_video_root = os.path.abspath(str(VIDEOS_DIR / task_id))
    if (
        not abs_path.startswith(task_video_root + os.sep)
        and abs_path != task_video_root
    ):
        raise HTTPException(400, detail="无效的视频路径")

    if not os.path.isfile(abs_path):
        raise HTTPException(404, detail="原始视频不存在")

    return abs_path
