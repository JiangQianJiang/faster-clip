"""Symmetric encryption for API keys in Celery task messages.

Uses Fernet (AES-128-CBC + HMAC) so API keys are never plaintext in Redis.
The encryption key comes from API_KEY_ENCRYPTION_KEY env var.
"""

from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    if not settings.api_key_encryption_key:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY 环境变量未设置")
    return Fernet(settings.api_key_encryption_key.encode())


def encrypt_api_key(value: str) -> str:
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_api_key(token: str) -> str:
    if not token:
        return token
    return _get_fernet().decrypt(token.encode()).decode()
