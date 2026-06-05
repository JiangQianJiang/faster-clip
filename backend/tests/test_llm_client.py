"""Tests for LLM client: _extract_json, analyze error classification, retry."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analyzer import (
    AuthError,
    ConnectionError_,
    LLMError,
    ParseError,
    _extract_json,
    analyze,
)

# ── _extract_json() tests ──────────────────────────────────────────────────


def test_extract_plain_json_array():
    result = _extract_json('[{"start_time_s": 1.0, "end_time_s": 5.0}]')
    assert len(result) == 1
    assert result[0]["start_time_s"] == 1.0


def test_extract_markdown_code_block():
    text = '```json\n[{"start_time_s": 2.0}]\n```'
    result = _extract_json(text)
    assert len(result) == 1
    assert result[0]["start_time_s"] == 2.0


def test_extract_markdown_no_lang():
    text = '```\n[{"start_time_s": 3.0}]\n```'
    result = _extract_json(text)
    assert len(result) == 1
    assert result[0]["start_time_s"] == 3.0


def test_extract_json_with_surrounding_text():
    text = 'Here is the result:\n[{"start_time_s": 4.0}]\nHope that helps.'
    result = _extract_json(text)
    assert len(result) == 1
    assert result[0]["start_time_s"] == 4.0


def test_extract_no_json_raises_parse_error():
    try:
        _extract_json("no json here")
        assert False, "should raise"
    except ParseError as e:
        assert "未在响应中找到 JSON 数组" in str(e)


def test_extract_invalid_json_raises_parse_error():
    try:
        _extract_json('[{"start": invalid}]')
        assert False, "should raise"
    except ParseError as e:
        assert "JSON 解析失败" in str(e)


def test_extract_no_array_found_raises_parse_error():
    try:
        _extract_json('{"key": "value"}')
        assert False, "should raise"
    except ParseError as e:
        assert "未在响应中找到 JSON 数组" in str(e)


# ── analyze() tests ────────────────────────────────────────────────────────


def _make_llm_response(text):
    resp = MagicMock()
    resp.content = [MagicMock()]
    resp.content[0].text = text
    return resp


def test_analyze_valid_response():
    """Normal response with valid JSON → parsed clips."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_llm_response(
        '[{"start_time_s": 10, "end_time_s": 50, "score": 0.9, "reason": "good"}]'
    )
    with patch("app.services.analyzer.Anthropic", return_value=mock_client):
        result = analyze("prompt", "https://api.example.com", "m", "sk-test")
    assert len(result) == 1
    assert result[0]["start_time_s"] == 10


def test_analyze_parse_failure_then_retry_success():
    """First response unparseable, retry succeeds."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _make_llm_response("no json here"),
        _make_llm_response(
            '[{"start_time_s": 20, "end_time_s": 60, "score": 0.8, "reason": "ok"}]'
        ),
    ]
    with patch("app.services.analyzer.Anthropic", return_value=mock_client):
        result = analyze("prompt", "https://api.example.com", "m", "sk-test")
    assert len(result) == 1
    assert result[0]["start_time_s"] == 20
    assert mock_client.messages.create.call_count == 2


def test_analyze_auth_error_raises_auth_error():
    """401 → AuthError without retry."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("401 Unauthorized")
    with patch("app.services.analyzer.Anthropic", return_value=mock_client):
        try:
            analyze("prompt", "https://api.example.com", "m", "sk-test")
            assert False, "should raise"
        except AuthError:
            pass
    assert mock_client.messages.create.call_count == 1


def test_analyze_connection_error_raises_connection_error():
    """Connection refused → ConnectionError_."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("Connection refused")
    with patch("app.services.analyzer.Anthropic", return_value=mock_client):
        try:
            analyze("prompt", "https://api.example.com", "m", "sk-test")
            assert False, "should raise"
        except ConnectionError_:
            pass


def test_analyze_generic_error_raises_llm_error():
    """Unknown error → LLMError."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("unknown failure")
    with patch("app.services.analyzer.Anthropic", return_value=mock_client):
        try:
            analyze("prompt", "https://api.example.com", "m", "sk-test")
            assert False, "should raise"
        except LLMError:
            pass
