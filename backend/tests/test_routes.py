"""Tests for API routes using FastAPI TestClient."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _setup_temp_db(db_path):
    import app.config
    import app.models.task as task_mod

    app.config.settings.database_path = db_path
    task_mod.DB_PATH = Path(db_path)
    from app.models.task import init_db

    init_db()


def _insert_task(db_path, task_id, clips):
    import sqlite3

    conn = sqlite3.connect(db_path)
    now = "2026-05-26T00:00:00+00:00"
    conn.execute(
        """INSERT INTO tasks (id, status, video_path, video_filename,
           config_json, clips_json, created_at, updated_at)
           VALUES (?, 'done', ?, ?, ?, ?, ?, ?)""",
        (
            task_id,
            f"data/videos/{task_id}/original.mp4",
            "test.mp4",
            json.dumps({"llm_base_url": "http://x", "llm_model": "m"}),
            json.dumps(clips),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()


def _make_client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def _make_info(duration=600.0):
    """Create a mock VideoInfo with attributes needed by probe consumers."""
    info = MagicMock()
    info.duration = duration
    info.width = 1920
    info.height = 1080
    info.codec = "h264"
    info.container = "mp4"
    info.fps = 30.0
    info.fps_mode = "stable"
    info.has_video = True
    info.subtitle_streams = []
    return info


# ── AC-1: POST upload validation ──────────────────────────────────────────


def test_upload_rejects_unsupported_extension():
    """POST /api/tasks returns 400 for files with unsupported extensions."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.post(
            "/api/tasks",
            files={"file": ("test.txt", b"not a video", "text/plain")},
            data={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude-opus-4-7",
                "llm_api_key": "sk-test",
            },
        )
        assert response.status_code == 400
        assert "不支持的视频格式" in response.json()["detail"]
    finally:
        os.unlink(db_path)


# ── AC-5: download clip_index validation ──────────────────────────────────


def test_download_rejects_non_integer_clip_index():
    """GET download returns 400 when clip_index is not an integer."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.get("/api/tasks/any-task/clips/abc/download")
        assert response.status_code == 400
        assert "无效的片段索引" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_download_rejects_negative_clip_index():
    """GET download returns 400 when clip_index is negative."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.get("/api/tasks/any-task/clips/-1/download")
        assert response.status_code == 400
        assert "无效的片段索引" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_download_rejects_out_of_range_index():
    """GET download returns 404 when clip_index exceeds clips array length."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-out-of-range"
        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": f"/tmp/{task_id}/clip_000.mp4",
                }
            ],
        )
        # Create parent dir so path ownership check passes
        os.makedirs(f"/tmp/{task_id}", exist_ok=True)
        Path(f"/tmp/{task_id}/clip_000.mp4").touch()

        client = _make_client()

        with patch("app.api.clips.OUTPUT_DIR", Path("/tmp")):
            response = client.get(f"/api/tasks/{task_id}/clips/5/download")
        assert response.status_code == 404
        assert "片段不存在" in response.json()["detail"]
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(f"/tmp/{task_id}", ignore_errors=True)


def test_download_rejects_path_traversal():
    """GET download returns 400 when clip filepath is outside task output dir."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-path-traversal"
        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": "/etc/passwd",
                }
            ],
        )
        # Path traversal check happens before file existence check

        client = _make_client()
        response = client.get(f"/api/tasks/{task_id}/clips/0/download")
        assert response.status_code == 400
        assert "无效的片段路径" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_get_task_includes_media_info_from_db_cache():
    """GET task returns fps metadata from DB cache (no ffprobe call)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "00000000-0000-0000-0000-000000000201"
        video_dir = tempfile.mkdtemp()
        video_path = Path(video_dir) / "original.mp4"
        video_path.write_bytes(b"fake mp4")
        _insert_task_full(db_path, task_id, video_path=str(video_path))

        client = _make_client()
        # No probe patch — media_info now reads from DB cache
        response = client.get(f"/api/tasks/{task_id}")

        assert response.status_code == 200
        media_info = response.json()["media_info"]
        assert media_info == {"fps": 29.97, "fps_mode": "stable"}
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(video_dir, ignore_errors=True)


def test_video_endpoint_serves_original_video():
    """GET original video endpoint returns the task video file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "00000000-0000-0000-0000-000000000202"
        tmp_videos = tempfile.mkdtemp()
        task_video_dir = Path(tmp_videos) / task_id
        task_video_dir.mkdir(parents=True)
        video_path = task_video_dir / "original.mp4"
        video_path.write_bytes(b"fake video bytes")
        _insert_task_full(db_path, task_id, video_path=str(video_path))

        client = _make_client()
        with patch("app.api._common.VIDEOS_DIR", Path(tmp_videos)):
            response = client.get(f"/api/tasks/{task_id}/video")

        assert response.status_code == 200
        assert "video/mp4" in response.headers["content-type"]
        assert response.content == b"fake video bytes"
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_videos, ignore_errors=True)


