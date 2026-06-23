import logging
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.clips import router as clips_router
from app.api.settings import router as settings_router
from app.api.subtitles import router as subtitles_router
from app.api.tasks_crud import router as tasks_crud_router
from app.auth import create_auth_verify_router
from app.config import _validate_startup_config
from app.logging_config import (
    _task_id_var,
    get_task_id,
    install_log_filter,
    setup_json_logging,
)
from app.rate_limit import RateLimitMiddleware
from app.security_headers import SecurityHeadersMiddleware

_logger = logging.getLogger("app.main")

# UUID pattern for extracting task_id from URL paths
_TASK_ID_PATTERN = re.compile(
    r"/tasks/([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_config()
    install_log_filter()
    setup_json_logging()
    _logger.info("Application startup complete")
    yield


app = FastAPI(title="live-clipper", version="0.1.0", lifespan=lifespan)
app.include_router(tasks_crud_router)
app.include_router(subtitles_router)
app.include_router(clips_router)
app.include_router(chat_router)
app.include_router(settings_router)
app.include_router(create_auth_verify_router())

# Middleware order (add_middleware prepends — last added = outermost):
# Execution order: outermost first → innermost last
# 1. SecurityHeadersMiddleware (outermost — wraps all responses)
# 2. CORSMiddleware (handles preflight)
# 3. RateLimitMiddleware (rate-limits requests)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log every HTTP request with timing and task_id context."""
    start = time.monotonic()

    # Extract task_id from URL path (path_params not populated yet in middleware).
    # Always reset context after the request so no stale task_id leaks.
    path = request.url.path
    m = _TASK_ID_PATTERN.search(path)
    token = _task_id_var.set(m.group(1) if m else None)

    try:
        _logger.info(
            "request.start",
            extra={
                "method": request.method,
                "path": path,
                "task_id": get_task_id(),
                "client_ip": request.client.host if request.client else None,
            },
        )

        response = await call_next(request)

        duration_ms = (time.monotonic() - start) * 1000
        _logger.info(
            "request.end",
            extra={
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
                "task_id": get_task_id(),
            },
        )

        return response
    finally:
        _task_id_var.reset(token)


@app.middleware("http")
async def transcript_traversal_guard(request: Request, call_next):
    raw = request.scope.get("raw_path", b"").decode("latin-1")
    if "/transcript" in raw:
        lower = raw.lower()
        if ".." in raw or "%2f" in lower or "%2e%2e" in lower:
            return _secure_response(400, {"code": "INVALID_PATH", "detail": "无效的路径"})
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _secure_response(
    status_code: int,
    content: dict,
    extra_headers: dict | None = None,
) -> JSONResponse:
    """Return a JSONResponse with all required security headers."""
    headers = {
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(status_code=status_code, content=content, headers=headers)


# Standardized error handlers

@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: Exception):
    return _secure_response(
        401,
        {"code": "UNAUTHORIZED", "detail": "需要有效的访问令牌"},
        extra_headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    detail = exc.detail if isinstance(exc, HTTPException) else "资源不存在"
    return _secure_response(404, {"code": "NOT_FOUND", "detail": detail})


@app.exception_handler(422)
async def validation_handler(request: Request, exc: Exception):
    detail = "请求参数无效"
    if isinstance(exc, HTTPException):
        detail = exc.detail
    elif hasattr(exc, "errors"):
        detail = str(exc.errors()) if callable(exc.errors) else str(getattr(exc, "errors", detail))
    return _secure_response(422, {"code": "VALIDATION_ERROR", "detail": detail})


@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc: Exception):
    return _secure_response(
        429,
        {"code": "RATE_LIMITED", "detail": "请求过于频繁，请稍后重试"},
        extra_headers={"Retry-After": "60"},
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    _logger.error("internal_error", extra={"error": str(exc), "path": str(request.url)})
    return _secure_response(500, {"code": "INTERNAL_ERROR", "detail": "服务器内部错误"})
