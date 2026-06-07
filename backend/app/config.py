import os


class Settings:
    app_name: str = "live-clipper"
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # SQLite
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

    is_test = os.getenv("PYTEST_RUNNING", "").lower() == "true"

    errors = []
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

    # Validate ACCESS_TOKEN (required in non-test environments, min 32 chars)
    access_token = os.getenv("ACCESS_TOKEN", "")
    if not is_test:
        if not access_token:
            errors.append(
                "缺少必需的环境变量 ACCESS_TOKEN。请设置一个至少 32 个字符的高熵随机令牌。"
            )
        elif len(access_token) < 32:
            errors.append(
                f"ACCESS_TOKEN 长度不足: 需要至少 32 个字符，当前长度为 {len(access_token)}。"
            )

    if errors:
        msg = "启动配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
        raise SystemExit(msg)
