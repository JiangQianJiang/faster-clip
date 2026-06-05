"""Tests for pipeline-level export failure semantics."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.asr import ASRError, AuthError
from app.worker.pipeline import StageError, run


def _make_info(duration=7200):
    info = MagicMock()
    info.duration = duration
    info.width = 1920
    info.height = 1080
    info.codec = "h264"
    info.container = "mp4"
    info.fps = 30.0
    info.fps_mode = "stable"
    info.has_video = True
    info.subtitle_streams = [{"codec_type": "subtitle", "codec_name": "subrip"}]
    return info


def _make_segments():
    return [{"start_time_s": 0, "end_time_s": 5, "text": "test segment"}]


def _make_raw_clips():
    return [
        {
            "start_time_s": 10,
            "end_time_s": 50,
            "score": 0.9,
            "reason": "first highlight",
        },
        {
            "start_time_s": 100,
            "end_time_s": 150,
            "score": 0.8,
            "reason": "second highlight",
        },
    ]


def _make_config():
    return {
        "llm_base_url": "http://x",
        "llm_model": "m",
        "clip_min_duration": 30,
        "clip_max_duration": 120,
        "buffer_seconds": 3,
        "burn_subtitle": False,
    }


def test_partial_export_failure_done_with_mixed_status():
    """One clip export fails, other succeeds → status 'done' with per-clip statuses."""
    task_id = "test-partial-fail"
    config = _make_config()

    export_results = [
        RuntimeError("缩略图生成失败"),
        {
            "video": f"/fake/output/{task_id}/clip_001.mp4",
            "thumbnail": f"/fake/output/{task_id}/clip_001.jpg",
            "export_start": 100.0,
            "export_end": 150.0,
        },
    ]

    def fake_export(*args, **kwargs):
        result = export_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    mock_status = MagicMock()
    mock_open = MagicMock()

    with (
        patch("app.worker.pipeline.probe", return_value=_make_info()),
        patch("app.worker.pipeline.has_text_subtitles", return_value=True),
        patch(
            "app.worker.pipeline.extract_embedded_subtitles",
            return_value=_make_segments(),
        ),
        patch(
            "app.worker.pipeline.save_transcript", return_value="/fake/transcript.json"
        ),
        patch("app.worker.pipeline.build_prompt", return_value="fake prompt"),
        patch("app.worker.pipeline.analyze", return_value=_make_raw_clips()),
        patch("app.worker.pipeline._export_clip", side_effect=fake_export),
        patch("app.worker.pipeline.update_task_status", side_effect=mock_status),
        patch("app.worker.pipeline.os.makedirs"),
        patch("builtins.open", mock_open),
    ):
        run(task_id, "/fake/video.mp4", config, "sk-llm", "sk-asr")

    final_calls = [
        c for c in mock_status.call_args_list if c[0][1] in ("done", "error")
    ]
    assert final_calls, "should have a final status update"
    final_call = final_calls[-1]
    assert final_call[0][0] == task_id
    assert final_call[0][1] == "done"

    clips_json = json.loads(final_call[1]["clips_json"])
    assert len(clips_json) == 2
    assert clips_json[0]["status"] == "failed"
    assert clips_json[0]["error"] == "缩略图生成失败"
    assert clips_json[1]["status"] == "success"
    assert clips_json[1]["filepath"].endswith(".mp4")


def test_all_export_failure_error_with_failed_stage():
    """All clip exports fail → status 'error' with failed_stage='exporting_clips'."""
    task_id = "test-all-fail"
    config = _make_config()

    def fake_export(*args, **kwargs):
        raise RuntimeError("ffmpeg 导出失败: codec error")

    mock_status = MagicMock()
    mock_open = MagicMock()

    with (
        patch("app.worker.pipeline.probe", return_value=_make_info()),
        patch("app.worker.pipeline.has_text_subtitles", return_value=True),
        patch(
            "app.worker.pipeline.extract_embedded_subtitles",
            return_value=_make_segments(),
        ),
        patch(
            "app.worker.pipeline.save_transcript", return_value="/fake/transcript.json"
        ),
        patch("app.worker.pipeline.build_prompt", return_value="fake prompt"),
        patch("app.worker.pipeline.analyze", return_value=_make_raw_clips()),
        patch("app.worker.pipeline._export_clip", side_effect=fake_export),
        patch("app.worker.pipeline.update_task_status", side_effect=mock_status),
        patch("app.worker.pipeline.os.makedirs"),
        patch("builtins.open", mock_open),
    ):
        run(task_id, "/fake/video.mp4", config, "sk-llm", "sk-asr")

    final_calls = [
        c for c in mock_status.call_args_list if c[0][1] in ("done", "error")
    ]
    assert final_calls
    final_call = final_calls[-1]
    assert final_call[0][0] == task_id
    assert final_call[0][1] == "error"
    assert final_call[1]["failed_stage"] == "exporting_clips"
    assert "所有片段导出均失败" in final_call[1]["error_message"]

    clips_json = json.loads(final_call[1]["clips_json"])
    assert len(clips_json) == 2
    assert all(c["status"] == "failed" for c in clips_json)


# ── ASR temp audio cleanup on failure paths ──────────────────────────────


def test_asr_auth_failure_cleans_up_temp_audio():
    """ASR auth error → temp WAV unlinked, StageError.retryable=False."""
    config = _make_config()
    with (
        patch("app.worker.pipeline.probe", return_value=_make_info()),
        patch("app.worker.pipeline.has_text_subtitles", return_value=False),
        patch("app.worker.pipeline.update_task_status"),
        patch(
            "app.worker.pipeline.extract_audio", return_value="/tmp/test_extracted.wav"
        ),
        patch("app.worker.pipeline.transcribe", side_effect=AuthError("401")),
        patch("app.worker.pipeline.os.path.exists", return_value=True),
        patch("app.worker.pipeline.os.unlink") as mock_unlink,
    ):
        try:
            run("t-asr-auth", "/f.wav", config, "sk-llm", "sk-asr")
            assert False, "should have raised StageError"
        except StageError as e:
            assert e.stage == "extracting_subtitles"
            assert e.retryable is False

    mock_unlink.assert_called_once_with("/tmp/test_extracted.wav")


def test_asr_retry_exhaustion_cleans_up_temp_audio():
    """ASR retry exhaustion → temp WAV unlinked, StageError.retryable=True."""
    config = _make_config()
    with (
        patch("app.worker.pipeline.probe", return_value=_make_info()),
        patch("app.worker.pipeline.has_text_subtitles", return_value=False),
        patch("app.worker.pipeline.update_task_status"),
        patch(
            "app.worker.pipeline.extract_audio", return_value="/tmp/test_extracted2.wav"
        ),
        patch(
            "app.worker.pipeline.transcribe", side_effect=ASRError("retry exhausted")
        ),
        patch("app.worker.pipeline.os.path.exists", return_value=True),
        patch("app.worker.pipeline.os.unlink") as mock_unlink,
    ):
        try:
            run("t-asr-retry", "/f.wav", config, "sk-llm", "sk-asr")
            assert False, "should have raised StageError"
        except StageError as e:
            assert e.stage == "extracting_subtitles"
            assert e.retryable is True

    mock_unlink.assert_called_once_with("/tmp/test_extracted2.wav")
