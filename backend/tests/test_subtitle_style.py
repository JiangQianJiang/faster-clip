"""Unit tests for subtitle_style service."""

import json
import os
import tempfile

import pytest

from app.services.subtitle_style import (
    _load_presets,
    build_force_style,
    get_preset,
)

# --- Test data ---

SAMPLE_PRESETS = {
    "douyin": {
        "name": "抖音短视频",
        "font_size": 32,
        "font_color": "&H00FFFF",
        "bold": True,
        "alignment": 2,
        "margin_v": 80,
        "max_chars": 15,
    },
    "minimal": {
        "name": "简约对话",
        "font_size": 26,
        "font_color": "&HFFFFFF",
        "bold": False,
        "alignment": 2,
        "margin_v": 80,
        "max_chars": 15,
    },
}


def _write_presets(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# --- Preset loading ---


def test_get_preset_douyin():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        result = get_preset("douyin", _path=preset_path)
        assert result["font_size"] == 32
        assert result["font_color"] == "&H00FFFF"
        assert result["bold"] is True


def test_get_preset_minimal():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        result = get_preset("minimal", _path=preset_path)
        assert result["font_size"] == 26
        assert result["font_color"] == "&HFFFFFF"
        assert result["bold"] is False


def test_get_preset_nonexistent_raises():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        with pytest.raises(ValueError, match="Unknown preset"):
            get_preset("nonexistent", _path=preset_path)


def test_get_preset_returns_copy():
    """get_preset returns a new dict, not a reference to internal data."""
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        a = get_preset("douyin", _path=preset_path)
        b = get_preset("douyin", _path=preset_path)
        a["font_size"] = 99
        assert b["font_size"] == 32


# --- force_style construction ---


def test_build_force_style_douyin():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        result = build_force_style("douyin", _path=preset_path)
        # Should contain FontSize, PrimaryColour, Bold=-1 (true), Alignment, MarginV
        assert "FontSize=32" in result
        assert "PrimaryColour=&H00FFFF" in result
        assert "Bold=-1" in result
        assert "Alignment=2" in result
        assert "MarginV=80" in result
        # Should be wrapped in single quotes
        assert result.startswith("'") and result.endswith("'")


def test_build_force_style_minimal():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        result = build_force_style("minimal", _path=preset_path)
        assert "FontSize=26" in result
        assert "PrimaryColour=&HFFFFFF" in result
        assert "Bold=0" in result  # false → 0


# --- Override merging ---


def test_build_force_style_with_overrides():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        result = build_force_style("douyin", {"font_size": 40}, _path=preset_path)
        # Override should take effect
        assert "FontSize=40" in result
        # Other fields from preset
        assert "PrimaryColour=&H00FFFF" in result
        assert "Bold=-1" in result


# --- Validation ---


def test_override_font_size_below_min():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        with pytest.raises(ValueError, match="out of range"):
            build_force_style("douyin", {"font_size": 4}, _path=preset_path)


def test_override_font_size_above_max():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        with pytest.raises(ValueError, match="out of range"):
            build_force_style("douyin", {"font_size": 50}, _path=preset_path)


def test_override_alignment_out_of_range():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        with pytest.raises(ValueError, match="out of range"):
            build_force_style("douyin", {"alignment": 0}, _path=preset_path)


def test_override_margin_v_out_of_range():
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        with pytest.raises(ValueError, match="out of range"):
            build_force_style("douyin", {"margin_v": 250}, _path=preset_path)


def test_override_at_boundaries():
    """Boundary values should pass validation."""
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        # font_size at min boundary
        r1 = build_force_style("douyin", {"font_size": 8}, _path=preset_path)
        assert "FontSize=8" in r1
        # font_size at max boundary
        r2 = build_force_style("douyin", {"font_size": 48}, _path=preset_path)
        assert "FontSize=48" in r2
        # margin_v at boundaries
        r3 = build_force_style("douyin", {"margin_v": 0}, _path=preset_path)
        assert "MarginV=0" in r3
        r4 = build_force_style("douyin", {"margin_v": 200}, _path=preset_path)
        assert "MarginV=200" in r4


# --- outline_color handling ---


def test_outline_color_override():
    """outline_color should serialize as ASS color string, not crash on int()."""
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        result = build_force_style(
            "douyin", {"outline_color": "&H000000"}, _path=preset_path
        )
        assert "OutlineColour=&H000000" in result


def test_string_numeric_override_validated():
    """String '999' for font_size should be converted and validated."""
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        with pytest.raises(ValueError, match="out of range"):
            build_force_style("douyin", {"font_size": "999"}, _path=preset_path)


def test_font_color_and_outline_color_both_strings():
    """Both font_color and outline_color should be treated as ASS hex strings."""
    with tempfile.TemporaryDirectory() as tmp:
        preset_path = os.path.join(tmp, "subtitle_styles.json")
        _write_presets(preset_path, SAMPLE_PRESETS)
        result = build_force_style(
            "minimal",
            {
                "font_color": "&HFF0000",
                "outline_color": "&H0000FF",
            },
            _path=preset_path,
        )
        assert "PrimaryColour=&HFF0000" in result
        assert "OutlineColour=&H0000FF" in result


# --- File not found ---


def test_load_presets_file_not_found():
    with pytest.raises(FileNotFoundError):
        _load_presets("/nonexistent/path/subtitle_styles.json")
