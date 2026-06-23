"""Tests for cleanup task selection logic."""

import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.models.task as task_mod
from app.models.task import create_task, get_expired_tasks, get_task, init_db


def _iso(days_ago: int = 0, hours_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago, hours=hours_ago)).isoformat()


def _use_temp_db(tmp_path: str):
    """Point both settings and module-level DB_PATH to a temp database."""
    import app.config

    app.config.settings.database_path = tmp_path
    task_mod.DB_PATH = Path(tmp_path)


def test_done_older_than_retention_selected():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()
        tid = create_task(tmp_path, "done_task", {"llm_base_url": "http://x", "llm_model": "m"})
        import sqlite3

        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ?, status = 'done' WHERE id = ?",
            (_iso(days_ago=8), _iso(days_ago=8), tid),
        )
        conn.commit()
        conn.close()

        tasks = get_expired_tasks(7)
        assert any(t["id"] == tid for t in tasks), "done task >7d should be expired"
    finally:
        os.unlink(tmp_path)


def test_error_older_than_retention_selected():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()
        tid = create_task(tmp_path, "error_task", {"llm_base_url": "http://x", "llm_model": "m"})
        import sqlite3

        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ?, status = 'error' WHERE id = ?",
            (_iso(days_ago=8), _iso(days_ago=8), tid),
        )
        conn.commit()
        conn.close()

        tasks = get_expired_tasks(7)
        assert any(t["id"] == tid for t in tasks), "error task >7d should be expired"
    finally:
        os.unlink(tmp_path)


def test_done_within_retention_not_selected():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()
        tid = create_task(tmp_path, "recent", {"llm_base_url": "http://x", "llm_model": "m"})
        import sqlite3

        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ?, status = 'done' WHERE id = ?",
            (_iso(days_ago=3), _iso(days_ago=3), tid),
        )
        conn.commit()
        conn.close()

        tasks = get_expired_tasks(7)
        assert not any(t["id"] == tid for t in tasks), "done task <7d should not be expired"
    finally:
        os.unlink(tmp_path)


def test_pending_requires_both_timestamps_expired():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()
        tid = create_task(tmp_path, "zombie", {"llm_base_url": "http://x", "llm_model": "m"})
        import sqlite3

        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ?, status = 'pending' WHERE id = ?",
            (_iso(days_ago=8), _iso(days_ago=1), tid),
        )
        conn.commit()
        conn.close()

        tasks = get_expired_tasks(7)
        assert not any(t["id"] == tid for t in tasks), (
            "pending with recent updated_at should NOT be expired"
        )
    finally:
        os.unlink(tmp_path)


def test_pending_both_old_selected():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()
        tid = create_task(tmp_path, "zombie2", {"llm_base_url": "http://x", "llm_model": "m"})
        import sqlite3

        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ?, status = 'pending' WHERE id = ?",
            (_iso(days_ago=8), _iso(days_ago=8), tid),
        )
        conn.commit()
        conn.close()

        tasks = get_expired_tasks(7)
        assert any(t["id"] == tid for t in tasks), (
            "pending with both timestamps >7d should be expired"
        )
    finally:
        os.unlink(tmp_path)


def test_processing_never_selected():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()
        # Stagnant processing task (updated_at 30 days ago) should be selected
        tid = create_task(tmp_path, "stuck", {"llm_base_url": "http://x", "llm_model": "m"})
        import sqlite3

        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ?, status = 'processing' WHERE id = ?",
            (_iso(days_ago=30), _iso(days_ago=30), tid),
        )
        conn.commit()
        conn.close()

        tasks = get_expired_tasks(7)
        assert any(t["id"] == tid for t in tasks), (
            "stagnant processing task (updated_at older than retention) should be expired"
        )

    finally:
        os.unlink(tmp_path)


