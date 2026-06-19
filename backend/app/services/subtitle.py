"""Subtitle extraction and normalization."""

import json
import logging
import os
import re
import subprocess
import tempfile


class SubtitleError(Exception):
    pass


class CorruptedVideo(SubtitleError):
    pass


SUBTITLE_CODECS = {"subrip", "ass", "webvtt", "mov_text"}

UTF8_BOM = b"\xef\xbb\xbf"
SUPPORTED_IMPORT_FORMATS = {"srt", "vtt", "ass"}


def parse_subtitle_bytes(content: bytes, format: str) -> tuple[list, list]:
    """Parse subtitle file bytes into segments. Returns (segments, warnings).

    Handles UTF-8 BOM detection and stripping, decodes UTF-8,
    routes to the appropriate parser, and validates/normalizes the result.
    """
    if format not in SUPPORTED_IMPORT_FORMATS:
        raise ValueError(f"Unsupported subtitle format: {format}")

    if isinstance(content, bytearray):
        content = bytes(content)

    if content.startswith(UTF8_BOM):
        content = content[3:]

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Encoding error: file must be UTF-8 encoded")

    if format == "srt":
        raw = _parse_srt(text)
    elif format == "vtt":
        raw = _parse_vtt(text)
    else:
        raw = _parse_ass(text)

    if not raw:
        raise ValueError("No valid segments found in subtitle file")

    from app.services.transcript_validator import MAX_SEGMENTS, validate_transcript

    if len(raw) > MAX_SEGMENTS:
        raise ValueError(f"Too many segments: {len(raw)} (max {MAX_SEGMENTS})")

    segments, warnings = validate_transcript(raw)
    return segments, warnings


def has_text_subtitles(subtitle_streams: list[dict]) -> bool:
    return any(
        s.get("codec_name", "").lower() in SUBTITLE_CODECS
        or _tag_language(s, "chi", "zho", "zh")
        for s in subtitle_streams
    )