def test_video_endpoint_supports_range_requests():
    """GET original video endpoint supports byte-range requests for seeking."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "00000000-0000-0000-0000-000000000204"
        tmp_videos = tempfile.mkdtemp()
        task_video_dir = Path(tmp_videos) / task_id
        task_video_dir.mkdir(parents=True)
        video_path = task_video_dir / "original.mp4"
        video_path.write_bytes(b"0123456789")
        _insert_task_full(db_path, task_id, video_path=str(video_path))

        client = _make_client()
        with patch("app.api._common.VIDEOS_DIR", Path(tmp_videos)):
            response = client.get(
                f"/api/tasks/{task_id}/video",
                headers={"Range": "bytes=2-5"},
            )

        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-range"].startswith("bytes 2-5/10")
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_videos, ignore_errors=True)


def test_video_endpoint_rejects_path_traversal():
    """GET original video endpoint rejects DB paths outside the task video dir."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "00000000-0000-0000-0000-000000000203"
        tmp_videos = tempfile.mkdtemp()
        _insert_task_full(db_path, task_id, video_path="/etc/passwd")

        client = _make_client()
        with patch("app.api._common.VIDEOS_DIR", Path(tmp_videos)):
            response = client.get(f"/api/tasks/{task_id}/video")

        assert response.status_code == 400
        assert "视频路径" in response.json()["detail"]
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_videos, ignore_errors=True)


# ── AC-5: thumbnail clip_index validation ─────────────────────────────────


def test_thumbnail_rejects_non_integer_clip_index():
    """GET thumbnail returns 400 when clip_index is not an integer."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.get("/api/tasks/any-task/clips/abc/thumbnail")
        assert response.status_code == 400
        assert "无效的片段索引" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_thumbnail_rejects_negative_clip_index():
    """GET thumbnail returns 400 when clip_index is negative."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.get("/api/tasks/any-task/clips/-1/thumbnail")
        assert response.status_code == 400
        assert "无效的片段索引" in response.json()["detail"]
    finally:
        os.unlink(db_path)


# ── AC-1: valid upload with monkeypatched probe + Celery ──────────────────


def test_upload_valid_file_returns_201():
    """POST /api/tasks uses server settings keys and does not require browser keys."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        tmp_videos = tempfile.mkdtemp()
        tmp_output = tempfile.mkdtemp()
        client = _make_client()

        with (
            patch("app.api.tasks_crud.settings.llm_api_key", "settings-llm-secret"),
            patch("app.api.tasks_crud.settings.asr_api_key", "settings-asr-secret"),
            patch("app.api.tasks_crud.probe", return_value=_make_info()),
            patch("app.worker.celery_app.process_video_task.apply_async") as mock_apply,
            patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
        ):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.anthropic.com",
                    "llm_model": "claude-opus-4-7",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert "task_id" in data
        task_id = data["task_id"]

        from app.models.task import get_task

        task = get_task(task_id)
        assert task is not None
        assert task["status"] == "queued"

        config_json = json.loads(task["config_json"])
        assert "llm_api_key" not in config_json
        assert "asr_api_key" not in config_json
        assert "sk-ant" not in json.dumps(config_json)

        mock_apply.assert_called_once()
        kwargs = mock_apply.call_args.kwargs["kwargs"]
        from app.crypto import decrypt_api_key

        assert decrypt_api_key(kwargs["llm_api_key"]) == "settings-llm-secret"
        assert decrypt_api_key(kwargs["asr_api_key"]) == "settings-asr-secret"
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_videos, ignore_errors=True)
        shutil.rmtree(tmp_output, ignore_errors=True)


# ── AC-5: successful download / thumbnail responses ──────────────────────


def test_download_success_returns_mp4():
    """GET download returns 200 with video/mp4 and Content-Disposition header."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-download-ok"
        tmp_output = tempfile.mkdtemp()
        task_output = Path(tmp_output) / task_id
        task_output.mkdir(parents=True, exist_ok=True)
        clip_file = task_output / "clip_000.mp4"
        clip_file.write_text("fake mp4 content")

        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": str(clip_file),
                }
            ],
        )

        client = _make_client()
        with patch("app.api.clips.OUTPUT_DIR", Path(tmp_output)):
            response = client.get(f"/api/tasks/{task_id}/clips/0/download")

        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"
        cd = response.headers["content-disposition"]
        assert "attachment" in cd
        assert "clip_000.mp4" in cd
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_output, ignore_errors=True)