def test_processing_recent_not_expired():
    """Processing tasks updated within retention period should not be expired."""
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _use_temp_db(tmp_path)
    try:
        _use_temp_db(tmp_path)
        init_db()
        tid = create_task(
            tmp_path,
            "active-processing",
            {"llm_base_url": "http://x", "llm_model": "m"},
        )
        import sqlite3

        conn = sqlite3.connect(tmp_path)
        # Processing task updated only 1 day ago — should NOT be expired
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ?, status = 'processing' WHERE id = ?",
            (_iso(days_ago=10), _iso(days_ago=1), tid),
        )
        conn.commit()
        conn.close()

        tasks = get_expired_tasks(7)
        assert not any(t["id"] == tid for t in tasks), (
            "recently updated processing task should not be expired"
        )
    finally:
        os.unlink(tmp_path)


# ── AC-9: cleanup_expired_tasks() deletion behavior ──────────────────────


def test_cleanup_deletes_dirs_and_db_row():
    """cleanup_expired_tasks removes real directories and DB row on success."""
    import shutil
    from unittest.mock import patch

    from app.worker.celery_app import cleanup_expired_tasks

    tmp_videos = tempfile.mkdtemp()
    tmp_output = tempfile.mkdtemp()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _use_temp_db(db_path)
        init_db()

        # Insert an expired task directly
        conn = __import__("sqlite3").connect(db_path)
        tid = "task-real-delete"
        conn.execute(
            """INSERT INTO tasks (id, status, video_path, video_filename,
               config_json, created_at, updated_at)
               VALUES (?, 'done', ?, ?, ?, ?, ?)""",
            (
                tid,
                f"data/videos/{tid}/original.mp4",
                "test.mp4",
                '{"llm_base_url":"http://x","llm_model":"m"}',
                _iso(days_ago=8),
                _iso(days_ago=8),
            ),
        )
        conn.commit()
        conn.close()

        # Create real directories with files
        task_video_dir = os.path.join(tmp_videos, tid)
        task_output_dir = os.path.join(tmp_output, tid)
        os.makedirs(task_video_dir)
        os.makedirs(task_output_dir)
        Path(os.path.join(task_video_dir, "original.mp4")).touch()
        Path(os.path.join(task_output_dir, "manifest.json")).touch()

        # Redirect hardcoded paths to temp dirs
        orig_join = os.path.join

        def fake_join(*args):
            result = orig_join(*args)
            if result.startswith("data/videos/"):
                return result.replace("data/videos/", tmp_videos + "/", 1)
            if result.startswith("data/output/"):
                return result.replace("data/output/", tmp_output + "/", 1)
            return result

        with patch("app.worker.celery_app.os.path.join", side_effect=fake_join):
            cleanup_expired_tasks()

        # Directories should be deleted
        assert not os.path.exists(task_video_dir), "video dir should be deleted"
        assert not os.path.exists(task_output_dir), "output dir should be deleted"

        # DB row should be deleted
        assert get_task(tid) is None, "DB row should be deleted"
    finally:
        os.unlink(db_path)
        shutil.rmtree(tmp_videos, ignore_errors=True)
        shutil.rmtree(tmp_output, ignore_errors=True)


