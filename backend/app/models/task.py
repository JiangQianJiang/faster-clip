"""Task database model and persistence operations."""

import json
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from app.config import settings
from app.database import BaseDatabase, get_database

DB_PATH = Path(settings.database_path)
SCHEMA_VERSION = 6

VALID_STATUSES = ("pending", "queued", "processing", "done", "error")

_MIGRATION_LOCK_FILE = DB_PATH.parent / ".migration.lock"


def _database() -> BaseDatabase:
    return get_database(DB_PATH)


def _is_retryable_db_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in (
            "locked",
            "busy",
            "deadlock",
            "lock wait timeout",
            "try restarting transaction",
        )
    )


def _with_retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if _is_retryable_db_error(e) and attempt < 2:
                    time.sleep(0.1)
                    continue
                raise
        return None

    return wrapper


from contextlib import contextmanager


@contextmanager
def _migration_lock(timeout: int = 30):
    if settings.database_engine == "mysql":
        yield
        return

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
        raise RuntimeError(f"无法在 {timeout}s 内获取迁移锁，请确认没有其他进程正在运行迁移")
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
    db = _database()
    with db.transaction() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
        """)
        _ensure_tasks_table(conn, settings.database_engine)
        _ensure_tool_runs_table(conn, settings.database_engine)
        row = conn.fetchone("SELECT version FROM schema_version")
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def _text_type(engine: str) -> str:
    return "LONGTEXT" if engine == "mysql" else "TEXT"


def _short_text_type(engine: str) -> str:
    return "VARCHAR(255)" if engine == "mysql" else "TEXT"


def _id_type(engine: str) -> str:
    return "VARCHAR(36)" if engine == "mysql" else "TEXT"


def _table_columns(conn, table_name: str, engine: str) -> set[str]:
    if engine == "mysql":
        rows = conn.fetchall(f"SHOW COLUMNS FROM {table_name}")
        return {row["Field"] for row in rows}
    rows = conn.fetchall(f"PRAGMA table_info({table_name})")
    return {row["name"] for row in rows}


def _add_missing_columns(conn, table_name: str, engine: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table_name, engine)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def _ensure_index(conn, table_name: str, index_name: str, columns: str, engine: str) -> None:
    if engine == "mysql":
        row = conn.fetchone(
            f"SHOW INDEX FROM {table_name} WHERE Key_name = ?",
            (index_name,),
        )
        if row is None:
            conn.execute(f"CREATE INDEX {index_name} ON {table_name}({columns})")
        return
    conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({columns})")


def _ensure_tasks_table(conn, engine: str) -> None:
    text_type = _text_type(engine)
    short_text_type = _short_text_type(engine)
    id_type = _id_type(engine)
    config_default = "NOT NULL" if engine == "mysql" else "NOT NULL DEFAULT '{}'"
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS tasks (
            id {id_type} PRIMARY KEY,
            status {short_text_type} NOT NULL DEFAULT 'pending',
            stage {short_text_type},
            video_path {text_type},
            video_filename {text_type},
            config_json {text_type} {config_default},
            subtitle_segment_count INTEGER,
            clips_json {text_type},
            error_message {text_type},
            failed_stage {short_text_type},
            empty_clips_reason {text_type},
            created_at {short_text_type} NOT NULL,
            updated_at {short_text_type} NOT NULL,
            started_at {short_text_type},
            completed_at {short_text_type},
            transcript_source {short_text_type},
            transcript_modified_at {short_text_type},
            chat_history_json {text_type},
            chat_updated_at {short_text_type},
            media_info_json {text_type},
            version INTEGER NOT NULL DEFAULT 0,
            transcript_version INTEGER NOT NULL DEFAULT 0,
            chat_version INTEGER NOT NULL DEFAULT 0
        )
    """)
    _add_missing_columns(
        conn,
        "tasks",
        engine,
        {
            "transcript_source": short_text_type,
            "transcript_modified_at": short_text_type,
            "chat_history_json": text_type,
            "chat_updated_at": short_text_type,
            "media_info_json": text_type,
            "version": "INTEGER NOT NULL DEFAULT 0",
            "transcript_version": "INTEGER NOT NULL DEFAULT 0",
            "chat_version": "INTEGER NOT NULL DEFAULT 0",
        },
    )


