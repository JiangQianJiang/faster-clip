"""Tests for API key non-persistence in SQLite."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.models.task as task_mod
from app.models.task import create_task, get_task, init_db


def _use_temp_db(tmp_path: str):
    import app.config

    app.config.settings.database_path = tmp_path
    task_mod.DB_PATH = Path(tmp_path)


def test_config_json_excludes_api_keys():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()

        config = {
            "llm_base_url": "https://api.anthropic.com",
            "llm_model": "claude-opus-4-7",
            "clip_min_duration": 30,
            "clip_max_duration": 120,
            "buffer_seconds": 3,
            "burn_subtitle": False,
            "llm_api_key": "sk-ant-secret123",
            "asr_api_key": "sk-whisper-secret456",
        }
        tid = create_task(tmp_path, "test", config)
        task = get_task(tid)
        config_json = json.loads(task["config_json"])

        assert "llm_api_key" not in config_json, (
            "llm_api_key must NOT be in config_json"
        )
        assert "asr_api_key" not in config_json, (
            "asr_api_key must NOT be in config_json"
        )
        assert "sk-ant-secret123" not in json.dumps(config_json), (
            "key value must not appear"
        )
    finally:
        os.unlink(tmp_path)


def test_get_response_excludes_key_fields():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _use_temp_db(tmp_path)
        init_db()

        config = {
            "llm_base_url": "https://api.anthropic.com",
            "llm_model": "claude-opus-4-7",
            "clip_min_duration": 30,
            "clip_max_duration": 120,
            "buffer_seconds": 3,
            "burn_subtitle": False,
        }
        tid = create_task(tmp_path, "test2", config)
        task = get_task(tid)

        assert "llm_api_key" not in task, "GET response must not include llm_api_key"
        assert "asr_api_key" not in task, "GET response must not include asr_api_key"
    finally:
        os.unlink(tmp_path)
