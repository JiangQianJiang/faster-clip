"""Tests for ffprobe probe() validation of unreadable video streams.

The probe() function must reject video streams whose codec / dimensions
ffprobe cannot parse (e.g. HEVC-in-FLV with non-standard codec tags),
rather than silently returning width=0 / codec="unknown".
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.ffprobe import CorruptedVideo, DurationTooLong, probe


def _make_mock_subprocess(returncode=0, stdout="{}", stderr=""):
    """Build a MagicMock simulating subprocess.run result."""
    m = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _mock_ffprobe_output(
    *,
    codec_name=None,
    width=None,
    height=None,
    duration=60,
    container="flv",
    format_tags=None,
):
    """Build realistic ffprobe JSON for a single video stream."""
    stream = {"codec_type": "video"}
    if codec_name is not None:
        stream["codec_name"] = codec_name
    if width is not None:
        stream["width"] = width
    if height is not None:
        stream["height"] = height
    # Add a nominal r_frame_rate so fps helpers don't choke
    stream["r_frame_rate"] = "25/1"
    stream["avg_frame_rate"] = "25/1"
    fmt: dict = {
        "format_name": container,
        "duration": str(duration),
    }
    if format_tags:
        fmt["tags"] = format_tags
    return json.dumps(
        {
            "format": fmt,
            "streams": [stream],
        }
    )


class TestProbeRejectsUnreadableStream:
    def test_width_zero(self):
        """ffprobe returns width=0 → CorruptedVideo."""
        out = _mock_ffprobe_output(codec_name="hevc", width=0, height=1080)
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            try:
                probe("/fake/video.flv")
                assert False, "should have raised CorruptedVideo"
            except CorruptedVideo as e:
                assert "分辨率" in str(e)

    def test_width_none(self):
        """ffprobe returns width=None → CorruptedVideo."""
        out = _mock_ffprobe_output(codec_name="hevc", width=None, height=1080)
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            try:
                probe("/fake/video.flv")
                assert False, "should have raised CorruptedVideo"
            except CorruptedVideo as e:
                assert "分辨率" in str(e)

    def test_height_zero(self):
        """ffprobe returns height=0 → CorruptedVideo."""
        out = _mock_ffprobe_output(codec_name="hevc", width=1920, height=0)
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            try:
                probe("/fake/video.flv")
                assert False, "should have raised CorruptedVideo"
            except CorruptedVideo as e:
                assert "分辨率" in str(e)

    def test_height_none(self):
        """ffprobe returns height=None → CorruptedVideo."""
        out = _mock_ffprobe_output(codec_name="hevc", width=1920, height=None)
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            try:
                probe("/fake/video.flv")
                assert False, "should have raised CorruptedVideo"
            except CorruptedVideo as e:
                assert "分辨率" in str(e)

    def test_both_codec_and_dims_missing(self):
        """All stream properties unreadable → CorruptedVideo."""
        out = _mock_ffprobe_output(codec_name=None, width=None, height=None)
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            try:
                probe("/fake/video.flv")
                assert False, "should have raised CorruptedVideo"
            except CorruptedVideo as e:
                assert "0x0" in str(e)


class TestProbeAcceptsValidStream:
    def test_twelve_hour_video_passes_duration_validation(self):
        """qwen3-asr-flash-filetrans supports recordings up to 12 hours."""
        out = _mock_ffprobe_output(
            codec_name="h264",
            width=1920,
            height=1080,
            container="mp4",
            duration=12 * 60 * 60,
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.mp4")
            assert info.duration == 12 * 60 * 60

    def test_video_longer_than_twelve_hours_is_rejected(self):
        """Recordings beyond the ASR provider's 12h filetrans limit are rejected."""
        out = _mock_ffprobe_output(
            codec_name="h264",
            width=1920,
            height=1080,
            container="mp4",
            duration=12 * 60 * 60 + 1,
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            try:
                probe("/fake/video.mp4")
                assert False, "should have raised DurationTooLong"
            except DurationTooLong as e:
                assert "最长 12 小时" in str(e)

    def test_h264_mp4(self):
        """Standard H.264 MP4 passes probe."""
        out = _mock_ffprobe_output(codec_name="h264", width=1920, height=1080, container="mp4")
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.mp4")
            assert info.codec == "h264"
            assert info.width == 1920
            assert info.height == 1080
            assert info.container == "mp4"

    def test_hevc_mp4(self):
        """HEVC in MP4 (standard container) passes probe."""
        out = _mock_ffprobe_output(codec_name="hevc", width=3840, height=2160, container="mp4")
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.mp4")
            assert info.codec == "hevc"
            assert info.width == 3840
            assert info.height == 2160

    def test_h264_flv(self):
        """H.264 in FLV (standard) passes probe."""
        out = _mock_ffprobe_output(codec_name="h264", width=1280, height=720, container="flv")
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.flv")
            assert info.codec == "h264"
            assert info.width == 1280

    def test_unknown_codec_with_valid_dims(self):
        """Unknown codec but valid dimensions → accepted with codec='unknown'.

        This covers ffmpeg builds (e.g. Debian) that cannot identify HEVC in
        FLV containers but can still report the stream dimensions.  The
        downstream pipeline can auto-detect the codec at processing time.
        """
        out = _mock_ffprobe_output(codec_name=None, width=1920, height=1080)
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.flv")
            assert info.codec == "unknown"
            assert info.width == 1920
            assert info.height == 1080

    def test_hevc_in_flv_format_tag_fallback(self):
        """HEVC-in-FLV where stream metadata is unreadable but format tags
        carry displayWidth / displayHeight (Bilibili live recording pattern).
        """
        out = _mock_ffprobe_output(
            codec_name=None,
            width=0,
            height=0,
            container="flv",
            format_tags={
                "displayWidth": "1920",
                "displayHeight": "1080",
                "fps": "60",
                "encoder": "BVC-SRT LiveHime/7.23.0",
            },
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.flv")
            assert info.codec == "unknown"
            assert info.width == 1920
            assert info.height == 1080
            assert info.container == "flv"

    def test_codec_from_encoder_tag_hevc(self):
        """Encoder tag contains 'hevc' → codec inferred as 'hevc'."""
        out = _mock_ffprobe_output(
            codec_name=None,
            width=1920,
            height=1080,
            container="flv",
            format_tags={"encoder": "LIVE-SRT-HEVC/1.2.3"},
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.flv")
            assert info.codec == "hevc"

    def test_codec_from_encoder_tag_h264(self):
        """Encoder tag contains 'h264' → codec inferred as 'h264'."""
        out = _mock_ffprobe_output(
            codec_name=None,
            width=1920,
            height=1080,
            container="flv",
            format_tags={"encoder": "LIVE-SRT-H264/1.2.3"},
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.flv")
            assert info.codec == "h264"
