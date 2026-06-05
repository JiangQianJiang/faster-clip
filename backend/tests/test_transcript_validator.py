"""Tests for shared transcript validator."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.transcript_validator import (
    MAX_SEGMENTS,
    MAX_TEXT_LENGTH,
    normalize_transcript,
    validate_segment,
    validate_transcript,
    validate_transcript_strict,
)


class TestValidateSegment:
    def test_valid_segment(self):
        seg = {"start_time_s": 1.0, "end_time_s": 3.5, "text": "Hello"}
        ok, err = validate_segment(seg)
        assert ok
        assert err == ""

    def test_non_dict_input(self):
        ok, err = validate_segment("not a dict")
        assert not ok
        assert "dict" in err

    def test_missing_fields(self):
        ok, err = validate_segment({"start_time_s": 1.0})
        assert not ok
        assert "missing required fields" in err

    def test_non_numeric_timestamps(self):
        seg = {"start_time_s": "abc", "end_time_s": "def", "text": "x"}
        ok, err = validate_segment(seg)
        assert not ok
        assert "numbers" in err

    def test_negative_start_time(self):
        seg = {"start_time_s": -1.0, "end_time_s": 3.0, "text": "x"}
        ok, err = validate_segment(seg)
        assert not ok
        assert "non-negative" in err

    def test_end_not_greater_than_start(self):
        seg = {"start_time_s": 5.0, "end_time_s": 3.0, "text": "x"}
        ok, err = validate_segment(seg)
        assert not ok
        assert "greater than" in err

    def test_end_equal_to_start(self):
        seg = {"start_time_s": 5.0, "end_time_s": 5.0, "text": "x"}
        ok, err = validate_segment(seg)
        assert not ok
        assert "greater than" in err

    def test_empty_text_after_strip(self):
        seg = {"start_time_s": 1.0, "end_time_s": 3.0, "text": "   "}
        ok, err = validate_segment(seg)
        assert not ok
        assert "empty" in err

    def test_empty_string_text(self):
        seg = {"start_time_s": 1.0, "end_time_s": 3.0, "text": ""}
        ok, err = validate_segment(seg)
        assert not ok
        assert "empty" in err

    def test_text_not_string(self):
        seg = {"start_time_s": 1.0, "end_time_s": 3.0, "text": 123}
        ok, err = validate_segment(seg)
        assert not ok
        assert "string" in err

    def test_text_exceeds_max_length(self):
        seg = {
            "start_time_s": 1.0,
            "end_time_s": 3.0,
            "text": "x" * (MAX_TEXT_LENGTH + 1),
        }
        ok, err = validate_segment(seg)
        assert not ok
        assert str(MAX_TEXT_LENGTH) in err

    def test_text_at_max_length(self):
        seg = {
            "start_time_s": 1.0,
            "end_time_s": 3.0,
            "text": "x" * MAX_TEXT_LENGTH,
        }
        ok, err = validate_segment(seg)
        assert ok

    def test_nan_timestamp_rejected(self):
        seg = {"start_time_s": float("nan"), "end_time_s": 3.0, "text": "x"}
        ok, err = validate_segment(seg)
        assert not ok
        assert "finite" in err

    def test_infinity_timestamp_rejected(self):
        seg = {"start_time_s": 1.0, "end_time_s": float("inf"), "text": "x"}
        ok, err = validate_segment(seg)
        assert not ok
        assert "finite" in err

    def test_zero_start_time_valid(self):
        seg = {"start_time_s": 0.0, "end_time_s": 1.0, "text": "Start at zero"}
        ok, err = validate_segment(seg)
        assert ok


class TestValidateTranscript:
    def test_non_list_input(self):
        segs, warnings = validate_transcript("not a list")
        assert segs == []
        assert len(warnings) == 1

    def test_non_dict_entries_filtered_with_warning(self):
        """null and scalar entries produce warnings instead of crashing."""
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "Valid"},
            None,
            "scalar",
            {"start_time_s": 5.0, "end_time_s": 8.0, "text": "Also valid"},
        ]
        valid, warnings = validate_transcript(segs)
        assert len(valid) == 2
        assert len(warnings) == 2
        assert any("dict" in w for w in warnings)

    def test_mixed_valid_invalid(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "Valid"},
            {"start_time_s": -5.0, "end_time_s": 3.0, "text": "Bad start"},
            {"start_time_s": 5.0, "end_time_s": 8.0, "text": "Also valid"},
            {"start_time_s": 1.0, "end_time_s": 2.0, "text": "   "},
        ]
        valid, warnings = validate_transcript(segs)
        assert len(valid) == 2
        assert len(warnings) == 2
        assert any("negative" in w for w in warnings)
        assert any("empty" in w for w in warnings)

    def test_all_invalid(self):
        segs = [
            {"start_time_s": -1.0, "end_time_s": -2.0, "text": ""},
            {"start_time_s": 5.0, "end_time_s": 3.0, "text": "  "},
        ]
        valid, warnings = validate_transcript(segs)
        assert valid == []
        assert len(warnings) == 2

    def test_warnings_use_line_numbers(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 2.0, "text": "ok"},
            {"start_time_s": -1.0, "end_time_s": 2.0, "text": "bad"},
            {"start_time_s": 3.0, "end_time_s": 4.0, "text": "ok"},
        ]
        valid, warnings = validate_transcript(segs)
        assert "line 2" in warnings[0]

    def test_normalizes_timestamps(self):
        segs = [
            {"start_time_s": 1.234567, "end_time_s": 3.987654, "text": "test"},
        ]
        valid, warnings = validate_transcript(segs)
        assert valid[0]["start_time_s"] == 1.235
        assert valid[0]["end_time_s"] == 3.988

    def test_strips_text(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": " hello "},
        ]
        valid, warnings = validate_transcript(segs)
        assert valid[0]["text"] == "hello"

    def test_sorts_by_start_time(self):
        segs = [
            {"start_time_s": 10.0, "end_time_s": 11.0, "text": "third"},
            {"start_time_s": 1.0, "end_time_s": 2.0, "text": "first"},
            {"start_time_s": 5.0, "end_time_s": 6.0, "text": "second"},
        ]
        valid, warnings = validate_transcript(segs)
        assert valid[0]["start_time_s"] == 1.0
        assert valid[1]["start_time_s"] == 5.0
        assert valid[2]["start_time_s"] == 10.0

    def test_max_segments_accepted(self):
        segs = [
            {"start_time_s": float(i), "end_time_s": float(i + 1), "text": f"s{i}"}
            for i in range(MAX_SEGMENTS)
        ]
        valid, warnings = validate_transcript(segs)
        assert len(valid) == MAX_SEGMENTS

    def test_exceeds_max_segments_not_truncated(self):
        """validate_transcript returns all valid segments; caller checks limit."""
        segs = [
            {"start_time_s": float(i), "end_time_s": float(i + 1), "text": f"s{i}"}
            for i in range(MAX_SEGMENTS + 100)
        ]
        valid, warnings = validate_transcript(segs)
        assert len(valid) == MAX_SEGMENTS + 100


class TestValidateTranscriptStrict:
    def test_valid_transcript(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "First"},
            {"start_time_s": 5.0, "end_time_s": 8.0, "text": "Second"},
        ]
        err = validate_transcript_strict(segs)
        assert err is None

    def test_non_list_input(self):
        err = validate_transcript_strict("not a list")
        assert err is not None
        assert "array" in err

    def test_empty_list(self):
        err = validate_transcript_strict([])
        assert err is not None
        assert "empty" in err

    def test_invalid_segment(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": ""},
        ]
        err = validate_transcript_strict(segs)
        assert err is not None
        assert "index 0" in err

    def test_negative_timestamp(self):
        segs = [
            {"start_time_s": -1.0, "end_time_s": 3.0, "text": "x"},
        ]
        err = validate_transcript_strict(segs)
        assert err is not None
        assert "non-negative" in err

    def test_timing_violation(self):
        segs = [
            {"start_time_s": 5.0, "end_time_s": 3.0, "text": "x"},
        ]
        err = validate_transcript_strict(segs)
        assert err is not None

    def test_unsorted_segments_are_sorted_in_place(self):
        segs = [
            {"start_time_s": 10.0, "end_time_s": 11.0, "text": "Out of order"},
            {"start_time_s": 1.0, "end_time_s": 2.0, "text": "Should be first"},
        ]
        err = validate_transcript_strict(segs)
        assert err is None
        assert [s["text"] for s in segs] == ["Should be first", "Out of order"]

    def test_empty_text(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "   "},
        ]
        err = validate_transcript_strict(segs)
        assert err is not None

    def test_text_too_long(self):
        segs = [
            {
                "start_time_s": 1.0,
                "end_time_s": 3.0,
                "text": "x" * (MAX_TEXT_LENGTH + 1),
            },
        ]
        err = validate_transcript_strict(segs)
        assert err is not None
        assert "text" in err.lower()

    def test_exceeds_max_segments(self):
        segs = [
            {"start_time_s": float(i), "end_time_s": float(i + 1), "text": f"s{i}"}
            for i in range(MAX_SEGMENTS + 1)
        ]
        err = validate_transcript_strict(segs)
        assert err is not None
        assert str(MAX_SEGMENTS) in err

    def test_normalizes_in_place(self):
        segs = [
            {"start_time_s": 1.234567, "end_time_s": 3.987654, "text": " hello "},
        ]
        err = validate_transcript_strict(segs)
        assert err is None
        assert segs[0]["start_time_s"] == 1.235
        assert segs[0]["end_time_s"] == 3.988
        assert segs[0]["text"] == "hello"

    def test_unicode_text_preserved(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "你好世界 🎉"},
        ]
        err = validate_transcript_strict(segs)
        assert err is None
        assert segs[0]["text"] == "你好世界 🎉"


class TestNormalizeTranscript:
    def test_rounds_timestamps(self):
        segs = [
            {"start_time_s": 1.234567, "end_time_s": 3.987654, "text": "test"},
        ]
        result = normalize_transcript(segs)
        assert result[0]["start_time_s"] == 1.235
        assert result[0]["end_time_s"] == 3.988

    def test_strips_text(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": " hello "},
        ]
        result = normalize_transcript(segs)
        assert result[0]["text"] == "hello"

    def test_sorts_by_start_time(self):
        segs = [
            {"start_time_s": 10.0, "end_time_s": 11.0, "text": "third"},
            {"start_time_s": 1.0, "end_time_s": 2.0, "text": "first"},
            {"start_time_s": 5.0, "end_time_s": 6.0, "text": "second"},
        ]
        result = normalize_transcript(segs)
        assert [s["start_time_s"] for s in result] == [1.0, 5.0, 10.0]

    def test_returns_new_list(self):
        segs = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "test"},
        ]
        result = normalize_transcript(segs)
        assert result is not segs
