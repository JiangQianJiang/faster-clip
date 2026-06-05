"""Tests for validate_clips in services/analyzer.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analyzer import validate_clips


def test_caps_to_three():
    clips = [
        {"start_time_s": 10, "end_time_s": 50, "score": 8, "reason": "good"},
        {"start_time_s": 60, "end_time_s": 100, "score": 7, "reason": "ok"},
        {"start_time_s": 120, "end_time_s": 160, "score": 6, "reason": "fine"},
        {"start_time_s": 200, "end_time_s": 240, "score": 9, "reason": "best"},
    ]
    result = validate_clips(
        clips, video_duration=300, min_duration=30, max_duration=120
    )
    assert len(result) <= 3, f"expected <=3, got {len(result)}"


def test_rejects_out_of_bounds():
    clips = [
        {"start_time_s": -20, "end_time_s": 10, "score": 8, "reason": "before start"},
        {"start_time_s": 290, "end_time_s": 320, "score": 8, "reason": "beyond end"},
    ]
    result = validate_clips(
        clips, video_duration=300, min_duration=30, max_duration=120
    )
    assert len(result) == 0, "both out of bounds, expected empty"


def test_clamps_near_boundary():
    clips = [
        {"start_time_s": -5, "end_time_s": 40, "score": 8, "reason": "slightly before"},
        {
            "start_time_s": 285,
            "end_time_s": 305,
            "score": 7,
            "reason": "slightly after",
        },
    ]
    result = validate_clips(
        clips, video_duration=300, min_duration=30, max_duration=120
    )
    assert result[0]["start_time_s"] == 0.0
    assert result[0]["end_time_s"] <= 300


def test_resolves_overlaps():
    clips = [
        {"start_time_s": 0, "end_time_s": 70, "score": 8, "reason": "first"},
        {"start_time_s": 60, "end_time_s": 80, "score": 9, "reason": "second"},
    ]
    result = validate_clips(clips, video_duration=100, min_duration=10, max_duration=90)
    for i in range(len(result)):
        for j in range(i + 1, len(result)):
            a, b = result[i], result[j]
            overlap = (
                a["start_time_s"] < b["end_time_s"]
                and b["start_time_s"] < a["end_time_s"]
            )
            assert not overlap, f"clips {i} and {j} overlap"


def test_all_satisfy_min_max_duration():
    clips = [
        {"start_time_s": 0, "end_time_s": 20, "score": 8, "reason": "short"},
        {"start_time_s": 50, "end_time_s": 150, "score": 9, "reason": "long"},
    ]
    result = validate_clips(clips, video_duration=200, min_duration=30, max_duration=60)
    for c in result:
        dur = c["end_time_s"] - c["start_time_s"]
        assert 30 <= dur <= 60, f"duration {dur} not in [30, 60]"


def test_sorted_by_score_desc():
    clips = [
        {"start_time_s": 0, "end_time_s": 60, "score": 3, "reason": "low"},
        {"start_time_s": 70, "end_time_s": 130, "score": 9, "reason": "high"},
        {"start_time_s": 140, "end_time_s": 200, "score": 6, "reason": "mid"},
    ]
    result = validate_clips(
        clips, video_duration=300, min_duration=30, max_duration=120
    )
    scores = [c["score"] for c in result]
    assert scores == sorted(scores, reverse=True), f"not sorted desc: {scores}"


def test_rejects_negative_duration():
    clips = [
        {"start_time_s": 100, "end_time_s": 50, "score": 8, "reason": "reversed"},
    ]
    result = validate_clips(
        clips, video_duration=300, min_duration=30, max_duration=120
    )
    assert len(result) == 0


def test_defensive_score_parse():
    clips = [
        {"start_time_s": 0, "end_time_s": 50, "score": "not_a_number", "reason": "bad"},
        {"start_time_s": 60, "end_time_s": 110, "score": None, "reason": "none"},
    ]
    result = validate_clips(
        clips, video_duration=300, min_duration=30, max_duration=120
    )
    for c in result:
        assert isinstance(c["score"], (int, float)), "score must be numeric"


def test_empty_input():
    result = validate_clips([], video_duration=300, min_duration=30, max_duration=120)
    assert result == []


def test_expand_short_clip_within_bounds():
    """Short clip should be expanded to min_duration using available space."""
    clips = [
        {"start_time_s": 50, "end_time_s": 65, "score": 8, "reason": "15s clip"},
    ]
    result = validate_clips(
        clips, video_duration=200, min_duration=30, max_duration=120
    )
    assert len(result) == 1
    dur = result[0]["end_time_s"] - result[0]["start_time_s"]
    assert dur >= 30, f"should expand to min 30, got {dur}"
