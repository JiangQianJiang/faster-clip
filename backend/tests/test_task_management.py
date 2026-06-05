"""Tests for GET /api/tasks list and DELETE /api/tasks/{task_id} endpoints."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_routes import _insert_task_full, _make_client, _setup_temp_db

# ── AC-1: GET /api/tasks list endpoint ─────────────────────────────────────


def test_list_empty_returns_empty_array():
    """GET /api/tasks returns empty array when no tasks exist."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        os.unlink(db_path)


def test_list_returns_tasks_ordered_by_created_at_desc():
    """GET /api/tasks returns tasks ordered by created_at descending."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        _insert_task_full(
            db_path,
            "a0000000-0000-0000-0000-000000000001",
            status="done",
            created_at="2026-05-20T00:00:00+00:00",
        )
        _insert_task_full(
            db_path,
            "a0000000-0000-0000-0000-000000000002",
            status="done",
            created_at="2026-05-25T00:00:00+00:00",
        )
        _insert_task_full(
            db_path,
            "a0000000-0000-0000-0000-000000000003",
            status="error",
            created_at="2026-05-22T00:00:00+00:00",
        )

        client = _make_client()
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data[0]["task_id"] == "a0000000-0000-0000-0000-000000000002"
        assert data[1]["task_id"] == "a0000000-0000-0000-0000-000000000003"
        assert data[2]["task_id"] == "a0000000-0000-0000-0000-000000000001"
    finally:
        os.unlink(db_path)


def test_list_respects_limit():
    """GET /api/tasks?limit=N returns at most N tasks."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        for i in range(5):
            _insert_task_full(
                db_path,
                f"a0000000-0000-0000-0000-00000000000{i}",
                created_at=f"2026-05-2{i}T00:00:00+00:00",
            )

        client = _make_client()
        response = client.get("/api/tasks?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2
    finally:
        os.unlink(db_path)


def test_list_rejects_non_positive_limit():
    """GET /api/tasks?limit=0 returns 422."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()
        response = client.get("/api/tasks?limit=0")
        assert response.status_code == 422
        assert "limit" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_list_shape_has_no_config():
    """GET /api/tasks response items have lightweight shape without config field."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        _insert_task_full(
            db_path,
            "a0000000-0000-0000-0000-000000000001",
            status="done",
            created_at="2026-05-26T00:00:00+00:00",
            clips_json=json.dumps(
                [
                    {
                        "start_time_s": 0,
                        "end_time_s": 10,
                        "score": 0.9,
                        "reason": "test",
                        "status": "success",
                        "filepath": "/tmp/clip.mp4",
                    }
                ]
            ),
        )

        client = _make_client()
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        item = data[0]
        assert "task_id" in item
        assert "status" in item
        assert "clips_count" in item
        assert item["clips_count"] == 1
        assert "config" not in item
    finally:
        os.unlink(db_path)


# ── AC-2: DELETE /api/tasks/{task_id} endpoint ─────────────────────────────


def test_delete_success_returns_204():
    """DELETE /api/tasks/{id} returns 204 and removes the task."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "a0000000-0000-0000-0000-000000000001"
        _insert_task_full(db_path, task_id, status="done")

        client = _make_client()
        response = client.delete(f"/api/tasks/{task_id}")
        assert response.status_code == 204
        assert response.content == b""

        from app.models.task import get_task

        assert get_task(task_id) is None
    finally:
        os.unlink(db_path)


def test_delete_not_found_returns_404():
    """DELETE /api/tasks/{id} returns 404 for non-existent task."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()
        response = client.delete("/api/tasks/a0000000-0000-0000-0000-000000000099")
        assert response.status_code == 404
        assert "Task not found" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_delete_invalid_uuid_returns_400():
    """DELETE /api/tasks/{id} returns 400 for invalid UUID format."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        client = _make_client()
        response = client.delete("/api/tasks/not-a-valid-uuid")
        assert response.status_code == 400
        assert "Invalid task_id" in response.json()["detail"]
    finally:
        os.unlink(db_path)


def test_delete_pending_revokes_without_terminate():
    """DELETE /api/tasks/{id} for pending task calls revoke with terminate=False."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "a0000000-0000-0000-0000-000000000001"
        _insert_task_full(db_path, task_id, status="pending")

        client = _make_client()
        with patch("app.worker.celery_app.celery_app.control.revoke") as mock_revoke:
            response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 204
        mock_revoke.assert_any_call(task_id, terminate=False)
    finally:
        os.unlink(db_path)


def test_delete_queued_revokes_without_terminate():
    """DELETE /api/tasks/{id} for queued task calls revoke with terminate=False."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "a0000000-0000-0000-0000-000000000001"
        _insert_task_full(db_path, task_id, status="queued")

        client = _make_client()
        with patch("app.worker.celery_app.celery_app.control.revoke") as mock_revoke:
            response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 204
        mock_revoke.assert_any_call(task_id, terminate=False)
    finally:
        os.unlink(db_path)


def test_delete_processing_revokes_with_terminate():
    """DELETE /api/tasks/{id} for processing task calls revoke with terminate=True."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "a0000000-0000-0000-0000-000000000001"
        _insert_task_full(db_path, task_id, status="processing")

        client = _make_client()
        with patch("app.worker.celery_app.celery_app.control.revoke") as mock_revoke:
            response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 204
        mock_revoke.assert_any_call(task_id, terminate=True)
    finally:
        os.unlink(db_path)


def test_delete_done_does_not_revoke():
    """DELETE /api/tasks/{id} for done task does not call Celery revoke."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "a0000000-0000-0000-0000-000000000001"
        _insert_task_full(db_path, task_id, status="done")

        client = _make_client()
        with patch("app.worker.celery_app.celery_app.control.revoke") as mock_revoke:
            response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 204
        mock_revoke.assert_not_called()
    finally:
        os.unlink(db_path)


def test_delete_cleans_up_video_and_output_dirs():
    """DELETE /api/tasks/{id} removes video and output directories."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "a0000000-0000-0000-0000-000000000001"
        _insert_task_full(db_path, task_id, status="done")

        tmp_videos = tempfile.mkdtemp()
        tmp_output = tempfile.mkdtemp()
        video_dir = Path(tmp_videos) / task_id
        output_dir = Path(tmp_output) / task_id
        video_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "original.mp4").write_text("fake video")
        (output_dir / "manifest.json").write_text("{}")

        client = _make_client()
        with (
            patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
        ):
            response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 204
        assert not video_dir.exists()
        assert not output_dir.exists()
    finally:
        os.unlink(db_path)
        import shutil

        shutil.rmtree(tmp_videos, ignore_errors=True)
        shutil.rmtree(tmp_output, ignore_errors=True)


def test_delete_idempotent():
    """DELETE /api/tasks/{id} is idempotent - second delete returns 404."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _setup_temp_db(db_path)
        task_id = "a0000000-0000-0000-0000-000000000001"
        _insert_task_full(db_path, task_id, status="done")

        client = _make_client()
        r1 = client.delete(f"/api/tasks/{task_id}")
        assert r1.status_code == 204

        r2 = client.delete(f"/api/tasks/{task_id}")
        assert r2.status_code == 404
    finally:
        os.unlink(db_path)
