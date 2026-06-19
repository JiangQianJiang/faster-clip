import asyncio
import json
from pathlib import Path

import pytest

import app.models.task as task_model


def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(task_model, "DB_PATH", db_path)
    monkeypatch.setattr(
        task_model, "_MIGRATION_LOCK_FILE", db_path.parent / ".migration.lock"
    )
    task_model.init_db()
    return db_path


def _make_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    _use_temp_db(tmp_path, monkeypatch)
    task_id = task_model.create_task(
        str(tmp_path / "video.mp4"),
        "video.mp4",
        {"llm_base_url": "https://api.anthropic.com", "llm_model": "claude"},
    )
    task_model.update_task_status(task_id, "done", subtitle_segment_count=1)
    return task_id


def test_tool_runs_lifecycle_redacts_sensitive_values(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)

    from app.models.task import (
        create_tool_run,
        finish_tool_run_error,
        finish_tool_run_rejected,
        finish_tool_run_success,
        list_tool_runs,
    )

    run_id = create_tool_run(
        task_id=task_id,
        tool_name="fake_tool",
        input_data={
            "safe": "value",
            "api_key": "dashscope-secret-value",
            "provider_api_key": "provider-secret-value",
            "_runtime_api_key": "sk-ant-test-secret",
            "Authorization": "Bearer token sk-test-secret",
            "env": "ACCESS_TOKEN = supersecret123",
            "nested": {"asr_api_key": "sk-nested-secret", "custom_token": "nested-token-value"},
        },
        state_before="transcript_ready",
    )
    finish_tool_run_success(
        run_id,
        output_data={"ok": True, "echo": "sk-ant-output-secret"},
        state_after="clips_ready",
        duration_ms=12,
    )

    success_run = list_tool_runs(task_id)[0]
    assert success_run["status"] == "success"
    assert success_run["duration_ms"] == 12
    serialized = json.dumps(success_run, ensure_ascii=False)
    assert "sk-ant-test-secret" not in serialized
    assert "sk-test-secret" not in serialized
    assert "sk-nested-secret" not in serialized
    assert "dashscope-secret-value" not in serialized
    assert "provider-secret-value" not in serialized
    assert "nested-token-value" not in serialized
    assert "sk-ant-output-secret" not in serialized
    assert "supersecret123" not in serialized
    assert "api_key" not in success_run["input_json"]
    assert "provider_api_key" not in success_run["input_json"]
    assert "_runtime_api_key" not in success_run["input_json"]
    assert "Authorization" not in success_run["input_json"]

    error_id = create_tool_run(
        task_id=task_id,
        tool_name="fake_tool",
        input_data={"x": 1},
        state_before="transcript_ready",
    )
    finish_tool_run_error(error_id, error_message="boom sk-ant-error-secret", duration_ms=3)

    rejected_id = create_tool_run(
        task_id=task_id,
        tool_name="fake_tool",
        input_data={"x": 2},
        state_before="uploaded",
    )
    finish_tool_run_rejected(rejected_id, reason="当前任务还没有 transcript_ready", duration_ms=1)

    statuses = [run["status"] for run in list_tool_runs(task_id)]
    assert statuses == ["success", "error", "rejected"]


class _FakeSuccessTool:
    name = "fake_success_tool"
    description = "fake"
    user_facing = True
    parameters = {"type": "object", "properties": {}}
    requires_state = []
    produces_state = None
    destructive = False
    requires_checkpoint = False
    fatal_on_failure = False
    timeout_seconds = 120

    def __init__(self):
        self.calls = []

    async def execute(self, task_id: str, value: str = "", _runtime_api_key: str = ""):
        self.calls.append(
            {"task_id": task_id, "value": value, "runtime_key": _runtime_api_key}
        )
        from app.tools.base import ToolResult

        return ToolResult(
            success=True,
            data={"value": value, "secret": _runtime_api_key},
            user_message="ok",
        )


class _FakeFailTool(_FakeSuccessTool):
    name = "fake_fail_tool"

    async def execute(self, task_id: str):
        raise RuntimeError("boom")


class _FakeTransientTool(_FakeSuccessTool):
    name = "fake_transient_tool"

    def __init__(self):
        super().__init__()
        self.count = 0

    async def execute(self, task_id: str):
        self.count += 1
        from app.tools.base import ToolResult

        if self.count == 1:
            return ToolResult(success=False, error="connection timeout", user_message="retry")
        return ToolResult(success=True, data={"attempt": self.count}, user_message="ok")


