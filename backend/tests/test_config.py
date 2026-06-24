"""Tests for startup configuration validation (AC-8 negative startup)."""

import importlib
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

EMPTY_SETTINGS_ENV = {"APP_SETTINGS_PATH": os.devnull}


def _reload_settings():
    """Reload the config module so os.getenv re-reads the environment."""
    import app.config

    importlib.reload(app.config)
    return app.config


def test_startup_missing_asr_provider_fails_with_clear_error():
    """Missing DEFAULT_ASR_PROVIDER → SystemExit with Chinese error message."""
    try:
        with patch.dict(
            os.environ,
            {
                **EMPTY_SETTINGS_ENV,
                "API_KEY_ENCRYPTION_KEY": "gCW0ZvxPWL4R5PMVxpLNMCNQ2xhT1NWK_vDXI5_OHOk=",
            },
            clear=True,
        ):
            cfg = _reload_settings()

            try:
                cfg._validate_startup_config()
                assert False, "should have raised SystemExit"
            except SystemExit as e:
                assert "DEFAULT_ASR_PROVIDER" in str(e)
                assert "缺少" in str(e)
            finally:
                cfg.STARTUP_VALIDATION_DONE = False
    finally:
        _reload_settings()


def test_startup_valid_asr_provider_passes():
    """DEFAULT_ASR_PROVIDER=whisper_api → validation passes without error.
    ACCESS_TOKEN is no longer required after auth removal.
    """
    try:
        with patch.dict(
            os.environ,
            {
                **EMPTY_SETTINGS_ENV,
                "DEFAULT_ASR_PROVIDER": "whisper_api",
                "API_KEY_ENCRYPTION_KEY": "gCW0ZvxPWL4R5PMVxpLNMCNQ2xhT1NWK_vDXI5_OHOk=",
            },
            clear=True,
        ):
            cfg = _reload_settings()
            assert cfg.settings.default_asr_provider == "whisper_api"

            try:
                cfg._validate_startup_config()
            except SystemExit:
                assert False, "should not raise for valid config"
            finally:
                cfg.STARTUP_VALIDATION_DONE = False
    finally:
        _reload_settings()


def test_startup_invalid_asr_provider_value_fails():
    """Invalid DEFAULT_ASR_PROVIDER → SystemExit with supported values.
    ACCESS_TOKEN is no longer required after auth removal.
    """
    try:
        with patch.dict(
            os.environ,
            {
                **EMPTY_SETTINGS_ENV,
                "DEFAULT_ASR_PROVIDER": "openai_whisper",
                "API_KEY_ENCRYPTION_KEY": "gCW0ZvxPWL4R5PMVxpLNMCNQ2xhT1NWK_vDXI5_OHOk=",
            },
            clear=True,
        ):
            cfg = _reload_settings()

            try:
                cfg._validate_startup_config()
                assert False, "should have raised SystemExit"
            except SystemExit as e:
                assert "不支持的" in str(e)
                assert "whisper_api" in str(e)
            finally:
                cfg.STARTUP_VALIDATION_DONE = False
    finally:
        _reload_settings()


def test_database_defaults_to_mysql_outside_pytest():
    """Production/default config uses MySQL as the primary database engine."""
    try:
        with patch.dict(
            os.environ,
            {
                **EMPTY_SETTINGS_ENV,
                "DEFAULT_ASR_PROVIDER": "qwen",
                "API_KEY_ENCRYPTION_KEY": "gCW0ZvxPWL4R5PMVxpLNMCNQ2xhT1NWK_vDXI5_OHOk=",
            },
            clear=True,
        ):
            cfg = _reload_settings()

            assert cfg.settings.database_engine == "mysql"
            assert cfg.settings.database_url.startswith("mysql+pymysql://")
    finally:
        _reload_settings()


def test_database_defaults_to_sqlite_during_pytest():
    """Tests default to the local SQLite fallback unless a test opts into MySQL."""
    try:
        with patch.dict(
            os.environ,
            {
                **EMPTY_SETTINGS_ENV,
                "PYTEST_RUNNING": "true",
                "DEFAULT_ASR_PROVIDER": "qwen",
                "API_KEY_ENCRYPTION_KEY": "gCW0ZvxPWL4R5PMVxpLNMCNQ2xhT1NWK_vDXI5_OHOk=",
            },
            clear=True,
        ):
            cfg = _reload_settings()

            assert cfg.settings.database_engine == "sqlite"
            assert cfg.settings.database_url.startswith("sqlite:///")
    finally:
        _reload_settings()


def test_default_video_duration_limit_is_twelve_hours():
    """Default upload duration cap follows qwen3-asr-flash-filetrans's 12h limit."""
    try:
        with patch.dict(
            os.environ,
            {
                **EMPTY_SETTINGS_ENV,
                "PYTEST_RUNNING": "true",
                "DEFAULT_ASR_PROVIDER": "qwen",
                "API_KEY_ENCRYPTION_KEY": "gCW0ZvxPWL4R5PMVxpLNMCNQ2xhT1NWK_vDXI5_OHOk=",
            },
            clear=True,
        ):
            cfg = _reload_settings()

            assert cfg.settings.max_video_duration_seconds == 12 * 60 * 60
    finally:
        _reload_settings()


