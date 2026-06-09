"""Subtitle line-breaker: post-processes ASR text for readable line wrapping.

Inserts ``\\n`` line breaks into subtitle text, enforcing a maximum character count
per line, compressing filler words, and protecting English/proper-noun boundaries.

Also provides word-level segment splitting: when ASR segments carry per-word
timestamps, long segments are split into sub-segments at word or punctuation
boundaries, each with its own start/end timestamps.

Design
------

* **split_segments** splits the transcript timeline into subtitle *cards*,
  each sized for up to 2 display lines (``MAX_CHARS_PER_SEGMENT`` chars).
  When word-level timestamps are available the split is anchored to word
  boundaries; otherwise character-count interpolation is used as a fallback.
  Every result has ``break_lines`` applied so downstream consumers always
  receive display-ready text.

* **break_lines** splits a single segment's text into at most 2 display lines
  using a tiered priority system for linguistically natural break points.
"""

import re

# A Chinese subtitle card should comfortably hold 2 lines.
# 12 chars/line is the mobile-friendly budget; 2 × 12 = 24 chars total.
MAX_CHARS_PER_SEGMENT = 24
MAX_CHARS_PER_LINE = 12

# ---------------------------------------------------------------------------
# Filler compression
# ---------------------------------------------------------------------------

_FILLER_PAIRS: list[tuple[str, str]] = [
    ("那个那个", "那个"),
    ("那那个", "那"),  # normalize 那＋那个 filler chain at start
    ("然后然后", "然后"),
    ("就是就是", "就是"),
    ("这个这个", "这个"),
]

# Single-character repetitions: 3+ identical Chinese chars → 1
# e.g. "大家好大家好大家好" → "大家好"
_REPEATED_CHAR_PATTERN = re.compile(r"([一-鿿])\1{2,}")

# Multi-character repetitions: same 2+-char substring repeated 2+ times
# e.g. "谢谢你谢谢你" → "谢谢你"
_REPEATED_PHRASE_PATTERN = re.compile(r"(.{2,6}?)\1{2,}")


def _compress_fillers(text: str) -> str:
    """Compress repeated filler-word pairs and repeated character patterns."""
    # Known filler pairs.
    for pattern, replacement in _FILLER_PAIRS:
        while pattern in text:
            text = text.replace(pattern, replacement)

    # Runs of identical Chinese characters collapse to a single char.
    text = _REPEATED_CHAR_PATTERN.sub(r"\1", text)

    # Repeated multi-char phrases collapse to one occurrence.
    # Iterate until stable (cascading: "ABABAB" → "AB")
    prev = None
    while prev != text:
        prev = text
        text = _REPEATED_PHRASE_PATTERN.sub(r"\1", text)

    # Collapse runs of identical filler characters at the start.
    text = re.sub(r"^(那{2,})", "那", text)

    return text


# ---------------------------------------------------------------------------
# Semantic break-point engine
# ---------------------------------------------------------------------------

# Punctuation marks that are natural break points.
_PUNCTUATION = set("。，！？、；：")

# Tiered break-point patterns, evaluated in order.  Each tier is a function
# (text: str, budget: int) → int | None that returns the *index after* the
# break character (suitable for ``text[:idx]``), or None if no match.
#
# For a line budget of N chars we scan the *first N chars* of *text* to find
# the best split point.  Tiers are tried in order; the first non-None result
# wins.


def _break_at_strong_punct(text: str, budget: int) -> int | None:
    """Break AFTER ``。！？`` — sentence boundaries."""
    best = None
    for i, ch in enumerate(text):
        if i >= budget:
            break
        if ch in ("。", "！", "？"):
            best = i + 1
    return best


def _break_at_medium_punct(text: str, budget: int) -> int | None:
    """Break AFTER ``，、；：`` — clause boundaries."""
    best = None
    for i, ch in enumerate(text):
        if i >= budget:
            break
        if ch in ("，", "、", "；", "："):
            best = i + 1
    return best


