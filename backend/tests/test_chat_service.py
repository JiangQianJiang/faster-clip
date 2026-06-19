"""Integration tests for ChatService (task4/5/8 — AC-2, AC-5)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat_service import (
    ChatService,
    _redact_keys,
    _redact_message,
    _redact_value,
)

# Conditionally init DB — only for tests that need real DB access
# Tests that mock _build_context skip DB entirely


# Helper to make mocked Anthropic content blocks
class _MockTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _MockToolUseBlock:
    type = "tool_use"

    def __init__(self, name, input_data, block_id="toolu_001"):
        self.name = name
        self.input = input_data
        self.id = block_id


class _MockStream:
    """Mock async stream for AsyncAnthropic.messages.stream().

    Acts as both async context manager and async iterator, yielding
    text_delta events then providing get_final_message().
    """

    def __init__(self, final_message, text_events=None):
        self._final_message = final_message
        self._events = text_events or []
        self._index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def get_final_message(self):
        return self._final_message


def _make_stream_from_response(mock_response):
    """Build a _MockStream that yields text_delta events for text blocks."""
    text_events = []
    for block in mock_response.content:
        if hasattr(block, "text") and block.text:
            event = MagicMock()
            event.type = "content_block_delta"
            event.delta = MagicMock()
            event.delta.type = "text_delta"
            event.delta.text = block.text
            text_events.append(event)
    return _MockStream(mock_response, text_events)


# ─── task7: API key redaction ───


def test_redact_value_preserves_dict_types():
    """Recursive _redact_value keeps dict/list types, redacts strings."""
    input_data = {
        "task_id": "abc",
        "llm_api_key": "sk-ant-secret-123",
        "nested": {"key": "sk-ant-nested-456"},
        "list": [{"x": "sk-ant-in-list"}],
        "count": 5,
    }
    result = _redact_value(input_data)
    assert isinstance(result, dict)
    assert isinstance(result["nested"], dict)
    assert isinstance(result["list"], list)
    assert isinstance(result["list"][0], dict)
    assert "llm_api_key" not in result
    assert result["nested"]["key"] == "[REDACTED]"
    assert result["list"][0]["x"] == "[REDACTED]"
    assert result["count"] == 5
    assert result["task_id"] == "abc"


def test_redact_sk_ant_key():
    text = "Authorization: Bearer sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456"
    result = _redact_keys(text)
    assert "sk-ant-api03" not in result
    assert "[REDACTED]" in result


def test_redact_sk_key():
    text = "key=sk-proj-1234567890abcdef"
    result = _redact_keys(text)
    assert "sk-proj" not in result
    assert "[REDACTED]" in result


def test_redact_access_token_assignment():
    text = "ACCESS_TOKEN = supersecret123"
    result = _redact_keys(text)
    assert "supersecret123" not in result
    assert "[REDACTED]" in result


def test_redact_message_deep():
    msg = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "abc",
                "content": '{"llm_api_key": "sk-ant-secret123"}',
            }
        ],
    }
    result = _redact_message(msg)
    serialized = json.dumps(result)
    assert "sk-ant-secret123" not in serialized
    assert "[REDACTED]" in serialized


# ─── task4: ChatService initialization ───


def test_chat_service_init():
    svc = ChatService(
        task_id="test-123",
        llm_config={
            "llm_base_url": "https://api.anthropic.com",
            "llm_model": "test-model",
        },
        api_key="sk-ant-test-key",
    )
    assert svc.task_id == "test-123"
    assert svc.model == "test-model"
    assert svc.history == []


# ─── task4: Context building ───


def test_build_context_with_task():
    """_build_context includes task state info."""
    from app.models.task import init_db as _init_db

    _init_db()

    svc = ChatService(
        task_id="nonexistent-task-id",
        llm_config={"llm_base_url": "https://api.anthropic.com", "llm_model": "claude"},
        api_key="sk-ant-test",
    )
    ctx = svc._build_context()
    assert "video clipping assistant" in ctx
    # With nonexistent task, should still produce valid context
    assert isinstance(ctx, str)


# ─── task4: Error handling in chat ───


def test_chat_with_network_error():
    """Chat should yield error SSE on Anthropic API failure."""
    import asyncio

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://nonexistent.example.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )
        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_build_context", return_value="test"),
        ):
            events = []
            async for event in svc.chat("hello"):
                events.append(event)
            assert len(events) > 0

    asyncio.run(_run())


# ─── task4: Checkpoint detection ───


def test_checkpoint_tools_set():
    """Verify CHECKPOINT_TOOLS contains the right tools."""
    from app.services.chat_service import CHECKPOINT_TOOLS

    assert "analyze_highlights" in CHECKPOINT_TOOLS
    assert "export_clips" in CHECKPOINT_TOOLS
    assert "extract_embedded_subtitles" in CHECKPOINT_TOOLS
    assert "run_asr" in CHECKPOINT_TOOLS
    assert "kernel_run_asr" in CHECKPOINT_TOOLS


def test_fatal_tools_independent_of_checkpoint():
    """FATAL_TOOLS is a separate set from CHECKPOINT_TOOLS."""
    from app.services.chat_service import CHECKPOINT_TOOLS, FATAL_TOOLS

    assert "analyze_highlights" in FATAL_TOOLS
    assert "export_clips" in FATAL_TOOLS
    assert "extract_embedded_subtitles" in FATAL_TOOLS
    assert "kernel_run_asr" in FATAL_TOOLS
    # User-facing run_asr is NOT fatal (user-initiated re-run).
    assert "run_asr" not in FATAL_TOOLS
    # Non-fatal checkpoint tools are NOT in FATAL_TOOLS
    assert "add_clip" not in FATAL_TOOLS
    assert "refine_clips" not in FATAL_TOOLS
    assert "delete_clip" not in FATAL_TOOLS
    # FATAL_TOOLS is a proper subset of CHECKPOINT_TOOLS but independently defined
    assert FATAL_TOOLS.issubset(CHECKPOINT_TOOLS)


def test_auto_mode_no_checkpoint():
    """In 'auto' mode, successful analyze_highlights does NOT emit checkpoint."""

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
            checkpoint_mode="auto",
        )

        from app.tools.base import ToolResult

        async def mock_execute(tool_name, tool_input):
            return ToolResult(success=True, data={}, user_message=f"完成: {tool_name}")

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(
                svc, "_build_context", return_value="You are a test assistant."
            ),
            patch.object(svc, "_execute_tool_with_retry", side_effect=mock_execute),
        ):
            mock_tool_response = MagicMock()
            mock_tool_response.stop_reason = "tool_use"
            mock_tool_response.content = [
                _MockToolUseBlock("analyze_highlights", {"task_id": "test-id"}),
            ]

            mock_end_response = MagicMock()
            mock_end_response.stop_reason = "end_turn"
            mock_end_response.content = [_MockTextBlock("Analysis done.")]

            svc.async_client.messages.stream = MagicMock(
                side_effect=[
                    _make_stream_from_response(mock_tool_response),
                    _make_stream_from_response(mock_end_response),
                ]
            )

            events = []
            async for event in svc.chat("analyze"):
                events.append(event)

            events_text = "".join(events)
            assert '"type": "checkpoint"' not in events_text
            assert "tool_result" in events_text  # tool still executed

    asyncio.run(_run())


def test_invalid_checkpoint_mode_raises():
    """Invalid checkpoint_mode raises ValueError."""
    with pytest.raises(ValueError, match="Invalid checkpoint_mode"):
        ChatService(
            task_id="x",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
            checkpoint_mode="invalid",
        )


# ─── task4: SSE event formatting ───


def test_sse_event_format():
    svc = ChatService(
        task_id="x",
        llm_config={"llm_base_url": "https://api.anthropic.com", "llm_model": "claude"},
        api_key="sk-ant-test",
    )
    event = svc._sse_event("thinking", "hello world")
    assert event.startswith("data: ")
    assert "\n\n" in event

    parsed = json.loads(event[len("data: ") :].strip())
    assert parsed["type"] == "thinking"
    assert parsed["data"] == "hello world"


# ─── task4: block_to_dict ───


def test_block_to_dict():
    svc = ChatService(
        task_id="x",
        llm_config={"llm_base_url": "https://api.anthropic.com", "llm_model": "claude"},
        api_key="sk-ant-test",
    )

    class MockTextBlock:
        type = "text"
        text = "hello"

    result = svc._block_to_dict(MockTextBlock())
    assert result["text"] == "hello"
    assert "name" not in result  # text blocks don't have tool names


# ─── task8: Deep tool-loop tests with mocked Anthropic ───


def test_tool_use_triggers_checkpoint_and_stops():
    """When LLM returns analyze_highlights tool_use in 'confirm' mode, the loop emits
    thinking → text → tool_start → tool_result → checkpoint and stops."""

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
            checkpoint_mode="confirm",
        )

        from app.tools.base import ToolResult

        async def mock_execute(tool_name, tool_input):
            return ToolResult(success=True, data={}, user_message=f"完成: {tool_name}")

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(
                svc, "_build_context", return_value="You are a test assistant."
            ),
            patch.object(svc, "_execute_tool_with_retry", side_effect=mock_execute),
        ):
            # Mock Anthropic: first call returns tool_use for analyze_highlights
            mock_tool_response = MagicMock()
            mock_tool_response.stop_reason = "tool_use"
            mock_tool_response.content = [
                _MockTextBlock("Let me analyze the transcript."),
                _MockToolUseBlock("analyze_highlights", {"task_id": "test-id"}),
            ]

            mock_end_response = MagicMock()
            mock_end_response.stop_reason = "end_turn"
            mock_end_response.content = [_MockTextBlock("Analysis complete.")]

            svc.async_client.messages.stream = MagicMock(
                side_effect=[
                    _make_stream_from_response(mock_tool_response),
                    _make_stream_from_response(mock_end_response),
                ]
            )

            events = []
            async for event in svc.chat("analyze my video"):
                events.append(event)

            # Check event types
            event_types = []
            for e in events:
                if e.startswith("data: "):
                    parsed = json.loads(e[len("data: ") :].strip())
                    event_types.append(parsed["type"])

            assert "thinking" in event_types
            assert "tool_start" in event_types
            assert "tool_result" in event_types
            assert "checkpoint" in event_types

    asyncio.run(_run())


def test_invalid_tool_call_returns_error():
    """When LLM requests a non-existent tool, chat emits error SSE and returns."""

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(
                svc, "_build_context", return_value="You are a test assistant."
            ),
        ):
            mock_response = MagicMock()
            mock_response.stop_reason = "tool_use"
            mock_response.content = [
                _MockToolUseBlock("nonexistent_tool", {}),
            ]

            svc.async_client.messages.stream = MagicMock(
                return_value=_make_stream_from_response(mock_response)
            )

            events = []
            async for event in svc.chat("do something impossible"):
                events.append(event)

            events_text = "".join(events)
            # Must contain error event (terminal), not just tool_result
            assert '"type": "error"' in events_text
            # Should also have tool_start before the error
            assert "tool_start" in events_text
            # Must not contain checkpoint (should terminate before)
            assert '"type": "checkpoint"' not in events_text

    asyncio.run(_run())


def test_non_checkpoint_tool_continues_loop():
    """Non-checkpoint tool like get_transcript does not stop the loop."""

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        from app.tools.base import ToolResult

        async def mock_execute(tool_name, tool_input):
            return ToolResult(success=True, data={}, user_message=f"OK: {tool_name}")

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(
                svc, "_build_context", return_value="You are a test assistant."
            ),
            patch.object(svc, "_execute_tool_with_retry", side_effect=mock_execute),
        ):
            # First: get_transcript tool_use (non-checkpoint)
            mock1 = MagicMock()
            mock1.stop_reason = "tool_use"
            mock1.content = [
                _MockToolUseBlock("get_transcript", {"task_id": "test-id"})
            ]

            # Second: end_turn (loop continues because no checkpoint)
            mock2 = MagicMock()
            mock2.stop_reason = "end_turn"
            mock2.content = [_MockTextBlock("Here is your transcript.")]

            svc.async_client.messages.stream = MagicMock(
                side_effect=[
                    _make_stream_from_response(mock1),
                    _make_stream_from_response(mock2),
                ]
            )

            events = []
            async for event in svc.chat("show transcript"):
                events.append(event)

            events_text = "".join(events)
            assert '"type": "checkpoint"' not in events_text

    asyncio.run(_run())


# ─── task5/task7: Endpoint-level key path tests ───


def test_chat_endpoint_missing_key_returns_400():
    """POST without llm_api_key on a task without encrypted config key returns 400."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.task import create_task, init_db, update_task_status

    init_db()
    task_id = create_task(
        "/tmp/test.mp4",
        "test.mp4",
        {
            "llm_base_url": "https://api.anthropic.com",
            "llm_model": "claude",
        },
    )
    update_task_status(task_id, "done")

    client = TestClient(app)
    resp = client.post(f"/api/tasks/{task_id}/chat", json={"message": "hello"})
    assert resp.status_code == 400
    assert "API Key" in resp.json()["detail"]