def _register_temp_tool(monkeypatch: pytest.MonkeyPatch, tool):
    import app.tools as tools_mod

    registry = dict(tools_mod._registry)
    registry[tool.name] = tool
    monkeypatch.setattr(tools_mod, "_registry", registry)
    return tool


def test_tool_executor_success_records_tool_run_and_filters_inputs(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)
    tool = _register_temp_tool(monkeypatch, _FakeSuccessTool())

    from app.services.tool_executor import ToolExecutor
    from app.models.task import list_tool_runs

    result = asyncio.run(
        ToolExecutor().execute_tool(
            task_id=task_id,
            tool_name=tool.name,
            tool_input={"value": "hello", "ignored": "drop"},
            runtime_api_key="sk-ant-test-secret",
            state_before="transcript_ready",
        )
    )

    assert result.success is True
    assert tool.calls == [
        {"task_id": task_id, "value": "hello", "runtime_key": "sk-ant-test-secret"}
    ]
    runs = list_tool_runs(task_id)
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["duration_ms"] is not None
    assert "hello" in runs[0]["input_json"]
    assert "drop" in runs[0]["input_json"]
    assert "sk-ant-test-secret" not in runs[0]["input_json"]
    assert "sk-ant-test-secret" not in (runs[0]["output_json"] or "")


def test_tool_executor_failure_unknown_and_transient_retry(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)
    failing_tool = _register_temp_tool(monkeypatch, _FakeFailTool())
    transient_tool = _register_temp_tool(monkeypatch, _FakeTransientTool())

    from app.models.task import list_tool_runs
    from app.services.tool_executor import ToolExecutor

    executor = ToolExecutor(retry_sleep_seconds=0)
    failed = asyncio.run(
        executor.execute_tool(task_id=task_id, tool_name=failing_tool.name, tool_input={})
    )
    unknown = asyncio.run(
        executor.execute_tool(task_id=task_id, tool_name="missing_tool", tool_input={})
    )
    retried = asyncio.run(
        executor.execute_tool(task_id=task_id, tool_name=transient_tool.name, tool_input={})
    )

    assert failed.success is False
    assert failed.error == "boom"
    assert unknown.success is False
    assert "Unknown tool" in unknown.error
    assert retried.success is True
    assert transient_tool.count == 2

    runs = list_tool_runs(task_id)
    assert [run["status"] for run in runs] == ["error", "error", "success"]
    assert "boom" in (runs[0]["error_message"] or "")
    assert "Unknown tool" in (runs[1]["error_message"] or "")


