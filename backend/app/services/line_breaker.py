"""Subtitle line-breaker: post-processes ASR text for readable line wrapping.

Inserts \n line breaks into subtitle text, enforcing a maximum character count
per line, compressing filler words, and protecting English/proper-noun boundaries.

Also provides word-level segment splitting: when ASR segments carry per-word
timestamps, long segments are split into sub-segments at word or punctuation
boundaries, each with its own start/end timestamps.
"""

import re

DEFAULT_MAX_CHARS_PER_LINE = 12

_FILLER_PAIRS: list[tuple[str, str]] = [
    ("那个那个", "那个"),
    ("那那个", "那"),  # normalize 那＋那个 filler chain at start
    ("然后然后", "然后"),
    ("就是就是", "就是"),
    ("这个这个", "这个"),
]

# Set of Chinese punctuation marks treated as preferred break points.
_PUNCTUATION = set("。，！？、；：")

# Punctuation marks that are natural line-break points (wider set for
# word-level splitting — includes commas, periods, question/exclamation marks).
_WORD_BREAK_PUNCTUATION = set("，。！？、；：,.!?;:")


def _compress_fillers(text: str) -> str:
    """Compress repeated filler-word pairs and leading filler chains."""
    for pattern, replacement in _FILLER_PAIRS:
        while pattern in text:
            text = text.replace(pattern, replacement)
    # Collapse runs of identical filler characters at the start (that survive
    # pair compression, e.g. "那那" from a partial chain).
    text = re.sub(r"^(那{2,})", "那", text)
    return text


def _find_break_point(text: str, max_chars: int) -> int:
    """Return the index *after* the last punctuation within *max_chars*, or -1."""
    best = -1
    for i, ch in enumerate(text):
        if i >= max_chars:
            break
        if ch in _PUNCTUATION:
            best = i + 1  # break AFTER the punctuation
    return best


def _is_safe_break(text: str, pos: int) -> bool:
    """Return True if breaking at *pos* does not split a protected token."""
    if pos <= 0 or pos >= len(text):
        return False
    left_char = text[pos - 1]
    right_char = text[pos]
    # Don't break inside any adjacent ASCII alphanumeric pair — this
    # protects English words ("OpenAI"), numbers ("8080"), and mixed
    # alphanumeric tokens ("GPT4Turbo", "v2Beta").
    if (
        left_char.isascii()
        and left_char.isalnum()
        and right_char.isascii()
        and right_char.isalnum()
    ):
        return False
    return True


def break_lines(text: str, max_chars_per_line: int = DEFAULT_MAX_CHARS_PER_LINE) -> str:
    """Insert ``\\n`` into *text* so each line is at most *max_chars_per_line*.

    Idempotent — text that already contains ``\\n`` is returned unchanged.
    Returns at most 2 lines; overflow is truncated with an ellipsis.
    """
    if not text:
        return text
    if "\n" in text:
        return text  # idempotent — already broken

    original_text = text
    text = _compress_fillers(text)

    # If the compressed text still fits on one line, return it as-is.
    # If compression removed everything, return the original (avoid empty output).
    if len(text) <= max_chars_per_line:
        return text if text else original_text

    # Try to break at the last punctuation within the character budget.
    break_at = _find_break_point(text, max_chars_per_line)
    if break_at > 0 and _is_safe_break(text, break_at):
        first = text[:break_at]
        second = text[break_at:]
    else:
        # Hard break — start at max_chars and backtrack to a safe position.
        break_at = max_chars_per_line
        while break_at > 0 and not _is_safe_break(text, break_at):
            break_at -= 1
        if break_at <= 0:
            # Cannot find a safe break boundary — the text is a single
            # unbreakable token.  Truncate it to respect the line budget.
            if len(text) > max_chars_per_line:
                return text[: max_chars_per_line - 1] + "…"
            return text
        first = text[:break_at]
        second = text[break_at:]

    # Truncate the second line if it still exceeds the budget, backtracking
    # to avoid splitting a protected token (English word / number).
    if len(second) > max_chars_per_line:
        cut = max_chars_per_line - 1
        while cut > 0 and not _is_safe_break(second, cut):
            cut -= 1
        if cut <= 0:
            cut = max_chars_per_line - 1  # fallback
        second = second[:cut] + "…"

    return f"{first}\n{second}"


# ---------------------------------------------------------------------------
# Word-level segment splitting
# ---------------------------------------------------------------------------


