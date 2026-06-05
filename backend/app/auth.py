"""Authentication middleware and verification endpoint."""

import logging
import os
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_logger = logging.getLogger("app.auth")

# Public paths that do not require authentication
_PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/verify",  # Used to verify token validity from frontend
}

# Token required minimum length
_MIN_TOKEN_LENGTH = 32


def get_access_token() -> str | None:
    """Return the configured access token, or None if not set."""
    token = os.getenv("ACCESS_TOKEN", "")
    return token if token else None


def validate_access_token() -> None:
    """Validate ACCESS_TOKEN at startup. Raises SystemExit on failure."""
    token = os.getenv("ACCESS_TOKEN", "")
    if not token:
        raise SystemExit(
            "缺少必需的环境变量 ACCESS_TOKEN。"
            "请设置一个至少 32 个字符的高熵随机令牌。"
        )
    if len(token) < _MIN_TOKEN_LENGTH:
        raise SystemExit(
            f"ACCESS_TOKEN 长度不足: 需要至少 {_MIN_TOKEN_LENGTH} 个字符，"
            f"当前长度为 {len(token)}。"
        )


def _rate_limit_auth_fail(client_ip: str) -> int | None:
    """Count auth failure. Returns Retry-After seconds if over limit, None if allowed."""
    import os

    import redis

    limit = int(os.getenv("RATE_LIMIT_AUTH_FAIL", "10"))
    try:
        r = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        key = f"rate:auth_fail:ip:{client_ip}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, 60)
        if count > limit:
            ttl = r.ttl(key)
            return max(ttl, 1) if ttl and ttl > 0 else 60
        return None
    except Exception:
        return None  # Fail-open: best-effort


def verify_token(request: Request) -> bool:
    """Constant-time comparison of the request's Bearer token against ACCESS_TOKEN.

    Checks Authorization header first, then falls back to ?token= query parameter.
    The query parameter fallback enables <video>, <img>, and <a> elements to
    authenticate when they cannot send custom HTTP headers.
    """
    expected = os.getenv("ACCESS_TOKEN", "")
    if not expected:
        return False

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided = auth_header[7:]  # Strip "Bearer " prefix
        return secrets.compare_digest(provided, expected)

    # Fallback: token in query parameter (for media elements)
    token = request.query_params.get("token", "")
    if token:
        return secrets.compare_digest(token, expected)

    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces Bearer Token authentication on protected routes."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow OPTIONS preflight without authentication
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow health check
        if path == "/api/health":
            return await call_next(request)

        # All /api/** routes require authentication (except public paths above)
        if path.startswith("/api/"):
            if not verify_token(request):
                client_ip = request.client.host if request.client else "unknown"
                _logger.warning(
                    "auth.failed",
                    extra={
                        "path": path,
                        "method": request.method,
                        "client_ip": client_ip,
                    },
                )
                retry_after = _rate_limit_auth_fail(client_ip)
                if retry_after is not None:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "code": "RATE_LIMITED",
                            "detail": f"认证失败次数过多，请在 {retry_after} 秒后重试",
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
                return JSONResponse(
                    status_code=401,
                    content={
                        "code": "UNAUTHORIZED",
                        "detail": "需要有效的访问令牌",
                    },
                    headers={"WWW-Authenticate": "Bearer"},
                )

        return await call_next(request)


def create_auth_verify_router():
    """Create a router with the /api/auth/verify endpoint."""
    from fastapi import APIRouter, Request

    router = APIRouter()

    @router.get("/api/auth/verify")
    async def auth_verify(request: Request):
        """Lightweight endpoint to verify token validity."""
        if not verify_token(request):
            raise HTTPException(
                status_code=401,
                detail="无效的访问令牌",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {"status": "ok"}

    return router
