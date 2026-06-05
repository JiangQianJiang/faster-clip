"""Chat orchestration service — conversation engine for AI mode."""

import asyncio
import json
import logging
import time as time_mod
from collections.abc import AsyncGenerator
from typing import Any

from anthropic import Anthropic, AsyncAnthropic

from app.logging_config import TaskContextAdapter
from app.tools import ToolResult, get_tool, get_tool_schemas

_logger = TaskContextAdapter(logging.getLogger("app.chat"), {})

CHECKPOINT_TOOLS = {
    "extract_embedded_subtitles",
    "kernel_run_asr",
    "run_asr",
    "analyze_highlights",
    "export_clips",
    "add_clip",
    "refine_clips",
    "delete_clip",
}

# Tools whose failure should mark the task as error.
# Independent of CHECKPOINT_TOOLS so that fatal error handling works
# regardless of the active checkpoint mode.
FATAL_TOOLS = {
    "extract_embedded_subtitles",
    "kernel_run_asr",
    "analyze_highlights",
    "export_clips",
}

# Checkpoint tools whose failure should NOT mark the task as error.
# These are edit/management tools where validation failures (out-of-range index,
# invalid time range, etc.) are normal user/AI mistakes, not pipeline failures.
_NON_FATAL_CHECKPOINT_TOOLS = {"add_clip", "refine_clips", "delete_clip"}

# Tools that are considered destructive — used by "selective" checkpoint mode.
_DESTRUCTIVE_TOOLS = {"export_clips", "delete_clip", "refine_clips"}

# API key patterns to redact before storing history
import re

KEY_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9_-]+"),
    re.compile(r"sk-[a-zA-Z0-9_-]+"),
]


def _redact_keys(text: str) -> str:
    """Replace API key patterns with [REDACTED]."""
    for pattern in KEY_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _redact_value(value):
    """Recursively redact API keys, preserving JSON types.

    Strings are pattern-redacted; dicts/lists are recursed into;
    primitives pass through unchanged.
    """
    if isinstance(value, str):
        return _redact_keys(value)
    if isinstance(value, dict):
        return {_redact_keys(k): _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(i) for i in value]
    return value


def _redact_message(msg: dict) -> dict:
    """Deep-redact API keys from a message dict, preserving structure."""
    return _redact_value(msg)


class ChatHistoryConflict(Exception):
    """Raised when chat history cannot be saved due to a version conflict."""
    pass


