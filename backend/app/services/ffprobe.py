"""Video file validation using ffprobe."""

import json
import os
import subprocess
from dataclasses import dataclass

from app.config import settings

ALLOWED_CONTAINERS = {"mp4", "mov", "mkv", "avi", "webm", "m4v", "flv"}


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    codec: str
    container: str
    has_video: bool
    subtitle_streams: list[dict]
    fps: float = 0.0
    fps_mode: str = "average"


class FFprobeError(Exception):
    pass


class FormatNotSupported(FFprobeError):
    def __init__(self, container: str):
        self.container = container
        super().__init__(
            f"不支持的视频格式: .{container}，支持: {', '.join(sorted(ALLOWED_CONTAINERS))}"
        )


class NoVideoStream(FFprobeError):
    def __init__(self):
        super().__init__("视频文件中未检测到视频流")


class DurationTooLong(FFprobeError):
    def __init__(self, duration: float):
        hours = settings.max_video_duration_seconds / 3600
        super().__init__(f"视频时长 {duration:.0f} 秒超过限制（最长 {hours:.0f} 小时）")


class CorruptedVideo(FFprobeError):
    def __init__(self, detail: str = ""):
        msg = "视频文件无法读取，可能已损坏"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


def probe(filepath: str) -> VideoInfo:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-print_format",
        "json",
        filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise CorruptedVideo("ffprobe 超时，文件可能过大或已损坏")
    except FileNotFoundError:
        raise FFprobeError("ffprobe 不可用，请确认 ffmpeg 已安装")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if stderr:
            raise CorruptedVideo(stderr[:200])
        raise CorruptedVideo("ffprobe 返回非零退出码")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise CorruptedVideo("ffprobe 输出无法解析")

    fmt = data.get("format", {})
    format_name = fmt.get("format_name", "")
    container = _resolve_container(format_name, filepath)
    if container not in ALLOWED_CONTAINERS:
        raise FormatNotSupported(container)

    duration = float(fmt.get("duration", 0))
    if duration > settings.max_video_duration_seconds:
        raise DurationTooLong(duration)

    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    if not video_streams:
        raise NoVideoStream()

    vs = video_streams[0]
    codec_name = vs.get("codec_name")
    width = vs.get("width")
    height = vs.get("height")

    # Reject streams ffprobe can't decode at all (truly corrupted / unknown codec tags)
    if not codec_name or not width or not height or width <= 0 or height <= 0:
        raise CorruptedVideo(
            f"无法解析视频流编码信息（编码: {codec_name or 'unknown'}, "
            f"分辨率: {width or 0}x{height or 0}），"
            f"视频流可能已损坏或使用了不支持的编码格式"
        )

    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        codec=codec_name,
        container=container.lower(),
        has_video=True,
        subtitle_streams=subtitle_streams,
        fps=_stream_fps(vs),
        fps_mode=_stream_fps_mode(vs),
    )


def _resolve_container(format_name: str, filepath: str) -> str:
    # First try to match ffprobe's format_name against allowed containers
    fmt_parts = {p.lower() for p in format_name.split(",")}
    for c in ALLOWED_CONTAINERS:
        if c in fmt_parts:
            return c
    # Fallback: try the file extension (e.g. "file.flv" → "flv")
    ext = os.path.splitext(filepath)[1].lstrip(".").lower()
    if ext in ALLOWED_CONTAINERS:
        return ext
    return ext  # return actual extension for a clearer error message


def _parse_rate(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            if den_f == 0:
                return 0.0
            return float(num) / den_f
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _stream_fps(stream: dict) -> float:
    avg = _parse_rate(stream.get("avg_frame_rate"))
    nominal = _parse_rate(stream.get("r_frame_rate"))
    fps = avg or nominal
    return round(fps, 3) if fps > 0 else 0.0


def _stream_fps_mode(stream: dict) -> str:
    avg = _parse_rate(stream.get("avg_frame_rate"))
    nominal = _parse_rate(stream.get("r_frame_rate"))
    if avg > 0 and nominal > 0 and abs(avg - nominal) < 0.001:
        return "stable"
    return "average"
