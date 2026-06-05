"""Redis-based distributed lock for chat mutual exclusion."""

import asyncio
import logging
import os
import uuid

import redis

_logger = logging.getLogger("app.chat_lock")

# Default lock TTL (must be longer than max chat processing time)
DEFAULT_LOCK_TTL = int(os.getenv("CHAT_LOCK_TTL", "300"))  # 5 minutes
# Lease renewal interval (renew at half TTL)
_RENEWAL_INTERVAL = DEFAULT_LOCK_TTL / 2


def _get_redis() -> redis.Redis:
    """Get Redis connection."""
    return redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        socket_connect_timeout=3,
        socket_timeout=3,
    )


# Lua script for safe lock release (only delete if owner matches)
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# Lua script for lease renewal (only renew if owner matches)
_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


class ChatLockUnavailable(Exception):
    """Raised when the lock service (Redis) is unavailable."""
    pass


class ChatLock:
    """Distributed lock for per-task chat mutual exclusion."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.lock_key = f"chat-lock:{task_id}"
        self.owner = str(uuid.uuid4())
        self._redis: redis.Redis | None = None
        self._renewal_task: asyncio.Task | None = None
        self._acquired = False
        self.lock_lost = asyncio.Event()

    async def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if acquired, False if held by another owner."""
        self._redis = _get_redis()
        try:
            # SET NX (only if not exists) with TTL
            acquired = self._redis.set(
                self.lock_key, self.owner, nx=True, ex=DEFAULT_LOCK_TTL
            )
            if acquired:
                self._acquired = True
                _logger.info(
                    "chat_lock.acquired",
                    extra={"task_id": self.task_id, "owner": self.owner[:8]},
                )
                # Start lease renewal
                self._renewal_task = asyncio.create_task(self._renew_loop())
            return bool(acquired)
        except redis.RedisError as e:
            _logger.error(
                "chat_lock.acquire_failed",
                extra={"task_id": self.task_id, "error": str(e)},
            )
            raise ChatLockUnavailable(
                "聊天服务暂时不可用，请稍后重试"
            ) from e

    async def release(self) -> bool:
        """Release the lock if we still own it."""
        if not self._acquired or not self._redis:
            return False

        # Cancel renewal task
        if self._renewal_task and not self._renewal_task.done():
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass

        try:
            release_fn = self._redis.register_script(_RELEASE_SCRIPT)
            result = release_fn(keys=[self.lock_key], args=[self.owner])
            if result:
                _logger.info(
                    "chat_lock.released",
                    extra={"task_id": self.task_id, "owner": self.owner[:8]},
                )
                self._acquired = False
                return True
            _logger.warning(
                "chat_lock.release_failed_not_owner",
                extra={"task_id": self.task_id},
            )
            return False
        except redis.RedisError as e:
            _logger.error(
                "chat_lock.release_error",
                extra={"task_id": self.task_id, "error": str(e)},
            )
            self._acquired = False
            return False

    async def _renew_loop(self):
        """Periodically renew the lock lease."""
        try:
            while self._acquired and self._redis:
                await asyncio.sleep(_RENEWAL_INTERVAL)
                if not self._acquired:
                    break
                try:
                    renew_fn = self._redis.register_script(_RENEW_SCRIPT)
                    result = renew_fn(
                        keys=[self.lock_key],
                        args=[self.owner, DEFAULT_LOCK_TTL],
                    )
                    if not result:
                        _logger.warning(
                            "chat_lock.renew_lost",
                            extra={"task_id": self.task_id},
                        )
                        self._acquired = False
                        self.lock_lost.set()
                except redis.RedisError:
                    _logger.warning(
                        "chat_lock.renew_error",
                        extra={"task_id": self.task_id},
                    )
                    self._acquired = False
                    self.lock_lost.set()
        except asyncio.CancelledError:
            pass

    def is_acquired(self) -> bool:
        return self._acquired