def test_chat_endpoint_with_request_key_starts_chat():
    """POST with llm_api_key starts ChatService and sends key to Anthropic."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.task import create_task, init_db, update_task_status

    init_db()
    task_id = create_task(
        "/tmp/test.mp4",
        "test.mp4",
        {
            "llm_base_url": "https://api.anthropic.com",
            "llm_model": "claude",
        },
    )
    update_task_status(task_id, "done")

    # Capture AsyncAnthropic constructor call
    captured_api_key = None

    def _make_endpoint_stream(text):
        """Build a mock stream with the given text response."""
        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.content = [_MockTextBlock(text)]
        resp.usage = MagicMock()
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 5
        return _make_stream_from_response(resp)

    with (
        patch("app.services.chat_service.Anthropic"),
        patch("app.services.chat_service.AsyncAnthropic") as mock_async,
    ):
        mock_async.return_value.messages.stream = MagicMock(
            return_value=_make_endpoint_stream("Hello from test")
        )

        client = TestClient(app)
        resp = client.post(
            f"/api/tasks/{task_id}/chat",
            json={"message": "hello", "llm_api_key": "sk-ant-test-key-verify"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # Consume stream via resp.text (TestClient buffers it)
        body = resp.text
        assert "Hello from test" in body

        # Verify AsyncAnthropic received the key
        mock_async.assert_called_once()
        call_kwargs = mock_async.call_args[1]
        assert call_kwargs["api_key"] == "sk-ant-test-key-verify"


def test_chat_endpoint_history_redacted_after_request_key():
    """After successful chat with request key, persisted history is non-empty and redacted."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.task import create_task, get_task, init_db, update_task_status

    init_db()
    task_id = create_task(
        "/tmp/test.mp4",
        "test.mp4",
        {
            "llm_base_url": "https://api.anthropic.com",
            "llm_model": "claude",
        },
    )
    update_task_status(task_id, "done")

    def _make_endpoint_stream2(text):
        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.content = [_MockTextBlock(text)]
        resp.usage = MagicMock()
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 5
        return _make_stream_from_response(resp)

    with (
        patch("app.services.chat_service.Anthropic"),
        patch("app.services.chat_service.AsyncAnthropic") as mock_async,
    ):
        mock_async.return_value.messages.stream = MagicMock(
            return_value=_make_endpoint_stream2("Chat response")
        )

        client = TestClient(app)
        resp = client.post(
            f"/api/tasks/{task_id}/chat",
            json={"message": "hello", "llm_api_key": "sk-ant-redact-test-12345"},
        )
        # Consume stream to trigger _save_history
        _body = resp.text

    task = get_task(task_id)
    history = task.get("chat_history_json") or ""
    assert history, "chat_history_json should not be empty after successful chat"
    assert "sk-ant-redact-test-12345" not in history
    assert "sk-ant" not in history


