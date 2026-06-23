"""Tests for subtitle parsing in services/subtitle.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.subtitle import (
    UTF8_BOM,
    _parse_srt,
    _parse_vtt,
    parse_subtitle_bytes,
    segments_to_ass,
    segments_to_srt,
    segments_to_vtt,
)


class TestParseSRT:
    def test_standard_srt(self):
        text = "1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n"
        result = _parse_srt(text)
        assert len(result) == 1
        assert result[0]["start_time_s"] == 1.0
        assert result[0]["end_time_s"] == 3.5
        assert result[0]["text"] == "Hello world"

    def test_html_tags_stripped(self):
        text = "1\n00:00:01,000 --> 00:00:03,000\n<b>bold</b> text\n\n"
        result = _parse_srt(text)
        assert result[0]["text"] == "bold text"

    def test_multiline_body(self):
        text = "1\n00:00:01,000 --> 00:00:05,000\nLine one\nLine two\n\n"
        result = _parse_srt(text)
        assert "Line one Line two" in result[0]["text"]

    def test_empty_body_returned_by_parser(self):
        """Parser returns cues even with empty body (validation handles filtering)."""
        text = "1\n00:00:01,000 --> 00:00:03,000\n   \n\n"
        result = _parse_srt(text)
        assert len(result) == 1
        assert result[0]["text"] == ""

    def test_multiple_entries(self):
        text = (
            "1\n00:00:01,000 --> 00:00:03,000\nFirst\n\n"
            "2\n00:00:05,000 --> 00:00:08,500\nSecond\n\n"
        )
        result = _parse_srt(text)
        assert len(result) == 2
        assert result[1]["start_time_s"] == 5.0


class TestParseVTT:
    def test_webvtt_header_stripped(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello\n\n"
        result = _parse_vtt(text)
        assert len(result) == 1
        assert result[0]["text"] == "Hello"

    def test_unindexed_cues(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nFirst cue\n\n00:00:05.000 --> 00:00:08.000\nSecond cue\n\n"
        result = _parse_vtt(text)
        assert len(result) == 2

    def test_cue_with_id(self):
        text = "WEBVTT\n\ncue1\n00:00:01.000 --> 00:00:03.000\nWith ID\n\n"
        result = _parse_vtt(text)
        assert len(result) == 1
        assert result[0]["text"] == "With ID"

    def test_note_block_skipped(self):
        text = "WEBVTT\n\nNOTE this is a comment\n\n00:00:01.000 --> 00:00:03.000\nReal cue\n\n"
        result = _parse_vtt(text)
        assert len(result) == 1

    def test_style_block_skipped(self):
        text = "WEBVTT\n\nSTYLE\n::cue { color: white; }\n\n00:00:01.000 --> 00:00:03.000\nAfter style\n\n"
        result = _parse_vtt(text)
        assert len(result) >= 1
        assert any(c["text"] == "After style" for c in result)

    def test_comma_separator(self):
        text = "WEBVTT\n\n00:00:01,000 --> 00:00:03,000\nComma sep\n\n"
        result = _parse_vtt(text)
        assert len(result) == 1

    def test_with_hours(self):
        text = "WEBVTT\n\n01:00:01.000 --> 01:00:03.000\nWith hours\n\n"
        result = _parse_vtt(text)
        assert len(result) == 1
        assert result[0]["start_time_s"] == 3601.0

    def test_cue_settings_ignored(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000 align:start line:80%\nWith settings\n\n"
        result = _parse_vtt(text)
        assert len(result) == 1
        assert result[0]["text"] == "With settings"

    def test_empty_vtt(self):
        result = _parse_vtt("")
        assert result == []


class TestParseSubtitleBytes:
    """Tests for parse_subtitle_bytes() — task8."""

    def test_srt_parse(self):
        content = b"1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n"
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Hello world"
        assert warnings == []

    def test_vtt_parse(self):
        content = b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello\n\n"
        segments, warnings = parse_subtitle_bytes(content, "vtt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Hello"

    def test_ass_parse(self):
        content = (
            b"[Script Info]\nScriptType: v4.00+\n\n"
            b"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
            b"MarginR, MarginV, Effect, Text\n"
            b"Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "ass")
        assert len(segments) == 1
        assert segments[0]["text"] == "Hello"

    def test_utf8_bom_stripped(self):
        content = UTF8_BOM + b"1\n00:00:01,000 --> 00:00:03,500\nBOM test\n\n"
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 1
        assert segments[0]["text"] == "BOM test"

    def test_unsupported_format(self):
        with pytest.raises(ValueError, match="Unsupported subtitle format"):
            parse_subtitle_bytes(b"", "txt")

    def test_non_utf8_encoding(self):
        content = b"\xff\xfeH\x00e\x00l\x00l\x00o\x00"
        with pytest.raises(ValueError, match="Encoding error"):
            parse_subtitle_bytes(content, "srt")

    def test_empty_parse_result(self):
        content = b"garbage text\n\n"
        with pytest.raises(ValueError, match="No valid segments"):
            parse_subtitle_bytes(content, "srt")

    def test_multiline_text_concatenated(self):
        content = b"1\n00:00:01,000 --> 00:00:05,000\nLine one\nLine two\n\n"
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert segments[0]["text"] == "Line one Line two"

    def test_overlapping_timestamps_accepted(self):
        content = (
            b"1\n00:00:01,000 --> 00:00:05,000\nFirst\n\n"
            b"2\n00:00:03,000 --> 00:00:07,000\nOverlapping\n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 2

    def test_out_of_order_sorted(self):
        content = (
            b"2\n00:00:05,000 --> 00:00:08,000\nSecond\n\n"
            b"1\n00:00:01,000 --> 00:00:03,000\nFirst\n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert segments[0]["start_time_s"] == 1.0
        assert segments[1]["start_time_s"] == 5.0

    def test_negative_timestamp_skipped(self):
        from app.services.transcript_validator import validate_transcript

        # simulate raw parse with a bad segment
        raw = [{"start_time_s": -1.0, "end_time_s": 3.0, "text": "bad"}]
        valid, warnings = validate_transcript(raw)
        assert len(valid) == 0
        assert any("negative" in w for w in warnings)

    def test_end_before_start_skipped(self):
        from app.services.transcript_validator import validate_transcript

        raw = [{"start_time_s": 5.0, "end_time_s": 3.0, "text": "bad"}]
        valid, warnings = validate_transcript(raw)
        assert len(valid) == 0

    def test_empty_text_skipped(self):
        from app.services.transcript_validator import validate_transcript

        raw = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "   "}]
        valid, warnings = validate_transcript(raw)
        assert len(valid) == 0

    def test_bytearray_input(self):
        content = bytearray(b"1\n00:00:01,000 --> 00:00:03,500\nTest\n\n")
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Test"

    def test_empty_text_produces_warning(self):
        """Import with empty-text cue returns warning via validator, not parser."""
        content = (
            b"1\n00:00:01,000 --> 00:00:03,500\nValid\n\n2\n00:00:05,000 --> 00:00:08,000\n   \n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid"
        assert len(warnings) == 1
        assert "empty" in warnings[0]
        # Source line 5 = the cue number line for the second (empty) cue
        assert "line 5" in warnings[0]

    def test_vtt_invalid_timing_produces_warning(self):
        """VTT import with end <= start returns warning via validator."""
        content = (
            b"WEBVTT\n\n"
            b"00:00:05.000 --> 00:00:03.000\nBad timing\n\n"
            b"00:00:06.000 --> 00:00:09.000\nGood\n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "vtt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Good"
        assert len(warnings) == 1
        assert any("greater than" in w for w in warnings)

    def test_vtt_warning_line_before_note_block(self):
        """Warning for empty-body cue before NOTE block uses correct source line."""
        content = (
            b"WEBVTT\n\n"
            b"00:00:01.000 --> 00:00:03.000\n   \n\n"
            b"NOTE after\nline2\n\n"
            b"00:00:04.000 --> 00:00:05.000\nValid\n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "vtt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid"
        assert len(warnings) == 1
        assert "empty" in warnings[0]
        assert "line 3" in warnings[0]

    def test_vtt_warning_line_after_note_block(self):
        """Warning for empty-body cue after NOTE block uses correct source line."""
        content = (
            b"WEBVTT\n\n"
            b"NOTE before\nline2\n\n"
            b"00:00:01.000 --> 00:00:03.000\n   \n\n"
            b"00:00:04.000 --> 00:00:05.000\nValid\n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "vtt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid"
        assert len(warnings) == 1
        assert "empty" in warnings[0]
        assert "line 6" in warnings[0]

    def test_srt_crlf_line_endings(self):
        """SRT file with Windows CRLF line endings parses correctly."""
        content = b"1\r\n00:00:01,000 --> 00:00:03,500\r\nHello world\r\n\r\n"
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Hello world"
        assert segments[0]["start_time_s"] == 1.0
        assert warnings == []

    def test_too_many_parsed_cues_rejected(self):
        """Import with >5000 parsed cues rejected even if some are invalid."""
        from app.services.transcript_validator import MAX_SEGMENTS

        lines = []
        # Generate MAX_SEGMENTS + 1 cues, first one invalid (empty text)
        lines.append("1\n00:00:01,000 --> 00:00:01,500\n\n")
        for i in range(1, MAX_SEGMENTS + 1):
            s = i
            ms = 0
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            ts = f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
            te = f"{h:02d}:{m:02d}:{sec:02d},500"
            lines.append(f"{i + 1}\n{ts} --> {te}\nSegment {i}\n")
        large_srt = "\n".join(lines).encode("utf-8")

        with pytest.raises(ValueError, match="Too many segments"):
            parse_subtitle_bytes(large_srt, "srt")

    def test_max_segments_accepted(self):
        """Import with exactly 5000 parsed cues accepted."""
        from app.services.transcript_validator import MAX_SEGMENTS

        lines = []
        for i in range(MAX_SEGMENTS):
            s = i
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            ts = f"{h:02d}:{m:02d}:{sec:02d},000"
            te = f"{h:02d}:{m:02d}:{sec:02d},500"
            lines.append(f"{i + 1}\n{ts} --> {te}\nSegment {i}\n")
        large_srt = "\n".join(lines).encode("utf-8")

        segments, warnings = parse_subtitle_bytes(large_srt, "srt")
        assert len(segments) == MAX_SEGMENTS

    # ── Negative timestamp import tests ─────────────────────────────────

    def test_srt_negative_start_skipped_with_warning(self):
        """SRT import with negative start timestamp skips segment with warning."""
        content = (
            b"1\n00:00:01,000 --> 00:00:03,500\nValid\n\n"
            b"2\n-00:00:01,000 --> 00:00:03,000\nNegative start\n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid"
        assert len(warnings) == 1
        assert "non-negative" in warnings[0]
        assert "line " in warnings[0]

    def test_vtt_negative_start_skipped_with_warning(self):
        """VTT import with negative start timestamp skips segment with warning."""
        content = (
            b"WEBVTT\n\n"
            b"00:00:01.000 --> 00:00:03.500\nValid\n\n"
            b"-00:00:01.000 --> 00:00:03.000\nNegative start\n\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "vtt")
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid"
        assert len(warnings) == 1
        assert "non-negative" in warnings[0]

    def test_ass_negative_start_skipped_with_warning(self):
        """ASS import with negative start timestamp skips segment with warning."""
        content = (
            b"[Script Info]\nScriptType: v4.00+\n\n"
            b"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
            b"MarginR, MarginV, Effect, Text\n"
            b"Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Valid\n"
            b"Dialogue: 0,-0:00:01.00,0:00:03.00,Default,,0,0,0,,Negative start\n"
        )
        segments, warnings = parse_subtitle_bytes(content, "ass")
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid"
        assert len(warnings) == 1
        assert "non-negative" in warnings[0]

    def test_line_metadata_stripped_from_output(self):
        """_line field is not present in normalized segments."""
        content = b"1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n"
        segments, warnings = parse_subtitle_bytes(content, "srt")
        assert len(segments) == 1
        assert "_line" not in segments[0]


class TestFormatExporters:
    """Tests for segments_to_srt/vtt/ass — task9."""

    def test_srt_export_format(self):
        segments = [
            {"start_time_s": 1.0, "end_time_s": 3.5, "text": "Hello"},
            {"start_time_s": 5.0, "end_time_s": 8.0, "text": "World"},
        ]
        result = segments_to_srt(segments)
        assert "00:00:01,000 --> 00:00:03,500" in result
        assert "00:00:05,000 --> 00:00:08,000" in result
        assert "Hello" in result
        assert "World" in result
        assert "1\n" in result
        assert "2\n" in result

    def test_vtt_export_format(self):
        segments = [
            {"start_time_s": 1.0, "end_time_s": 3.5, "text": "Hello"},
        ]
        result = segments_to_vtt(segments)
        assert result.startswith("WEBVTT\n")
        assert "00:00:01.000 --> 00:00:03.500" in result
        assert "Hello" in result

    def test_vtt_uses_period_separator(self):
        segments = [
            {"start_time_s": 1.5, "end_time_s": 3.75, "text": "Test"},
        ]
        result = segments_to_vtt(segments)
        assert "00:00:01.500 --> 00:00:03.750" in result

    def test_ass_export_format(self):
        segments = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "Hello"},
        ]
        result = segments_to_ass(segments)
        assert "[Script Info]" in result
        assert "[Events]" in result
        assert "Dialogue:" in result
        assert "Hello" in result

    def test_ass_newline_escape(self):
        segments = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "Line 1\nLine 2"},
        ]
        result = segments_to_ass(segments)
        assert "Line 1\\NLine 2" in result

    def test_srt_round_trip(self):
        original = [
            {"start_time_s": 1.0, "end_time_s": 3.5, "text": "Hello world"},
            {"start_time_s": 5.0, "end_time_s": 8.0, "text": "Second cue"},
        ]
        srt_out = segments_to_srt(original)
        reimported, warnings = parse_subtitle_bytes(srt_out.encode("utf-8"), "srt")
        assert len(reimported) == 2
        assert reimported[0]["text"] == "Hello world"
        assert reimported[1]["text"] == "Second cue"
        assert reimported[0]["start_time_s"] == 1.0
        assert reimported[0]["end_time_s"] == 3.5

    def test_vtt_round_trip(self):
        original = [
            {"start_time_s": 1.0, "end_time_s": 3.5, "text": "VTT round trip"},
        ]
        vtt_out = segments_to_vtt(original)
        reimported, warnings = parse_subtitle_bytes(vtt_out.encode("utf-8"), "vtt")
        assert len(reimported) == 1
        assert reimported[0]["text"] == "VTT round trip"

    def test_ass_round_trip(self):
        original = [
            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "ASS round trip"},
        ]
        ass_out = segments_to_ass(original)
        reimported, warnings = parse_subtitle_bytes(ass_out.encode("utf-8"), "ass")
        assert len(reimported) == 1
        assert reimported[0]["text"] == "ASS round trip"

    def test_empty_segments(self):
        assert segments_to_srt([]) == ""
        assert segments_to_vtt([]) == "WEBVTT\n"
        result = segments_to_ass([])
        assert "[Script Info]" in result
        if "[Events]" in result:
            assert "Dialogue:" not in result.split("[Events]")[1]

    def test_formatter_millisecond_rollover_srt(self):
        """SRT: 1.9996s exports as 2.000 not 1.000 (carry from ms rollover)."""
        srt = segments_to_srt([{"start_time_s": 1.9996, "end_time_s": 3.9996, "text": "x"}])
        assert "00:00:02,000" in srt, f"Expected 02,000 got: {srt}"
        assert "00:00:04,000" in srt, f"Expected 04,000 got: {srt}"

    def test_formatter_millisecond_rollover_vtt(self):
        """VTT: 1.9996s exports as 2.000 not 1.000."""
        vtt = segments_to_vtt([{"start_time_s": 1.9996, "end_time_s": 3.9996, "text": "x"}])
        assert "00:00:02.000" in vtt, f"Expected 02.000 got: {vtt}"
        assert "00:00:04.000" in vtt, f"Expected 04.000 got: {vtt}"

    def test_formatter_millisecond_rollover_ass(self):
        """ASS: 1.9996s exports as 2.000 not 1.000."""
        ass = segments_to_ass([{"start_time_s": 1.9996, "end_time_s": 3.9996, "text": "x"}])
        assert "0:00:02.000" in ass, f"Expected 0:00:02.000 got: {ass}"
        assert "0:00:04.000" in ass, f"Expected 0:00:04.000 got: {ass}"

    def test_formatter_rollover_hour_boundary(self):
        """3599.9996s (just under 1 hour) rolls over correctly."""
        srt = segments_to_srt([{"start_time_s": 3599.9996, "end_time_s": 3600.9996, "text": "x"}])
        assert "01:00:00,000" in srt
        assert "01:00:01,000" in srt

    def test_formatter_rollover_round_trip(self):
        """Rollover edge cases round-trip within 0.001s."""
        segments = [{"start_time_s": 1.9996, "end_time_s": 3599.9996, "text": "edge"}]
        for fmt_name, exporter in [("srt", segments_to_srt), ("vtt", segments_to_vtt)]:
            exported = exporter(segments)
            reimported, warnings = parse_subtitle_bytes(exported.encode("utf-8"), fmt_name)
            assert len(reimported) == 1
            assert warnings == []
            assert abs(reimported[0]["start_time_s"] - 2.0) <= 0.001, (
                f"{fmt_name}: start {segments[0]['start_time_s']} → {reimported[0]['start_time_s']}"
            )
            assert abs(reimported[0]["end_time_s"] - 3600.0) <= 0.001, (
                f"{fmt_name}: end {segments[0]['end_time_s']} → {reimported[0]['end_time_s']}"
            )

    def test_ass_millisecond_precision(self):
        """ASS export preserves millisecond precision within 0.001s."""
        original = {"start_time_s": 1.235, "end_time_s": 3.987, "text": "Precise"}
        ass_out = segments_to_ass([original])
        # The exported timestamp should have millisecond precision
        assert "0:00:01" in ass_out
        reimported, _ = parse_subtitle_bytes(ass_out.encode("utf-8"), "ass")
        assert len(reimported) == 1
        assert abs(reimported[0]["start_time_s"] - 1.235) <= 0.001
        assert abs(reimported[0]["end_time_s"] - 3.987) <= 0.001

    def test_all_formats_round_trip_precision(self):
        """SRT/VTT/ASS round-trip timestamps stay within 0.001s."""
        segments = [
            {"start_time_s": 1.234, "end_time_s": 5.678, "text": "Precise timing"},
            {"start_time_s": 10.001, "end_time_s": 15.999, "text": "Second cue"},
        ]
        for fmt, exporter in [
            ("srt", segments_to_srt),
            ("vtt", segments_to_vtt),
            ("ass", segments_to_ass),
        ]:
            exported = exporter(segments)
            reimported, warnings = parse_subtitle_bytes(exported.encode("utf-8"), fmt)
            assert len(reimported) == 2, f"{fmt}: expected 2 segments"
            assert warnings == [], f"{fmt}: unexpected warnings {warnings}"
            for i in range(2):
                delta_start = abs(reimported[i]["start_time_s"] - segments[i]["start_time_s"])
                delta_end = abs(reimported[i]["end_time_s"] - segments[i]["end_time_s"])
                assert delta_start <= 0.001, (
                    f"{fmt} seg {i}: start {segments[i]['start_time_s']} "
                    f"→ {reimported[i]['start_time_s']} (delta={delta_start})"
                )
                assert delta_end <= 0.001, (
                    f"{fmt} seg {i}: end {segments[i]['end_time_s']} "
                    f"→ {reimported[i]['end_time_s']} (delta={delta_end})"
                )
