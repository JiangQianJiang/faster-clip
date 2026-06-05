"""Chat API endpoint — SSE streaming for AI conversation mode."""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

_logger = logging.getLogger("app.api.chat")

router = APIRouter(prefix="/api/tasks", tags=["chat"])


def _get_llm_api_key(task_config: dict, request_body: dict) -> str:
    """Resolve LLM API key for chat.

    Priority:
    1. Encrypted key in task config_json (tasks with API key stored at creation)
    2. Plaintext key in request body (normal tasks where config_json has no key)

    Returns the plaintext key, or raises HTTPException if unavailable.
    """
    from app.crypto import decrypt_api_key

    # Try encrypted key from task config first
    encrypted = task_config.get("llm_api_key", "")
    if encrypted:
        try:
            plain = decrypt_api_key(encrypted)
            if plain:
                return plain
        except Exception:
            pass

    # Fall back to request body
    request_key = (request_body.get("llm_api_key") or "").strip()
    if request_key:
        return request_key

    raise HTTPException(
        400,
        detail="该任务缺少 LLM API Key。请在请求中提供 llm_api_key，或先在经典模式中配置。",
    )


@router.post("/{task_id}/chat")
async def chat_endpoint(task_id: str, request: Request):
    """SSE streaming chat endpoint.

    Request body: {"message": "...", "llm_api_key": "sk-ant-..." (optional)}
    The llm_api_key is used in-memory only and never persisted.
    """
    from app.models.task import get_task

    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, detail="任务不存在")

    # Parse request body
    try:
        body = await request.json()
        user_message = (body.get("message") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        raise HTTPException(400, detail="请求体必须是 JSON 格式")

    if not user_message:
        raise HTTPException(400, detail="消息不能为空")

    # Load LLM config from task
    config = json.loads(task.get("config_json") or "{}")
    llm_base_url = config.get("llm_base_url", "")
    llm_model = config.get("llm_model", "")

    if not llm_base_url or not llm_model:
        raise HTTPException(400, detail="该任务缺少 LLM 配置，请先在经典模式中配置")

    # Resolve API key (from config or request body)
    llm_api_key = _get_llm_api_key(config, body)

    # Resolve checkpoint mode (from config or request body, default "auto")
    checkpoint_mode_raw = (
        body.get("checkpoint_mode") or config.get("checkpoint_mode") or "auto"
    )
    if not isinstance(checkpoint_mode_raw, str):
        raise HTTPException(400, detail="checkpoint_mode 必须是字符串")
    checkpoint_mode = checkpoint_mode_raw.strip()
    if checkpoint_mode not in ("auto", "confirm", "selective"):
        raise HTTPException(
            400,
            detail=f"无效的 checkpoint_mode '{checkpoint_mode}'，可选：auto, confirm, selective",
        )

    # Acquire Redis distributed lock for this task's chat
    from app.chat_lock import ChatLock

    from app.chat_lock import ChatLock, ChatLockUnavailable

    chat_lock = ChatLock(task_id)
    try:
        acquired = await chat_lock.acquire()
    except ChatLockUnavailable:
        return JSONResponse(
            status_code=503,
            content={
                "code": "SERVICE_UNAVAILABLE",
                "detail": "聊天服务暂时不可用，请稍后重试",
            },
        )
    if not acquired:
        return JSONResponse(
            status_code=409,
            content={
                "code": "CHAT_IN_PROGRESS",
                "detail": "该任务已有正在进行的聊天，请等待完成后再发送消息",
            },
        )

    # Build chat service
    from app.services.chat_service import ChatService

    chat_service = ChatService(
        task_id=task_id,
        llm_config={
            "llm_base_url": llm_base_url,
            "llm_model": llm_model,
        },
        api_key=llm_api_key,
        checkpoint_mode=checkpoint_mode,
    )

    async def event_stream():
        svc = chat_service
        try:
            async for sse_event in svc.chat(user_message):
                if chat_lock.lock_lost.is_set():
                    yield (
                        'data: {"type":"error","data":{"code":"LOCK_LOST",'
                        '"detail":"聊天锁已丢失，请刷新后重试"}}\n\n'
                    )
                    break
                yield sse_event
        finally:
            await chat_lock.release()
            del svc

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