def test_transient_error_auto_retry_once():
    """Transient error (connection timeout) triggers one auto-retry, succeeds on 2nd attempt."""

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        call_count = 0

        async def flaky_execute(**kwargs):
            nonlocal call_count
            call_count += 1
            from app.tools.base import ToolResult

            if call_count == 1:
                return ToolResult(
                    success=False, error="connection timeout", user_message="first fail"
                )
            return ToolResult(success=True, data={}, user_message="second success")

        from app.tools import get_tool

        tool = get_tool("get_transcript")
        assert tool is not None

        with (
            patch.object(tool, "execute", side_effect=flaky_execute),
            patch("app.services.chat_service.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await svc._execute_tool_with_retry(
                "get_transcript", {"task_id": "x"}
            )

        assert result.success is True
        assert result.user_message == "second success"
        assert call_count == 2  # initial + 1 auto-retry

    asyncio.run(_run())


def test_non_transient_error_no_retry():
    """Non-transient errors (parameter error, etc.) return immediately — no auto-retry."""

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        call_count = 0

        async def fail_with_param_error(**kwargs):
            nonlocal call_count
            call_count += 1
            from app.tools.base import ToolResult

            return ToolResult(
                success=False,
                error="invalid segment index: 99 out of range",
                user_message="片段索引无效: 99",
            )

        from app.tools import get_tool

        tool = get_tool("get_transcript")
        assert tool is not None

        with (
            patch.object(tool, "execute", side_effect=fail_with_param_error),
            patch("app.services.chat_service.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await svc._execute_tool_with_retry(
                "get_transcript", {"task_id": "x"}
            )

        assert result.success is False
        assert "invalid segment index" in result.error
        assert call_count == 1  # no retry — param errors are not transient

    asyncio.run(_run())


def test_transient_error_retry_fails():
    """Transient error on both attempts — returns failure after 1 retry (2 calls total)."""

    async def _run():
        svc = ChatService(
            task_id="test-id",
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        call_count = 0

        async def always_timeout(**kwargs):
            nonlocal call_count
            call_count += 1
            from app.tools.base import ToolResult

            return ToolResult(
                success=False,
                error=f"connection timed out (attempt {call_count})",
                user_message=f"连接超时 {call_count}",
            )

        from app.tools import get_tool

        tool = get_tool("get_transcript")
        assert tool is not None

        with (
            patch.object(tool, "execute", side_effect=always_timeout),
            patch("app.services.chat_service.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await svc._execute_tool_with_retry(
                "get_transcript", {"task_id": "x"}
            )

        assert result.success is False
        assert "timed out" in result.error
        assert call_count == 2  # initial + 1 auto-retry, then give up

    asyncio.run(_run())


def test_save_history_preserves_status():
    """_save_history does not change task status from 'error' to 'done'."""

    def _run():
        # Ensure DB is initialized
        from app.models.task import create_task, get_task, init_db, update_task_status

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
        )
        update_task_status(task_id, "error", error_message="test error")

        svc = ChatService(
            task_id=task_id,
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )
        svc.history = [{"role": "user", "content": "hello"}]

        import asyncio

        asyncio.run(svc._save_history())

        task = get_task(task_id)
        assert task is not None
        assert task["status"] == "error"
        assert task["chat_history_json"] is not None

    _run()


# ─── task8: Failed checkpoint tool → error status ───


def test_failed_checkpoint_sets_task_error():
    """Failed analyze_highlights emits no checkpoint, sets task status to error."""

    async def _run():
        from app.models.task import create_task, get_task, init_db, update_task_status

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
        )
        update_task_status(task_id, "done")

        svc = ChatService(
            task_id=task_id,
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        from app.tools.base import ToolResult

        async def mock_fail(tool_name, tool_input):
            if tool_name == "analyze_highlights":
                return ToolResult(
                    success=False, error="LLM error", user_message="分析失败"
                )
            return ToolResult(success=True, data={}, user_message="ok")

        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [
            _MockToolUseBlock("analyze_highlights", {"task_id": task_id})
        ]

        mock_end = MagicMock()
        mock_end.stop_reason = "end_turn"
        mock_end.content = [_MockTextBlock("Sorry, analysis failed. Try again?")]

        svc.async_client.messages.stream = MagicMock(
            side_effect=[
                _make_stream_from_response(mock_response),
                _make_stream_from_response(mock_end),
            ]
        )

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(svc, "_build_context", return_value="test"),
            patch.object(svc, "_execute_tool_with_retry", side_effect=mock_fail),
        ):
            events = []
            async for event in svc.chat("analyze"):
                events.append(event)

        events_text = "".join(events)
        assert '"type": "checkpoint"' not in events_text
        # Task should be in error state
        task = get_task(task_id)
        assert task["status"] == "error"
        assert task["failed_stage"] == "analyze_highlights"

    asyncio.run(_run())


# ─── processing guard: checkpoint failures must not flip status to error ───


def test_processing_guard_analyze_highlights_preserves_status():
    """When task is processing, analyze_highlights guard refusal must not
    set the task to error. AC-4 negative: processing state is preserved."""

    async def _run():
        from app.models.task import create_task, get_task, init_db, update_task_status

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
        )
        update_task_status(task_id, "processing", stage="analyzing")

        svc = ChatService(
            task_id=task_id,
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        from app.tools.base import ToolResult

        async def mock_guard_refusal(tool_name, tool_input):
            if tool_name == "analyze_highlights":
                return ToolResult(
                    success=False,
                    error="Cannot analyze while task is processing",
                    user_message="任务处理中，请等待完成后再试",
                )
            return ToolResult(success=True, data={}, user_message="ok")

        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [
            _MockToolUseBlock("analyze_highlights", {"task_id": task_id})
        ]

        mock_end = MagicMock()
        mock_end.stop_reason = "end_turn"
        mock_end.content = [_MockTextBlock("请等待处理完成后再试。")]

        svc.async_client.messages.stream = MagicMock(
            side_effect=[
                _make_stream_from_response(mock_response),
                _make_stream_from_response(mock_end),
            ]
        )

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(svc, "_build_context", return_value="test"),
            patch.object(
                svc, "_execute_tool_with_retry", side_effect=mock_guard_refusal
            ),
        ):
            events = []
            async for event in svc.chat("analyze"):
                events.append(event)

        # Task must remain processing — NOT flipped to error
        task = get_task(task_id)
        assert task["status"] == "processing"
        assert task.get("failed_stage") is None
        # Checkpoint must not be emitted for guard refusal
        events_text = "".join(events)
        assert '"type": "checkpoint"' not in events_text

    asyncio.run(_run())


def test_processing_guard_export_clips_preserves_status():
    """When task is processing (not ai_exporting), export_clips guard refusal
    must not set the task to error. AC-5 negative: processing state is preserved."""

    async def _run():
        import tempfile

        from app.models.task import create_task, get_task, init_db, update_task_status

        init_db()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            vp = f.name
            f.write(b"data")
        task_id = create_task(
            vp,
            "test.mp4",
            {
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
        )
        update_task_status(
            task_id,
            "processing",
            stage="analyzing",
            clips_json='[{"start_time_s":0,"end_time_s":5,"status":"success"}]',
        )

        svc = ChatService(
            task_id=task_id,
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        from app.tools.base import ToolResult

        async def mock_guard_refusal(tool_name, tool_input):
            if tool_name == "export_clips":
                return ToolResult(
                    success=False,
                    error="Cannot export while task is processing",
                    user_message="任务处理中，请等待完成后再试",
                )
            return ToolResult(success=True, data={}, user_message="ok")

        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [
            _MockToolUseBlock("export_clips", {"task_id": task_id})
        ]

        mock_end = MagicMock()
        mock_end.stop_reason = "end_turn"
        mock_end.content = [_MockTextBlock("请等待处理完成后再试。")]

        svc.async_client.messages.stream = MagicMock(
            side_effect=[
                _make_stream_from_response(mock_response),
                _make_stream_from_response(mock_end),
            ]
        )

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(svc, "_build_context", return_value="test"),
            patch.object(
                svc, "_execute_tool_with_retry", side_effect=mock_guard_refusal
            ),
        ):
            events = []
            async for event in svc.chat("export"):
                events.append(event)

        # Task must remain processing — NOT flipped to error
        task = get_task(task_id)
        assert task["status"] == "processing"
        assert task.get("failed_stage") is None
        # Checkpoint must not be emitted for guard refusal
        events_text = "".join(events)
        assert '"type": "checkpoint"' not in events_text

    asyncio.run(_run())


# ─── task12: ExportClips does not call ffmpeg in API process ───


def test_export_clips_enqueues_celery_not_ffmpeg():
    """ExportClips.execute enqueues Celery task, does not import ffmpeg or subprocess."""
    import json

    from app.models.task import create_task, init_db, update_task_status

    init_db()
    # Need a real file for video_path check
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        video_path = f.name
        f.write(b"fake video data")

    task_id = create_task(
        video_path,
        "test.mp4",
        {
            "llm_base_url": "https://api.anthropic.com",
            "llm_model": "claude",
        },
    )
    update_task_status(
        task_id,
        "done",
        clips_json=json.dumps(
            [{"start_time_s": 0, "end_time_s": 10, "status": "success", "score": 9}]
        ),
    )

    import asyncio

    from app.tools.user.export_clips import _export_clips

    with patch("app.worker.celery_app.export_clips_task") as mock_task:
        mock_task.apply_async = MagicMock()
        result = asyncio.run(
            _export_clips.execute(
                task_id=task_id,
                clip_indices=[0],
                burn_subtitle=False,
            )
        )
        assert result.success is True
        assert "已启动" in result.user_message
        mock_task.apply_async.assert_called_once()


# ─── task8: Failed export_clips Checkpoint/status coverage ───


def test_failed_export_clips_sets_task_error():
    """Failed export_clips in chat emits no checkpoint, sets task to error."""

    async def _run():
        import tempfile

        from app.models.task import create_task, get_task, init_db, update_task_status

        init_db()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            vp = f.name
            f.write(b"data")
        task_id = create_task(
            vp,
            "test.mp4",
            {
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
        )
        update_task_status(
            task_id,
            "done",
            clips_json='[{"start_time_s":0,"end_time_s":5,"status":"success"}]',
        )

        svc = ChatService(
            task_id=task_id,
            llm_config={
                "llm_base_url": "https://api.anthropic.com",
                "llm_model": "claude",
            },
            api_key="sk-ant-test",
        )

        from app.tools.base import ToolResult

        async def mock_fail(tool_name, tool_input):
            if tool_name == "export_clips":
                return ToolResult(
                    success=False, error="enqueue failed", user_message="导出失败"
                )
            return ToolResult(success=True, data={}, user_message="ok")

        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [
            _MockToolUseBlock("export_clips", {"task_id": task_id})
        ]

        mock_end = MagicMock()
        mock_end.stop_reason = "end_turn"
        mock_end.content = [_MockTextBlock("Export failed. Try again?")]

        svc.async_client.messages.stream = MagicMock(
            side_effect=[
                _make_stream_from_response(mock_response),
                _make_stream_from_response(mock_end),
            ]
        )

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(svc, "_build_context", return_value="test"),
            patch.object(svc, "_execute_tool_with_retry", side_effect=mock_fail),
        ):
            events = []
            async for event in svc.chat("export"):
                events.append(event)

        events_text = "".join(events)
        assert '"type": "checkpoint"' not in events_text
        task = get_task(task_id)
        assert task["status"] == "error"
        assert task["failed_stage"] == "export_clips"

    asyncio.run(_run())


# ─── task5: Checkpoint persistence, API filtering, consumption, compat ───


def test_checkpoint_actions_per_tool():
    """Each checkpoint tool produces the correct action list."""
    from app.services.chat_service import ChatService

    ca = ChatService._checkpoint_actions

    # analyze_highlights -> preview + continue
    a = ca(["analyze_highlights"])
    assert len(a) == 2
    assert a[0] == {"label": "预览片段", "action": "preview"}
    assert a[1] == {"label": "继续", "action": "continue"}

    # export_clips -> preview + continue
    e = ca(["export_clips"])
    assert len(e) == 2
    assert e[0]["action"] == "preview"

    # extract_embedded_subtitles + run_asr -> open_editor + continue (one continue only)
    combined = ca(["extract_embedded_subtitles", "run_asr"])
    actions = [x["action"] for x in combined]
    assert "open_editor" in actions
    assert actions.count("continue") == 1
    assert len(combined) == 2  # open_editor + one continue

    # Non-checkpoint tools produce empty list
    assert ca(["get_transcript"]) == []
    assert ca([]) == []


def test_api_messages_recursive():
    """_api_messages recursively strips _-prefixed keys, preserves strings."""
    from app.services.chat_service import ChatService

    original = [
        {
            "role": "user",
            "_checkpoint": {"consumed": False},
            "content": [
                {
                    "type": "tool_result",
                    "_hidden": "secret",
                    "content": '{"key":"val"}',
                },
            ],
        },
    ]
    filtered = ChatService._api_messages(original)

    # Original unchanged
    assert "_checkpoint" in original[0]
    assert original[0]["content"][0].get("_hidden") == "secret"

    # Filtered: _-prefixed keys gone
    assert len(filtered) == 1
    assert "_checkpoint" not in filtered[0]
    assert filtered[0]["role"] == "user"
    blocks = filtered[0]["content"]
    assert len(blocks) == 1
    assert blocks[0]["type"] == "tool_result"
    assert "_hidden" not in blocks[0]
    # JSON string content preserved byte-for-byte
    assert blocks[0]["content"] == '{"key":"val"}'

    # Deep copy: filtered content list is independent
    assert filtered[0]["content"] is not original[0]["content"]


def test_checkpoint_on_assistant_message():
    """_checkpoint is written to the assistant message, not the user tool_result."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.tools.base import ToolResult

    async def _run():
        from app.models.task import create_task, init_db

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.test.com",
                "llm_model": "claude",
                "clip_min_duration": 30,
                "clip_max_duration": 120,
            },
        )

        svc = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
            checkpoint_mode="confirm",
        )

        class _MockToolUse:
            type = "tool_use"
            name = "analyze_highlights"
            id = "toolu_001"
            input = {"task_id": task_id}

        class _MockText:
            type = "text"
            text = "OK"

        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [_MockText, _MockToolUse]

        mock_end = MagicMock()
        mock_end.stop_reason = "end_turn"
        mock_end.content = [_MockText]

        svc.async_client.messages.stream = MagicMock(
            side_effect=[
                _make_stream_from_response(mock_response),
                _make_stream_from_response(mock_end),
            ]
        )

        with (
            patch.object(svc, "_load_history", new_callable=AsyncMock),
            patch.object(svc, "_save_history", new_callable=AsyncMock),
            patch.object(svc, "_build_context", return_value="sys"),
            patch.object(
                svc,
                "_execute_tool_with_retry",
                return_value=ToolResult(success=True, user_message="ok"),
            ),
        ):
            events = []
            async for event in svc.chat("analyze"):
                events.append(event)

        # _checkpoint must be on the assistant message, not user tool_result
        for m in svc.history:
            if m.get("role") == "assistant":
                cp = m.get("_checkpoint")
                if cp:
                    assert isinstance(cp, dict)
                    assert cp.get("consumed") is False
                    assert len(cp.get("actions", [])) > 0
            else:
                assert "_checkpoint" not in m

    asyncio.run(_run())


def test_checkpoint_roundtrip():
    """_checkpoint survives _save_history -> _load_history round-trip."""
    import asyncio

    async def _run():
        from app.models.task import create_task, init_db

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.test.com",
                "llm_model": "claude",
                "clip_min_duration": 30,
                "clip_max_duration": 120,
            },
        )

        svc = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )
        svc.history = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "OK"}],
                "_checkpoint": {
                    "actions": [{"label": "继续", "action": "continue"}],
                    "consumed": False,
                },
            },
        ]
        await svc._save_history()

        svc2 = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )
        await svc2._load_history()

        assert len(svc2.history) == 2
        assistant = svc2.history[1]
        assert assistant["role"] == "assistant"
        cp = assistant.get("_checkpoint")
        assert cp is not None
        assert cp["consumed"] is False
        assert cp["actions"] == [{"label": "继续", "action": "continue"}]

    asyncio.run(_run())


def test_consume_checkpoints_persists():
    """_consume_checkpoints marks consumed and persists to DB."""
    import asyncio

    async def _run():
        from app.models.task import create_task, init_db

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.test.com",
                "llm_model": "claude",
                "clip_min_duration": 30,
                "clip_max_duration": 120,
            },
        )

        svc = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )
        svc.history = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "OK"}],
                "_checkpoint": {
                    "actions": [{"label": "继续", "action": "continue"}],
                    "consumed": False,
                },
            },
        ]
        # Save the unconsumed checkpoint first
        await svc._save_history()

        # Now consume
        await svc._load_history()
        await svc._consume_checkpoints()

        assert svc.history[1]["_checkpoint"]["consumed"] is True

        # Verify persisted
        svc2 = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )
        await svc2._load_history()
        assert svc2.history[1]["_checkpoint"]["consumed"] is True

    asyncio.run(_run())


def test_old_history_no_checkpoint():
    """History without _checkpoint loads and passes through _api_messages()."""

    async def _run():
        from app.models.task import create_task, init_db

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.test.com",
                "llm_model": "claude",
                "clip_min_duration": 30,
                "clip_max_duration": 120,
            },
        )

        svc = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )
        svc.history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        ]
        await svc._save_history()

        svc2 = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )
        await svc2._load_history()
        assert len(svc2.history) == 2

        filtered = ChatService._api_messages(svc2.history)
        assert len(filtered) == 2
        assert filtered[0]["role"] == "user"


def test_build_checkpoint_context_extracts_summary():
    """_build_checkpoint_context returns the tool names and user_messages
    from the most recent unconsumed checkpoint."""
    import asyncio

    async def _run():
        from app.models.task import create_task, init_db

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.test.com",
                "llm_model": "claude",
            },
        )

        svc = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )

        # Simulate: AI called analyze_highlights, got 3 clips, checkpoint set
        svc.history = [
            {"role": "user", "content": "找精彩片段"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "分析中..."},
                    {
                        "type": "tool_use",
                        "name": "analyze_highlights",
                        "id": "t1",
                        "input": {},
                    },
                ],
                "_checkpoint": {
                    "actions": [
                        {"label": "预览片段", "action": "preview"},
                        {"label": "继续", "action": "continue"},
                    ],
                    "consumed": False,
                },
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": '{"success":true,"data":{"clips":[]},"user_message":"找到 3 个精彩片段：\\n片段 1: [10s-30s] 9.0/10 — 搞笑"}',
                    },
                ],
            },
        ]

        ctx = svc._build_checkpoint_context()
        assert "analyze_highlights" in ctx
        assert "找到 3 个精彩片段" in ctx
        assert "The user's message below is a response to this result." in ctx

    asyncio.run(_run())


def test_build_checkpoint_context_ignores_consumed():
    """_build_checkpoint_context returns empty string when all checkpoints
    are already consumed."""
    import asyncio

    async def _run():
        from app.models.task import create_task, init_db

        init_db()
        task_id = create_task(
            "/tmp/test.mp4",
            "test.mp4",
            {
                "llm_base_url": "https://api.test.com",
                "llm_model": "claude",
            },
        )

        svc = ChatService(
            task_id,
            llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
            api_key="sk-test",
        )

        svc.history = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "export_clips",
                        "id": "t1",
                        "input": {},
                    }
                ],
                "_checkpoint": {"actions": [], "consumed": True},  # already consumed
            },
        ]

        ctx = svc._build_checkpoint_context()
        assert ctx == ""

    asyncio.run(_run())


def test_build_checkpoint_context_empty_history():
    """_build_checkpoint_context returns empty string for empty history."""
    svc = ChatService(
        "test-id",
        llm_config={"llm_base_url": "https://api.test.com", "llm_model": "claude"},
        api_key="sk-test",
    )
    svc.history = []
    assert svc._build_checkpoint_context() == ""

    # Also returns empty for history with no checkpoint
    svc.history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]
    assert svc._build_checkpoint_context() == ""
