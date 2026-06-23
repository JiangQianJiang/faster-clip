import os

from app.services.settings_file import load_settings_file, nested_get


def _is_pytest_running() -> bool:
    return os.getenv("PYTEST_RUNNING", "").lower() == "true"


def _bool_value(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _env_or_file(env_name: str, file_settings: dict, file_path: str, default=None):
    value = os.getenv(env_name)
    if value is not None:
        return value
    return nested_get(file_settings, file_path, default)


def _int_env_or_file(env_name: str, file_settings: dict, file_path: str, default: int) -> int:
    return int(_env_or_file(env_name, file_settings, file_path, default))


class Settings:
    def __init__(self):
        file_settings = load_settings_file()

        self.app_name: str = str(nested_get(file_settings, "app_name", "live-clipper"))
        self.debug: bool = _bool_value(_env_or_file("DEBUG", file_settings, "debug", False))

        # Redis
        self.redis_url: str = str(
            _env_or_file("REDIS_URL", file_settings, "redis.url", "redis://redis:6379/0")
        )

        # Database
        # MySQL is the production/default path. SQLite is kept for local/test fallback.
        default_database_engine = "sqlite" if _is_pytest_running() else "mysql"
        self.database_engine: str = str(
            _env_or_file(
                "DATABASE_ENGINE",
                file_settings,
                "database.engine",
                default_database_engine,
            )
        ).lower()
        default_database_url = (
            "sqlite:///data/live-clipper.db"
            if self.database_engine == "sqlite"
            else "mysql+pymysql://fasterclip:password@mysql:3306/fasterclip"
        )
        self.database_url: str = str(
            _env_or_file("DATABASE_URL", file_settings, "database.url", default_database_url)
        )
        self.database_path: str = str(
            _env_or_file("DATABASE_PATH", file_settings, "database.path", "data/live-clipper.db")
        )

        # Upload limits
        self.max_upload_size_bytes: int = _int_env_or_file(
            "MAX_UPLOAD_SIZE_BYTES",
            file_settings,
            "upload.max_size_bytes",
            2 * 1024 * 1024 * 1024,
        )
        self.max_video_duration_seconds: int = _int_env_or_file(
            "MAX_VIDEO_DURATION_SECONDS",
            file_settings,
            "upload.max_video_duration_seconds",
            2 * 60 * 60,
        )

        # Runtime
        self.ffmpeg_timeout_seconds: int = _int_env_or_file(
            "FFMPEG_TIMEOUT", file_settings, "runtime.ffmpeg_timeout_seconds", 600
        )
        self.fonts_dir: str = str(
            _env_or_file("FONTS_DIR", file_settings, "runtime.fonts_dir", "/usr/share/fonts")
        )
        self.retention_days: int = _int_env_or_file(
            "RETENTION_DAYS", file_settings, "runtime.retention_days", 7
        )
        self.chat_lock_ttl: int = _int_env_or_file(
            "CHAT_LOCK_TTL", file_settings, "runtime.chat_lock_ttl", 300
        )
        self.chat_tool_result_max_chars: int = _int_env_or_file(
            "CHAT_TOOL_RESULT_MAX_CHARS",
            file_settings,
            "runtime.chat_tool_result_max_chars",
            4000,
        )
        self.presets_path: str = str(
            _env_or_file("PRESETS_PATH", file_settings, "runtime.presets_path", "")
        )
        self.log_format: str = (
            str(_env_or_file("LOG_FORMAT", file_settings, "logging.format", "")).strip().lower()
        )

        # Rate limits
        self.rate_limit_auth_fail: int = _int_env_or_file(
            "RATE_LIMIT_AUTH_FAIL", file_settings, "rate_limit.auth_fail", 10
        )
        self.rate_limit_upload: int = _int_env_or_file(
            "RATE_LIMIT_UPLOAD", file_settings, "rate_limit.upload", 5
        )
        self.rate_limit_chat: int = _int_env_or_file(
            "RATE_LIMIT_CHAT", file_settings, "rate_limit.chat", 20
        )
        self.rate_limit_other: int = _int_env_or_file(
            "RATE_LIMIT_OTHER", file_settings, "rate_limit.other", 120
        )

        # ASR
        self.default_asr_provider: str | None = _env_or_file(
            "DEFAULT_ASR_PROVIDER", file_settings, "asr.provider"
        )
        self.asr_api_key: str = str(_env_or_file("ASR_API_KEY", file_settings, "asr.api_key", ""))
        self.asr_base_url: str = str(
            _env_or_file("ASR_BASE_URL", file_settings, "asr.base_url", "")
        )
        self.asr_model: str = str(_env_or_file("ASR_MODEL", file_settings, "asr.model", ""))
        self.qwen_poll_timeout_seconds: int = _int_env_or_file(
            "QWEN_POLL_TIMEOUT", file_settings, "asr.qwen_poll_timeout_seconds", 600
        )

        # LLM
        self.llm_api_key: str = str(_env_or_file("LLM_API_KEY", file_settings, "llm.api_key", ""))
        self.llm_base_url: str = str(
            _env_or_file("LLM_BASE_URL", file_settings, "llm.base_url", "")
        )
        self.llm_model: str = str(_env_or_file("LLM_MODEL", file_settings, "llm.model", ""))

        # Security
        self.access_token: str = str(
            _env_or_file("ACCESS_TOKEN", file_settings, "security.access_token", "")
        )
        self.api_key_encryption_key: str | None = _env_or_file(
            "API_KEY_ENCRYPTION_KEY",
            file_settings,
            "security.api_key_encryption_key",
        )


settings = Settings()

STARTUP_VALIDATION_DONE = False


def _validate_startup_config() -> None:
    """Validate required configuration at startup. Exits on failure."""
    global STARTUP_VALIDATION_DONE
    if STARTUP_VALIDATION_DONE:
        return
    STARTUP_VALIDATION_DONE = True

    is_test = _is_pytest_running()

    errors = []
    if settings.database_engine not in ("mysql", "sqlite"):
        errors.append(
            f'不支持的 DATABASE_ENGINE: "{settings.database_engine}"，当前支持: mysql, sqlite'
        )

    if not settings.default_asr_provider:
        if not is_test:
            errors.append(
                '缺少必需的环境变量 DEFAULT_ASR_PROVIDER，请设置为 "whisper_api" 或 "qwen"'
            )
    elif settings.default_asr_provider not in ("whisper_api", "qwen"):
        errors.append(
            f'不支持的 DEFAULT_ASR_PROVIDER: "{settings.default_asr_provider}"，'
            f"当前支持: whisper_api, qwen"
        )

    if not settings.api_key_encryption_key:
        if not is_test:
            errors.append("缺少必需的环境变量 API_KEY_ENCRYPTION_KEY，生成方式见 .env.example")

    if errors:
        msg = "启动配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
        raise SystemExit(msg)
