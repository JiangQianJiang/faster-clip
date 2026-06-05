"""Tests for thumbnail behavior in _export_clip."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.worker.pipeline import _compute_export_window, _export_clip


def test_export_window_for_thumbnail_midpoint():
    """The midpoint used for thumbnail extraction is within the export window."""
    clip_start, clip_end = 10.0, 50.0
    export_start, export_end = _compute_export_window(
        clip_start,
        clip_end,
        buffer=3,
        max_duration=120,
        video_duration=7200,
    )
    mid = (export_start + export_end) / 2
    assert export_start <= mid <= export_end


def test_thumbnail_ffmpeg_failure_raises_runtime_error():
    """_export_clip raises RuntimeError when thumbnail ffmpeg returns nonzero."""
    call_count = [0]

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:
            result.returncode = 0
            result.stderr = ""
        else:
            result.returncode = 1
            result.stderr = "thumbnail error"
        return result

    with patch("subprocess.run", side_effect=fake_run):
        raised = False
        try:
            _export_clip(
                "/fake/video.mp4",
                "/fake/output",
                0,
                {"start_time_s": 10.0, "end_time_s": 50.0},
                buffer=3,
                burn=False,
            )
        except RuntimeError as e:
            assert "缩略图生成失败" in str(e)
            raised = True
        assert raised, "should have raised RuntimeError"


def test_thumbnail_file_missing_raises_runtime_error():
    """_export_clip raises RuntimeError when thumbnail file is not on disk."""
    call_count = [0]

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        call_count[0] += 1
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch("os.path.isfile", return_value=False),
    ):
        raised = False
        try:
            _export_clip(
                "/fake/video.mp4",
                "/fake/output",
                0,
                {"start_time_s": 10.0, "end_time_s": 50.0},
                buffer=3,
                burn=False,
            )
        except RuntimeError as e:
            assert "缩略图生成失败" in str(e)
            raised = True
        assert raised, "should have raised RuntimeError"
