"""Tests for AC-6: API key security — log redaction, broker/result config."""

import io
import logging
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── LogRecordFactory redaction tests ──────────────────────────────────────────


def _make_record(msg, args=None):
    """Create a real LogRecord through the currently installed factory."""
    return logging.getLogRecordFactory()(
        "test",
        logging.INFO,
        "",
        0,
        msg,
        args,
        None,
        None,
    )


def test_install_log_filter_redacts_key_in_message():
    """After install, sk-... keys in log messages are replaced with ***."""
    # force re-install for this test by resetting the guard
    import app.logging_config as lc
    from app.logging_config import install_log_filter

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False

    install_log_filter()

    record = _make_record(
        "Using key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA for LLM"
    )
    assert "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in record.msg
    assert "***" in record.msg
    assert "Using key *** for LLM" in record.msg

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_install_log_filter_redacts_key_in_args():
    """After install, sk-... keys in log record args are replaced with ***."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    record = _make_record(
        "API call failed",
        (
            "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "https://api.example.com",
            500,
        ),
    )
    assert record.args[0] == "***"
    assert record.args[1] == "https://api.example.com"
    assert record.args[2] == 500

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_install_log_filter_preserves_non_key_content():
    """Log messages without API keys are not modified."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    record = _make_record("Task completed successfully", ("job-123", "done"))
    assert record.msg == "Task completed successfully"
    assert record.args == ("job-123", "done")

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_install_log_filter_handles_non_string_args():
    """Non-string args pass through unmodified."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    record = _make_record(None, (42, None, 3.14))  # None msg should not crash
    assert record.msg is None
    assert record.args == (42, None, 3.14)

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_install_log_filter_handles_none_args():
    """None record.args should not crash the factory."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    record = _make_record("No args message", None)
    assert record.msg == "No args message"

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_install_log_filter_redacts_multiple_keys():
    """Multiple sk-... keys in one record are all redacted."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    record = _make_record(
        "LLM key=sk-12345678901234567890123456789012 ASR key=sk-asr123456789012345678901234567890"
    )
    assert "sk-12345678901234567890123456789012" not in record.msg
    assert "sk-asr123456789012345678901234567890" not in record.msg
    assert record.msg.count("***") == 2

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


# ── Process-wide coverage: named logger + propagate=False ─────────────────────


def test_named_logger_with_own_handler_redacts_key():
    """A named logger with propagate=False still redacts keys via factory."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)

    logger = logging.getLogger("test_named_redact")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    logger.info("Using key sk-test123456789012345678901234567890 in named logger")
    handler.flush()
    output = buf.getvalue()

    assert "sk-test123456789012345678901234567890" not in output
    assert "***" in output

    # Cleanup
    logger.removeHandler(handler)
    handler.close()
    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_root_logger_redacts_key():
    """Root logger also redacts keys via factory."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    old_handlers = list(logging.root.handlers)
    logging.root.handlers.clear()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.DEBUG)

    logging.root.info("API key sk-rootsecret12345678901234567890123 in root logger")
    handler.flush()
    output = buf.getvalue()

    assert "sk-rootsecret12345678901234567890123" not in output
    assert "***" in output

    logging.root.handlers.clear()
    for h in old_handlers:
        logging.root.addHandler(h)
    logging.root.setLevel(logging.NOTSET)
    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_formatted_args_in_log_message_redacted():
    """Keys in %s-formatted log messages are redacted in the formatted output."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    logging.root.addHandler(handler)

    logging.root.info(
        "Calling LLM with key %s at %s",
        "sk-formatted98765432109876543210987654",
        "https://api.example.com",
    )
    handler.flush()
    output = buf.getvalue()

    assert "sk-formatted98765432109876543210987654" not in output
    assert "***" in output

    logging.root.removeHandler(handler)
    handler.close()
    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_short_sk_prefix_not_redacted():
    """Short sk- patterns like 'sk-0' are not false-positive redacted."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    record = _make_record("task_id=sk-0 is not a real key")
    assert "sk-0" in record.msg
    assert "***" not in record.msg

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_install_log_filter_is_idempotent():
    """Calling install_log_filter() multiple times does not double-wrap."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()
    factory_after_first = logging.getLogRecordFactory()
    install_log_filter()
    factory_after_second = logging.getLogRecordFactory()

    assert factory_after_first is factory_after_second

    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


