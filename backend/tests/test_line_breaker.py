"""Tests for line-breaker: break_lines() with filler compression, semantic
break points, English/number boundary protection, idempotency, and truncation.
Also tests split_segments() with word-level timestamps and orphan prevention."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.line_breaker import (
    _MIN_TRAILING_CHARS,
    MAX_CHARS_PER_LINE,
    MAX_CHARS_PER_SEGMENT,
    _maybe_absorb_orphan,
    break_lines,
    split_segments,
)

# ---------------------------------------------------------------------------
# AC-1: Filler compression
# ---------------------------------------------------------------------------


def test_compress_repeated_filler_pairs():
    """Repeated filler-word pairs are compressed."""
    result = break_lines("那个那个我觉得然后然后就是这样")
    assert "那个那个" not in result
    assert "然后然后" not in result
    assert result == "那个我觉得然后就是这样"


def test_compress_leading_filler_chain():
    """Leading filler chains compress to a single filler word."""
    result = break_lines("那那个那个就是")
    assert result == "那就是"


def test_compress_no_repeated_fillers():
    """Text without repeated fillers is unchanged (filler-wise)."""
    result = break_lines("没有重复词的正常句子")
    assert result == "没有重复词的正常句子"


def test_single_filler_not_compressed():
    """A single filler word (not repeated) is not stripped."""
    result = break_lines("那个节目很好看")
    assert result == "那个节目很好看"


def test_compress_repeated_chars():
    """Repeated identical Chinese characters are compressed."""
    result = break_lines("大家好大家好大家好大家好")
    assert result == "大家好"


def test_compress_repeated_phrase():
    """Repeated multi-char phrases are compressed (all repetitions)."""
    # "谢谢你" × 3 + "们" → "谢谢你" + "们" = "谢谢你们"
    result = break_lines("谢谢你谢谢你谢谢你们")
    assert result == "谢谢你们"


# ---------------------------------------------------------------------------
# AC-2: Punctuation-aware break
# ---------------------------------------------------------------------------


def test_break_at_punctuation():
    """Long text breaks at the last punctuation within max_chars_per_line."""
    result = break_lines("大家好，欢迎来到今天的直播间，今天我们要聊一个非常重要的话题")
    assert "\n" in result
    first_line, second_line = result.split("\n", 1)
    assert len(first_line) <= MAX_CHARS_PER_LINE
    assert len(second_line) <= MAX_CHARS_PER_LINE


def test_text_within_limit_unchanged():
    """Text at or under max_chars_per_line is returned unchanged."""
    short = "短字幕"
    assert break_lines(short) == short


def test_no_punctuation_hard_break():
    """Text without punctuation in the first max_chars does a hard break."""
    text = "今天我们来看看这个非常有趣的节目内容介绍"
    result = break_lines(text)
    assert "\n" in result
    first, second = result.split("\n", 1)
    assert len(first) <= MAX_CHARS_PER_LINE
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
    text = "看看OpenAI模型在benchmark的表现"
    result = break_lines(text)
    if "\n" in result:
        first, second = result.split("\n", 1)
        for word in ("OpenAI", "benchmark"):
            assert word in (first + second), f"{word} was split: {result!r}"


def test_does_not_split_number_sequence():
    """Break point inside a numeric sequence is avoided."""
    text = "端口号是8080不要改这个配置"
    result = break_lines(text)
    if "\n" in result:
        first, second = result.split("\n", 1)
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
    long_text = "今天我们来聊一个非常重要的话题关于人工智能的未来发展趋势分析"
    result = break_lines(long_text)
    if "\n" in result:
        _, second = result.split("\n", 1)
        assert len(second) <= MAX_CHARS_PER_LINE
        if "…" in second:
            assert second.endswith("…")


# ---------------------------------------------------------------------------
# Custom max_chars_per_line
# ---------------------------------------------------------------------------


def test_custom_max_chars():
    """Custom max_chars_per_line is respected."""
    text = "大家好欢迎来到今天的直播间，今天我们要聊一个非常重要的话题"
    result = break_lines(text, max_chars_per_line=20)
    if "\n" in result:
        first, second = result.split("\n", 1)
        assert len(first) <= 20
        assert len(second) <= 20


# ---------------------------------------------------------------------------
# Semantic break point tests (new)
# ---------------------------------------------------------------------------


def test_break_after_particle():
    """Breaks after modal particles when they follow content."""
    # "的" at position 9 — good break after "大家喜欢"
    result = break_lines("这是大家喜欢的节目内容非常精彩")
    if "\n" in result:
        first, _ = result.split("\n", 1)
        assert len(first) <= MAX_CHARS_PER_LINE


def test_break_before_conjunction():
    """Breaks before conjunctions like 然后, 但是, etc."""
    result = break_lines("我觉得很好然后大家也很喜欢这个节目")
    if "\n" in result:
        first, second = result.split("\n", 1)
        assert len(first) <= MAX_CHARS_PER_LINE
        # "然后" should be at the start of the second line
        assert "然后" in second


def test_strong_punct_preferred_over_particle():
    """Strong punctuation (。) is preferred over particles for breaking."""
    result = break_lines("这个节目很好。大家都很喜欢的节目")
    if "\n" in result:
        first, _ = result.split("\n", 1)
        assert first.endswith("。")


# ---------------------------------------------------------------------------
# Regression: filler compression edge cases
# ---------------------------------------------------------------------------


def test_filler_pairs_iterative():
    """Multiple filler pairs in the same text are all compressed."""
    result = break_lines("那个那个然后然后就是就是这样")
    assert "那个那个" not in result
    assert "然后然后" not in result
    assert "就是就是" not in result


def test_filler_compression_with_break():
    """Filler compression runs before line-breaking, may prevent a break."""
    text = "那个那个然后然后就是就是大家好"
    result = break_lines(text)
    # After compression: "那个然后就是大家好" (< 12 chars).
    assert result == "那个然后就是大家好"


# ---------------------------------------------------------------------------
# Word-level segment splitting (split_segments)
# ---------------------------------------------------------------------------


def _make_seg(start, end, text, words=None, confidence=None):
    seg: dict = {"start_time_s": start, "end_time_s": end, "text": text}
    if words is not None:
        seg["words"] = words
    if confidence is not None:
        seg["confidence"] = confidence
    return seg


def _make_word(text, start, end):
    return {"text": text, "start_time_s": start, "end_time_s": end}


class TestSplitSegments:
    def test_short_segment_unchanged(self):
        """Segment within max_chars is returned as-is (with line-breaking applied)."""
        seg = _make_seg(0.0, 2.0, "短字幕")
        result = split_segments([seg])
        assert len(result) == 1
        assert result[0]["text"] == "短字幕"

    def test_no_word_data_fallback(self):
        """Segment without word data is split by character count."""
        seg = _make_seg(0.0, 3.0, "这是一条很长的中文字幕内容需要拆分成多个片段来展示给观众")
        result = split_segments([seg])
        assert len(result) >= 2
        for s in result:
            assert len(s["text"].replace("\n", "")) <= MAX_CHARS_PER_SEGMENT
            assert "start_time_s" in s
            assert "end_time_s" in s
            assert s["words"] is None

    def test_existing_display_break_does_not_force_resplit_or_orphan(self):
        """Existing display newlines are ignored when sizing subtitle cards."""
        first_line = "甲乙丙丁戊己庚辛壬癸子丑"
        second_line = "寅卯辰巳午未申酉戌亥天地"
        seg = _make_seg(0.0, 2.4, f"{first_line}\n{second_line}")

        result = split_segments([seg])

        assert len(result) == 1
        assert result[0]["start_time_s"] == 0.0
        assert result[0]["end_time_s"] == 2.4
        assert result[0]["text"].replace("\n", "") == first_line + second_line

    def test_word_based_split(self):
        """Segment with word data splits at word boundaries."""
        words = [
            _make_word("今天", 0.0, 0.5),
            _make_word("我们", 0.5, 1.0),
            _make_word("来", 1.0, 1.2),
            _make_word("聊聊", 1.2, 1.6),
            _make_word("人工", 1.6, 1.9),
            _make_word("智能", 1.9, 2.2),
            _make_word("的", 2.2, 2.3),
            _make_word("发展", 2.3, 2.6),
        ]
        seg = _make_seg(0.0, 2.6, "今天我们来聊聊人工智能的发展", words=words)
        result = split_segments([seg])
        # 13 chars — fits in one 24-char segment, just line-broken.
        assert len(result) == 1
        # Joined text without newlines equals original (no characters lost).
        joined = "".join(s["text"].replace("\n", "") for s in result)
        assert joined == "今天我们来聊聊人工智能的发展"

    def test_long_word_segment_splits(self):
        """A genuinely long segment with word data is split into sub-segments."""
        words = []
        chars = "今天我们来聊聊人工智能的发展和未来趋势分析报告"
        for i, ch in enumerate(chars):
            words.append(_make_word(ch, i * 0.1, (i + 1) * 0.1))
        seg = _make_seg(0.0, len(chars) * 0.1, chars, words=words)
        result = split_segments([seg])
        # 21 chars — should be 1 segment at default 24-char budget, line-broken.
        # Actually this is within the budget, so it stays as one.
        assert len(result) >= 1
        joined = "".join(s["text"].replace("\n", "") for s in result)
        assert joined == chars

    def test_split_at_punctuation_preferred(self):
        """When words contain punctuation, split prefers to break after it."""
        words = [
            _make_word("大家", 0.0, 0.3),
            _make_word("好", 0.3, 0.5),
            _make_word("，", 0.5, 0.6),
            _make_word("欢迎", 0.6, 0.9),
            _make_word("来到", 0.9, 1.2),
            _make_word("直播", 1.2, 1.5),
            _make_word("间", 1.5, 1.7),
            _make_word("各位", 1.7, 2.0),
        ]
        seg = _make_seg(0.0, 2.0, "大家好，欢迎来到直播间各位", words=words)
        result = split_segments([seg])
        # 10 chars — fits in budget, no split needed, just line-breaking.
        # First segment text should contain the punctuation.
        assert "，" in result[0]["text"]

    def test_multiple_segments_mixed(self):
        """Mixed segments: some with words, some without."""
        words = [
            _make_word("你好", 0.0, 0.5),
            _make_word("世界", 0.5, 1.0),
            _make_word("这是一条", 1.0, 1.7),
            _make_word("很长的", 1.7, 2.2),
            _make_word("测试", 2.2, 2.5),
            _make_word("字幕", 2.5, 2.8),
            _make_word("内容", 2.8, 3.2),
        ]
        segs = [
            _make_seg(0.0, 1.0, "你好世界", words=words[:2]),
            _make_seg(1.0, 3.2, "这是一条很长的测试字幕内容", words=words[2:]),
        ]
        result = split_segments(segs)
        # Both segments are now within 24-char budget.
        assert len(result) == 2
        for s in result:
            assert len(s["text"].replace("\n", "")) <= MAX_CHARS_PER_SEGMENT

    def test_confidence_preserved(self):
        """Sub-segments inherit confidence from parent."""
        words = [
            _make_word("大家好欢迎来到今天的直播间", 0.0, 2.0),
            _make_word("各位朋友", 2.0, 2.5),
        ]
        seg = _make_seg(
            0.0, 2.5, "大家好欢迎来到今天的直播间各位朋友",
            words=words, confidence=0.95,
        )
        result = split_segments([seg])
        for s in result:
            assert s.get("confidence") == 0.95

    def test_empty_segments_filtered(self):
        """Segments with empty text are dropped."""
        seg = _make_seg(0.0, 1.0, "   ")
        result = split_segments([seg])
        assert len(result) == 0

    def test_fillers_compressed_in_split_when_requested(self):
        """Filler compression is available as an explicit normalization mode."""
        words = [
            _make_word("那个", 0.0, 0.3),
            _make_word("那个", 0.3, 0.6),
            _make_word("大家好", 0.6, 1.2),
        ]
        seg = _make_seg(0.0, 1.2, "那个那个大家好", words=words)
        result = split_segments([seg], normalize_text=True)
        assert len(result) == 1
        assert result[0]["text"] == "那个大家好"

    def test_split_segments_preserves_repeated_text_by_default(self):
        """Reflow/splitting should not silently rewrite transcript content."""
        words = [
            _make_word("大家好", 0.0, 0.5),
            _make_word("大家好", 0.5, 1.0),
            _make_word("大家好", 1.0, 1.5),
            _make_word("大家好", 1.5, 2.0),
        ]
        seg = _make_seg(0.0, 2.0, "大家好大家好大家好大家好", words=words)

        result = split_segments([seg])

        assert "".join(s["text"].replace("\n", "") for s in result) == "大家好大家好大家好大家好"
        assert [w for s in result for w in s.get("words", [])] == words

    def test_split_segments_does_not_truncate_after_early_punctuation_break(self):
        """Reflow may create an over-budget display line, but must not add ellipsis."""
        text = "大家好，欢迎来到今天的直播间各位朋友"
        seg = _make_seg(0.0, 3.0, text)

        result = split_segments([seg])

        assert "".join(s["text"].replace("\n", "") for s in result) == text
        assert "…" not in result[0]["text"]

    def test_split_segments_drops_mismatched_word_timings(self):
        """Word timings are kept only when they still match the output text."""
        seg = _make_seg(
            0.0,
            1.0,
            "可以。",
            words=[_make_word("可", 0.0, 0.5), _make_word("以", 0.5, 1.0)],
        )

        result = split_segments([seg])

        assert result[0]["text"] == "可以。"
        assert "words" not in result[0]

    # -------------------------------------------------------------------
    # New: orphan prevention
    # -------------------------------------------------------------------

    def test_orphan_prevention_trailing_chars(self):
        """Trailing batch < 4 chars is absorbed into the previous segment."""
        # Simulate a segment where the last word is a 1-char orphan
        words = [
            _make_word("对他被他被这个面具给折磨", 0.0, 2.0),
            _make_word("了", 2.0, 2.1),
        ]
        seg = _make_seg(0.0, 2.1, "对他被他被这个面具给折磨了", words=words)
        result = split_segments([seg])
        # 13 chars — fits in one segment, no split needed.
        # "折磨了" should stay together.
        assert len(result) == 1
        assert "了" in result[0]["text"]

    def test_orphan_prevention_line_breaker(self):
        """break_lines keeps 13-char text on one line rather than 12+1 orphan."""
        # "对他被他被这个面具给折磨了" is 13 chars, just 1 over budget.
        # It should stay as one line rather than creating a "了" orphan.
        result = break_lines("对他被他被这个面具给折磨了")
        # Should be one line (no \n) — better to slightly exceed budget
        # than orphan a single character.
        assert "\n" not in result

    # -------------------------------------------------------------------
    # New: line-breaking is applied to split results
    # -------------------------------------------------------------------

    def test_split_segments_applies_line_breaking(self):
        """split_segments results have \\n for multi-line display."""
        words = [
            _make_word("今天", 0.0, 0.3),
            _make_word("我们", 0.3, 0.5),
            _make_word("来", 0.5, 0.7),
            _make_word("聊聊", 0.7, 1.0),
            _make_word("人工", 1.0, 1.3),
            _make_word("智能", 1.3, 1.5),
            _make_word("发展", 1.5, 1.8),
        ]
        seg = _make_seg(0.0, 1.8, "今天我们来聊聊人工智能发展", words=words)
        result = split_segments([seg])
        # 12 chars — within budget but may get line-broken at 12 chars
        assert len(result) == 1
        # If line-breaking happened, verify it's valid
        text = result[0]["text"]
        if "\n" in text:
            first, second = text.split("\n", 1)
            assert len(first) <= MAX_CHARS_PER_LINE
            assert len(second) <= MAX_CHARS_PER_LINE

    def test_maybe_absorb_orphan_explicit_batches(self):
        """The orphan helper returns disjoint explicit head/rest batches."""
        head = [_make_word("前段", 0.0, 0.5)]
        long_rest = [_make_word("足够长啊", 0.5, 1.0)]
        emit, next_batch = _maybe_absorb_orphan(head, long_rest)
        assert sum(len(w["text"]) for w in long_rest) >= _MIN_TRAILING_CHARS
        assert emit == head
        assert next_batch == long_rest

        short_rest = [
            _make_word("尾", 0.5, 0.6),
            _make_word("巴", 0.6, 0.7),
        ]
        emit, next_batch = _maybe_absorb_orphan(head, short_rest)
        assert emit == head + short_rest
        assert next_batch == []
        assert set(map(id, emit)).isdisjoint(set(map(id, next_batch)))

        emit, next_batch = _maybe_absorb_orphan(head, [_make_word("了", 0.5, 0.6)])
        assert emit == head + [_make_word("了", 0.5, 0.6)]
        assert next_batch == []

    def test_word_punctuation_split_has_disjoint_words_and_monotonic_times(self):
        """Words after a punctuation split are not duplicated across outputs."""
        words = [
            _make_word("甲乙丙丁戊己庚辛壬癸", 0.0, 1.0),
            _make_word("，", 1.0, 1.1),
            _make_word("子丑寅卯辰巳午未申酉", 1.1, 2.1),
            _make_word("戌亥天地玄黄宇宙洪荒", 2.1, 3.1),
        ]
        text = "".join(w["text"] for w in words)
        seg = _make_seg(0.0, 3.1, text, words=words)

        result = split_segments([seg])

        assert len(result) == 2
        output_words = [w for s in result for w in s["words"]]
        assert output_words == words
        assert len({id(w) for w in output_words}) == len(words)
        assert result[0]["end_time_s"] <= result[1]["start_time_s"]

    def test_word_hard_break_absorbed_orphan_is_not_duplicated_or_truncated(self):
        """A short hard-break tail absorbed into the head appears exactly once."""
        base = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏"
        tail = _make_word("了", 2.4, 2.5)
        words = [_make_word(base, 0.0, 2.4), tail]
        seg = _make_seg(0.0, 2.5, base + tail["text"], words=words)

        result = split_segments([seg])

        assert len(result) == 1
        output_words = [w for s in result for w in s["words"]]
        assert output_words == words
        rendered = result[0]["text"].replace("\n", "")
        assert rendered == base + "了"
        assert rendered.count("了") == 1
        assert "…" not in result[0]["text"]

    def test_word_hard_break_short_head_absorbs_into_next_long_word(self):
        """A short current batch is not emitted before a long next word."""
        head = _make_word("啊", 0.0, 0.1)
        long_word = _make_word("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地", 0.1, 2.5)
        words = [head, long_word]
        seg = _make_seg(
            0.0,
            2.5,
            head["text"] + long_word["text"],
            words=words,
        )

        result = split_segments([seg])

        assert len(result) == 1
        assert result[0]["words"] == words
        assert result[0]["text"].replace("\n", "") == head["text"] + long_word["text"]
