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


# ── confidence preservation ──────────────────────────────────────────────


class TestGetClipSubtitleSegmentsConfidence:
    def test_confidence_preserved_in_filtered_segments(self):
        segments = [
            {"start_time_s": 50, "end_time_s": 55, "text": "with confidence", "confidence": 0.72},
        ]
        result = get_clip_subtitle_segments(segments, window_start=50, window_end=60)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.72

    def test_confidence_preserved_across_boundary_crossing(self):
        segments = [
            {"start_time_s": 45, "end_time_s": 55, "text": "boundary", "confidence": 0.88},
        ]
        result = get_clip_subtitle_segments(segments, window_start=50, window_end=60)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.88

    def test_confidence_absent_not_injected(self):
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "plain"},
        ]
        result = get_clip_subtitle_segments(segments, window_start=0, window_end=10)
        assert len(result) == 1
        assert "confidence" not in result[0]

    def test_confidence_null_preserved(self):
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "null conf", "confidence": None},
        ]
        result = get_clip_subtitle_segments(segments, window_start=0, window_end=10)
        assert len(result) == 1
        assert result[0]["confidence"] is None


# ── export preserves transcript segments ──────────────────────────────────


class TestExportPreservesSegments:
    """generate_clip_subtitles writes filtered transcript segments without reflow."""

    def test_long_text_stays_single_cue_in_srt(self):
        long_text = "大家好欢迎来到今天的直播间今天我们要聊一个非常重要的话题"
        segments = [{"start_time_s": 0, "end_time_s": 5, "text": long_text}]
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_clip_subtitles(segments, 0, 10, tmpdir, 0)
            srt_path = os.path.join(tmpdir, "clip_000.srt")
            assert os.path.isfile(srt_path)
            with open(srt_path) as f:
                content = f.read()
            cue_bodies = _extract_srt_bodies(content)
            assert cue_bodies == [long_text]

    def test_long_text_stays_single_cue_in_vtt(self):
        long_text = "大家好欢迎来到今天的直播间今天我们要聊一个非常重要的话题"
        segments = [{"start_time_s": 0, "end_time_s": 5, "text": long_text}]
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_clip_subtitles(segments, 0, 10, tmpdir, 0)
            vtt_path = os.path.join(tmpdir, "clip_000.vtt")
            assert os.path.isfile(vtt_path)
            with open(vtt_path) as f:
                content = f.read()
            cue_bodies = _extract_vtt_bodies(content)
            assert cue_bodies == [long_text]

    def test_ass_export_keeps_single_dialogue(self):
        long_text = "大家好欢迎来到今天的直播间今天我们要聊一个非常重要的话题"
        segments = [{"start_time_s": 0, "end_time_s": 5, "text": long_text}]
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_clip_subtitles(segments, 0, 10, tmpdir, 0)
            ass_path = os.path.join(tmpdir, "clip_000.ass")
            assert os.path.isfile(ass_path)
            with open(ass_path) as f:
                content = f.read()
            assert content.count("Dialogue:") == 1
            assert long_text in content

    def test_pre_broken_text_not_double_broken(self):
        """Pre-existing newline in text is not doubled by the idempotent breaker."""
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "第一行\n第二行"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = generate_clip_subtitles(segments, 0, 10, tmpdir, 0)
            srt_path = os.path.join(tmpdir, "clip_000.srt")
            with open(srt_path) as f:
                content = f.read()
            # The original text (with single newline) should appear verbatim.
            assert "第一行\n第二行" in content
            # "第一行\n\n第二行" (double newline) would mean double-breaking.
            assert "第一行\n\n第二行" not in content

    def test_short_text_unchanged_in_export(self):
        """Short text under max_chars is not broken."""
        segments = [
            {"start_time_s": 0, "end_time_s": 5, "text": "短字幕"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = generate_clip_subtitles(segments, 0, 10, tmpdir, 0)
            srt_path = os.path.join(tmpdir, "clip_000.srt")
            with open(srt_path) as f:
                content = f.read()
            assert "短字幕" in content


# ── helpers for extracting cue bodies from subtitle formats ──────────────



def _extract_srt_bodies(content: str) -> list[str]:
    """Extract text bodies from SRT content, in order."""
    bodies: list[str] = []
    for block in content.strip().split("\n\n"):
        lines = block.split("\n")
        # SRT block: index, timestamp, body...
        if len(lines) >= 3:
            bodies.append(lines[2])
    return bodies


def _extract_vtt_bodies(content: str) -> list[str]:
    """Extract text bodies from VTT content, in order."""
    bodies: list[str] = []
    in_cue = False
    for line in content.split("\n"):
        line = line.strip()
        if "-->" in line:
            in_cue = True
            continue
        if in_cue:
            if line == "":
                in_cue = False
            else:
                bodies.append(line)
    return bodies
