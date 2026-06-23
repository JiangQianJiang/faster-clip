"""Tests for _compute_export_window in worker/pipeline.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.worker.pipeline import _compute_export_window


def test_preserves_highlight_when_no_budget():
    """10-130 with buffer=3, max=120: highlight must be fully preserved."""
    s, e = _compute_export_window(10, 130, buffer=3, max_duration=120, video_duration=7200)
    assert s <= 10, f"export_start {s} must cover clip_start 10"
    assert e >= 130, f"export_end {e} must cover clip_end 130"
    assert e - s <= 120, f"duration {e - s} must not exceed max 120"


def test_full_buffer_when_budget_available():
    """10-50 with buffer=5, max=120: full buffer on both sides."""
    s, e = _compute_export_window(10, 50, buffer=5, max_duration=120, video_duration=7200)
    assert s == 5, f"expected export_start 5, got {s}"
    assert e == 55, f"expected export_end 55, got {e}"


def test_boundary_clip_no_buffer():
    """0-120 with buffer=5, max=120: no budget, highlight preserved."""
    s, e = _compute_export_window(0, 120, buffer=5, max_duration=120, video_duration=7200)
    assert s == 0, "export_start clamped to 0"
    assert e == 120, "export_end must preserve clip end"


def test_start_boundary_limits_before_buffer():
    """0-50 with buffer=10, max=120: before buffer limited by video start."""
    s, e = _compute_export_window(0, 50, buffer=10, max_duration=120, video_duration=7200)
    assert s == 0, "cannot go below 0"
    assert e == 60, "full after buffer of 10 applied"


def test_end_boundary_limits_after_buffer():
    """clip near video end: after buffer limited by remaining space."""
    s, e = _compute_export_window(7100, 7150, buffer=10, max_duration=120, video_duration=7200)
    assert s == 7090
    assert e == 7160, f"after buffer limited to 7160, got {e}"


def test_buffer_symmetric_within_budget():
    """Normal case: symmetric buffer allocation."""
    s, e = _compute_export_window(100, 160, buffer=5, max_duration=120, video_duration=7200)
    assert s == 95
    assert e == 165
    assert e - s == 70


def test_large_buffer_exceeds_budget():
    """buffer=30 on 30s clip, max=60: buffer trimmed to budget."""
    s, e = _compute_export_window(100, 130, buffer=30, max_duration=60, video_duration=7200)
    assert s <= 100, "highlight start preserved"
    assert e >= 130, "highlight end preserved"
    assert e - s <= 60, "duration within max"
