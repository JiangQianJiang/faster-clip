"""Load server settings from a local JSON file."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS_PATH = "data/settings.json"


def get_settings_path() -> Path:
    return Path(os.getenv("APP_SETTINGS_PATH", DEFAULT_SETTINGS_PATH))


def load_settings_file() -> dict[str, Any]:
    path = get_settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_settings_file(settings: dict[str, Any]) -> None:
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as tmp:
        tmp.write(payload)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def nested_get(settings: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = settings
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current