def test_dict_style_logging_redacts_key():
    """logger.info('key %(api_key)s', {'api_key': 'sk-...'}) redacts without error."""
    import app.logging_config as lc

    old_factory = logging.getLogRecordFactory()
    lc._redacting_installed = False
    from app.logging_config import install_log_filter

    install_log_filter()

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    logging.root.addHandler(handler)

    logging.root.info(
        "key %(api_key)s", {"api_key": "sk-dictsecret1234567890123456789012345"}
    )
    handler.flush()
    output = buf.getvalue()

    assert "sk-dictsecret1234567890123456789012345" not in output
    assert "***" in output
    assert "--- Logging error ---" not in output

    logging.root.removeHandler(handler)
    handler.close()
    logging.setLogRecordFactory(old_factory)
    lc._redacting_installed = False


# ── Celery broker/result config tests ────────────────────────────────────────


def test_celery_result_backend_is_disabled():
    """Celery result backend is None → no task results persisted to Redis."""
    from app.worker.celery_app import celery_app

    assert celery_app.conf.result_backend is None


def test_celery_task_serializer_is_json():
    """Celery uses JSON serialization for task messages."""
    from app.worker.celery_app import celery_app

    assert celery_app.conf.task_serializer == "json"


def test_celery_accepts_only_json():
    """Celery only accepts JSON content type."""
    from app.worker.celery_app import celery_app

    assert celery_app.conf.accept_content == ["json"]


# ── Key not persisted to SQLite ─────────────────────────────────────────────


def test_settings_has_no_default_api_keys():
    """Settings has API key fields, but no hard-coded default key values."""
    from app.config import settings

    assert settings.asr_api_key == ""
    assert settings.llm_api_key == ""


# ── AC-2: Request lifecycle task_id cleanup ──────────────────────────────────


def test_task_id_cleared_after_request():
    """task_id is None after a task-scoped request returns (no context leak)."""
    import asyncio

    from app.logging_config import (
        _task_id_var,
        get_task_id,
        install_log_filter,
        setup_json_logging,
    )

    install_log_filter()
    setup_json_logging()
    # Clear any stale task_id from previous tests
    _task_id_var.set(None)
    from app.main import request_logging_middleware

    async def run():
        # Simulate a task request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/tasks/00000000-0000-0000-0000-000000000001",
            "raw_path": b"/api/tasks/00000000-0000-0000-0000-000000000001",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 12345),
            "server": ("localhost", 8000),
        }
        request = MagicMock()
        request.scope = scope
        request.url.path = "/api/tasks/00000000-0000-0000-0000-000000000001"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        request.path_params = {}

        class FakeResponse:
            status_code = 200

        async def fake_call_next(_req):
            # Inside the request, task_id must be set
            tid = get_task_id()
            assert tid == "00000000-0000-0000-0000-000000000001", (
                f"Expected task_id inside request, got {tid}"
            )
            return FakeResponse()

        response = await request_logging_middleware(request, fake_call_next)
        assert response.status_code == 200

        # After the request, task_id must be None
        tid_after = get_task_id()
        assert tid_after is None, f"Expected None after request, got {tid_after}"

        # Subsequent non-task request also has None
        request2 = MagicMock()
        request2.scope = scope
        request2.url.path = "/api/health"
        request2.client.host = "127.0.0.1"
        request2.method = "GET"
        request2.path_params = {}

        async def fake_call_next2(_req):
            tid = get_task_id()
            assert tid is None, f"Expected None for non-task request, got {tid}"
            return FakeResponse()

        response2 = await request_logging_middleware(request2, fake_call_next2)
        assert response2.status_code == 200

        # And still None after non-task request
        assert get_task_id() is None

    asyncio.run(run())
