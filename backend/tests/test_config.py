"""Tests for startup configuration validation (AC-8 negative startup)."""

import importlib
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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
