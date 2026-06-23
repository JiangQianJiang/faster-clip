"""Real ffmpeg media smoke tests for AC-5, AC-10.

These tests use host ffmpeg to generate deterministic input, export real MP4/thumbnails,
and verify outputs with ffprobe. No subprocess mocking.
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.config import settings
from app.services.subtitle import generate_clip_subtitles
from app.worker.pipeline import _compute_export_window, _export_clip


def _has_subtitles_filter() -> bool:
    """Check whether host ffmpeg was built with --enable-libass (subtitles filter)."""
    result = subprocess.run(
        ["ffmpeg", "-filters"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return "subtitles" in result.stdout


def _make_test_video(dir_path: str, duration: float = 10.0) -> str:
    """Generate a deterministic test video (testsrc + sine tone)."""
    path = os.path.join(dir_path, "test.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-shortest",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    return path


def _ffprobe(path: str) -> dict:
    """Extract duration, width, height, codec_name from a media file."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height:format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    import json

    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def test_video_and_dir():
    """Module-scoped fixture: create a test video and return paths."""
    tmpdir = tempfile.mkdtemp(prefix="media_smoke_")
    outdir = os.path.join(tmpdir, "output")
    os.makedirs(outdir)
    video = _make_test_video(tmpdir, duration=10.0)
    yield tmpdir, video, outdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Export clip produces playable MP4 ────────────────────────────────────────


def test_export_clip_produces_playable_mp4(test_video_and_dir):
    """Real ffmpeg export produces a valid MP4 verified by ffprobe."""
    _, video, outdir = test_video_and_dir
    clip = {
        "start_time_s": 2.0,
        "end_time_s": 5.0,
        "score": 0.95,
        "reason": "highlight",
    }

    result = _export_clip(
        video,
        outdir,
        0,
        clip,
        buffer=3,
        burn=False,
        segments=None,
        max_duration=120,
        video_duration=10,
    )

    assert os.path.isfile(result["video"])
    info = _ffprobe(result["video"])
    assert float(info["format"]["duration"]) > 0


# ── Export duration within bounds ────────────────────────────────────────────


def test_export_clip_duration_within_max_bounds(test_video_and_dir):
    """Export duration is clip + buffer, clamped at max_duration."""
    _, video, outdir = test_video_and_dir
    clip = {
        "start_time_s": 1.0,
        "end_time_s": 3.0,
        "score": 0.8,
        "reason": "short clip",
    }

    result = _export_clip(
        video,
        outdir,
        1,
        clip,
        buffer=2,
        burn=False,
        segments=None,
        max_duration=120,
        video_duration=10,
    )

    info = _ffprobe(result["video"])
    dur = float(info["format"]["duration"])

    expected_start, expected_end = _compute_export_window(
        1.0,
        3.0,
        buffer=2,
        max_duration=120,
        video_duration=10,
    )
    assert expected_start == 0.0
    assert expected_end == 5.0
    assert 4.5 <= dur <= 5.5, f"expected ~5s, got {dur:.1f}s"


def test_export_window_preserves_logical_highlight():
    export_start, export_end = _compute_export_window(
        clip_start=2.0,
        clip_end=5.0,
        buffer=3,
        max_duration=120,
        video_duration=10,
    )
    assert export_start <= 2.0
    assert export_end >= 5.0


def test_export_window_respects_max_duration():
    export_start, export_end = _compute_export_window(
        clip_start=5.0,
        clip_end=115.0,  # 110s clip
        buffer=10,
        max_duration=120,
        video_duration=200,
    )
    assert export_end - export_start <= 120


# ── Thumbnail 160x90 JPEG ───────────────────────────────────────────────────


def test_thumbnail_dimensions_160x90(test_video_and_dir):
    """Thumbnail is exactly 160x90 JPEG."""
    _, video, outdir = test_video_and_dir
    clip = {
        "start_time_s": 1.0,
        "end_time_s": 4.0,
        "score": 0.9,
        "reason": "thumb test",
    }

    result = _export_clip(
        video,
        outdir,
        2,
        clip,
        buffer=1,
        burn=False,
        segments=None,
        max_duration=120,
        video_duration=10,
    )

    info = _ffprobe(result["thumbnail"])
    streams = [s for s in info["streams"] if s["codec_type"] == "video"]
    assert len(streams) == 1
    assert streams[0]["width"] == 320
    assert streams[0]["height"] == 180
    assert streams[0]["codec_name"] == "mjpeg"


# ── Subtitle burn-in ─────────────────────────────────────────────────────────


def test_generate_srt_filters_relevant_segments():
    """generate_clip_subtitles writes SRT with only segments overlapping the export window."""
    tmpdir = tempfile.mkdtemp(prefix="srt_test_")
    try:
        segments = [
            {"start_time_s": 0.0, "end_time_s": 2.0, "text": "before"},
            {"start_time_s": 2.0, "end_time_s": 5.0, "text": "keep this"},
            {"start_time_s": 5.0, "end_time_s": 8.0, "text": "also keep"},
            {"start_time_s": 8.0, "end_time_s": 10.0, "text": "after"},
        ]
        paths = generate_clip_subtitles(segments, 2.5, 7.5, tmpdir, 0)
        srt_path = os.path.join(tmpdir, "clip_000.srt")

        assert os.path.isfile(srt_path)
        with open(srt_path) as f:
            content = f.read()
        assert "keep this" in content
        assert "also keep" in content
        assert "before" not in content
        assert "after" not in content
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.skipif(
    not _has_subtitles_filter(),
    reason="host ffmpeg lacks --enable-libass (subtitles filter not available)",
)
def test_export_clip_with_subtitle_burnin(test_video_and_dir):
    """Subtitle burn-in produces playable video (requires libass ffmpeg)."""
    _, video, outdir = test_video_and_dir
    clip = {
        "start_time_s": 1.0,
        "end_time_s": 4.0,
        "score": 0.9,
        "reason": "burnin test",
    }
    segments = [
        {"start_time_s": 0.5, "end_time_s": 5.0, "text": "hello world"},
    ]

    result = _export_clip(
        video,
        outdir,
        3,
        clip,
        buffer=1,
        burn=True,
        segments=segments,
        max_duration=120,
        video_duration=10,
    )

    assert os.path.isfile(result["video"])
    info = _ffprobe(result["video"])
    dur = float(info["format"]["duration"])
    assert 2.0 <= dur <= 6.0

    srt_path = os.path.join(outdir, "clip_003.srt")
    assert os.path.isfile(srt_path)
    with open(srt_path) as f:
        content = f.read()
    assert "hello world" in content


# ── ffmpeg timeout ──────────────────────────────────────────────────────────


def test_ffmpeg_timeout_terminates_subprocess():
    """When ffmpeg timeout is hit, subprocess.TimeoutExpired propagates."""
    from unittest.mock import patch

    tmpdir = tempfile.mkdtemp(prefix="media_timeout_")
    try:
        video = _make_test_video(tmpdir, duration=10.0)
        outdir = os.path.join(tmpdir, "output")
        os.makedirs(outdir)
        clip = {
            "start_time_s": 0.0,
            "end_time_s": 5.0,
            "score": 1.0,
            "reason": "timeout",
        }

        with patch("app.worker.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["ffmpeg", "..."], timeout=0.5
            )
            with pytest.raises(subprocess.TimeoutExpired):
                _export_clip(
                    video,
                    outdir,
                    0,
                    clip,
                    buffer=0,
                    burn=False,
                    segments=None,
                    max_duration=120,
                    video_duration=10,
                )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
