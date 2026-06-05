"""Tests for get_clip_subtitle_segments and generate_clip_subtitles in subtitle.py."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.subtitle import generate_clip_subtitles, get_clip_subtitle_segments


class TestGetClipSubtitleSegments:
    def test_timestamps_relative_to_window_start(self):
        segments = [
            {"start_time_s": 50, "end_time_s": 55, "text": "Hello"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=50, window_end=60)
        assert len(result) == 1
        assert result[0]["start_time_s"] == 0.0
        assert result[0]["end_time_s"] == 5.0
        assert result[0]["text"] == "Hello"

    def test_filters_segments_outside_window(self):
        segments = [
            {"start_time_s": 0, "end_time_s": 10, "text": "before"},
            {"start_time_s": 50, "end_time_s": 55, "text": "inside"},
            {"start_time_s": 90, "end_time_s": 100, "text": "after"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=40, window_end=60)
        texts = [s["text"] for s in result]
        assert "inside" in texts
        assert "before" not in texts
        assert "after" not in texts

    def test_empty_when_no_overlap(self):
        segments = [
            {"start_time_s": 0, "end_time_s": 10, "text": "early"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=50, window_end=60)
        assert result == []

    def test_partial_overlap_clamped(self):
        segments = [
            {"start_time_s": 45, "end_time_s": 55, "text": "overlap"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=50, window_end=60)
        assert len(result) == 1
        assert result[0]["start_time_s"] == 0.0  # clamped: max(45-50, 0)
        assert result[0]["end_time_s"] == 5.0  # clamped: min(55-50, 10)

    def test_multiple_segments(self):
        segments = [
            {"start_time_s": 10, "end_time_s": 12, "text": "A"},
            {"start_time_s": 14, "end_time_s": 16, "text": "B"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=10, window_end=20)
        assert len(result) == 2

    def test_zero_duration_segment_dropped(self):
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "should drop"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=5, window_end=15)
        assert len(result) == 0  # rel_start=0, rel_end=0, dropped

    def test_segment_at_window_boundary(self):
        """Segment exactly at window boundary: rel_start should be 0."""
        segments = [
            {"start_time_s": 10, "end_time_s": 15, "text": "boundary"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=10, window_end=20)
        assert len(result) == 1
        assert result[0]["start_time_s"] == 0.0

    def test_empty_segments_input(self):
        result = get_clip_subtitle_segments([], window_start=0, window_end=10)
        assert result == []


class TestGenerateClipSubtitles:
    def test_writes_all_three_formats(self):
        segments = [
            {"start_time_s": 10, "end_time_s": 15, "text": "Test subtitle"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = generate_clip_subtitles(segments, 10, 20, tmpdir, 0)
            assert len(paths) == 3
            for ext in ("srt", "vtt", "ass"):
                fpath = os.path.join(tmpdir, f"clip_000.{ext}")
                assert os.path.isfile(fpath), f"Missing {fpath}"
                assert fpath in paths

    def test_srt_content_correct(self):
        segments = [
            {"start_time_s": 50, "end_time_s": 55, "text": "Hello world"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_clip_subtitles(segments, 50, 60, tmpdir, 0)
            with open(os.path.join(tmpdir, "clip_000.srt")) as f:
                content = f.read()
            assert "00:00:00" in content
            assert "Hello world" in content

    def test_vtt_has_header(self):
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "VTT test"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_clip_subtitles(segments, 0, 10, tmpdir, 0)
            with open(os.path.join(tmpdir, "clip_000.vtt")) as f:
                content = f.read()
            assert content.startswith("WEBVTT")

    def test_ass_has_script_info(self):
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "ASS test"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_clip_subtitles(segments, 0, 10, tmpdir, 0)
            with open(os.path.join(tmpdir, "clip_000.ass")) as f:
                content = f.read()
            assert "[Script Info]" in content

    def test_empty_segments_still_writes_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = generate_clip_subtitles([], 0, 10, tmpdir, 0)
            assert len(paths) == 3
            for ext in ("srt", "vtt", "ass"):
                fpath = os.path.join(tmpdir, f"clip_000.{ext}")
                assert os.path.isfile(fpath)

    def test_best_effort_does_not_raise(self):
        """generate_clip_subtitles should not raise even with bad data."""
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "ok"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = generate_clip_subtitles(segments, 0, 10, "/nonexistent/dir", 0)
            assert paths == []  # best-effort: failed, no paths returned