def split_segments(
    segments: list[dict],
    max_chars_per_line: int = DEFAULT_MAX_CHARS_PER_LINE,
) -> list[dict]:
    """Split long segments into sub-segments using word-level timestamps.

    When a segment carries a ``words`` array (from Qwen ASR with
    ``enable_words=True``), it is split at word boundaries so each resulting
    sub-segment is at most *max_chars_per_line* characters.  Punctuation
    marks are preferred as split points.

    Segments without word data are split by character count with
    proportionally interpolated timestamps as a fallback.

    Returns a new list of segments.  Segments that are already within the
    limit are returned unchanged (except that their ``text`` is run through
    filler compression).
    """
    result: list[dict] = []
    for seg in segments:
        words = seg.get("words")
        text = seg.get("text", "")
        if not text.strip():
            continue

        compressed = _compress_fillers(text)
        if len(compressed) <= max_chars_per_line:
            # Short enough — keep as a single segment.
            entry = dict(seg)
            entry["text"] = compressed
            result.append(entry)
            continue

        if words:
            result.extend(
                _split_segment_by_words(seg, words, compressed, max_chars_per_line)
            )
        else:
            result.extend(
                _split_segment_by_chars(seg, compressed, max_chars_per_line)
            )

    return result


def _split_segment_by_words(
    seg: dict,
    words: list[dict],
    compressed_text: str,
    max_chars: int,
) -> list[dict]:
    """Split a segment into sub-segments at word/punctuation boundaries.

    Accumulates words until *max_chars* would be exceeded, then emits a
    sub-segment.  When breaking, prefers splitting after a punctuation mark
    so the sub-segment reads more naturally.
    """
    sub_segments: list[dict] = []
    batch: list[dict] = []
    batch_chars = 0
    last_punct_idx: int | None = None

    for w in words:
        w_text = w.get("text", "")
        w_chars = len(w_text)

        # Track whether this word is a break-friendly punctuation mark.
        is_punct = w_chars == 1 and w_text in _WORD_BREAK_PUNCTUATION

        if batch and batch_chars + w_chars > max_chars:
            # Determine the split point: prefer punctuation, else hard break.
            if last_punct_idx is not None and last_punct_idx >= 0:
                # Emit up to and including the punctuation word.
                punct_batch = batch[: last_punct_idx + 1]
                rest = batch[last_punct_idx + 1:]
                sub_segments.append(_make_sub_segment(punct_batch, seg))
                batch = rest + [w]
                batch_chars = sum(len(x["text"]) for x in batch)
            else:
                # No punctuation anchor — break before the current word.
                sub_segments.append(_make_sub_segment(batch, seg))
                batch = [w]
                batch_chars = w_chars
            last_punct_idx = None
        else:
            batch.append(w)
            batch_chars += w_chars

        if is_punct:
            last_punct_idx = len(batch) - 1

    if batch:
        sub_segments.append(_make_sub_segment(batch, seg))

    return sub_segments


def _split_segment_by_chars(
    seg: dict,
    text: str,
    max_chars: int,
) -> list[dict]:
    """Fallback: split a segment by character count when no word data exists.

    Timestamps are interpolated proportionally from the parent segment's
    duration.  This is a rough estimate — word-level timestamps should be
    preferred whenever available.
    """
    chars = list(text)
    duration = seg["end_time_s"] - seg["start_time_s"]
    if duration <= 0:
        return [seg]

    sub_segments: list[dict] = []
    for i in range(0, len(chars), max_chars):
        chunk = chars[i: i + max_chars]
        chunk_text = "".join(chunk)
        ratio_start = i / len(chars)
        ratio_end = min((i + len(chunk)) / len(chars), 1.0)
        entry: dict = {
            "start_time_s": round(seg["start_time_s"] + duration * ratio_start, 3),
            "end_time_s": round(seg["start_time_s"] + duration * ratio_end, 3),
            "text": chunk_text,
            "words": None,
        }
        if "confidence" in seg:
            entry["confidence"] = seg["confidence"]
        sub_segments.append(entry)

    return sub_segments


def _make_sub_segment(words: list[dict], parent_seg: dict) -> dict:
    """Build a segment dict from a list of word dicts."""
    text = "".join(w["text"] for w in words)
    entry: dict = {
        "start_time_s": words[0]["start_time_s"],
        "end_time_s": words[-1]["end_time_s"],
        "text": text,
        "words": words,
    }
    if "confidence" in parent_seg:
        entry["confidence"] = parent_seg["confidence"]
    return entry
