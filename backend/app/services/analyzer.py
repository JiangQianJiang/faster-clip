"""LLM-based highlight analysis using Anthropic-format API."""

import json
import re

from anthropic import Anthropic


class LLMError(Exception):
    pass


class AuthError(LLMError):
    pass


class ConnectionError_(LLMError):
    pass


class ParseError(LLMError):
    pass


SYSTEM_PROMPT = """你是一个专业的直播内容剪辑师。请分析以下直播字幕，找出最精彩的 1-3 个片段。

要求：
- 每个片段 {min_dur}-{max_dur} 秒
- 返回 JSON 数组格式（只返回 JSON，不要其他内容）
- 精彩定义：情绪高潮、冲突转折、关键信息、意外事件、共鸣时刻

输出格式：
[{{"start_time_s": <float>, "end_time_s": <float>, "score": <float 0-10>, "reason": "<中文理由>"}}]

字幕内容：
{transcript}"""


RETRY_PROMPT_SUFFIX = """
请严格只返回 JSON 数组，不要包含 markdown 代码块标记或其他文本。
格式必须为：[{{"start_time_s": ..., "end_time_s": ..., "score": ..., "reason": "..."}}]
"""


def build_prompt(segments: list[dict], config: dict) -> str:
    lines = []
    for seg in segments:
        start = seg["start_time_s"]
        end = seg["end_time_s"]
        text = seg["text"]
        timestamp = f"[{_fmt_time(start)} -> {_fmt_time(end)}]"
        lines.append(f"{timestamp} {text}")

    transcript = "\n".join(lines)
    return SYSTEM_PROMPT.format(
        min_dur=config.get("clip_min_duration", 30),
        max_dur=config.get("clip_max_duration", 120),
        transcript=transcript,
    )


def _fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:05.2f}"


def analyze(
    prompt: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int = 120,
) -> list[dict]:
    client = Anthropic(api_key=api_key, base_url=base_url.rstrip("/"))
    messages = [{"role": "user", "content": prompt}]
    system = "你是一个专业的直播内容剪辑师。按要求的 JSON 格式返回结果。"

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
            timeout=timeout,
        )
    except Exception as e:
        msg = str(e).lower()
        if any(c in msg for c in ("401", "403", "unauthorized", "forbidden")):
            raise AuthError(f"LLM API key 无效: {e}")
        if any(c in msg for c in ("timeout", "connection", "connect", "refused")):
            raise ConnectionError_(f"LLM 服务连接失败: {e}")
        raise LLMError(f"LLM API 调用失败: {e}")

    text = "".join(block.text for block in resp.content if hasattr(block, "text"))

    try:
        parsed = _extract_json(text)
    except ParseError:
        try:
            resp2 = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                messages=messages
                + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": RETRY_PROMPT_SUFFIX},
                ],
                timeout=timeout,
            )
            text2 = "".join(
                block.text for block in resp2.content if hasattr(block, "text")
            )
            parsed = _extract_json(text2)
        except Exception as e:
            if isinstance(e, (AuthError, ConnectionError_)):
                raise
            raise ParseError("LLM 返回的 JSON 无法解析（已重试一次）")

    return parsed


def _extract_json(text: str) -> list[dict]:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()

    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        raise ParseError("未在响应中找到 JSON 数组")

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise ParseError("JSON 解析失败")

    if not isinstance(parsed, list):
        raise ParseError("JSON 根元素不是数组")

    return parsed


def validate_clips(
    clips: list[dict],
    video_duration: float,
    min_duration: float,
    max_duration: float,
) -> list[dict]:
    # Step 1: Parse candidates defensively, clamp/reject by bounds
    candidates = []
    for raw in clips:
        try:
            start = float(raw.get("start_time_s", -1))
            end = float(raw.get("end_time_s", -1))
        except (ValueError, TypeError):
            continue
        if start >= end:
            continue
        tolerance = 10.0
        if start < -tolerance or end > video_duration + tolerance:
            continue
        start = max(start, 0.0)
        end = min(end, video_duration)
        try:
            score = float(raw.get("score", 0))
        except (ValueError, TypeError):
            score = 0.0
        candidates.append(
            dict(
                start_time_s=start,
                end_time_s=end,
                score=score,
                reason=str(raw.get("reason", "")),
            )
        )

    if not candidates:
        return []

    # Step 2: Sort by start time for overlap repair
    candidates.sort(key=lambda c: c["start_time_s"])
    candidates = _resolve_overlaps(candidates)

    # Step 3: Enforce max_duration before min repair
    for c in candidates:
        dur = c["end_time_s"] - c["start_time_s"]
        if dur > max_duration:
            c["end_time_s"] = c["start_time_s"] + max_duration

    # Step 4: Expand short clips within non-overlapping space and max_duration
    for i, c in enumerate(candidates):
        dur = c["end_time_s"] - c["start_time_s"]
        if dur >= min_duration:
            continue
        needed = min_duration - dur
        # Expand forward (after)
        limit_after = video_duration
        if i + 1 < len(candidates):
            limit_after = min(limit_after, candidates[i + 1]["start_time_s"])
        available_after = max(0.0, limit_after - c["end_time_s"])
        expand_after = min(needed, available_after)
        c["end_time_s"] += expand_after
        needed -= expand_after
        # Expand backward (before)
        if needed > 0:
            limit_before = 0.0
            if i > 0:
                limit_before = max(limit_before, candidates[i - 1]["end_time_s"])
            available_before = max(0.0, c["start_time_s"] - limit_before)
            expand_before = min(needed, available_before)
            c["start_time_s"] -= expand_before
        # Clamp to max_duration
        if c["end_time_s"] - c["start_time_s"] > max_duration:
            c["end_time_s"] = c["start_time_s"] + max_duration

    # Step 5: Re-resolve overlaps after expansion
    candidates = _resolve_overlaps(candidates)

    # Step 6: Final invariant check
    result = []
    for c in candidates:
        dur = c["end_time_s"] - c["start_time_s"]
        if (
            c["start_time_s"] >= 0
            and c["end_time_s"] <= video_duration
            and c["start_time_s"] < c["end_time_s"]
            and min_duration <= dur <= max_duration
        ):
            result.append(c)

    # Step 7: Sort by score descending, cap to 3
    result.sort(key=lambda c: c["score"], reverse=True)
    return result[:3]


def _resolve_overlaps(clips: list[dict]) -> list[dict]:
    if len(clips) <= 1:
        return clips
    result = [clips[0]]
    for i in range(1, len(clips)):
        if clips[i]["start_time_s"] < result[-1]["end_time_s"]:
            clips[i]["start_time_s"] = result[-1]["end_time_s"]
        if clips[i]["start_time_s"] >= clips[i]["end_time_s"]:
            continue
        result.append(clips[i])
    return result
