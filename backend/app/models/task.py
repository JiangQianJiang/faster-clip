"""Task database model and persistence operations."""

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from app.config import settings

DB_PATH = Path(settings.database_path)
SCHEMA_VERSION = 6

VALID_STATUSES = ("pending", "queued", "processing", "done", "error")

_MIGRATION_LOCK_FILE = DB_PATH.parent / ".migration.lock"


def _with_retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    if attempt < 2:
                        time.sleep(0.1)
                        continue
                raise
        return None

    return wrapper


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


from contextlib import contextmanager


@contextmanager
def _migration_lock(timeout: int = 30):
    """Context manager that owns and releases a file-based migration lock.

    Raises RuntimeError if the lock cannot be acquired within timeout.
    Lock acquisition is separate from the yield so migration-body exceptions
    are never caught as lock-acquisition errors.
    """
    import fcntl

    _MIGRATION_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(_MIGRATION_LOCK_FILE), os.O_CREAT | os.O_RDWR)
    deadline = time.time() + timeout
    # Phase 1: acquire lock (no yield — exceptions here are lock failures)
    while time.time() < deadline:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(0.5)
        except OSError:
            os.close(fd)
            raise RuntimeError("无法获取迁移锁：文件系统错误")
    else:
        os.close(fd)
        raise RuntimeError(
            f"无法在 {timeout}s 内获取迁移锁，请确认没有其他进程正在运行迁移"
        )
    # Phase 2: lock held — yield with nested cleanup so close always runs
    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def init_db():
    with _migration_lock():
        _init_db_impl()


def _init_db_impl():
    """Run schema migrations. Must be called inside _migration_lock."""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
        """)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0

        if current < 1:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    stage TEXT,
                    video_path TEXT,
                    video_filename TEXT,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    subtitle_segment_count INTEGER,
                    clips_json TEXT,
                    error_message TEXT,
                    failed_stage TEXT,
                    empty_clips_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
            """)
            if current == 0:
                conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            else:
                conn.execute("UPDATE schema_version SET version = 1")

        if current < 2:
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN transcript_source TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN transcript_modified_at TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute("UPDATE schema_version SET version = 2")

        if current < 3:
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN chat_history_json TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN chat_updated_at TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute("UPDATE schema_version SET version = 3")

        if current < 4:
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN media_info_json TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute("UPDATE schema_version SET version = 4")

        if current < 5:
            for col, default in [
                ("version", "0"),
                ("transcript_version", "0"),
                ("chat_version", "0"),
            ]:
                try:
                    conn.execute(
                        f"ALTER TABLE tasks ADD COLUMN {col} INTEGER NOT NULL DEFAULT {default}"
                    )
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            # Verify columns exist before advancing version
            cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if {"version", "transcript_version", "chat_version"}.issubset(cols):
                conn.execute("UPDATE schema_version SET version = 5")

        if current < 6:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT,
                    error_message TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    state_before TEXT,
                    state_after TEXT,
                    attempt INTEGER DEFAULT 1
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_runs_task_id_started_at "
                "ON tool_runs(task_id, started_at)"
            )
            conn.execute("UPDATE schema_version SET version = 6")

        conn.commit()
    finally:
        conn.close()