def _ensure_tool_runs_table(conn, engine: str) -> None:
    text_type = _text_type(engine)
    short_text_type = _short_text_type(engine)
    id_type = _id_type(engine)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS tool_runs (
            id {id_type} PRIMARY KEY,
            task_id {id_type} NOT NULL,
            tool_name {short_text_type} NOT NULL,
            status {short_text_type} NOT NULL,
            input_json {text_type} NOT NULL,
            output_json {text_type},
            error_message {text_type},
            started_at {short_text_type} NOT NULL,
            finished_at {short_text_type},
            duration_ms INTEGER,
            state_before {short_text_type},
            state_after {short_text_type},
            attempt INTEGER DEFAULT 1
        )
    """)
    _add_missing_columns(
        conn,
        "tool_runs",
        engine,
        {
            "output_json": text_type,
            "error_message": text_type,
            "finished_at": short_text_type,
            "duration_ms": "INTEGER",
            "state_before": short_text_type,
            "state_after": short_text_type,
            "attempt": "INTEGER DEFAULT 1",
        },
    )
    _ensure_index(
        conn,
        "tool_runs",
        "idx_tool_runs_task_id_started_at",
        "task_id, started_at",
        engine,
    )


@_with_retry
def create_task(video_path: str, video_filename: str, config: dict) -> str:
    task_id = str(uuid.uuid4())
    now = _now()

    clean_config = {k: v for k, v in config.items() if k not in ("llm_api_key", "asr_api_key")}

    with _database().transaction() as conn:
        conn.execute(
            """INSERT INTO tasks (id, status, video_path, video_filename,
               config_json, created_at, updated_at)
               VALUES (?, 'pending', ?, ?, ?, ?, ?)""",
            (task_id, video_path, video_filename, json.dumps(clean_config), now, now),
        )
        return task_id


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

    with _database().transaction() as conn:
        cursor = conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        if cursor.rowcount == 0:
            logging.warning(
                "update_task_status: task row not found (may have been deleted): %s",
                task_id,
            )
            return False
        return True


@_with_retry
def get_task(task_id: str) -> dict | None:
    with _database().connect() as conn:
        return conn.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))


@_with_retry
def update_chat_history(task_id: str, chat_history_json: str, chat_updated_at: str):
    """Update chat history fields without touching task status.

    This avoids clobbering status when the worker and chat concurrently
    update the same task row (e.g., during async export).
    """
    with _database().transaction() as conn:
        conn.execute(
            "UPDATE tasks SET chat_history_json = ?, chat_updated_at = ? WHERE id = ?",
            (chat_history_json, chat_updated_at, task_id),
        )


@_with_retry
def delete_task(task_id: str) -> bool:
    with _database().transaction() as conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0


@_with_retry
def get_expired_tasks(retention_days: int) -> list[dict]:
    with _database().connect() as conn:
        rows = conn.fetchall(
            "SELECT * FROM tasks WHERE status IN ('done', 'error') AND created_at < ?",
            (_days_ago(retention_days),),
        )
        rows += conn.fetchall(
            "SELECT * FROM tasks WHERE status IN ('pending', 'queued') "
            "AND created_at < ? AND updated_at < ?",
            (_days_ago(retention_days), _days_ago(retention_days)),
        )
        # Stagnant processing tasks (worker crash, deletion race, etc.)
        rows += conn.fetchall(
            "SELECT * FROM tasks WHERE status = 'processing' AND updated_at < ?",
            (_days_ago(retention_days),),
        )
        return rows


@_with_retry
def list_tasks(limit: int = 50, after: str | None = None) -> list[dict]:
    with _database().connect() as conn:
        if after:
            return conn.fetchall(
                "SELECT * FROM tasks WHERE created_at < ? ORDER BY created_at DESC LIMIT ?",
                (after, limit),
            )
        return conn.fetchall(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )


@_with_retry
def update_task_if_version(task_id: str, expected_version: int, **fields) -> dict | None:
    """Conditional update: only succeeds if version matches. Returns updated row or None."""
    if not fields:
        return get_task(task_id)

    set_parts = [f"{k} = ?" for k in fields]
    set_parts.append("version = version + 1")
    set_parts.append("updated_at = ?")

    values = list(fields.values()) + [_now(), task_id, expected_version]

    with _database().transaction() as conn:
        cursor = conn.execute(
            f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = ? AND version = ?",
            values,
        )
        if cursor.rowcount == 0:
            return None  # None = conflict or missing; caller checks get_task
    return get_task(task_id)


@_with_retry
def update_chat_history_if_version(
    task_id: str, expected_chat_version: int, chat_history_json: str, chat_updated_at: str
) -> bool:
    """Conditional chat history update. Returns True on success, False on conflict."""
    with _database().transaction() as conn:
        cursor = conn.execute(
            """UPDATE tasks
               SET chat_history_json = ?, chat_updated_at = ?, chat_version = chat_version + 1
               WHERE id = ? AND chat_version = ?""",
            (chat_history_json, chat_updated_at, task_id, expected_chat_version),
        )
        return cursor.rowcount > 0


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

    with _database().transaction() as conn:
        cursor = conn.execute(
            f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = ? AND transcript_version = ?",
            values,
        )
        return cursor.rowcount > 0


_SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "api-key",
    "llm_api_key",
    "asr_api_key",
    "_runtime_api_key",
    "authorization",
    "auth_header",
    "access_token",
}

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"ACCESS_TOKEN\s*[=:]\s*[^\s,}\]]+", re.IGNORECASE),
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
            key_lower = key_text.lower()
            if (
                key_lower in _SENSITIVE_FIELD_NAMES
                or key_lower.endswith("_api_key")
                or "token" in key_lower
            ):
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
    try:
        with _database().transaction() as conn:
            cursor = conn.execute(
                """UPDATE tool_runs
                   SET status = ?, output_json = ?, error_message = ?,
                       finished_at = ?, duration_ms = ?, state_after = ?
                   WHERE id = ?""",
                (
                    status,
                    output_json,
                    error_text,
                    finished_at,
                    duration_ms,
                    state_after,
                    run_id,
                ),
            )
            if cursor.rowcount == 0:
                raise RuntimeError(f"tool_run not found: {run_id}")
    except Exception:
        logging.exception("tool_run_finish_failed run_id=%s status=%s", run_id, status)
        raise


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
    try:
        with _database().transaction() as conn:
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
            return run_id
    except Exception:
        logging.exception("tool_run_create_failed task_id=%s tool=%s", task_id, tool_name)
        raise


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
    with _database().connect() as conn:
        return conn.fetchall(
            "SELECT * FROM tool_runs WHERE task_id = ? ORDER BY started_at ASC, id ASC",
            (task_id,),
        )


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
