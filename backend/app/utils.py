"""Shared utility functions."""

from datetime import UTC, datetime


def utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()