def test_workflow_runtime_rejects_invalid_state_and_records_rejected_run(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    task_id = task_model.create_task(str(tmp_path / "video.mp4"), "video.mp4", {})
    task = task_model.get_task(task_id)

    from app.models.task import list_tool_runs
    from app.services.tool_executor import ToolExecutor
    from app.services.workflow_runtime import WorkflowRuntime
    from app.tools import get_tool

    tool = get_tool("analyze_highlights")
    allowed, reason = WorkflowRuntime().validate_tool_call(task, tool)

    assert allowed is False
    assert "transcript_ready" in reason
    assert "analyze_highlights" in reason

    result = ToolExecutor().record_rejected_tool_call(
        task_id=task_id,
        tool_name="analyze_highlights",
        tool_input={"task_id": task_id},
        reason=reason,
        state_before=WorkflowRuntime.get_task_state(task),
    )
    assert result.success is False
    assert result.error == reason
    runs = list_tool_runs(task_id)
    assert len(runs) == 1
    assert runs[0]["status"] == "rejected"
    assert reason in runs[0]["error_message"]


def test_workflow_runtime_advances_state_after_success(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)
    task_model.update_task_status(task_id, "processing", stage="transcribing")

    from app.models.task import get_task
    from app.services.workflow_runtime import WorkflowRuntime
    from app.tools import get_tool
    from app.tools.base import ToolResult

    runtime = WorkflowRuntime()
    task = get_task(task_id)
    assert runtime.get_task_state(task) == "transcript_ready"

    new_state = runtime.apply_tool_success(
        task_id,
        get_tool("analyze_highlights"),
        ToolResult(success=True, data={"clips": []}, user_message="ok"),
    )

    assert new_state == "clips_ready"
    updated = get_task(task_id)
    assert updated["stage"] == "clips_ready"


def test_workflow_runtime_done_with_transcript_is_not_exported(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)

    from app.models.task import get_task
    from app.services.workflow_runtime import WorkflowRuntime
    from app.tools import get_tool

    runtime = WorkflowRuntime()
    task = get_task(task_id)

    assert runtime.get_task_state(task) == "transcript_ready"
    allowed, reason = runtime.validate_tool_call(task, get_tool("get_export_progress"))
    assert allowed is False
    assert "get_export_progress" in reason


def test_workflow_runtime_done_with_unexported_clips_is_clips_ready(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)
    task_model.update_task_status(
        task_id,
        "done",
        clips_json=json.dumps([{"start": 0, "end": 5, "title": "clip"}]),
        subtitle_segment_count=1,
    )

    from app.models.task import get_task
    from app.services.workflow_runtime import WorkflowRuntime

    assert WorkflowRuntime.get_task_state(get_task(task_id)) == "clips_ready"


def test_workflow_runtime_exported_requires_export_signal(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)
    task_model.update_task_status(
        task_id,
        "done",
        clips_json=json.dumps([{"status": "success", "filepath": "/tmp/export.mp4"}]),
        subtitle_segment_count=1,
    )

    from app.models.task import get_task
    from app.services.workflow_runtime import WorkflowRuntime

    assert WorkflowRuntime.get_task_state(get_task(task_id)) == "exported"


def test_workflow_runtime_preserves_async_export_processing_state(tmp_path, monkeypatch):
    task_id = _make_task(tmp_path, monkeypatch)
    task_model.update_task_status(task_id, "processing", stage="ai_exporting")

    from app.models.task import get_task
    from app.services.workflow_runtime import WorkflowRuntime
    from app.tools import get_tool
    from app.tools.base import ToolResult

    new_state = WorkflowRuntime().apply_tool_success(
        task_id,
        get_tool("export_clips"),
        ToolResult(
            success=True,
            data={"enqueued": True, "clip_count": 1},
            user_message="queued",
        ),
    )

    assert new_state == "exporting"
    updated = get_task(task_id)
    assert updated["status"] == "processing"
    assert updated["stage"] == "ai_exporting"


def test_chat_service_executes_tool_via_executor_and_persists_redacted_history(
    tmp_path, monkeypatch
):
    task_id = _make_task(tmp_path, monkeypatch)

    from unittest.mock import MagicMock, patch

    from app.services.chat_service import ChatService
    from app.tools import get_tool
    from app.tools.base import ToolResult
    from tests.test_chat_service import (
        _MockTextBlock,
        _MockToolUseBlock,
        _make_stream_from_response,
    )

    tool = get_tool("get_transcript")
    calls = []

    async def fake_execute(task_id: str, offset: int = 0, limit: int = 0, **_kwargs):
        calls.append({"task_id": task_id, "offset": offset, "limit": limit})
        return ToolResult(
            success=True,
            data={"segments": [], "secret": "sk-ant-test-secret"},
            user_message="字幕为空",
        )

    svc = ChatService(
        task_id=task_id,
        llm_config={"llm_base_url": "https://api.anthropic.com", "llm_model": "claude"},
        api_key="sk-ant-test-secret",
        checkpoint_mode="auto",
    )

    mock_tool_response = MagicMock()
    mock_tool_response.stop_reason = "tool_use"
    mock_tool_response.content = [_MockToolUseBlock("get_transcript", {"limit": 1})]
    mock_tool_response.usage = MagicMock(input_tokens=1, output_tokens=1)

    mock_end_response = MagicMock()
    mock_end_response.stop_reason = "end_turn"
    mock_end_response.content = [_MockTextBlock("done")]
    mock_end_response.usage = MagicMock(input_tokens=1, output_tokens=1)

    svc.async_client.messages.stream = MagicMock(
        side_effect=[
            _make_stream_from_response(mock_tool_response),
            _make_stream_from_response(mock_end_response),
        ]
    )

    with patch.object(tool, "execute", side_effect=fake_execute):
        events = []
        async def _collect():
            async for event in svc.chat("show transcript"):
                events.append(event)
        asyncio.run(_collect())

    from app.models.task import get_task, list_tool_runs

    assert calls == [{"task_id": task_id, "offset": 0, "limit": 1}]
    events_text = "".join(events)
    assert '"type": "tool_start"' in events_text
    assert '"type": "tool_result"' in events_text
    assert '"type": "text"' in events_text

    runs = list_tool_runs(task_id)
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert "sk-ant-test-secret" not in json.dumps(runs, ensure_ascii=False)

    history = get_task(task_id)["chat_history_json"] or ""
    assert history
    assert "sk-ant-test-secret" not in history