def extract_embedded_subtitles(
    video_path: str, streams: list[dict]
) -> list[dict] | None:
    text_streams = [
        s for s in streams if s.get("codec_name", "").lower() in SUBTITLE_CODECS
    ]
    if not text_streams:
        return None

    stream_index = text_streams[0].get("index", 0)
    codec = text_streams[0].get("codec_name", "subrip")

    ext_map = {"subrip": "srt", "ass": "ass", "webvtt": "vtt", "mov_text": "srt"}
    suffix = ext_map.get(codec, "srt")

    with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
        tmp_path = tmp.name

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-map",
        f"0:{stream_index}",
        "-c:s",
        codec if codec != "mov_text" else "srt",
        tmp_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            os.unlink(tmp_path)
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return None

    try:
        with open(tmp_path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception:
        os.unlink(tmp_path)
        return None

    os.unlink(tmp_path)

    if codec in ("ass",):
        parsed = _parse_ass(raw)
    elif codec in ("webvtt",):
        parsed = _parse_vtt(raw)
    else:
        parsed = _parse_srt(raw)

    if not parsed:
        return None
    return parsed


def _parse_srt(text: str) -> list[dict]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    segments = []
    pattern = re.compile(
        r"(\d+)\s*\n"
        r"(-?)(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
        r"(-?)(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\n"
        r"([\s\S]*?)(?=\n\n|\n?\Z)",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        start = _to_seconds(m.group(3), m.group(4), m.group(5), m.group(6))
        if m.group(2):
            start = -start
        end = _to_seconds(m.group(8), m.group(9), m.group(10), m.group(11))
        if m.group(7):
            end = -end
        body = m.group(12).strip().replace("\n", " ")
        body = re.sub(r"<[^>]+>", "", body)
        line_no = text[: m.start()].count("\n") + 1
        segments.append(
            {
                "start_time_s": start,
                "end_time_s": end,
                "text": body,
                "_line": line_no,
            }
        )
    return segments


def _parse_vtt(text: str) -> list[dict]:
    segments = []
    lines = text.splitlines()
    n = len(lines)
    i = 0

    timestamp_re = re.compile(
        r"(-?)(\d{2}:)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*"
        r"(-?)(\d{2}:)?(\d{2}):(\d{2})[.,](\d{3})"
    )

    metadata_re = re.compile(r"^(?:NOTE|STYLE|REGION)(?:\s|$)", re.IGNORECASE)

    # Skip WEBVTT header and its metadata lines
    if n > 0 and re.match(r"^WEBVTT", lines[0], re.IGNORECASE):
        i = 1
        while i < n and lines[i].strip() != "":
            i += 1
        if i < n and lines[i].strip() == "":
            i += 1

    while i < n:
        stripped = lines[i].strip()
        line_no = i + 1  # 1-based original source line number

        if not stripped:
            i += 1
            continue

        if metadata_re.match(stripped):
            i += 1
            while i < n and lines[i].strip() != "":
                i += 1
            if i < n and lines[i].strip() == "":
                i += 1
            continue

        ts_match = timestamp_re.match(stripped)
        if ts_match:
            sign1 = ts_match.group(1)
            h1 = int(ts_match.group(2)[:-1]) if ts_match.group(2) else 0
            start = (
                h1 * 3600
                + int(ts_match.group(3)) * 60
                + int(ts_match.group(4))
                + int(ts_match.group(5)) / 1000.0
            )
            if sign1:
                start = -start

            sign2 = ts_match.group(6)
            h2 = int(ts_match.group(7)[:-1]) if ts_match.group(7) else 0
            end = (
                h2 * 3600
                + int(ts_match.group(8)) * 60
                + int(ts_match.group(9))
                + int(ts_match.group(10)) / 1000.0
            )
            if sign2:
                end = -end

            i += 1
            body_lines = []
            while i < n:
                if lines[i].strip() == "":
                    break
                body_lines.append(lines[i])
                i += 1

            body = "\n".join(body_lines).strip().replace("\n", " ")
            body = re.sub(r"<[^>]+>", "", body)

            segments.append(
                {
                    "start_time_s": start,
                    "end_time_s": end,
                    "text": body,
                    "_line": line_no,
                }
            )
        else:
            # Possibly a cue ID — if next line is a timestamp, skip this line
            if i + 1 < n and timestamp_re.match(lines[i + 1].strip()):
                i += 1
            else:
                i += 1

    return segments


def _parse_ass(text: str) -> list[dict]:
    segments = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) >= 10:
                start = _ass_time_to_s(parts[1].strip())
                end = _ass_time_to_s(parts[2].strip())
                body = parts[9].strip()
                body = re.sub(r"\{[^}]*\}", "", body)
                body = re.sub(r"\\[Nn]", " ", body)
                segments.append(
                    {
                        "start_time_s": start,
                        "end_time_s": end,
                        "text": body,
                        "_line": line_no,
                    }
                )
    return segments


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def _ass_time_to_s(t: str) -> float:
    parts = t.split(":")
    if len(parts) == 3:
        sign = -1 if parts[0].startswith("-") else 1
        return sign * (abs(int(parts[0])) * 3600 + int(parts[1]) * 60 + float(parts[2]))
    return 0.0


def _tag_language(stream: dict, *langs) -> bool:
    tags = stream.get("tags", {})
    language = tags.get("language", "").lower()
    title = tags.get("title", "").lower()
    for l in langs:
        if l in language or l in title:
            return True
    return False


# ---------------------------------------------------------------------------
# Export formatters — convert internal segments to standard subtitle formats
# ---------------------------------------------------------------------------


def segments_to_srt(segments: list[dict]) -> str:
    """Convert segments to SRT format with ordered cues."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg["start_time_s"])
        end = _format_srt_time(seg["end_time_s"])
        lines.append(f"{i}\n{start} --> {end}\n{seg['text']}\n")
    return "\n".join(lines)


def segments_to_vtt(segments: list[dict]) -> str:
    """Convert segments to VTT format with WEBVTT header."""
    lines = ["WEBVTT"]
    for i, seg in enumerate(segments, 1):
        start = _format_vtt_time(seg["start_time_s"])
        end = _format_vtt_time(seg["end_time_s"])
        lines.append(f"\n{i}\n{start} --> {end}\n{seg['text']}")
    return "\n".join(lines) + "\n"


def segments_to_ass(segments: list[dict]) -> str:
    """Convert segments to ASS format with Dialogue lines only."""
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 384",
        "PlayResY: 288",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text",
    ]
    for seg in segments:
        start = _format_ass_time(seg["start_time_s"])
        end = _format_ass_time(seg["end_time_s"])
        text = seg["text"].replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def _ms_to_hms(seconds: float) -> tuple[int, int, int, int]:
    """Decompose seconds into (hours, minutes, seconds, milliseconds)."""
    total_ms = round(seconds * 1000)
    h = total_ms // 3_600_000
    m = (total_ms % 3_600_000) // 60_000
    s = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return h, m, s, ms


def _format_srt_time(seconds: float) -> str:
    h, m, s, ms = _ms_to_hms(seconds)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    h, m, s, ms = _ms_to_hms(seconds)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _format_ass_time(seconds: float) -> str:
    h, m, s, ms = _ms_to_hms(seconds)
    return f"{h}:{m:02d}:{s:02d}.{ms:03d}"


def save_transcript(segments: list[dict], output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "transcript.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    return path


def save_raw_transcript(segments: list[dict], output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "transcript.raw.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    return path


def get_clip_subtitle_segments(
    segments: list[dict],
    window_start: float,
    window_end: float,
) -> list[dict]:
    """Filter and offset transcript segments for a clip export window.

    Returns segments with timestamps relative to window_start, clamped to
    [0, window_duration]. Zero/negative-duration segments are dropped.
    """
    window_dur = window_end - window_start
    result = []
    for seg in segments:
        if seg["end_time_s"] <= window_start or seg["start_time_s"] >= window_end:
            continue
        abs_start = max(seg["start_time_s"], window_start)
        abs_end = min(seg["end_time_s"], window_end)
        rel_start = max(seg["start_time_s"] - window_start, 0.0)
        rel_end = min(seg["end_time_s"] - window_start, window_dur)
        if rel_end - rel_start <= 0:
            continue
        clipped_words = None
        if "words" in seg and seg["words"]:
            clipped_words = [
                {
                    "text": w["text"],
                    "start_time_s": round(
                        max(w["start_time_s"] - window_start, 0.0), 3
                    ),
                    "end_time_s": round(
                        min(w["end_time_s"] - window_start, window_dur), 3
                    ),
                }
                for w in seg["words"]
                if w["end_time_s"] > window_start
                and w["start_time_s"] < window_end
                and min(w["end_time_s"], window_end)
                - max(w["start_time_s"], window_start)
                > 0
            ]
        if clipped_words:
            text = "".join(str(w["text"]) for w in clipped_words)
        else:
            text = seg["text"]
        if not str(text).strip():
            continue
        entry: dict = {
            "start_time_s": round(rel_start, 3),
            "end_time_s": round(rel_end, 3),
            "text": text,
        }
        if "confidence" in seg:
            entry["confidence"] = seg["confidence"]
        if clipped_words:
            entry["words"] = clipped_words
        result.append(entry)
    return result


def _clip_text_by_time_ratio(seg: dict, abs_start: float, abs_end: float) -> str:
    text = str(seg.get("text", "")).replace("\n", "")
    if not text:
        return text
    duration = float(seg["end_time_s"]) - float(seg["start_time_s"])
    if duration <= 0:
        return text
    total = len(text)
    start_idx = max(
        0,
        min(total, round((abs_start - float(seg["start_time_s"])) / duration * total)),
    )
    end_idx = max(
        start_idx,
        min(total, round((abs_end - float(seg["start_time_s"])) / duration * total)),
    )
    return text[start_idx:end_idx] or text


def generate_clip_subtitles(
    segments: list[dict],
    window_start: float,
    window_end: float,
    output_dir: str,
    clip_index: int,
) -> list[str]:
    """Generate SRT/VTT/ASS subtitle files for a clip. Best-effort per format.

    Returns list of paths to successfully written files. Failures are logged
    via warning but do not raise — callers should treat this as non-fatal.
    """
    logger = logging.getLogger(__name__)

    filtered = get_clip_subtitle_segments(segments, window_start, window_end)

    fmt_configs = [
        ("srt", segments_to_srt),
        ("vtt", segments_to_vtt),
        ("ass", segments_to_ass),
    ]
    written = []
    for ext, formatter in fmt_configs:
        path = os.path.join(output_dir, f"clip_{clip_index:03d}.{ext}")
        try:
            content = formatter(filtered)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            written.append(path)
        except Exception:
            logger.warning(
                "Failed to write clip subtitle %s for clip %d",
                ext,
                clip_index,
                exc_info=True,
            )
    return written
