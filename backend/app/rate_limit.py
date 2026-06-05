"""Rate limiting middleware using Redis sliding-window counters."""

import logging
import os
import time

import redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_logger = logging.getLogger("app.rate_limit")

# Default rate limit configuration (all overrideable via env vars)
_DEFAULT_LIMITS = {
    "auth_fail": int(os.getenv("RATE_LIMIT_AUTH_FAIL", "10")),       # per IP per minute
    "upload": int(os.getenv("RATE_LIMIT_UPLOAD", "5")),              # per token per minute
    "chat": int(os.getenv("RATE_LIMIT_CHAT", "20")),                 # per token per minute
    "other": int(os.getenv("RATE_LIMIT_OTHER", "120")),              # per token per minute
}

_WINDOW_SECONDS = 60  # 1-minute sliding window


def _get_redis() -> redis.Redis | None:
    """Get Redis connection. Returns None if Redis is unavailable."""
    try:
        r = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        r.ping()
        return r
    except Exception:
        return None


def _get_client_ip(request: Request) -> str:
    """Get client IP, respecting X-Forwarded-For for trusted proxies."""
    # For LAN deployments, trust the first forwarded IP if present
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_token_key(request: Request) -> str:
    """Extract a rate-limit key from the Bearer token (hashed for safety)."""
    import hashlib

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token_hash = hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
        return f"token:{token_hash}"
    return f"ip:{_get_client_ip(request)}"


def _check_limit(r: redis.Redis, key_prefix: str, identifier: str, max_requests: int) -> tuple[bool, int]:
    """Check if request is within rate limit. Returns (allowed, retry_after_seconds)."""
    now_ms = int(time.time() * 1000)
    window_ms = _WINDOW_SECONDS * 1000
    key = f"rate:{key_prefix}:{identifier}"
    window_start = now_ms - window_ms

    # Lua script for atomic sliding-window check + increment
    lua_script = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window_start = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    local window_ms = tonumber(ARGV[4])

    -- Remove expired entries
    redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

    -- Count current window entries
    local count = redis.call('ZCARD', key)

    if count >= max_requests then
        -- Get the oldest entry to calculate retry-after
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        if #oldest > 0 then
            local oldest_score = tonumber(oldest[2])
            local retry_after = math.ceil((oldest_score + window_ms - now) / 1000)
            if retry_after < 1 then retry_after = 1 end
            return {0, retry_after}
        end
        return {0, window_ms / 1000}
    end

    -- Add current request
    redis.call('ZADD', key, now, now .. '-' .. count)
    redis.call('EXPIRE', key, math.ceil(window_ms / 1000) + 1)
    return {1, 0}
    """

    try:
        result = r.eval(lua_script, 1, key, now_ms, window_start, max_requests, window_ms)
        allowed = bool(result[0])
        retry_after = int(result[1]) if len(result) > 1 else 0
        return allowed, retry_after
    except Exception as e:
        _logger.error("rate_limit.redis_error", extra={"error": str(e)})
        return True, 0  # Fail-open: allow requests when Redis fails


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting based on route category."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip rate limiting for OPTIONS and health
        if request.method == "OPTIONS":
            return await call_next(request)
        if path == "/api/health":
            return await call_next(request)

        r = _get_redis()
        if r is None:
            return await call_next(request)

        # Determine limit category (auth failures handled by AuthMiddleware)
        if path == "/api/tasks" and request.method == "POST":
            category = "upload"
            identifier = _get_token_key(request)
            max_req = _DEFAULT_LIMITS["upload"]
        elif path.endswith("/chat"):
            category = "chat"
            identifier = _get_token_key(request)
            max_req = _DEFAULT_LIMITS["chat"]
        else:
            category = "other"
            identifier = _get_token_key(request)
            max_req = _DEFAULT_LIMITS["other"]

        allowed, retry_after = _check_limit(r, category, identifier, max_req)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMITED",
                    "detail": f"请求过于频繁，请在 {retry_after} 秒后重试",
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