def _break_after_particle(text: str, budget: int) -> int | None:
    """Break AFTER a Chinese modal/function particle that follows content.

    Particles: 的 了 吗 呢 吧 啊 嘛 哦 呀 着 过 得

    Only breaks when the particle follows a CJK character (not a standalone
    particle at position 0), and the result keeps at least 4 chars on the
    first line (avoids creating very short first lines).
    """
    particles = set("的了吗呢吧啊嘛哦呀着过得")
    best = None
    for i, ch in enumerate(text):
        if i >= budget:
            break
        if ch in particles and i >= 1:
            prev = text[i - 1]
            # Preceding char should be a CJK character or ASCII letter
            if "一" <= prev <= "鿿" or (prev.isascii() and prev.isalpha()):
                # Minimum first-line length of 4 to avoid stub lines
                if i + 1 >= 4:
                    best = i + 1
    return best


def _break_before_conjunction(text: str, budget: int) -> int | None:
    """Break BEFORE a conjunction word.

    Conjunctions: 然后 但是 所以 因为 而且 不过 还是 如果 虽然 可是 但 那 这 也
    Only matches when the break point is within budget and leaves a
    meaningful first line (≥ 5 chars).
    """
    conj_pattern = re.compile(
        r"(然后|但是|所以|因为|而且|不过|还是|如果|虽然|可是)"
    )
    # Scan from the midpoint toward the end of the budget — prefer later breaks
    # (closer to budget limit) to fill the line better.
    best = None
    for m in conj_pattern.finditer(text):
        pos = m.start()
        if pos < budget and pos >= 5:  # first line ≥ 5 chars
            best = pos  # break BEFORE the conjunction
    return best


def _find_best_break(text: str, max_chars: int) -> int | None:
    """Return the best break index (characters BEFORE the break) within budget.

    Returns the position where the first line should end (exclusive index),
    or None if no good break point exists.  Tries tiered break strategies
    in priority order.
    """
    budget = min(max_chars, len(text))

    # Tier 1: strong punctuation (sentence end)
    pos = _break_at_strong_punct(text, budget)
    if pos is not None:
        return pos

    # Tier 2: medium punctuation (clause boundary)
    pos = _break_at_medium_punct(text, budget)
    if pos is not None:
        return pos

    # Tier 3: after modal/function particles
    pos = _break_after_particle(text, budget)
    if pos is not None:
        return pos

    # Tier 4: before conjunctions
    pos = _break_before_conjunction(text, budget)
    if pos is not None:
        return pos

    return None


# ---------------------------------------------------------------------------
# break_lines — display line splitting
# ---------------------------------------------------------------------------


def _is_safe_break(text: str, pos: int) -> bool:
    """Return True if breaking at *pos* does not split a protected token.

    *pos* is an exclusive-end index (i.e. we are splitting ``text[:pos]``
    from ``text[pos:]``).  A break is unsafe when it lands inside a run of
    adjacent ASCII alphanumeric characters — this protects English words,
    numbers, and mixed tokens like "GPT4Turbo".
    """
    if pos <= 0 or pos >= len(text):
        return False
    left_char = text[pos - 1]
    right_char = text[pos]
    if (
        left_char.isascii()
        and left_char.isalnum()
        and right_char.isascii()
        and right_char.isalnum()
    ):
        return False
    return True


def break_lines(
    text: str,
    max_chars_per_line: int = MAX_CHARS_PER_LINE,
    allow_truncate: bool = True,
) -> str:
    """Insert ``\\n`` into *text* so each line ≤ *max_chars_per_line*.

    Uses tiered semantic break-point selection for natural line wrapping.
    Returns at most 2 lines; overflow is truncated with an ellipsis unless
    *allow_truncate* is false.

    Idempotent — text that already contains ``\\n`` is returned unchanged.
    """
    if not text:
        return text
    if "\n" in text:
        return text  # idempotent

    original_text = text
    text = _compress_fillers(text)
    if not text:
        return original_text

    # Short enough for a single line — return as-is.
    if len(text) <= max_chars_per_line:
        return text

    # If text is only slightly over budget and no clean break exists,
    # keep it as a single line (better than creating an orphan second line).
    if len(text) <= max_chars_per_line + 2:
        # Try semantic break — if it would leave ≥ 3 chars on the second
        # line, use it; otherwise keep as one line.
        bp = _find_best_break(text, max_chars_per_line)
        if bp is None or len(text) - bp < 3:
            return text  # keep as single line, slightly over budget
        # Good break with meaningful second line — use it.
        if _is_safe_break(text, bp):
            return f"{text[:bp]}\n{text[bp:]}"
        return text

    # Try tiered semantic break points.
    break_pos = _find_best_break(text, max_chars_per_line)

    if break_pos is not None and _is_safe_break(text, break_pos):
        first = text[:break_pos]
        second = text[break_pos:]
    else:
        # No semantic break — fall back to hard break at budget limit,
        # backtracking to avoid splitting a protected token.
        break_pos = max_chars_per_line
        while break_pos > 0 and not _is_safe_break(text, break_pos):
            break_pos -= 1
        if break_pos <= 0:
            # Cannot find any safe boundary — text is one unbreakable token.
            if len(text) > max_chars_per_line:
                if not allow_truncate:
                    return text
                return text[: max_chars_per_line - 1] + "…"
            return text
        first = text[:break_pos]
        second = text[break_pos:]

    # Truncate second line if it still exceeds budget.
    if len(second) > max_chars_per_line:
        if not allow_truncate:
            return f"{first}\n{second}"
        cut = max_chars_per_line - 1
        while cut > 0 and not _is_safe_break(second, cut):
            cut -= 1
        if cut <= 0:
            cut = max_chars_per_line - 1
        second = second[:cut] + "…"

    return f"{first}\n{second}"


