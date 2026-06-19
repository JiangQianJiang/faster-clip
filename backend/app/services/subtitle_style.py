"""Subtitle burn-in style presets and force_style construction.

Provides preset loading from a JSON configuration file, user override
merging with validation, and ffmpeg ASS ``force_style`` string building.
"""

import json
import os

# Validation ranges for override parameters
_VALIDATION = {
    "font_size": (8, 48),
    "alignment": (1, 3),
    "margin_v": (0, 200),
}

# Mapping from preset field names to ASS style property names.
_FIELD_TO_ASS = {
    "font_size": "FontSize",
    "font_color": "PrimaryColour",
    "outline_color": "OutlineColour",
    "bold": "Bold",
    "alignment": "Alignment",
    "margin_v": "MarginV",
}


def _resolve_preset_path() -> str:
    """Return the absolute path to ``subtitle_styles.json``.

    Resolution order:
    1. ``PRESETS_PATH`` environment variable (if set).
    2. Walk upward from CWD looking for ``data/presets/subtitle_styles.json``.
    3. Walk upward from this file's directory (covers ``backend/`` CWD).
    """
    from app.config import settings

    if settings.presets_path:
        return settings.presets_path

    filename = os.path.join("data", "presets", "subtitle_styles.json")

    # Try walking up from CWD
    cwd = os.getcwd()
    while True:
        candidate = os.path.join(cwd, filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cwd)
        if parent == cwd:
            break
        cwd = parent

    # Try walking up from this file's directory
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(here, filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent

    # Last resort: CWD-relative (let FileNotFoundError surface if missing)
    return os.path.abspath(filename)


def _load_presets(path: str | None = None) -> dict:
    """Load all presets from the JSON configuration file.

    Args:
        path: Optional override for the preset file path (test injection).

    Returns:
        Dict mapping preset names to their parameter dicts.

    Raises:
        FileNotFoundError: If the preset file does not exist.
        ValueError: If the file is not valid JSON.
    """
    target = path or _resolve_preset_path()
    if not os.path.isfile(target):
        raise FileNotFoundError(f"Preset file not found: {target}")
    with open(target, encoding="utf-8") as f:
        return json.load(f)


def get_preset(name: str, *, _path: str | None = None) -> dict:
    """Return a single preset dict by name.

    Args:
        name: Preset key (e.g. ``"douyin"``, ``"minimal"``).
        _path: Test-only override for preset file path.

    Returns:
        The preset parameter dict.

    Raises:
        ValueError: If the preset name is not found.
    """
    presets = _load_presets(_path)
    if name not in presets:
        raise ValueError(
            f"Unknown preset '{name}'. Available: {', '.join(sorted(presets.keys()))}"
        )
    return dict(presets[name])


def _validate_override(key: str, value: int) -> None:
    """Validate a single override value against the allowed range.

    Args:
        key: Parameter name (must be in ``_VALIDATION``).
        value: The override value to check.

    Raises:
        ValueError: If the value is outside the allowed range.
    """
    if key not in _VALIDATION:
        return  # allow unknown keys through (they just won't map to ASS)
    lo, hi = _VALIDATION[key]
    if not (lo <= value <= hi):
        raise ValueError(f"Override '{key}' value {value} is out of range [{lo}, {hi}]")


def build_force_style(
    preset: str, overrides: dict | None = None, *, _path: str | None = None
) -> str:
    """Build an ffmpeg ASS ``force_style`` string from a preset and optional overrides.

    Args:
        preset: Preset name (e.g. ``"douyin"``).
        overrides: Optional dict of parameter overrides.  Supported keys:
            ``font_size``, ``font_color``, ``bold``, ``alignment``,
            ``margin_v``.
        _path: Test-only override for preset file path.

    Returns:
        A quoted ``force_style`` string suitable for ffmpeg's
        ``subtitles`` filter, e.g.
        ``'FontSize=32,PrimaryColour=&H00FFFF,Bold=1,Alignment=2,MarginV=80'``.

    Raises:
        ValueError: If the preset is unknown or an override fails validation.
    """
    base = get_preset(preset, _path=_path)
    merged = dict(base)

    if overrides:
        for key, value in overrides.items():
            # Validate numeric overrides (int, float, or numeric strings)
            if isinstance(value, (int, float)):
                _validate_override(key, int(value))
            elif isinstance(value, str) and key in _VALIDATION:
                try:
                    num = int(value)
                except (ValueError, TypeError):
                    raise ValueError(
                        f"Override '{key}' value '{value}' is not a valid integer"
                    )
                _validate_override(key, num)
                merged[key] = num  # normalize to int
                continue
            merged[key] = value

    parts: list[str] = []
    for field, ass_key in _FIELD_TO_ASS.items():
        val = merged.get(field)
        if val is None:
            continue

        if field == "bold":
            # ASS Bold: 0 = false, -1 = true
            val = -1 if val else 0
        elif field in ("font_color", "outline_color"):
            # Already in ASS hex format (&HAABBGGRR)
            val = str(val)
        else:
            val = str(int(val))

        parts.append(f"{ass_key}={val}")

    return "'" + ",".join(parts) + "'"
