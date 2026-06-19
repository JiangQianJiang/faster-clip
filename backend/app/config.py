import os


def _is_pytest_running() -> bool:
    return os.getenv("PYTEST_RUNNING", "").lower() == "true"


class Settings:
    app_name: str = "live-clipper"
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # Database
    # MySQL is the production/default path. SQLite is kept for local/test fallback.
    _default_database_engine = "sqlite" if _is_pytest_running() else "mysql"
    database_engine: str = os.getenv("DATABASE_ENGINE", _default_database_engine).lower()
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///data/live-clipper.db"
        if database_engine == "sqlite"
        else "mysql+pymysql://fasterclip:password@mysql:3306/fasterclip",
    )
    database_path: str = os.getenv("DATABASE_PATH", "data/live-clipper.db")

    # Upload limits
    max_upload_size_bytes: int = 2 * 1024 * 1024 * 1024  # 2GB
    max_video_duration_seconds: int = 2 * 60 * 60  # 2 hours

    # ffmpeg
    ffmpeg_timeout_seconds: int = int(
        os.getenv("FFMPEG_TIMEOUT", "600")
    )  # 10 min per clip
    fonts_dir: str = os.getenv("FONTS_DIR", "/usr/share/fonts")

    # Cleanup
    retention_days: int = 7

    # Default ASR provider (whisper_api / qwen)
    default_asr_provider: str | None = os.getenv("DEFAULT_ASR_PROVIDER")

    # Qwen ASR poll timeout (seconds)
    qwen_poll_timeout_seconds: int = int(os.getenv("QWEN_POLL_TIMEOUT", "600"))

    # API key encryption (Fernet key for securing keys in Celery task messages)
    api_key_encryption_key: str | None = os.getenv("API_KEY_ENCRYPTION_KEY")


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
            errors.append(
                "缺少必需的环境变量 API_KEY_ENCRYPTION_KEY，生成方式见 .env.example"
            )

    if errors:
        msg = "启动配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
        raise SystemExit(msg)