class ChatService:
    """Manages a conversation for a single task.

    Responsibilities:
    - Load/save chat history from the task's chat_history_json field
    - Build system context from task state (transcript, clips)
    - Run the Anthropic tool-calling loop
    - Detect checkpoints and emit pause events
    - Generate SSE (Server-Sent Events) for the frontend
    """

    def __init__(
        self,
        task_id: str,
        llm_config: dict,
        api_key: str,
        checkpoint_mode: str = "auto",
    ):
        """
        Args:
            task_id: Task UUID
            llm_config: dict with llm_base_url, llm_model
            api_key: Decrypted LLM API key (not stored)
            checkpoint_mode: One of "auto" (no pauses), "confirm" (all
                checkpoint tools pause), or "selective" (only destructive
                tools pause).  Default is "auto".
        """
        if checkpoint_mode not in ("auto", "confirm", "selective"):
            raise ValueError(
                f"Invalid checkpoint_mode '{checkpoint_mode}'. "
                "Must be one of: auto, confirm, selective"
            )
        self.checkpoint_mode = checkpoint_mode
        self.task_id = task_id
        self.llm_config = llm_config
        self.runtime_api_key = api_key  # in-memory only, never persisted
        self.client = Anthropic(
            api_key=api_key,
            base_url=llm_config.get("llm_base_url", "").rstrip("/") or None,
        )
        self.async_client = AsyncAnthropic(
            api_key=api_key,
            base_url=llm_config.get("llm_base_url", "").rstrip("/") or None,
        )
        self.model = llm_config.get("llm_model", "claude-sonnet-4-20250514")
        self.history: list[dict] = []
        self._chat_version: int = 0

    async def _load_history(self) -> None:
        """Load conversation history from the database.

        Also sanitizes any malformed thinking blocks that may have been
        persisted by older versions of _block_to_dict (which didn't handle
        the ``thinking`` content-block attribute).
        """
        from app.models.task import get_task

        task = get_task(self.task_id)
        if task is None:
            self.history = []
            self._chat_version = 0
            return

        self._chat_version = task.get("chat_version", 0)

        raw = task.get("chat_history_json") or ""
        if not raw:
            self.history = []
            return

        try:
            self.history = json.loads(raw)
        except json.JSONDecodeError:
            logging.warning("chat_history_json parse failed for task %s", self.task_id)
            self.history = []

        # Strip malformed thinking blocks — older _block_to_dict wrote
        # {"type": "thinking"} without the required ``thinking`` field,
        # which causes the API to reject the whole request.
        cleaned = False
        for msg in self.history:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            new_content = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    if "thinking" not in block:
                        cleaned = True
                        continue  # drop malformed block
                    # Even well-formed thinking blocks must not be sent
                    # back to the API — drop them too.
                    cleaned = True
                    continue
                new_content.append(block)
            if len(new_content) != len(content):
                msg["content"] = new_content

        if cleaned:
            logging.info(
                "Stripped malformed thinking blocks from history for task %s",
                self.task_id,
            )

    def _build_context(self, checkpoint_context: str = "") -> str:
        """Build system prompt context from current task state.

        Args:
            checkpoint_context: Optional summary of the checkpoint the user
                is responding to. Injected into the system prompt so the LLM
                has immediate context for ordinal references like "删掉第三个".
        """
        from app.models.task import get_task

        task = get_task(self.task_id)
        if task is None:
            return "You are a helpful video clipping assistant."

        status = task.get("status", "unknown")
        stage = task.get("stage", "")
        clips_json = task.get("clips_json") or "[]"

        try:
            clips = json.loads(clips_json)
        except json.JSONDecodeError:
            clips = []

        parts = [
            "You are a live-stream video clipping assistant. "
            "Help the user extract subtitles, find highlight clips, and export them as MP4 videos.",
            "",
            f"Current task: {task.get('video_filename', 'unknown')}",
            f"Status: {status}" + (f" / {stage}" if stage else ""),
            f"Subtitles: {task.get('subtitle_segment_count', 0)} segments",
            f"Clips found: {len(clips)}",
        ]

        # Summarize existing clips
        for i, c in enumerate(clips):
            start = c.get("start_time_s", 0)
            end = c.get("end_time_s", 0)
            score = c.get("score", "?")
            reason = c.get("reason", "")
            status_s = c.get("status", "")
            parts.append(
                f"  Clip {i + 1}: [{start:.0f}s-{end:.0f}s] score={score} "
                f"{reason} ({status_s})"
            )

        parts.append("")

        # Build workflow instruction based on checkpoint mode
        if self.checkpoint_mode == "auto":
            parts.append(
                "Workflow: use kernel tools to extract subtitles -> analyze highlights "
                "-> export clips. Execute tools as needed and explain what you're doing as you go. "
                "Continue autonomously without pausing for confirmation."
            )
        elif self.checkpoint_mode == "selective":
            parts.append(
                "Workflow: use kernel tools to extract subtitles -> analyze highlights "
                "-> export clips. When making destructive changes (export, delete, refine clips), "
                "pause and let the user review before continuing. For analysis and subtitle tools, "
                "continue autonomously."
            )
        else:  # confirm
            parts.append(
                "Workflow: use kernel tools to extract subtitles -> analyze highlights "
                "-> export clips. At each major step, pause and let the user review before continuing. "
                "Always explain what you're about to do and confirm with the user before taking action."
            )

        # Tool error handling guidance
        parts.append("")
        parts.append(
            "When a tool fails, analyze the error before retrying:\n"
            "- If the error is about invalid parameters (wrong index, out-of-range time, "
            "bad format), fix your parameters and call the tool again.\n"
            "- If the error is permanent (auth failure, task not found, no transcript "
            "available, video missing), report it to the user — retrying won't help.\n"
            "- If the error is a transient network issue, the system will auto-retry once; "
            "if it still fails, tell the user to check their network."
        )

        if checkpoint_context:
            parts.append("")
            parts.append(checkpoint_context)

        return "\n".join(parts)

    def _build_checkpoint_context(self) -> str:
        """Build a context summary from the most recent unconsumed checkpoint.

        Scans the history for the last assistant message that has an
        unconsumed ``_checkpoint``, extracts the completed tool names and
        their result summaries, and returns a string suitable for injection
        into the system prompt.

        This gives the LLM immediate context when the user responds with
        ordinal references like "删掉第三个" or "第一个扩5秒" — it no
        longer needs to re-parse tool_result JSON to map ordinals to indices.
        """
        if not self.history:
            return ""

        # Find the last assistant message with an unconsumed checkpoint
        for i in range(len(self.history) - 1, -1, -1):
            msg = self.history[i]
            cp = msg.get("_checkpoint")
            if not (isinstance(cp, dict) and cp.get("consumed") is False):
                continue

            # Extract tool names from this assistant message's content blocks
            content = msg.get("content", [])
            if not isinstance(content, list):
                return ""

            tool_names: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "")
                    if name:
                        tool_names.append(name)

            if not tool_names:
                return ""

            # Find the corresponding tool result (next message in history)
            summaries: list[str] = []
            if i + 1 < len(self.history):
                next_msg = self.history[i + 1]
                next_content = next_msg.get("content", [])
                if isinstance(next_content, list):
                    for block in next_content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "tool_result"
                        ):
                            try:
                                result = json.loads(block.get("content", "{}"))
                                if result.get("success"):
                                    um = result.get("user_message", "")
                                    if um:
                                        summaries.append(um)
                            except (json.JSONDecodeError, TypeError):
                                pass

            lines = [f"You just completed: {', '.join(tool_names)}."]
            if summaries:
                lines.append("Result:")
                lines.extend(
                    f"  [{tool_names[i]}] {s}" if i < len(tool_names) else f"  {s}"
                    for i, s in enumerate(summaries)
                )
            lines.append("The user's message below is a response to this result.")

            return "\n".join(lines)

        return ""

    async def _save_history(self) -> None:
        """Save conversation history to the database with version check.

        Uses conditional update to prevent silent overwrites of concurrent edits.
        Trims large tool results before saving.
        """
        from app.models.task import update_chat_history_if_version
        from app.utils import utcnow_iso

        # Trim large tool results before saving
        trimmed = self._trim_history(self.history)
        redacted = [_redact_message(m) for m in trimmed]
        serialized = json.dumps(redacted, ensure_ascii=False)
        now = utcnow_iso()

        success = update_chat_history_if_version(
            self.task_id,
            expected_chat_version=self._chat_version,
            chat_history_json=serialized,
            chat_updated_at=now,
        )

        if success:
            self._chat_version += 1
        else:
            _logger.warning(
                "chat_history_version_conflict",
                extra={"task_id": self.task_id, "expected": self._chat_version},
            )
            raise ChatHistoryConflict(
                f"聊天历史已被其他会话修改（期望版本: {self._chat_version}），请刷新后重试"
            )

    def _trim_history(self, history: list[dict]) -> list[dict]:
        """Trim large tool results to stay within configurable char limit."""
        max_chars = int(self._get_env("CHAT_TOOL_RESULT_MAX_CHARS", "4000"))
        trimmed = []
        for msg in history:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                new_content = []
                for block in msg["content"]:
                    if block.get("type") == "tool_result":
                        content = block.get("content", "")
                        if isinstance(content, str) and len(content) > max_chars:
                            block = {**block, "content": content[:max_chars] + f"\n... [截断，原 {len(content)} 字符]", "_trimmed": True}
                    new_content.append(block)
                msg = {**msg, "content": new_content}
            trimmed.append(msg)
        return trimmed

    @staticmethod
    def _get_env(key: str, default: str) -> str:
        import os
        return os.getenv(key, default)

    # Errors that are clearly transient — worth one auto-retry before
    # surfacing to the LLM.  Everything else (parameter errors, auth,
    # not-found, parse failures, business-logic rejections) is returned
    # immediately so the agent can decide whether to fix its input and
    # call again, try a different tool, or report to the user.
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

    async def _execute_tool_with_retry(
        self,
        tool_name: str,
        tool_input: dict,
    ) -> ToolResult:
        """Execute a tool with a single auto-retry for transient failures.

        Only network / timeout / server errors trigger an automatic retry
        (one extra attempt after a 2-second pause).  All other failures —
        parameter errors, auth failures, not-found, parse errors, etc. —
        are returned immediately so the LLM can decide the next step:
        fix the parameters and call again, try a different approach, or
        tell the user what went wrong.
        """
        import inspect as _inspect

        tool = get_tool(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
                user_message=f"未知工具: {tool_name}",
            )

        # Only pass kwargs the tool's execute() actually declares.
        try:
            sig = _inspect.signature(tool.execute)
            exec_kwargs = {
                k: v for k, v in tool_input.items() if k in sig.parameters
            }
        except (ValueError, TypeError):
            exec_kwargs = dict(tool_input)

        for attempt in range(2):  # initial + 1 auto-retry
            try:
                result = await tool.execute(**exec_kwargs)
            except Exception as e:
                result = ToolResult(
                    success=False,
                    error=str(e),
                    user_message=f"工具执行异常: {e}",
                )

            if result.success:
                return result

            # Auto-retry only for transient errors; surface everything else.
            error_lower = (result.error or "").lower()
            is_transient = any(p in error_lower for p in self._TRANSIENT_ERRORS)

            if not is_transient or attempt >= 1:
                return result

            logging.warning(
                "Tool %s failed with transient error, retrying in 2s: %s",
                tool_name,
                result.error,
            )
            await asyncio.sleep(2)

        return result  # unreachable; kept for type completeness

    # Per-tool checkpoint action definitions (static, no instance state).
    _CHECKPOINT_ACTION_MAP: dict[str, list[dict]] = {
        "extract_embedded_subtitles": [
            {"label": "打开字幕编辑器", "action": "open_editor"},
            {"label": "继续", "action": "continue"},
        ],
        "run_asr": [
            {"label": "打开字幕编辑器", "action": "open_editor"},
            {"label": "继续", "action": "continue"},
        ],
        "analyze_highlights": [
            {"label": "预览片段", "action": "preview"},
            {"label": "继续", "action": "continue"},
        ],
        "export_clips": [
            {"label": "浏览导出片段", "action": "preview"},
            {"label": "继续", "action": "continue"},
        ],
        "add_clip": [
            {"label": "预览片段", "action": "preview"},
            {"label": "继续", "action": "continue"},
        ],
        "refine_clips": [
            {"label": "预览片段", "action": "preview"},
            {"label": "继续", "action": "continue"},
        ],
        "delete_clip": [
            {"label": "预览片段", "action": "preview"},
            {"label": "继续", "action": "continue"},
        ],
    }

    @staticmethod
    def _checkpoint_actions(tool_names: list[str]) -> list[dict]:
        """Return deduplicated checkpoint actions for a list of successful checkpoint tool names.

        ``continue`` appears at most once (last).  Tool names not in the
        action map are silently skipped.
        """
        seen: set[str] = set()
        actions: list[dict] = []
        for name in tool_names:
            for a in ChatService._CHECKPOINT_ACTION_MAP.get(name, []):
                key = a["action"]
                if key == "continue":
                    if "continue" not in seen:
                        seen.add("continue")
                        actions.append(a)
                elif key not in seen:
                    seen.add(key)
                    actions.append(a)
        return actions

    @staticmethod
    def _api_messages(messages: list[dict]) -> list[dict]:
        """Return a deep copy of *messages* with all ``_``-prefixed keys
        recursively removed from dicts.  Strings (including JSON payloads
        such as ``tool_result.content``) are never parsed or modified.
        Lists are recursively processed.  The original structure is
        unchanged.
        """

        def _filter(value):
            if isinstance(value, dict):
                return {
                    k: _filter(v) for k, v in value.items() if not k.startswith("_")
                }
            if isinstance(value, list):
                return [_filter(v) for v in value]
            return value

        return _filter(messages)

    def _sse_event(self, event_type: str, data: Any) -> str:
        """Format an SSE event."""
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        return f"data: {payload}\n\n"

    async def _consume_checkpoints(self) -> None:
        """Mark every unconsumed ``_checkpoint`` in ``self.history`` as consumed.

        Called at the start of ``chat()`` so that sending a new message
        automatically consumes the previous checkpoint pause.
        """
        changed = False
        for msg in self.history:
            cp = msg.get("_checkpoint")
            if isinstance(cp, dict) and cp.get("consumed") is False:
                cp["consumed"] = True
                changed = True
        if changed:
            await self._save_history()

    async def chat(self, user_message: str) -> AsyncGenerator[str, None]:
        """Process a user message and yield SSE events.

        Args:
            user_message: Text input from the user.

        Yields:
            SSE-formatted strings for the frontend to consume.
        """
        # 1. Load history
        await self._load_history()

        # 2. Capture any pending checkpoint context before consuming it.
        #    This must happen before _consume_checkpoints() because that
        #    call marks the checkpoint consumed, erasing the signal we
        #    use to detect that the user is responding to a checkpoint.
        checkpoint_context = self._build_checkpoint_context()

        # 3. Consume any pending checkpoint from the previous turn
        await self._consume_checkpoints()

        # 4. Build context (with checkpoint summary if available)
        system_prompt = self._build_context(checkpoint_context)

        # 4. Add user message to history
        self.history.append({"role": "user", "content": user_message})

        # 4. Prepare tools — expose user-facing tools to the LLM
        tools = get_tool_schemas(for_user=True)

        # 5. Tool calling loop — use AsyncAnthropic streaming for real-time
        # token output. Each iteration makes one streaming LLM call, then
        # processes any tool_use blocks and loops if needed.
        #
        # Safety limit: prevent infinite retry loops when the LLM keeps
        # calling tools without making progress (e.g. retrying the same
        # failing call with slightly different parameters).
        _MAX_TOOL_CALL_ITERATIONS = 20
        _iteration = 0

        try:
            while _iteration < _MAX_TOOL_CALL_ITERATIONS:
                _iteration += 1
                yield self._sse_event("thinking", "正在思考...")

                # --- Streaming LLM call ---
                text_parts: list[str] = []
                llm_start = time_mod.monotonic()

                async with self.async_client.messages.stream(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=self._api_messages(self.history),
                    tools=tools,
                    timeout=120.0,
                ) as stream:
                    async for event in stream:
                        if (
                            event.type == "content_block_delta"
                            and getattr(event.delta, "type", None) == "text_delta"
                        ):
                            text_parts.append(event.delta.text)
                            yield self._sse_event("text_delta", event.delta.text)

                    final_msg = await stream.get_final_message()

                llm_duration = (time_mod.monotonic() - llm_start) * 1000
                _logger.info(
                    "llm.call",
                    extra={
                        "model": self.model,
                        "input_tokens": getattr(final_msg.usage, "input_tokens", None)
                        if hasattr(final_msg, "usage")
                        else None,
                        "output_tokens": getattr(final_msg.usage, "output_tokens", None)
                        if hasattr(final_msg, "usage")
                        else None,
                        "duration_ms": round(llm_duration, 1),
                        "stop_reason": final_msg.stop_reason,
                    },
                )

                # --- end_turn: final text response, save and exit ---
                if final_msg.stop_reason == "end_turn" or (
                    final_msg.stop_reason != "tool_use"
                    and final_msg.stop_reason is not None
                ):
                    full_text = "".join(text_parts)
                    if full_text:
                        yield self._sse_event("text", full_text)

                    self.history.append(
                        {
                            "role": "assistant",
                            "content": [
                                {"type": b.type, **self._block_to_dict(b)}
                                for b in final_msg.content
                                if b.type != "thinking"
                            ],
                        }
                    )
                    await self._save_history()
                    return

                # --- tool_use: execute tools ---
                if final_msg.stop_reason != "tool_use":
                    # Should not reach here, but guard against unexpected stop reasons
                    await self._save_history()
                    return

                # Build text + tool_use blocks from the final message
                tool_blocks = [b for b in final_msg.content if b.type == "tool_use"]
                text_blocks = [b for b in final_msg.content if b.type == "text"]

                # Yield any full text blocks (alongside tool_use) as reconciliation
                for block in text_blocks:
                    yield self._sse_event("text", block.text)

                # Add assistant response to history
                self.history.append(
                    {
                        "role": "assistant",
                        "content": [
                            {"type": b.type, **self._block_to_dict(b)}
                            for b in final_msg.content
                            if b.type != "thinking"
                        ],
                    }
                )
                assistant_msg = self.history[-1]

                if not tool_blocks:
                    break

                # Execute tools
                tool_results = []
                checkpoint_hit = False
                successful_checkpoint_tools: list[str] = []

                for block in tool_blocks:
                    tool_name = block.name
                    tool_use_id = block.id
                    tool_input = dict(block.input or {})

                    # Inject task_id and runtime key server-side
                    tool_input["task_id"] = self.task_id
                    if self.runtime_api_key:
                        tool_input["_runtime_api_key"] = self.runtime_api_key

                    yield self._sse_event(
                        "tool_start",
                        {
                            "tool": tool_name,
                            "tool_use_id": tool_use_id,
                            "input": {
                                k: v
                                for k, v in tool_input.items()
                                if k != "_runtime_api_key"
                            },
                        },
                    )

                    # Check unknown tool before executing
                    if get_tool(tool_name) is None:
                        yield self._sse_event(
                            "error",
                            {
                                "message": f"未知工具: {tool_name}",
                                "detail": f"Tool '{tool_name}' is not registered",
                            },
                        )
                        tool_results.append(
                            {
                                "tool_use_id": tool_use_id,
                                "content": json.dumps(
                                    {
                                        "success": False,
                                        "error": f"Unknown tool: {tool_name}",
                                        "user_message": f"未知工具: {tool_name}",
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                        self.history.append(
                            {
                                "role": "user",
                                "content": [
                                    {"type": "tool_result", **tr} for tr in tool_results
                                ],
                            }
                        )
                        await self._save_history()
                        return

                    tool_start = time_mod.monotonic()
                    result = await self._execute_tool_with_retry(tool_name, tool_input)
                    tool_duration = (time_mod.monotonic() - tool_start) * 1000
                    _logger.info(
                        "tool.execute",
                        extra={
                            "tool_name": tool_name,
                            "duration_ms": round(tool_duration, 1),
                            "success": result.success,
                        },
                    )

                    tool_results.append(
                        {
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(
                                {
                                    "success": result.success,
                                    "data": result.data,
                                    "error": result.error,
                                    "user_message": result.user_message,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )

                    yield self._sse_event(
                        "tool_result",
                        {
                            "tool": tool_name,
                            "tool_use_id": tool_use_id,
                            "success": result.success,
                            "user_message": result.user_message,
                        },
                    )

                    # Update task error state for fatal tool failures.
                    # Only skip processing-guard refusals — the tool rejected
                    # because the task is currently being processed by the
                    # worker. All other failures in fatal tools mark the task
                    # as error, including missing video, auth errors, etc.
                    if not result.success and tool_name in FATAL_TOOLS:
                        _error_text = (result.error or "") + (result.user_message or "")
                        _is_guard_refusal = (
                            "while task is processing" in _error_text
                            or "任务处理中" in _error_text
                        )
                        if not _is_guard_refusal:
                            from app.models.task import update_task_status as _update

                            _update(
                                self.task_id,
                                "error",
                                failed_stage=tool_name,
                                error_message=result.error
                                or result.user_message
                                or f"{tool_name} failed",
                            )

                    if result.success and tool_name in CHECKPOINT_TOOLS:
                        # Gate checkpoint emission on the active mode.
                        if self.checkpoint_mode == "confirm" or (
                            self.checkpoint_mode == "selective"
                            and tool_name in _DESTRUCTIVE_TOOLS
                        ):
                            checkpoint_hit = True
                            successful_checkpoint_tools.append(tool_name)
                        # "auto" mode: never set checkpoint_hit

                # Add tool results to history
                self.history.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", **tr} for tr in tool_results
                        ],
                    }
                )

                # Checkpoint: pause and let user review
                if checkpoint_hit:
                    actions = ChatService._checkpoint_actions(
                        successful_checkpoint_tools
                    )
                    _logger.info(
                        "checkpoint",
                        extra={
                            "checkpoint_tools": successful_checkpoint_tools,
                            "actions": [a["action"] for a in actions],
                        },
                    )
                    assistant_msg["_checkpoint"] = {
                        "actions": actions,
                        "consumed": False,
                    }
                    yield self._sse_event(
                        "checkpoint",
                        {
                            "tools_completed": successful_checkpoint_tools,
                            "actions": actions,
                            "message": "操作完成，请确认后继续",
                        },
                    )
                    await self._save_history()
                    return

                # Continue the tool-calling loop
                yield self._sse_event("thinking", "继续处理...")
            else:
                # Loop limit exceeded — agent is stuck retrying
                _logger.error(
                    "Tool call iteration limit (%d) exceeded for task %s",
                    _MAX_TOOL_CALL_ITERATIONS,
                    self.task_id,
                )
                yield self._sse_event(
                    "error",
                    {
                        "message": "对话轮次过多，请检查任务状态后重新发送消息",
                        "detail": f"Exceeded {_MAX_TOOL_CALL_ITERATIONS} tool-calling iterations",
                    },
                )
                await self._save_history()
                return

        except Exception as e:
            logging.exception("ChatService error for task %s", self.task_id)
            error_msg = str(e)
            if (
                "401" in error_msg
                or "403" in error_msg
                or "unauthorized" in error_msg.lower()
            ):
                user_msg = "LLM 认证失败，请检查 API Key 配置"
            elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                user_msg = "LLM 服务连接超时，请检查网络或稍后重试"
            else:
                user_msg = f"对话出错: {error_msg[:200]}"

            yield self._sse_event(
                "error",
                {
                    "message": user_msg,
                    "detail": error_msg[:500],
                },
            )
            # Save history even on error — the user's message has already
            # been appended and should not be lost.
            await self._save_history()
            return

        # 7. Save history
        await self._save_history()

    def _block_to_dict(self, block) -> dict:
        """Convert an Anthropic content block to a serializable dict."""
        d = {}
        if hasattr(block, "text"):
            d["text"] = block.text
        if hasattr(block, "name"):
            d["name"] = block.name
        if hasattr(block, "id"):
            d["id"] = block.id
        if hasattr(block, "input"):
            d["input"] = (
                _redact_value(dict(block.input))
                if isinstance(block.input, dict)
                else _redact_keys(str(block.input or ""))
            )
        if hasattr(block, "thinking"):
            d["thinking"] = block.thinking
        return d