def test_download_rejects_failed_clip():
    """GET download returns 404 when clip status is 'failed'."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-failed-clip"
        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.5,
                    "reason": "test",
                    "status": "failed",
                    "filepath": "/some/path.mp4",
                    "error": "ffmpeg failed",
                }
            ],
        )

        client = _make_client()
        response = client.get(f"/api/tasks/{task_id}/clips/0/download")
        assert response.status_code == 404
        assert "导出失败" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_download_rejects_missing_file():
    """GET download returns 404 when clip filepath does not exist on disk."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-missing-file"
        tmp_output = tempfile.mkdtemp()
        missing_path = str(Path(tmp_output) / task_id / "clip_000.mp4")

        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": missing_path,
                }
            ],
        )

        client = _make_client()
        with patch("app.api.clips.OUTPUT_DIR", Path(tmp_output)):
            response = client.get(f"/api/tasks/{task_id}/clips/0/download")
        assert response.status_code == 404
        assert "片段文件不存在" in response.json()["detail"]
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_output, ignore_errors=True)


def test_thumbnail_success_returns_jpeg():
    """GET thumbnail returns 200 with image/jpeg content type."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-thumb-ok"
        tmp_output = tempfile.mkdtemp()
        task_output = Path(tmp_output) / task_id
        task_output.mkdir(parents=True, exist_ok=True)
        thumb_file = task_output / "clip_000.jpg"
        thumb_file.write_text("fake jpeg")

        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": str(task_output / "clip_000.mp4"),
                    "thumbnail_path": str(thumb_file),
                }
            ],
        )

        client = _make_client()
        with patch("app.api.clips.OUTPUT_DIR", Path(tmp_output)):
            response = client.get(f"/api/tasks/{task_id}/clips/0/thumbnail")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_output, ignore_errors=True)


def test_thumbnail_rejects_out_of_range_index():
    """GET thumbnail returns 404 when clip_index exceeds clips array length."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-thumb-oob"
        tmp_output = tempfile.mkdtemp()

        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": str(Path(tmp_output) / task_id / "clip_000.mp4"),
                    "thumbnail_path": str(Path(tmp_output) / task_id / "clip_000.jpg"),
                }
            ],
        )

        client = _make_client()
        with patch("app.api.clips.OUTPUT_DIR", Path(tmp_output)):
            response = client.get(f"/api/tasks/{task_id}/clips/5/thumbnail")
        assert response.status_code == 404
        assert "片段不存在" in response.json()["detail"]
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_output, ignore_errors=True)


def test_thumbnail_rejects_path_traversal():
    """GET thumbnail returns 400 when thumbnail_path is outside task output dir."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-thumb-traversal"
        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": f"/tmp/{task_id}/clip_000.mp4",
                    "thumbnail_path": "/etc/passwd",
                }
            ],
        )

        client = _make_client()
        response = client.get(f"/api/tasks/{task_id}/clips/0/thumbnail")
        assert response.status_code == 400
        assert "无效的缩略图路径" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_thumbnail_rejects_missing_file():
    """GET thumbnail returns 404 when thumbnail file does not exist on disk."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "test-thumb-missing"
        tmp_output = tempfile.mkdtemp()
        missing_thumb = str(Path(tmp_output) / task_id / "clip_000.jpg")

        _insert_task(
            db_path,
            task_id,
            [
                {
                    "start_time_s": 10.0,
                    "end_time_s": 50.0,
                    "score": 0.9,
                    "reason": "test",
                    "status": "success",
                    "filepath": str(Path(tmp_output) / task_id / "clip_000.mp4"),
                    "thumbnail_path": missing_thumb,
                }
            ],
        )

        client = _make_client()
        with patch("app.api.clips.OUTPUT_DIR", Path(tmp_output)):
            response = client.get(f"/api/tasks/{task_id}/clips/0/thumbnail")
        assert response.status_code == 404
        assert "缩略图文件不存在" in response.json()["detail"]
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_output, ignore_errors=True)


# ── AC-1: 413 oversized upload ──────────────────────────────────────────────