# ---------------------------------------------------------------------------
# Word-level segment splitting
# ---------------------------------------------------------------------------

# Punctuation marks that are natural segment-break points.
_WORD_BREAK_PUNCTUATION = set("，。！？、；：,.!?;:")

# Minimum characters for a trailing sub-segment.  If splitting would create
# a trailing piece shorter than this, we instead absorb those characters
# into the preceding segment (slightly exceeding the budget).
_MIN_TRAILING_CHARS = 4


def _maybe_absorb_orphan(
    head_batch: list[dict],
    rest_batch: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Return batches after absorbing a too-short trailing batch into the head."""
    remaining = list(rest_batch)
    if sum(len(w["text"]) for w in remaining) >= _MIN_TRAILING_CHARS:
        return list(head_batch), remaining

    absorbed = []
    while remaining and sum(len(w["text"]) for w in remaining) < _MIN_TRAILING_CHARS:
        absorbed.append(remaining.pop(0))
    if not remaining:
        return list(head_batch) + absorbed, []
    return list(head_batch) + absorbed, remaining


def _last_word_break_punct_index(words: list[dict]) -> int | None:
    """Return the last punctuation index in a word batch, if any."""
    last_idx = None
    for idx, word in enumerate(words):
        text = word.get("text", "")
        if len(text) == 1 and text in _WORD_BREAK_PUNCTUATION:
            last_idx = idx
    return last_idx


def split_segments(
    segments: list[dict],
    max_chars_per_segment: int = MAX_CHARS_PER_SEGMENT,
    max_chars_per_line: int = MAX_CHARS_PER_LINE,
) -> list[dict]:
    """Split long segments into sub-segments at semantic boundaries.

    Each resulting sub-segment is at most *max_chars_per_segment* characters.
    Word-level timestamps are used when available; character-count interpolation
    is the fallback.

    Every result has ``break_lines`` applied so the text carries ``\\n``
    for multi-line display rendering.

    Segments already within the limit are returned with filler compression
    and line-breaking applied.
    """
    result: list[dict] = []
    for seg in segments:
        words = seg.get("words")
        text = seg.get("text", "")
        if not text.strip():
            continue

        # Always compress fillers first.
        text = text.replace("\n", "")
        compressed = _compress_fillers(text)
        if not compressed:
            compressed = text

        if len(compressed) <= max_chars_per_segment:
            # Fits in one subtitle card — just apply line-breaking.
            entry = dict(seg)
            entry["text"] = break_lines(compressed, max_chars_per_line)
            result.append(entry)
            continue

        # Need to split into multiple sub-segments.
        if words:
            sub = _split_segment_by_words(
                seg, words, compressed, max_chars_per_segment, max_chars_per_line
            )
        else:
            sub = _split_segment_by_chars(
                seg, compressed, max_chars_per_segment, max_chars_per_line
            )
        result.extend(sub)

    return result


def _split_segment_by_words(
    seg: dict,
    words: list[dict],
    compressed_text: str,
    max_chars: int,
    max_line_chars: int,
) -> list[dict]:
    """Split a segment into sub-segments at word/punctuation boundaries.

    Accumulates words until *max_chars* would be exceeded, then emits a
    sub-segment.  When breaking, prefers splitting after a punctuation mark;
    otherwise splits at a semantic boundary or hard break.

    **Orphan prevention**: if the trailing batch after a split has fewer
    than *_MIN_TRAILING_CHARS* characters, we instead absorb the first word(s)
    of the trailing batch into the current segment (slightly exceeding the
    budget) to avoid creating a tiny, unreadable trailing segment.
    """
    sub_segments: list[dict] = []
    batch: list[dict] = []
    batch_chars = 0
    last_punct_idx: int | None = None

    for w in words:
        w_text = w.get("text", "")
        w_chars = len(w_text)
        is_punct = w_chars == 1 and w_text in _WORD_BREAK_PUNCTUATION

        if batch and batch_chars + w_chars > max_chars:
            if last_punct_idx is not None and last_punct_idx >= 0:
                # Break after the last punctuation in the current batch.
                punct_batch = batch[: last_punct_idx + 1]
                rest = batch[last_punct_idx + 1:] + [w]
                emit_batch, next_batch = _maybe_absorb_orphan(punct_batch, rest)
            else:
                if batch_chars < _MIN_TRAILING_CHARS:
                    batch.append(w)
                    batch_chars += w_chars
                    if is_punct:
                        last_punct_idx = len(batch) - 1
                    continue
                emit_batch, next_batch = _maybe_absorb_orphan(batch, [w])

            sub_segments.append(_make_sub_segment(emit_batch, seg, max_line_chars))
            batch = list(next_batch)
            batch_chars = sum(len(x["text"]) for x in batch)
            last_punct_idx = _last_word_break_punct_index(batch)
            continue
        else:
            batch.append(w)
            batch_chars += w_chars

        if is_punct:
            last_punct_idx = len(batch) - 1

    if batch:
        sub_segments.append(_make_sub_segment(batch, seg, max_line_chars))

    return sub_segments


def _split_segment_by_chars(
    seg: dict,
    text: str,
    max_chars: int,
    max_line_chars: int,
) -> list[dict]:
    """Fallback: split a segment by character count when no word data exists.

    Splits at semantic boundaries within each *max_chars* window when possible.
    Timestamps are interpolated proportionally from the parent segment.
    """
    chars = list(text)
    duration = seg["end_time_s"] - seg["start_time_s"]
    if duration <= 0:
        return [seg]

    sub_segments: list[dict] = []
    pos = 0
    total = len(chars)

    while pos < total:
        budget = min(max_chars, total - pos)
        window = "".join(chars[pos : pos + budget])

        # Try to find a better split point within the window.
        split_offset = budget
        if pos + budget < total:  # not the last chunk
            # Try break points from best to worst
            bp = _find_best_break(window, budget)
            if bp is not None and bp >= _MIN_TRAILING_CHARS:
                # Check that the remainder isn't orphaned
                remainder = total - (pos + bp)
                if remainder >= _MIN_TRAILING_CHARS or remainder == 0:
                    split_offset = bp

        chunk = chars[pos : pos + split_offset]
        chunk_text = "".join(chunk)
        ratio_start = pos / total
        ratio_end = min((pos + len(chunk)) / total, 1.0)
        entry: dict = {
            "start_time_s": round(seg["start_time_s"] + duration * ratio_start, 3),
            "end_time_s": round(seg["start_time_s"] + duration * ratio_end, 3),
            "text": break_lines(chunk_text, max_line_chars),
            "words": None,
        }
        if "confidence" in seg:
            entry["confidence"] = seg["confidence"]
        sub_segments.append(entry)
        pos += split_offset

    return sub_segments


def _make_sub_segment(
    words: list[dict], parent_seg: dict, max_line_chars: int = MAX_CHARS_PER_LINE
) -> dict:
    """Build a segment dict from a list of word dicts, with line-breaking."""
    text = "".join(w["text"] for w in words)
    entry: dict = {
        "start_time_s": words[0]["start_time_s"],
        "end_time_s": words[-1]["end_time_s"],
        "text": break_lines(text, max_line_chars, allow_truncate=False),
        "words": words,
    }
    if "confidence" in parent_seg:
        entry["confidence"] = parent_seg["confidence"]
    return entry
