"""Regression tests for backend runtime image codec support."""

from pathlib import Path


DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_backend_image_requires_static_ffmpeg_for_hevc_flv_support():
    """Do not silently fall back to Debian ffmpeg; it cannot decode Bilibili HEVC-in-FLV."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "--noproxy '*'" in dockerfile
    assert "cp /tmp/ffmpeg/bin/ffmpeg /tmp/ffmpeg/bin/ffprobe /usr/local/bin/" in dockerfile
    assert "apt-get install -y --no-install-recommends ffmpeg" not in dockerfile
    assert "HEVC-in-FLV files will NOT be supported" not in dockerfile
