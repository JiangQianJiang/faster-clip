"""Database persistence adapter tests.

Default test runs use SQLite for speed. MySQL coverage is enabled locally by
setting MYSQL_TEST_DATABASE_URL, for example:
mysql+pymysql://fasterclip:password@127.0.0.1:3306/fasterclip_test
"""

import os
from pathlib import Path

import pytest

import app.config as app_config
import app.models.task as task_model


def _configure_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "adapter-test.db"
    settings = app_config.settings
    monkeypatch.setattr(settings, "database_engine", "sqlite", raising=False)
    monkeypatch.setattr(settings, "database_path", str(db_path), raising=False)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}", raising=False)
    monkeypatch.setattr(task_model, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(
        task_model,
        "_MIGRATION_LOCK_FILE",
        db_path.parent / ".migration.lock",
        raising=False,
    )


def _configure_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ["MYSQL_TEST_DATABASE_URL"]
    settings = app_config.settings
    monkeypatch.setattr(settings, "database_engine", "mysql", raising=False)
    monkeypatch.setattr(settings, "database_url", database_url, raising=False)


def _exercise_core_task_paths() -> str:
    task_model.init_db()
    task_model.init_db()

    first_id = task_model.create_task(
        "data/videos/first/original.mp4",
        "first.mp4",
        {"llm_model": "claude", "llm_api_key": "sk-should-not-persist"},
    )
    second_id = task_model.create_task(
        "data/videos/second/original.mp4",
        "second.mp4",
        {"llm_model": "claude"},
    )

    first = task_model.get_task(first_id)
    assert first is not None
    assert first["id"] == first_id
    assert first["status"] == "pending"
    assert "sk-should-not-persist" not in first["config_json"]

    tasks = task_model.list_tasks(limit=10)
    assert {row["id"] for row in tasks} >= {first_id, second_id}

    assert task_model.update_chat_history_if_version(
        first_id,
        0,
        '[{"role":"user","content":"hi"}]',
        "2026-06-19T00:00:00+00:00",
    )
    assert not task_model.update_chat_history_if_version(
        first_id,
        0,
        "[]",
        "2026-06-19T00:01:00+00:00",
    )
    assert task_model.get_task(first_id)["chat_version"] == 1

    assert task_model.bump_transcript_version_if_current(
        first_id,
        0,
        "2026-06-19T00:02:00+00:00",
        transcript_source="manual",
        subtitle_segment_count=3,
    )
    assert not task_model.bump_transcript_version_if_current(
        first_id,
        0,
        "2026-06-19T00:03:00+00:00",
        transcript_source="manual",
    )
    updated = task_model.get_task(first_id)
    assert updated["transcript_version"] == 1
    assert updated["subtitle_segment_count"] == 3

    return first_id


def _exercise_tool_run_paths(task_id: str) -> None:
    success_id = task_model.create_tool_run(
        task_id=task_id,
        tool_name="probe_video",
        input_data={"path": "video.mp4"},
        state_before="uploaded",
    )
    task_model.finish_tool_run_success(
        success_id,
        output_data={"ok": True},
        state_after="metadata_ready",
        duration_ms=11,
    )

    error_id = task_model.create_tool_run(
        task_id=task_id,
        tool_name="run_asr",
        input_data={"provider": "qwen"},
        state_before="metadata_ready",
    )
    task_model.finish_tool_run_error(
        error_id,
        error_message="boom",
        state_after="metadata_ready",
        duration_ms=7,
    )

    rejected_id = task_model.create_tool_run(
        task_id=task_id,
        tool_name="export_clips",
        input_data={"clip": 1},
        state_before="uploaded",
    )
    task_model.finish_tool_run_rejected(
        rejected_id,
        reason="missing transcript",
        state_after="uploaded",
        duration_ms=3,
    )

    runs = task_model.list_tool_runs(task_id)
    assert [row["id"] for row in runs] == [success_id, error_id, rejected_id]
    assert [row["status"] for row in runs] == ["success", "error", "rejected"]
    assert runs[0]["duration_ms"] == 11
    assert runs[1]["error_message"] == "boom"
    assert runs[2]["error_message"] == "missing transcript"


def test_sqlite_adapter_core_task_and_tool_paths(tmp_path, monkeypatch):
    _configure_sqlite(tmp_path, monkeypatch)
    task_id = _exercise_core_task_paths()
    _exercise_tool_run_paths(task_id)


@pytest.mark.mysql
@pytest.mark.skipif(
    not os.environ.get("MYSQL_TEST_DATABASE_URL"),
    reason="MYSQL_TEST_DATABASE_URL is not set",
)
def test_mysql_adapter_core_task_and_tool_paths(monkeypatch):
    _configure_mysql(monkeypatch)
    task_id = _exercise_core_task_paths()
    _exercise_tool_run_paths(task_id)
