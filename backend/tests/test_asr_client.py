"""Tests for ASR client: transcribe() response handling, retry, auth, empty."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.asr import ASRError, AuthError, EmptyTranscript, transcribe


def _make_seg_obj(start, end, text):
    s = MagicMock()
    s.start = start
    s.end = end
    s.text = text
    return s


def _mock_client(segments=None, side_effect=None):
    client = MagicMock()
    create = client.audio.transcriptions.create
    if side_effect:
        create.side_effect = side_effect
    elif segments is not None:
        resp = MagicMock()
        resp.segments = segments
        create.return_value = resp
    return client


def test_transcribe_object_segments():
    """Standard SDK response with object segments."""
    client = _mock_client(segments=[_make_seg_obj(0.0, 5.0, "hello world")])
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        result = transcribe("/f.wav", "sk-test")
    assert len(result) == 1
    assert result[0]["text"] == "hello world"


def test_transcribe_dict_top_level():
    """Dict-shaped Whisper response → _get_attr reads dict key."""
    client = MagicMock()
    client.audio.transcriptions.create.return_value = {
        "segments": [{"start": 0.0, "end": 5.0, "text": "dict top"}],
    }
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        result = transcribe("/f.wav", "sk-test")
    assert len(result) == 1
    assert result[0]["text"] == "dict top"


def test_transcribe_dict_segments():
    """Object response containing dict-shaped segment entries."""
    resp = MagicMock()
    resp.segments = [{"start": 1.0, "end": 6.0, "text": "dict seg"}]
    client = MagicMock()
    client.audio.transcriptions.create.return_value = resp
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        result = transcribe("/f.wav", "sk-test")
    assert len(result) == 1
    assert result[0]["text"] == "dict seg"


def test_transcribe_auth_no_retry():
    """401/403 → AuthError immediately, no retry."""
    client = _mock_client(side_effect=Exception("401 Unauthorized"))
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        try:
            transcribe("/f.wav", "sk-bad")
            assert False, "should have raised"
        except AuthError:
            pass
    assert client.audio.transcriptions.create.call_count == 1


def test_transcribe_retry_then_success():
    """First call fails, second succeeds after retry."""
    success_resp = MagicMock()
    success_resp.segments = [_make_seg_obj(0.0, 3.0, "retry ok")]
    client = MagicMock()
    client.audio.transcriptions.create.side_effect = [
        Exception("timeout"),
        success_resp,
    ]
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        result = transcribe("/f.wav", "sk-test")
    assert len(result) == 1
    assert result[0]["text"] == "retry ok"
    assert client.audio.transcriptions.create.call_count == 2


def test_transcribe_retry_exhaustion():
    """Three failures → ASRError."""
    client = _mock_client(side_effect=Exception("server error"))
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        try:
            transcribe("/f.wav", "sk-test")
            assert False, "should have raised"
        except ASRError as e:
            assert "已重试 3 次" in str(e)
    assert client.audio.transcriptions.create.call_count == 3


def test_transcribe_empty_transcript():
    """Zero segments → EmptyTranscript."""
    client = _mock_client(segments=[])
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        try:
            transcribe("/f.wav", "sk-test")
            assert False, "should have raised"
        except EmptyTranscript:
            pass


def test_transcribe_whitespace_text_filtered():
    """Blank text filtered → EmptyTranscript."""
    client = _mock_client(segments=[_make_seg_obj(0.0, 2.0, "   ")])
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=["/f.wav"]),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
    ):
        try:
            transcribe("/f.wav", "sk-test")
            assert False, "should have raised"
        except EmptyTranscript:
            pass


# ── multi-chunk timestamp offset & cleanup ─────────────────────────────────


def test_transcribe_multi_chunk_timestamp_offset():
    """Segments from chunk 2+ include accumulated offset from preceding chunks."""
    # Chunk 0: duration 10.0, segment at 0.0-3.0
    # Chunk 1: duration 8.0, segment at 2.0-5.0 → expected 12.0-15.0 (2.0+10.0)
    resp0 = MagicMock()
    resp0.segments = [_make_seg_obj(0.0, 3.0, "hello")]
    resp1 = MagicMock()
    resp1.segments = [_make_seg_obj(2.0, 5.0, "world")]

    client = MagicMock()
    client.audio.transcriptions.create.side_effect = [resp0, resp1]

    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch(
            "app.services.asr._split_audio",
            return_value=["/f.chunk0.wav", "/f.chunk1.wav"],
        ),
        patch("app.services.asr._get_duration", side_effect=[10.0, 8.0]),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
        patch("app.services.asr.os.path.exists", return_value=True),
        patch("app.services.asr.os.unlink") as mock_unlink,
    ):
        result = transcribe("/f.wav", "sk-test")

    assert len(result) == 2
    assert result[0]["start_time_s"] == 0.0
    assert result[0]["end_time_s"] == 3.0
    assert result[0]["text"] == "hello"
    assert result[1]["start_time_s"] == 12.0
    assert result[1]["end_time_s"] == 15.0
    assert result[1]["text"] == "world"
    assert mock_unlink.call_count == 2


def test_transcribe_chunk_files_cleaned_up_after_success():
    """Temporary chunk files are removed after successful transcription."""
    resp = MagicMock()
    resp.segments = [_make_seg_obj(0.0, 2.0, "ok")]

    client = MagicMock()
    client.audio.transcriptions.create.return_value = resp

    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch(
            "app.services.asr._split_audio",
            return_value=["/f.chunk0.wav", "/f.chunk1.wav"],
        ),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
        patch("app.services.asr.os.path.exists", return_value=True),
        patch("app.services.asr.os.unlink") as mock_unlink,
    ):
        transcribe("/f.wav", "sk-test")

    assert mock_unlink.call_count == 2


def test_transcribe_auth_failure_cleans_up_chunks():
    """Auth failure on chunk 1 → both chunk files still unlinked via finally."""
    from app.services.asr import AuthError

    resp0 = MagicMock()
    resp0.segments = [_make_seg_obj(0.0, 2.0, "ok")]

    client = MagicMock()
    client.audio.transcriptions.create.side_effect = [
        resp0,
        Exception("401 Unauthorized"),
    ]

    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch(
            "app.services.asr._split_audio",
            return_value=["/f.chunk0.wav", "/f.chunk1.wav"],
        ),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
        patch("app.services.asr.os.path.exists", return_value=True),
        patch("app.services.asr.os.unlink") as mock_unlink,
    ):
        try:
            transcribe("/f.wav", "sk-test")
            assert False, "should have raised"
        except AuthError:
            pass

    assert mock_unlink.call_count == 2


def test_transcribe_retry_exhaustion_cleans_up_chunks():
    """Retry exhaustion on chunk 1 → both chunk files still unlinked."""
    from app.services.asr import ASRError

    resp0 = MagicMock()
    resp0.segments = [_make_seg_obj(0.0, 2.0, "ok")]

    client = MagicMock()
    client.audio.transcriptions.create.side_effect = [
        resp0,
        Exception("timeout"),
        Exception("timeout"),
        Exception("timeout"),
    ]

    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch(
            "app.services.asr._split_audio",
            return_value=["/f.chunk0.wav", "/f.chunk1.wav"],
        ),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
        patch("app.services.asr.os.path.exists", return_value=True),
        patch("app.services.asr.os.unlink") as mock_unlink,
    ):
        try:
            transcribe("/f.wav", "sk-test")
            assert False, "should have raised"
        except ASRError:
            pass

    assert mock_unlink.call_count == 2


# ── first-chunk failure cleanup (outer finally safety net) ─────────────────


def test_transcribe_first_chunk_auth_failure_cleans_all_chunks():
    """Auth failure on chunk 0 → outer finally cleans all 3 generated chunks."""
    from app.services.asr import AuthError

    client = MagicMock()
    client.audio.transcriptions.create.side_effect = Exception("401 Unauthorized")

    chunks = ["/f.chunk0.wav", "/f.chunk1.wav", "/f.chunk2.wav"]
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=chunks),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
        patch("app.services.asr.os.path.exists", return_value=True),
        patch("app.services.asr.os.unlink") as mock_unlink,
    ):
        try:
            transcribe("/f.wav", "sk-test")
            assert False, "should have raised"
        except AuthError:
            pass

    unlinked = [c[0][0] for c in mock_unlink.call_args_list]
    for p in chunks:
        assert p in unlinked, f"{p} should have been unlinked"


def test_transcribe_first_chunk_retry_exhaustion_cleans_all_chunks():
    """Retry exhaustion on chunk 0 → outer finally cleans all 3 generated chunks."""
    from app.services.asr import ASRError

    client = MagicMock()
    client.audio.transcriptions.create.side_effect = [
        Exception("timeout"),
        Exception("timeout"),
        Exception("timeout"),
    ]

    chunks = ["/f.chunk0.wav", "/f.chunk1.wav", "/f.chunk2.wav"]
    with (
        patch("app.services.asr.OpenAI", return_value=client),
        patch("app.services.asr._split_audio", return_value=chunks),
        patch("app.services.asr._get_duration", return_value=10.0),
        patch("app.services.asr.time.sleep"),
        patch("builtins.open", MagicMock()),
        patch("app.services.asr.os.path.exists", return_value=True),
        patch("app.services.asr.os.unlink") as mock_unlink,
    ):
        try:
            transcribe("/f.wav", "sk-test")
            assert False, "should have raised"
        except ASRError:
            pass

    unlinked = [c[0][0] for c in mock_unlink.call_args_list]
    for p in chunks:
        assert p in unlinked, f"{p} should have been unlinked"