def test_permission_error_preserves_db_row():
    """PermissionError on rmtree keeps the DB row (both_cleared=False)."""
    import shutil
    from unittest.mock import patch

    from app.worker.celery_app import cleanup_expired_tasks

    tmp_videos = tempfile.mkdtemp()
    tmp_output = tempfile.mkdtemp()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _use_temp_db(db_path)
        init_db()

        tid = "task-perm-fail"
        conn = __import__("sqlite3").connect(db_path)
        conn.execute(
            """INSERT INTO tasks (id, status, video_path, video_filename,
               config_json, created_at, updated_at)
               VALUES (?, 'done', ?, ?, ?, ?, ?)""",
            (
                tid,
                f"data/videos/{tid}/original.mp4",
                "test.mp4",
                '{"llm_base_url":"http://x","llm_model":"m"}',
                _iso(days_ago=8),
                _iso(days_ago=8),
            ),
        )
        conn.commit()
        conn.close()

        task_video_dir = os.path.join(tmp_videos, tid)
        task_output_dir = os.path.join(tmp_output, tid)
        os.makedirs(task_video_dir)
        os.makedirs(task_output_dir)
        Path(os.path.join(task_video_dir, "original.mp4")).touch()

        orig_join = os.path.join

        def fake_join(*args):
            result = orig_join(*args)
            if result.startswith("data/videos/"):
                return result.replace("data/videos/", tmp_videos + "/", 1)
            if result.startswith("data/output/"):
                return result.replace("data/output/", tmp_output + "/", 1)
            return result

        with (
            patch("app.worker.celery_app.os.path.join", side_effect=fake_join),
            patch(
                "app.worker.celery_app.shutil.rmtree",
                side_effect=PermissionError("denied"),
            ),
        ):
            cleanup_expired_tasks()

        # Directories should still exist
        assert os.path.exists(task_video_dir), "video dir should remain after PermissionError"
        assert os.path.exists(task_output_dir), "output dir should remain after PermissionError"

        # DB row should NOT be deleted
        task = get_task(tid)
        assert task is not None, "DB row should be preserved after PermissionError"
        assert task["id"] == tid
    finally:
        os.unlink(db_path)
        shutil.rmtree(tmp_videos, ignore_errors=True)
        shutil.rmtree(tmp_output, ignore_errors=True)


def test_cleanup_continues_after_permission_error():
    """cleanup_expired_tasks continues to next task after one fails."""
    import shutil
    from unittest.mock import patch

    from app.worker.celery_app import cleanup_expired_tasks

    tmp_videos = tempfile.mkdtemp()
    tmp_output = tempfile.mkdtemp()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        _use_temp_db(db_path)
        init_db()

        tid_fail = "task-continue-fail"
        tid_ok = "task-continue-ok"
        conn = __import__("sqlite3").connect(db_path)
        for tid in (tid_fail, tid_ok):
            conn.execute(
                """INSERT INTO tasks (id, status, video_path, video_filename,
                   config_json, created_at, updated_at)
                   VALUES (?, 'done', ?, ?, ?, ?, ?)""",
                (
                    tid,
                    f"data/videos/{tid}/original.mp4",
                    "test.mp4",
                    '{"llm_base_url":"http://x","llm_model":"m"}',
                    _iso(days_ago=8),
                    _iso(days_ago=8),
                ),
            )
        conn.commit()
        conn.close()

        # Create real dirs for both tasks
        for tid in (tid_fail, tid_ok):
            os.makedirs(os.path.join(tmp_videos, tid))
            os.makedirs(os.path.join(tmp_output, tid))
            Path(os.path.join(tmp_videos, tid, "original.mp4")).touch()

        orig_join = os.path.join

        def fake_join(*args):
            result = orig_join(*args)
            if result.startswith("data/videos/"):
                return result.replace("data/videos/", tmp_videos + "/", 1)
            if result.startswith("data/output/"):
                return result.replace("data/output/", tmp_output + "/", 1)
            return result

        # shutil.rmtree fails only for tid_fail
        orig_rmtree = shutil.rmtree

        def fake_rmtree(d, **kwargs):
            if tid_fail in d:
                raise PermissionError("denied")
            return orig_rmtree(d, **kwargs)

        with (
            patch("app.worker.celery_app.os.path.join", side_effect=fake_join),
            patch("app.worker.celery_app.shutil.rmtree", side_effect=fake_rmtree),
        ):
            cleanup_expired_tasks()

        # Failed task: dirs remain, DB row preserved
        assert os.path.exists(os.path.join(tmp_videos, tid_fail))
        assert get_task(tid_fail) is not None, "failed task DB row should be preserved"

        # Successful task: dirs deleted, DB row removed
        assert not os.path.exists(os.path.join(tmp_videos, tid_ok)), (
            "successful task video dir should be deleted"
        )
        assert not os.path.exists(os.path.join(tmp_output, tid_ok)), (
            "successful task output dir should be deleted"
        )
        assert get_task(tid_ok) is None, "successful task DB row should be deleted"
    finally:
        os.unlink(db_path)
        shutil.rmtree(tmp_videos, ignore_errors=True)
        shutil.rmtree(tmp_output, ignore_errors=True)