@_with_retry
def create_task(video_path: str, video_filename: str, config: dict) -> str:
    task_id = str(uuid.uuid4())
    now = _now()

    clean_config = {
        k: v for k, v in config.items() if k not in ("llm_api_key", "asr_api_key")
    }

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO tasks (id, status, video_path, video_filename,
               config_json, created_at, updated_at)
               VALUES (?, 'pending', ?, ?, ?, ?, ?)""",
            (task_id, video_path, video_filename, json.dumps(clean_config), now, now),
        )
        conn.commit()
        return task_id
    finally:
        conn.close()


@_with_retry
def update_task_status(task_id: str, status: str, **kwargs):
    if status not in VALID_STATUSES:
        raise ValueError(f"无效的任务状态: {status}")
    allowed = {
        "stage",
        "error_message",
        "failed_stage",
        "empty_clips_reason",
        "subtitle_segment_count",
        "clips_json",
        "config_json",
        "started_at",
        "completed_at",
        "video_path",
        "transcript_source",
        "transcript_modified_at",
        "chat_history_json",
        "chat_updated_at",
        "media_info_json",
    }
    fields = {"status": status, "updated_at": _now()}
    for k, v in kwargs.items():
        if k in allowed:
            fields[k] = v

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]

    conn = _get_conn()
    try:
        cursor = conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        if cursor.rowcount == 0:
            logging.warning(
                "update_task_status: task row not found (may have been deleted): %s",
                task_id,
            )
            return False
        conn.commit()
        return True
    finally:
        conn.close()


@_with_retry
def get_task(task_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


@_with_retry
def update_chat_history(task_id: str, chat_history_json: str, chat_updated_at: str):
    """Update chat history fields without touching task status.

    This avoids clobbering status when the worker and chat concurrently
    update the same task row (e.g., during async export).
    """
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE tasks SET chat_history_json = ?, chat_updated_at = ? WHERE id = ?",
            (chat_history_json, chat_updated_at, task_id),
        )
        conn.commit()
    finally:
        conn.close()


@_with_retry
def delete_task(task_id: str) -> bool:
    conn = _get_conn()
    try:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


@_with_retry
def get_expired_tasks(retention_days: int) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status IN ('done', 'error') AND created_at < ?",
            (_days_ago(retention_days),),
        ).fetchall()
        rows += conn.execute(
            "SELECT * FROM tasks WHERE status IN ('pending', 'queued') "
            "AND created_at < ? AND updated_at < ?",
            (_days_ago(retention_days), _days_ago(retention_days)),
        ).fetchall()
        # Stagnant processing tasks (worker crash, deletion race, etc.)
        rows += conn.execute(
            "SELECT * FROM tasks WHERE status = 'processing' AND updated_at < ?",
            (_days_ago(retention_days),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@_with_retry
def list_tasks(limit: int = 50, after: str | None = None) -> list[dict]:
    conn = _get_conn()
    try:
        if after:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE created_at < ? ORDER BY created_at DESC LIMIT ?",
                (after, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@_with_retry
def update_task_if_version(task_id: str, expected_version: int, **fields) -> dict | None:
    """Conditional update: only succeeds if version matches. Returns updated row or None."""
    if not fields:
        return get_task(task_id)

    set_parts = [f"{k} = ?" for k in fields]
    set_parts.append("version = version + 1")
    set_parts.append("updated_at = ?")

    values = list(fields.values()) + [_now(), task_id, expected_version]

    conn = _get_conn()
    try:
        cursor = conn.execute(
            f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = ? AND version = ?",
            values,
        )
        if cursor.rowcount == 0:
            # Check if task exists at all (distinguish missing from version conflict)
            exists = conn.execute(
                "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return None  # None = conflict or missing; caller checks get_task
        conn.commit()
        return get_task(task_id)
    finally:
        conn.close()


@_with_retry
def update_chat_history_if_version(
    task_id: str, expected_chat_version: int, chat_history_json: str, chat_updated_at: str
) -> bool:
    """Conditional chat history update. Returns True on success, False on conflict."""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            """UPDATE tasks
               SET chat_history_json = ?, chat_updated_at = ?, chat_version = chat_version + 1
               WHERE id = ? AND chat_version = ?""",
            (chat_history_json, chat_updated_at, task_id, expected_chat_version),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


@_with_retry
def bump_transcript_version_if_current(
    task_id: str,
    expected_transcript_version: int,
    modified_at: str,
    **fields,
) -> bool:
    """Update transcript-related fields only if transcript_version matches.
    Returns True on success, False on conflict."""
    allowed = {
        "subtitle_segment_count",
        "transcript_source",
        "transcript_modified_at",
    }
    set_parts = [
        "transcript_version = transcript_version + 1",
        "transcript_modified_at = ?",
        "updated_at = ?",
    ]
    values = [modified_at, _now()]

    for k, v in fields.items():
        if k in allowed:
            set_parts.append(f"{k} = ?")
            values.append(v)

    values.extend([task_id, expected_transcript_version])

    conn = _get_conn()
    try:
        cursor = conn.execute(
            f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = ? AND transcript_version = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


_SENSITIVE_FIELD_NAMES = {
    "llm_api_key",
    "asr_api_key",
    "_runtime_api_key",
    "authorization",
    "access_token",
}

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"ACCESS_TOKEN\\s*[=:]\\s*[^\\s,}\\]]+", re.IGNORECASE),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
)


def _redact_sensitive_text(text: str) -> str:
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _sanitize_tool_payload(value):
    """Remove known secret fields and redact API-key shaped strings."""
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                continue
            sanitized[_redact_sensitive_text(key_text)] = _sanitize_tool_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_tool_payload(item) for item in value]
    return value


def _to_sanitized_json(value) -> str:
    return json.dumps(_sanitize_tool_payload(value), ensure_ascii=False)


def _finish_tool_run(
    run_id: str,
    *,
    status: str,
    output_data=None,
    error_message: str | None = None,
    state_after: str | None = None,
    duration_ms: int | None = None,
) -> None:
    finished_at = _now()
    output_json = _to_sanitized_json(output_data) if output_data is not None else None
    error_text = _redact_sensitive_text(error_message or "") if error_message else None
    conn = _get_conn()
    try:
        cursor = conn.execute(
            """UPDATE tool_runs
               SET status = ?, output_json = ?, error_message = ?,
                   finished_at = ?, duration_ms = ?, state_after = ?
               WHERE id = ?""",
            (status, output_json, error_text, finished_at, duration_ms, state_after, run_id),
        )
        if cursor.rowcount == 0:
            raise RuntimeError(f"tool_run not found: {run_id}")
        conn.commit()
    except Exception:
        logging.exception("tool_run_finish_failed run_id=%s status=%s", run_id, status)
        raise
    finally:
        conn.close()


@_with_retry
def create_tool_run(
    *,
    task_id: str,
    tool_name: str,
    input_data: dict,
    state_before: str | None = None,
    attempt: int = 1,
) -> str:
    run_id = str(uuid.uuid4())
    now = _now()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO tool_runs (
                   id, task_id, tool_name, status, input_json,
                   started_at, state_before, attempt
               ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)""",
            (
                run_id,
                task_id,
                tool_name,
                _to_sanitized_json(input_data),
                now,
                state_before,
                attempt,
            ),
        )
        conn.commit()
        return run_id
    except Exception:
        logging.exception("tool_run_create_failed task_id=%s tool=%s", task_id, tool_name)
        raise
    finally:
        conn.close()


