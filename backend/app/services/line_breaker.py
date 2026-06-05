"""Subtitle line-breaker: post-processes ASR text for readable line wrapping.

Inserts \n line breaks into subtitle text, enforcing a maximum character count
per line, compressing filler words, and protecting English/proper-noun boundaries.
"""

import re

DEFAULT_MAX_CHARS_PER_LINE = 14

_FILLER_PAIRS: list[tuple[str, str]] = [
    ("那个那个", "那个"),
    ("那那个", "那"),  # normalize 那＋那个 filler chain at start
    ("然后然后", "然后"),
    ("就是就是", "就是"),
    ("这个这个", "这个"),
]

# Set of Chinese punctuation marks treated as preferred break points.
_PUNCTUATION = set("。，！？、；：")


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
    """Return True if breaking at *pos* does not split an English word or number."""
    if pos <= 0 or pos >= len(text):
        return False
    left_char = text[pos - 1]
    right_char = text[pos]
    # Don't break inside ASCII letter sequences (English words).
    if (
        left_char.isascii()
        and left_char.isalpha()
        and right_char.isascii()
        and right_char.isalpha()
    ):
        return False
    # Don't break inside digit sequences.
    if left_char.isdigit() and right_char.isdigit():
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

    # Truncate the second line if it still exceeds the budget.
    # The ellipsis replaces the final character so total length stays at
    # max_chars_per_line (e.g. 14 chars including the ellipsis).
    if len(second) > max_chars_per_line:
        second = second[: max_chars_per_line - 1] + "…"

    return f"{first}\n{second}"
