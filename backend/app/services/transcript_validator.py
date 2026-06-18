"""Shared transcript validation used by import, PATCH, and GET endpoints."""

import math

MAX_SEGMENTS = 5000
MAX_TEXT_LENGTH = 1000
REQUIRED_FIELDS = {"start_time_s", "end_time_s", "text"}
MIN_SEGMENT_DURATION_SECONDS = 0.05


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

        # Normalize in place, preserving optional metadata fields.
        entry: dict = {
            "start_time_s": round(start, 3),
            "end_time_s": round(end, 3),
            "text": seg["text"].strip(),
        }
        for key in ("confidence", "words"):
            if key in seg:
                entry[key] = _normalize_words(seg[key]) if key == "words" else seg[key]
        segments[i] = entry

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


def sanitize_transcript_timeline(segments: list) -> tuple[list, list]:
    """Return valid, sorted, non-overlapping transcript segments.

    Invalid rows such as zero-duration cues are skipped.  Overlaps caused by
    ASR duplicate-prefix fragments are resolved by dropping the shorter
    duplicate; other overlaps are repaired by trimming the previous segment to
    the next segment's start.  The returned transcript is suitable for strict
    validation and downstream binary-search consumers.
    """
    valid_segments, warnings = validate_transcript(segments)
    repaired: list[dict] = []

    for seg in valid_segments:
        current = dict(seg)
        append_current = True
        while repaired and current["start_time_s"] < repaired[-1]["end_time_s"]:
            prev = repaired[-1]
            if _is_duplicate_fragment(prev, current):
                warnings.append(
                    f"overlap repaired: dropped duplicate fragment at {prev['start_time_s']:.3f}s"
                )
                repaired.pop()
                continue
            if _is_duplicate_fragment(current, prev):
                warnings.append(
                    f"overlap repaired: dropped duplicate fragment at {current['start_time_s']:.3f}s"
                )
                append_current = False
                break

            trimmed = _clip_segment_to_range(
                prev,
                prev["start_time_s"],
                current["start_time_s"],
            )
            if trimmed is None:
                warnings.append(
                    f"overlap repaired: dropped segment ending at {prev['end_time_s']:.3f}s"
                )
                repaired.pop()
                continue

            warnings.append(
                f"overlap repaired: trimmed segment ending at {prev['end_time_s']:.3f}s"
            )
            repaired[-1] = trimmed
            break

        if append_current:
            repaired.append(current)

    return repaired, warnings


def _normalize_segment(seg: dict) -> dict:
    result = {
        "start_time_s": round(float(seg["start_time_s"]), 3),
        "end_time_s": round(float(seg["end_time_s"]), 3),
        "text": str(seg.get("text", "")).strip(),
    }
    # Preserve optional metadata fields (e.g. ASR confidence) so they
    # survive the transcript pipeline end-to-end.
    for key in ("confidence", "words"):
        if key in seg:
            result[key] = _normalize_words(seg[key]) if key == "words" else seg[key]
    return result


def _normalize_words(words) -> list[dict] | None:
    if not isinstance(words, list):
        return None
    normalized = []
    for word in words:
        if not isinstance(word, dict):
            continue
        text = str(word.get("text", ""))
        try:
            start = float(word["start_time_s"])
            end = float(word["end_time_s"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        normalized.append(
            {
                "text": text,
                "start_time_s": round(start, 3),
                "end_time_s": round(end, 3),
            }
        )
    return normalized or None


def _is_duplicate_fragment(a: dict, b: dict) -> bool:
    """Return true when ``a`` is an overlapping short fragment duplicated in ``b``."""
    a_text = _text_key(a.get("text", ""))
    b_text = _text_key(b.get("text", ""))
    if not a_text or not b_text or a_text == b_text:
        return False
    if not (b["start_time_s"] < a["end_time_s"] and a["start_time_s"] < b["end_time_s"]):
        return False
    return len(a_text) < len(b_text) and b_text.startswith(a_text)


def _text_key(text: str) -> str:
    return str(text).replace("\n", "").replace(" ", "").strip()


def _clip_segment_to_range(seg: dict, start: float, end: float) -> dict | None:
    if end - start < MIN_SEGMENT_DURATION_SECONDS:
        return None

    entry = dict(seg)
    entry["start_time_s"] = round(start, 3)
    entry["end_time_s"] = round(end, 3)

    words = entry.get("words")
    if isinstance(words, list) and words:
        clipped_words = []
        for word in words:
            w_start = word.get("start_time_s")
            w_end = word.get("end_time_s")
            if w_start is None or w_end is None:
                continue
            if w_end <= start or w_start >= end:
                continue
            rel_word = dict(word)
            rel_word["start_time_s"] = round(max(float(w_start), start), 3)
            rel_word["end_time_s"] = round(min(float(w_end), end), 3)
            if rel_word["end_time_s"] > rel_word["start_time_s"]:
                clipped_words.append(rel_word)
        if clipped_words:
            entry["words"] = clipped_words
            entry["text"] = "".join(str(w.get("text", "")) for w in clipped_words)
        else:
            entry.pop("words", None)
            entry["text"] = _clip_text_by_ratio(seg, start, end)
    else:
        entry["text"] = _clip_text_by_ratio(seg, start, end)

    if not str(entry.get("text", "")).strip():
        return None
    return entry


def _clip_text_by_ratio(seg: dict, start: float, end: float) -> str:
    text = str(seg.get("text", "")).replace("\n", "")
    if not text:
        return text
    seg_start = float(seg["start_time_s"])
    seg_end = float(seg["end_time_s"])
    duration = seg_end - seg_start
    if duration <= 0:
        return text
    total = len(text)
    start_idx = max(0, min(total, round((start - seg_start) / duration * total)))
    end_idx = max(start_idx, min(total, round((end - seg_start) / duration * total)))
    return text[start_idx:end_idx] or text
