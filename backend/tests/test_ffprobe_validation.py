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

from app.services.ffprobe import CorruptedVideo, probe


def _make_mock_subprocess(returncode=0, stdout="{}", stderr=""):
    """Build a MagicMock simulating subprocess.run result."""
    m = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _mock_ffprobe_output(
    *, codec_name=None, width=None, height=None, duration=60, container="flv"
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
    return json.dumps(
        {
            "format": {
                "format_name": container,
                "duration": str(duration),
            },
            "streams": [stream],
        }
    )


class TestProbeRejectsUnreadableStream:
    def test_codec_name_none(self):
        """ffprobe can't identify codec → CorruptedVideo with helpful hint."""
        out = _mock_ffprobe_output(codec_name=None, width=1920, height=1080)
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            try:
                probe("/fake/video.flv")
                assert False, "should have raised CorruptedVideo"
            except CorruptedVideo as e:
                assert "编码" in str(e)
                assert "不支持的编码格式" in str(e)

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
    def test_h264_mp4(self):
        """Standard H.264 MP4 passes probe."""
        out = _mock_ffprobe_output(
            codec_name="h264", width=1920, height=1080, container="mp4"
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.mp4")
            assert info.codec == "h264"
            assert info.width == 1920
            assert info.height == 1080
            assert info.container == "mp4"

    def test_hevc_mp4(self):
        """HEVC in MP4 (standard container) passes probe."""
        out = _mock_ffprobe_output(
            codec_name="hevc", width=3840, height=2160, container="mp4"
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.mp4")
            assert info.codec == "hevc"
            assert info.width == 3840
            assert info.height == 2160

    def test_h264_flv(self):
        """H.264 in FLV (standard) passes probe."""
        out = _mock_ffprobe_output(
            codec_name="h264", width=1280, height=720, container="flv"
        )
        with patch("subprocess.run", return_value=_make_mock_subprocess(stdout=out)):
            info = probe("/fake/video.flv")
            assert info.codec == "h264"
            assert info.width == 1280
