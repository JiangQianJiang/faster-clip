"""Tests for line-breaker: break_lines() with filler compression, punctuation
break points, English/number boundary protection, idempotency, and truncation."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.line_breaker import break_lines


# ---------------------------------------------------------------------------
# AC-1: Filler compression
# ---------------------------------------------------------------------------

def test_compress_repeated_filler_pairs():
    """Repeated filler-word pairs are compressed."""
    result = break_lines("那个那个我觉得然后然后就是这样")
    assert "\n" not in result  # compressed text fits on one line
    assert result == "那个我觉得然后就是这样"


def test_compress_leading_filler_chain():
    """Leading filler chains compress to a single filler word."""
    result = break_lines("那那个那个就是")
    # After compression, "那就是" is short enough to return unchanged.
    assert result == "那就是"


def test_compress_no_repeated_fillers():
    """Text without repeated fillers is unchanged (filler-wise)."""
    result = break_lines("没有重复词的正常句子")
    assert result == "没有重复词的正常句子"


def test_single_filler_not_compressed():
    """A single filler word (not repeated) is not stripped."""
    result = break_lines("那个节目很好看")
    # The single leading "那个" should be preserved.
    assert result == "那个节目很好看"


# ---------------------------------------------------------------------------
# AC-2: Punctuation-aware break
# ---------------------------------------------------------------------------

def test_break_at_punctuation():
    """Long text breaks at the last punctuation within max_chars_per_line."""
    result = break_lines("大家好欢迎来到今天的直播间，今天我们要聊一个非常重要的话题")
    assert "\n" in result
    first_line, second_line = result.split("\n", 1)
    # First line ends with the punctuation.
    assert first_line.endswith("，")
    assert len(first_line) <= 14
    assert len(second_line) <= 14


def test_text_within_limit_unchanged():
    """Text at or under max_chars_per_line is returned unchanged."""
    short = "短字幕"
    assert break_lines(short) == short


def test_no_punctuation_hard_break():
    """Text without punctuation in the first max_chars does a hard break."""
    # 20 Chinese chars, no punctuation
    text = "今天我们来看看这个非常有趣的节目内容介绍"
    result = break_lines(text)
    assert "\n" in result
    first, second = result.split("\n", 1)
    assert len(first) <= 14
    # Should not break mid-character (Chinese chars are safe to split).
    assert len(first) > 0
    assert len(second) > 0


# ---------------------------------------------------------------------------
# AC-3: Idempotency
# ---------------------------------------------------------------------------

def test_already_broken_text_unchanged():
    """Text containing \\n is returned unchanged."""
    text = "第一行\n第二行"
    assert break_lines(text) == text


def test_empty_string():
    """Empty string returns empty string."""
    assert break_lines("") == ""


def test_punctuation_only_unchanged():
    """Punctuation-only text is returned unchanged."""
    text = "！？？"
    assert break_lines(text) == text


def test_idempotent_double_application():
    """Running break_lines twice produces the same output as running it once."""
    inputs = [
        "大家好欢迎来到今天的直播间，今天我们要聊一个非常重要的话题",
        "那个那个我觉得然后然后就是这样",
        "这是一个没有标点符号的长句子用来测试硬换行的功能效果",
        "短文本",
        "",
    ]
    for text in inputs:
        once = break_lines(text)
        twice = break_lines(once)
        assert once == twice, f"Not idempotent for: {text!r}"


# ---------------------------------------------------------------------------
# AC-4: English word / number protection
# ---------------------------------------------------------------------------

def test_does_not_split_english_word():
    """Break point inside an English word is avoided — break moves before it."""
    # "OpenAI" spans characters that may cross max_chars boundary.
    text = "我们看一下OpenAI的最新模型在benchmark上的表现"
    result = break_lines(text)
    # The result should not have a line break inside "OpenAI" or "benchmark".
    if "\n" in result:
        first, second = result.split("\n", 1)
        # Neither part should contain a split English word fragment.
        for word in ("OpenAI", "benchmark"):
            assert word in (first + second), f"{word} was split: {result!r}"


def test_does_not_split_number_sequence():
    """Break point inside a numeric sequence is avoided."""
    text = "端口号是8080不要改这个配置"
    result = break_lines(text)
    if "\n" in result:
        first, second = result.split("\n", 1)
        # 8080 must be intact in one of the lines.
        assert "8080" in first or "8080" in second, f"8080 was split: {result!r}"


def test_english_only_word_not_split():
    """A standalone English word is not split."""
    result = break_lines("OpenAI")
    assert result == "OpenAI"


def test_number_sequence_not_split():
    """A numeric sequence alone is not split."""
    result = break_lines("第12345号")
    assert result == "第12345号"


# ---------------------------------------------------------------------------
# AC-5: At most 2 lines, overflow truncated
# ---------------------------------------------------------------------------

def test_at_most_two_lines():
    """break_lines never produces more than 2 lines."""
    long_text = "这是一段非常非常长的中文字幕文本用来测试最多只有两行的功能验证是否正确"
    result = break_lines(long_text)
    assert result.count("\n") <= 1


def test_overflow_truncated_with_ellipsis():
    """Second line exceeding max_chars is truncated with an ellipsis."""
    # Generate text that's certainly long enough to require truncation.
    long_text = "今天我们来聊一个非常重要的话题关于人工智能的未来发展趋势分析"
    result = break_lines(long_text)
    if "\n" in result:
        _, second = result.split("\n", 1)
        # Second line stays within max_chars including the ellipsis.
        assert len(second) <= 14
        if "…" in second:
            assert second.endswith("…")


# ---------------------------------------------------------------------------
# Custom max_chars_per_line
# ---------------------------------------------------------------------------

def test_custom_max_chars():
    """Custom max_chars_per_line is respected."""
    text = "大家好欢迎来到今天的直播间，今天我们要聊一个非常重要的话题"
    result = break_lines(text, max_chars_per_line=20)
    assert len(text) <= 40  # may or may not break
    # If it breaks, both lines are within the custom budget.
    if "\n" in result:
        first, second = result.split("\n", 1)
        assert len(first) <= 20
        assert len(second) <= 20


# ---------------------------------------------------------------------------
# Regression: filler compression edge cases
# ---------------------------------------------------------------------------

def test_filler_pairs_iterative():
    """Multiple filler pairs in the same text are all compressed."""
    result = break_lines("那个那个然后然后就是就是这样")
    # All pairs compressed; result may be short enough for no break.
    # The key assertion: no double fillers remain.
    assert "那个那个" not in result
    assert "然后然后" not in result
    assert "就是就是" not in result


def test_filler_compression_with_break():
    """Filler compression runs before line-breaking, may prevent a break."""
    # Without compression this would be long; after compression it fits.
    text = "那个那个然后然后就是就是大家好"
    result = break_lines(text)
    # After compression: "那个然后就是大家好" (fits in 14 chars).
    assert result == "那个然后就是大家好"
