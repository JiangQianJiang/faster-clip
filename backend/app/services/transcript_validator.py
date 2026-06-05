"""Shared transcript validation used by import, PATCH, and GET endpoints."""

import math

MAX_SEGMENTS = 5000
MAX_TEXT_LENGTH = 1000
REQUIRED_FIELDS = {"start_time_s", "end_time_s", "text"}


def validate_segment(seg: dict) -> tuple[bool, str]:
    """Validate a single segment. Returns (is_valid, error_message)."""
    if not isinstance(seg, dict):
        msg = "segment must be a dict"
        return False, msg

    missing = REQUIRED_FIELDS - set(seg.keys())
    if missing:
        msg = f"missing required fields: {', '.join(sorted(missing))}"
        return False, msg

    try:
        start = float(seg["start_time_s"])
        end = float(seg["end_time_s"])
    except (ValueError, TypeError):
        return False, "start_time_s and end_time_s must be numbers"

    if not (math.isfinite(start) and math.isfinite(end)):
        return False, "start_time_s and end_time_s must be finite numbers"

    text = seg.get("text", "")
    if not isinstance(text, str):
        return False, "text must be a string"

    if start < 0:
        return False, "start_time_s must be non-negative"

    if end <= start:
        return False, "end_time_s must be greater than start_time_s"

    stripped = text.strip()
    if not stripped:
        return False, "text must not be empty"

    if len(stripped) > MAX_TEXT_LENGTH:
        msg = f"text must not exceed {MAX_TEXT_LENGTH} characters"
        return False, msg

    return True, ""


def validate_transcript(segments: list) -> tuple[list, list]:
    """Validate a transcript for import. Returns (valid_segments, warnings).

    Invalid segments are skipped with warnings. Valid segments are normalized.
    """
    if not isinstance(segments, list):
        return [], ["transcript must be a list of segments"]

    valid_segments = []
    warnings = []

    for i, seg in enumerate(segments):
        ok, err = validate_segment(seg)
        if not ok:
            if isinstance(seg, dict):
                line_ref = seg.get("_line", i + 1)
            else:
                line_ref = i + 1
            warnings.append(f"line {line_ref}: {err}")
        else:
            valid_segments.append(_normalize_segment(seg))

    valid_segments.sort(key=lambda s: s["start_time_s"])
    return valid_segments, warnings


def validate_transcript_strict(segments: list) -> str | None:
    """Fail-fast validation for full transcript replacement.

    The input is normalized in place: timestamps are rounded, text is stripped,
    internal parser fields are discarded, and segments are sorted by start time.
    Returns an error message or None if valid.
    """
    if not isinstance(segments, list):
        return "request body must contain a 'segments' array"

    if len(segments) == 0:
        return "segments array must not be empty"

    if len(segments) > MAX_SEGMENTS:
        msg = f"transcript must not exceed {MAX_SEGMENTS} segments"
        return msg

    for i, seg in enumerate(segments):
        ok, err = validate_segment(seg)
        if not ok:
            return f"invalid segment at index {i}: {err}"

        start = float(seg["start_time_s"])
        end = float(seg["end_time_s"])

        # Normalize in place
        segments[i] = {
            "start_time_s": round(start, 3),
            "end_time_s": round(end, 3),
            "text": seg["text"].strip(),
        }

    segments.sort(key=lambda s: (s["start_time_s"], s["end_time_s"]))
    for i in range(1, len(segments)):
        prev = segments[i - 1]
        curr = segments[i]
        if curr["start_time_s"] < prev["end_time_s"]:
            return f"segments overlap at index {i - 1} and {i}"

    return None


def normalize_transcript(segments: list) -> list:
    """Normalize transcript: sort, round to 3 decimals, strip text."""
    normalized = [_normalize_segment(s) for s in segments]
    normalized.sort(key=lambda s: s["start_time_s"])
    return normalized


def _normalize_segment(seg: dict) -> dict:
    return {
        "start_time_s": round(float(seg["start_time_s"]), 3),
        "end_time_s": round(float(seg["end_time_s"]), 3),
        "text": str(seg.get("text", "")).strip(),
    }