def test_upload_oversized_file_returns_413():
    """POST /api/tasks returns 413 when file exceeds max_upload_size_bytes."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        with patch("app.api.tasks_crud.settings.max_upload_size_bytes", 5):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"x" * 100, "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )
        assert response.status_code == 413
        detail = response.json()["detail"]
        assert "大小" in detail or "2GB" in detail
    finally:
        os.unlink(db_path)


# ── AC-1.1: config validation matrix (422) ──────────────────────────────────


def test_upload_non_url_base_url_returns_422():
    """POST /api/tasks returns 422 when llm_base_url is not a valid URL."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.post(
            "/api/tasks",
            files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
            data={
                "llm_base_url": "not-a-valid-url",
                "llm_model": "m",
                "llm_api_key": "sk-test",
            },
        )
        assert response.status_code == 422
        assert "llm_base_url" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_upload_empty_model_returns_422():
    """POST /api/tasks returns 422 when llm_model is empty."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.post(
            "/api/tasks",
            files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
            data={
                "llm_base_url": "https://api.example.com",
                "llm_model": "",
                "llm_api_key": "sk-test",
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert "llm_model" in str(body)
    finally:
        os.unlink(db_path)


def test_upload_negative_min_duration_returns_422():
    """POST /api/tasks returns 422 when clip_min_duration is negative."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.post(
            "/api/tasks",
            files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
            data={
                "llm_base_url": "https://api.example.com",
                "llm_model": "m",
                "llm_api_key": "sk-test",
                "clip_min_duration": "-10",
            },
        )
        assert response.status_code == 422
        assert "clip_min_duration" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_upload_max_less_than_min_returns_422():
    """POST /api/tasks returns 422 when clip_max_duration < clip_min_duration."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.post(
            "/api/tasks",
            files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
            data={
                "llm_base_url": "https://api.example.com",
                "llm_model": "m",
                "llm_api_key": "sk-test",
                "clip_min_duration": "120",
                "clip_max_duration": "30",
            },
        )
        assert response.status_code == 422
        assert "不能小于" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_upload_negative_buffer_returns_422():
    """POST /api/tasks returns 422 when buffer_seconds is negative."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        response = client.post(
            "/api/tasks",
            files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
            data={
                "llm_base_url": "https://api.example.com",
                "llm_model": "m",
                "llm_api_key": "sk-test",
                "buffer_seconds": "-5",
            },
        )
        assert response.status_code == 422
        assert "buffer_seconds" in response.json()["detail"]
    finally:
        os.unlink(db_path)


# ── AC-1: ffprobe error mappings ───────────────────────────────────────────


def test_upload_format_not_supported_returns_400():
    """POST /api/tasks returns 400 when ffprobe raises FormatNotSupported."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        from app.services.ffprobe import FormatNotSupported

        with patch("app.api.tasks_crud.probe", side_effect=FormatNotSupported("wmv")):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )
        assert response.status_code == 400
        assert "不支持的视频格式" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_upload_no_video_stream_returns_400():
    """POST /api/tasks returns 400 when ffprobe raises NoVideoStream."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        from app.services.ffprobe import NoVideoStream

        with patch("app.api.tasks_crud.probe", side_effect=NoVideoStream()):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )
        assert response.status_code == 400
        assert "视频流" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_upload_duration_too_long_returns_400():
    """POST /api/tasks returns 400 when ffprobe raises DurationTooLong."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        from app.services.ffprobe import DurationTooLong

        with patch("app.api.tasks_crud.probe", side_effect=DurationTooLong(99999)):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )
        assert response.status_code == 400
        assert "超过限制" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_upload_corrupted_video_returns_400():
    """POST /api/tasks returns 400 when ffprobe raises CorruptedVideo."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        from app.services.ffprobe import CorruptedVideo

        with patch("app.api.tasks_crud.probe", side_effect=CorruptedVideo("bad file")):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "无法读取" in detail or "损坏" in detail
    finally:
        os.unlink(db_path)


def test_upload_generic_ffprobe_error_returns_500():
    """POST /api/tasks returns 500 when ffprobe raises FFprobeError."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        from app.services.ffprobe import FFprobeError

        with patch(
            "app.api.tasks_crud.probe", side_effect=FFprobeError("ffprobe crash")
        ):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )
        assert response.status_code == 500
    finally:
        os.unlink(db_path)


# ── AC-1: disk-full 507 ────────────────────────────────────────────────────


def test_upload_disk_full_on_move_returns_507():
    """POST /api/tasks returns 507 when shutil.move fails with errno 28 (disk full)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()

        disk_full = OSError(28, "No space left on device")
        disk_full.errno = 28

        with (
            patch("app.api.tasks_crud.probe", return_value=_make_info()),
            patch("app.api.tasks_crud.shutil.move", side_effect=disk_full),
            patch("app.api.tasks_crud.delete_task"),
            patch("app.models.task.update_task_status"),
        ):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )
        assert response.status_code == 507
        assert "磁盘空间不足" in response.json()["detail"]
    finally:
        os.unlink(db_path)


