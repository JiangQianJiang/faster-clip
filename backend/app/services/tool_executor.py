"""Unified tool execution with audit records."""

import asyncio
import inspect
import logging
import time
from typing import Any

from app.models.task import (
    _redact_sensitive_text,
    create_tool_run,
    finish_tool_run_error,
    finish_tool_run_rejected,
    finish_tool_run_success,
)
from app.tools import ToolResult, get_tool

_logger = logging.getLogger("app.tool_executor")


_TRANSIENT_ERRORS = (
    "timeout",
    "timed out",
    "connection",
    "network",
    "dns",
    "name resolution",
    "reset by peer",
    "broken pipe",
    "eof",
    "temporarily unavailable",
    "rate limit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
    "service unavailable",
    "连接超时",
    "网络异常",
    "网络错误",
)


class ToolExecutor:
    """Execute registered tools and persist the tool_runs lifecycle."""

    def __init__(self, *, retry_sleep_seconds: float = 2.0):
        self.retry_sleep_seconds = retry_sleep_seconds

    async def execute_tool(
        self,
        *,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        runtime_api_key: str | None = None,
        state_before: str | None = None,
    ) -> ToolResult:
        """Execute one tool call, retry transient failures once, and record it."""
        run_input = dict(tool_input)
        run_input["task_id"] = task_id
        run_id = create_tool_run(
            task_id=task_id,
            tool_name=tool_name,
            input_data=run_input,
            state_before=state_before,
        )
        started = time.monotonic()

        tool = get_tool(tool_name)
        if tool is None:
            result = ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
                user_message=f"未知工具: {tool_name}",
            )
            finish_tool_run_error(
                run_id,
                error_message=result.error or result.user_message,
                duration_ms=self._elapsed_ms(started),
            )
            return result

        exec_input = dict(tool_input)
        exec_input["task_id"] = task_id
        if runtime_api_key:
            exec_input["_runtime_api_key"] = runtime_api_key
        exec_kwargs = self._filter_execute_kwargs(tool, exec_input)

        result = await self._execute_with_retry(tool_name, tool, exec_kwargs)
        duration_ms = self._elapsed_ms(started)
        if result.success:
            finish_tool_run_success(
                run_id,
                output_data={
                    "success": result.success,
                    "data": result.data,
                    "user_message": result.user_message,
                },
                duration_ms=duration_ms,
            )
        else:
            finish_tool_run_error(
                run_id,
                error_message=result.error or result.user_message or f"{tool_name} failed",
                duration_ms=duration_ms,
            )
        return result

    def record_rejected_tool_call(
        self,
        *,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        state_before: str | None = None,
    ) -> ToolResult:
        """Persist a workflow-rejected tool call without executing the tool."""
        started = time.monotonic()
        run_input = dict(tool_input)
        run_input["task_id"] = task_id
        run_id = create_tool_run(
            task_id=task_id,
            tool_name=tool_name,
            input_data=run_input,
            state_before=state_before,
        )
        finish_tool_run_rejected(
            run_id,
            reason=reason,
            duration_ms=self._elapsed_ms(started),
            state_after=state_before,
        )
        return ToolResult(success=False, error=reason, user_message=reason)

    async def _execute_with_retry(
        self, tool_name: str, tool, exec_kwargs: dict[str, Any]
    ) -> ToolResult:
        result = ToolResult(success=False, error="Tool did not execute", user_message="工具未执行")
        for attempt in range(2):
            try:
                result = await tool.execute(**exec_kwargs)
            except Exception as exc:
                result = ToolResult(
                    success=False,
                    error=str(exc),
                    user_message=f"工具执行异常: {exc}",
                )

            if result.success:
                return result

            error_lower = (result.error or "").lower()
            is_transient = any(pattern in error_lower for pattern in _TRANSIENT_ERRORS)
            if not is_transient or attempt >= 1:
                return result

            _logger.warning(
                "tool_transient_retry tool=%s error=%s",
                tool_name,
                _redact_sensitive_text(result.error or ""),
            )
            if self.retry_sleep_seconds > 0:
                await asyncio.sleep(self.retry_sleep_seconds)

        return result

    @staticmethod
    def _filter_execute_kwargs(tool, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            sig = inspect.signature(tool.execute)
        except (ValueError, TypeError):
            return dict(tool_input)
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return dict(tool_input)
        return {key: value for key, value in tool_input.items() if key in sig.parameters}

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, int(round((time.monotonic() - started) * 1000)))
