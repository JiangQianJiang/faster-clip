"""Compatibility helpers for API-related settings."""


def get_global_asr_api_key() -> str:
    from app.config import settings

    return str(settings.asr_api_key or "").strip()