# ── AC-1: queue failure cleanup ─────────────────────────────────────────────


def test_upload_apply_async_failure_cleans_up():
    """POST /api/tasks returns 500, DB row and video directory are cleaned up."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        tmp_videos = tempfile.mkdtemp()
        tmp_output = tempfile.mkdtemp()
        client = _make_client()

        from app.models.task import create_task as real_create
        from app.models.task import get_task

        created_ids = []

        def capture_create(*args, **kwargs):
            tid = real_create(*args, **kwargs)
            created_ids.append(tid)
            return tid

        with (
            patch("app.api.tasks_crud.probe", return_value=_make_info()),
            patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
            patch("app.api.tasks_crud.create_task", side_effect=capture_create),
            patch(
                "app.worker.celery_app.process_video_task.apply_async",
                side_effect=RuntimeError("redis down"),
            ) as mock_apply,
        ):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )

        assert response.status_code == 500
        assert "任务队列失败" in response.json()["detail"]
        mock_apply.assert_called_once()
        assert "task_id" not in response.json()
        assert len(created_ids) == 1
        assert get_task(created_ids[0]) is None
        assert not os.path.exists(Path(tmp_videos) / created_ids[0])
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_videos, ignore_errors=True)
        shutil.rmtree(tmp_output, ignore_errors=True)


def test_upload_queued_update_failure_cleans_up():
    """POST /api/tasks returns 500, DB row and video directory are cleaned up."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        tmp_videos = tempfile.mkdtemp()
        tmp_output = tempfile.mkdtemp()
        client = _make_client()

        from app.models.task import create_task as real_create
        from app.models.task import get_task

        created_ids = []
        call_count = [0]

        def capture_create(*args, **kwargs):
            tid = real_create(*args, **kwargs)
            created_ids.append(tid)
            return tid

        def update_side_effect(task_id, status, **kwargs):
            call_count[0] += 1
            if status == "queued":
                raise RuntimeError("db locked")

        with (
            patch("app.api.tasks_crud.probe", return_value=_make_info()),
            patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
            patch("app.api.tasks_crud.create_task", side_effect=capture_create),
            patch("app.worker.celery_app.process_video_task.apply_async"),
            patch(
                "app.api.tasks_crud.update_task_status", side_effect=update_side_effect
            ),
        ):
            response = client.post(
                "/api/tasks",
                files={"file": ("test.mp4", b"fake mp4", "video/mp4")},
                data={
                    "llm_base_url": "https://api.example.com",
                    "llm_model": "m",
                    "llm_api_key": "sk-test",
                },
            )

        assert response.status_code == 500
        assert "入队状态更新失败" in response.json()["detail"]
        assert len(created_ids) == 1
        assert get_task(created_ids[0]) is None
        assert not os.path.exists(Path(tmp_videos) / created_ids[0])
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_videos, ignore_errors=True)
        shutil.rmtree(tmp_output, ignore_errors=True)


# ── transcript endpoint ───────────────────────────────────────────────────────


def _insert_task_full(db_path, task_id, **overrides):
    import sqlite3

    conn = sqlite3.connect(db_path)
    now = "2026-05-26T00:00:00+00:00"
    row = {
        "id": task_id,
        "status": "done",
        "video_path": f"data/videos/{task_id}/original.mp4",
        "video_filename": "test.mp4",
        "config_json": json.dumps({"llm_base_url": "http://x", "llm_model": "m"}),
        "clips_json": "[]",
        "created_at": now,
        "updated_at": now,
        "media_info_json": json.dumps({"fps": 29.97, "fps_mode": "stable"}),
    }
    row.update(overrides)
    conn.execute(
        """INSERT INTO tasks (id, status, stage, video_path, video_filename,
           config_json, clips_json, error_message, failed_stage,
           empty_clips_reason, created_at, updated_at, media_info_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["id"],
            row["status"],
            row.get("stage"),
            row["video_path"],
            row["video_filename"],
            row["config_json"],
            row["clips_json"],
            row.get("error_message"),
            row.get("failed_stage"),
            row.get("empty_clips_reason"),
            row["created_at"],
            row["updated_at"],
            row.get("media_info_json"),
        ),
    )
    conn.commit()
    conn.close()