def test_settings_file_populates_server_settings(tmp_path):
    """APP_SETTINGS_PATH can provide all server-side settings."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "debug": True,
                "redis": {"url": "redis://settings-redis:6379/3"},
                "database": {
                    "engine": "sqlite",
                    "url": "sqlite:///settings.db",
                    "path": "settings.db",
                },
                "upload": {
                    "max_video_duration_seconds": 567,
                },
                "runtime": {
                    "ffmpeg_timeout_seconds": 42,
                    "fonts_dir": "/settings/fonts",
                    "retention_days": 9,
                    "chat_lock_ttl": 111,
                    "chat_tool_result_max_chars": 222,
                    "presets_path": "/settings/presets.json",
                },
                "logging": {"format": "json"},
                "rate_limit": {
                    "auth_fail": 2,
                    "upload": 3,
                    "chat": 4,
                    "other": 5,
                },
                "asr": {
                    "provider": "qwen",
                    "api_key": "settings-asr-key",
                    "base_url": "https://asr.example.com",
                    "model": "qwen3-asr-flash-filetrans",
                    "qwen_poll_timeout_seconds": 77,
                },
                "llm": {
                    "api_key": "settings-llm-key",
                    "base_url": "https://llm.example.com",
                    "model": "claude-test",
                },
                "security": {
                    "access_token": "settings-token-xxxxxxxxxxxxxxxxxxx",
                    "api_key_encryption_key": "settings-fernet-key",
                },
            }
        ),
        encoding="utf-8",
    )
    try:
        with patch.dict(
            os.environ,
            {"APP_SETTINGS_PATH": str(settings_path), "PYTEST_RUNNING": "true"},
            clear=True,
        ):
            cfg = _reload_settings()

            assert cfg.settings.debug is True
            assert cfg.settings.redis_url == "redis://settings-redis:6379/3"
            assert cfg.settings.database_engine == "sqlite"
            assert cfg.settings.database_url == "sqlite:///settings.db"
            assert cfg.settings.database_path == "settings.db"
            assert cfg.settings.max_video_duration_seconds == 567
            assert cfg.settings.ffmpeg_timeout_seconds == 42
            assert cfg.settings.fonts_dir == "/settings/fonts"
            assert cfg.settings.retention_days == 9
            assert cfg.settings.chat_lock_ttl == 111
            assert cfg.settings.chat_tool_result_max_chars == 222
            assert cfg.settings.presets_path == "/settings/presets.json"
            assert cfg.settings.log_format == "json"
            assert cfg.settings.rate_limit_auth_fail == 2
            assert cfg.settings.rate_limit_upload == 3
            assert cfg.settings.rate_limit_chat == 4
            assert cfg.settings.rate_limit_other == 5
            assert cfg.settings.default_asr_provider == "qwen"
            assert cfg.settings.asr_api_key == "settings-asr-key"
            assert cfg.settings.asr_base_url == "https://asr.example.com"
            assert cfg.settings.asr_model == "qwen3-asr-flash-filetrans"
            assert cfg.settings.qwen_poll_timeout_seconds == 77
            assert cfg.settings.llm_api_key == "settings-llm-key"
            assert cfg.settings.llm_base_url == "https://llm.example.com"
            assert cfg.settings.llm_model == "claude-test"
            assert cfg.settings.access_token == "settings-token-xxxxxxxxxxxxxxxxxxx"
            assert cfg.settings.api_key_encryption_key == "settings-fernet-key"
    finally:
        _reload_settings()


def test_environment_variables_override_settings_file(tmp_path):
    """Existing env vars remain compatible and take precedence over file values."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "redis": {"url": "redis://settings-redis:6379/3"},
                "asr": {"provider": "qwen", "api_key": "settings-asr-key"},
                "security": {"api_key_encryption_key": "settings-fernet-key"},
            }
        ),
        encoding="utf-8",
    )
    try:
        with patch.dict(
            os.environ,
            {
                "APP_SETTINGS_PATH": str(settings_path),
                "PYTEST_RUNNING": "true",
                "REDIS_URL": "redis://env-redis:6379/4",
                "DEFAULT_ASR_PROVIDER": "whisper_api",
                "ASR_API_KEY": "env-asr-key",
                "API_KEY_ENCRYPTION_KEY": "env-fernet-key",
            },
            clear=True,
        ):
            cfg = _reload_settings()

            assert cfg.settings.redis_url == "redis://env-redis:6379/4"
            assert cfg.settings.default_asr_provider == "whisper_api"
            assert cfg.settings.asr_api_key == "env-asr-key"
            assert cfg.settings.api_key_encryption_key == "env-fernet-key"
    finally:
        _reload_settings()