@_with_retry
def finish_tool_run_success(
    run_id: str,
    *,
    output_data,
    state_after: str | None = None,
    duration_ms: int | None = None,
) -> None:
    _finish_tool_run(
        run_id,
        status="success",
        output_data=output_data,
        state_after=state_after,
        duration_ms=duration_ms,
    )


@_with_retry
def finish_tool_run_error(
    run_id: str,
    *,
    error_message: str,
    duration_ms: int | None = None,
    state_after: str | None = None,
) -> None:
    _finish_tool_run(
        run_id,
        status="error",
        error_message=error_message,
        state_after=state_after,
        duration_ms=duration_ms,
    )


@_with_retry
def finish_tool_run_rejected(
    run_id: str,
    *,
    reason: str,
    duration_ms: int | None = None,
    state_after: str | None = None,
) -> None:
    _finish_tool_run(
        run_id,
        status="rejected",
        error_message=reason,
        state_after=state_after,
        duration_ms=duration_ms,
    )


@_with_retry
def list_tool_runs(task_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM tool_runs WHERE task_id = ? ORDER BY started_at ASC, id ASC",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _derive_clip_id(clip: dict) -> str:
    """Deterministically derive a UUID from stable clip properties for idempotent backfill."""
    import hashlib

    start = clip.get("start_time_s", 0)
    end = clip.get("end_time_s", 0)
    title = clip.get("reason", "") or ""
    material = f"{start:.3f}|{end:.3f}|{title}"
    digest = hashlib.sha256(material.encode()).hexdigest()[:32]
    # Format as UUID v5-style
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def ensure_clips_have_ids(clips_json: str | None) -> str | None:
    """Backfill clip_id UUIDs for legacy clips that lack them. Idempotent."""
    if not clips_json:
        return clips_json
    try:
        clips = json.loads(clips_json)
    except (json.JSONDecodeError, TypeError):
        return clips_json

    changed = False
    for clip in clips:
        if isinstance(clip, dict) and not clip.get("clip_id"):
            clip["clip_id"] = _derive_clip_id(clip)
            changed = True

    return json.dumps(clips) if changed else clips_json


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _days_ago(n: int) -> str:
    from datetime import timedelta

    return (datetime.now(UTC) - timedelta(days=n)).isoformat()
