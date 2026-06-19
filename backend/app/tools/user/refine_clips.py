"""User tool: refine clip boundaries (heuristic or LLM-assisted)."""

import json
import os
import re
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")

# Patterns for heuristic boundary adjustments
_EXPAND_PATTERN = re.compile(r"扩\s*(\d+)\s*秒")
_SHRINK_PATTERN = re.compile(r"缩\s*(\d+)\s*秒")
_TRIM_START_PATTERN = re.compile(r"去掉开头\s*(\d+)\s*秒")
_TRIM_END_PATTERN = re.compile(r"去掉结尾\s*(\d+)\s*秒|去掉末尾\s*(\d+)\s*秒")
_MERGE_PATTERN = re.compile(r"合并")


def _is_heuristic(instruction: str) -> bool:
    """Return True if the instruction can be handled without LLM."""
    patterns = [
        _EXPAND_PATTERN,
        _SHRINK_PATTERN,
        _TRIM_START_PATTERN,
        _TRIM_END_PATTERN,
        _MERGE_PATTERN,
    ]
    return any(p.search(instruction) for p in patterns)


def _apply_heuristic(
    clips: list[dict],
    clip_indices: list[int],
    instruction: str,
    video_duration: float = float("inf"),
) -> list[dict]:
    """Apply heuristic adjustments in-place on clips. Returns the modified clips."""
    indices = sorted(set(clip_indices))

    # Merge
    if _MERGE_PATTERN.search(instruction) and len(indices) >= 2:
        # Merge all specified clips: take earliest start and latest end
        merged_start = min(clips[i]["start_time_s"] for i in indices)
        merged_end = max(clips[i]["end_time_s"] for i in indices)
        merged_text = " ".join(clips[i].get("reason", "") for i in indices)
        # Remove in reverse order
        for i in sorted(indices, reverse=True):
            clips.pop(i)
        merged = {
            "start_time_s": merged_start,
            "end_time_s": merged_end,
            "score": 0,
            "reason": f"合并片段: {merged_text}",
            "status": "pending",
        }
        clips.insert(indices[0], merged)
        return clips

    # Expand / shrink / trim
    for idx in indices:
        if idx < 0 or idx >= len(clips):
            continue
        c = clips[idx]

        m_expand = _EXPAND_PATTERN.search(instruction)
        m_shrink = _SHRINK_PATTERN.search(instruction)
        m_trim_start = _TRIM_START_PATTERN.search(instruction)
        m_trim_end = _TRIM_END_PATTERN.search(instruction)

        if m_expand:
            delta = int(m_expand.group(1))
            c["start_time_s"] = max(0, c["start_time_s"] - delta)
            c["end_time_s"] = min(video_duration, c["end_time_s"] + delta)
        elif m_shrink:
            delta = int(m_shrink.group(1))
            new_start = c["start_time_s"] + delta
            new_end = c["end_time_s"] - delta
            # Clamp to valid range
            new_start = max(0, new_start)
            new_end = min(video_duration, new_end)
            # Ensure at least 1 second duration after shrinking
            if new_end - new_start < 1.0:
                mid = (c["start_time_s"] + c["end_time_s"]) / 2
                new_start = max(0, mid - 0.5)
                new_end = min(video_duration, mid + 0.5)
            # Final safety: ensure valid interval
            if new_end <= new_start:
                new_end = min(video_duration, new_start + 1.0)
            c["start_time_s"] = new_start
            c["end_time_s"] = new_end
        elif m_trim_start:
            delta = int(m_trim_start.group(1))
            c["start_time_s"] = min(c["end_time_s"] - 1, c["start_time_s"] + delta)
        elif m_trim_end:
            d1 = m_trim_end.group(1)
            d2 = m_trim_end.group(2)
            delta = int(d1 or d2 or 0)
            c["end_time_s"] = max(c["start_time_s"] + 1, c["end_time_s"] - delta)

        # Reset export status
        for key in (
            "status",
            "filepath",
            "thumbnail_path",
            "export_start_time_s",
            "export_end_time_s",
        ):
            if key == "status":
                c[key] = "pending"
            elif key in c:
                del c[key]

    return clips


def _get_video_duration(task_id: str) -> float:
    """Get video duration from task DB + ffprobe."""
    from app.models.task import get_task

    task = get_task(task_id)
    if task is None:
        return float("inf")
    video_path = task.get("video_path", "")
    if not video_path or not os.path.isfile(video_path):
        return float("inf")
    try:
        from app.services.ffprobe import probe

        info = probe(video_path)
        return info.duration
    except Exception:
        return float("inf")


class RefineClips(Tool):
    name = "refine_clips"
    description = (
        "Adjust clip boundaries or merge adjacent clips. "
        "Simple patterns like '扩X秒', '缩X秒', '合并', '去掉开头X秒' use heuristic rules. "
        "Semantic instructions like '保留完整对话' call the LLM to find natural break points."
    )
    user_facing = True
    requires_state = ["clips_ready"]
    produces_state = "clips_ready"
    destructive = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "clip_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Zero-based indices of clips to refine",
            },
            "instruction": {
                "type": "string",
                "description": "Refinement instruction in Chinese (e.g. '扩5秒', '保留完整对话')",
            },
        },
        "required": ["task_id", "clip_indices", "instruction"],
    }

    async def execute(
        self,
        task_id: str,
        clip_indices: list[int],
        instruction: str,
        _runtime_api_key: str = "",
    ) -> ToolResult:
        from app.models.task import get_task, update_task_status

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False,
                error="Task not found",
                user_message="任务不存在",
            )

        # Guard: reject mutations while task is processing (any stage)
        if task.get("status") in ("queued", "processing"):
            return ToolResult(
                success=False,
                error="Cannot refine clips while task is processing",
                user_message="任务处理中，无法调整片段，请等待完成",
            )

        try:
            clips = json.loads(task.get("clips_json") or "[]")
        except json.JSONDecodeError:
            clips = []

        # Validate indices
        invalid = [i for i in clip_indices if i < 0 or i >= len(clips)]
        if invalid:
            return ToolResult(
                success=False,
                error=f"Invalid indices: {invalid}",
                user_message=f"索引超出范围: {invalid}",
            )

        if not clips:
            return ToolResult(
                success=False,
                error="No clips to refine",
                user_message="没有可调整的片段",
            )

        video_duration = _get_video_duration(task_id)

        if _is_heuristic(instruction):
            clips = _apply_heuristic(clips, clip_indices, instruction, video_duration)
            mode = "heuristic"
        else:
            # LLM-assisted refinement: get surrounding transcript and call LLM
            config = json.loads(task.get("config_json") or "{}")
            api_key = _runtime_api_key
            if not api_key:
                from app.crypto import decrypt_api_key

                encrypted_key = config.get("llm_api_key", "")
                if encrypted_key:
                    try:
                        api_key = decrypt_api_key(encrypted_key)
                    except Exception:
                        return ToolResult(
                            success=False,
                            error="API key decryption failed",
                            user_message="API Key 解密失败",
                        )
            if not api_key:
                return ToolResult(
                    success=False,
                    error="No API key configured",
                    user_message="未配置 LLM API Key",
                )

            # Read transcript for context
            transcript_path = OUTPUT_DIR / task_id / "transcript.json"
            if not os.path.isfile(transcript_path):
                return ToolResult(
                    success=False,
                    error="Transcript not available",
                    user_message="字幕不可用，无法进行语义调整",
                )

            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)

            for idx in clip_indices:
                clip = clips[idx]
                # Collect surrounding 30s of transcript
                ctx_segs = []
                for seg in segments:
                    if (
                        seg["start_time_s"] >= clip["start_time_s"] - 30
                        and seg["end_time_s"] <= clip["end_time_s"] + 30
                    ):
                        ctx_segs.append(seg)

                from anthropic import Anthropic

                ctx_text = "\n".join(
                    f"[{s['start_time_s']:.1f}s-{s['end_time_s']:.1f}s] {s.get('text', '')}"
                    for s in ctx_segs
                )
                prompt = (
                    f"当前片段的范围是 [{clip['start_time_s']:.1f}s, {clip['end_time_s']:.1f}s]。\n"
                    f"用户的调整要求：{instruction}\n\n"
                    f"周围字幕上下文：\n{ctx_text}\n\n"
                    f"请根据用户要求和上下文，确定更合适的片段边界，返回JSON格式：\n"
                    f'{{"start_time_s": <float>, "end_time_s": <float>, "reason": "<中文理由>"}}\n'
                    f"只返回JSON，不要其他内容。"
                )

                llm_failed = False
                try:
                    client = Anthropic(
                        api_key=api_key,
                        base_url=config.get("llm_base_url", "").rstrip("/") or None,
                    )
                    resp = client.messages.create(
                        model=config.get("llm_model", "claude-sonnet-4-20250514"),
                        max_tokens=512,
                        system="你是一个专业的视频剪辑助手。只返回要求的JSON格式，不要其他内容。",
                        messages=[{"role": "user", "content": prompt}],
                        timeout=60.0,
                    )
                    text = ""
                    for block in resp.content:
                        if hasattr(block, "text"):
                            text += block.text

                    import re as _re

                    json_match = _re.search(r'\{[^{}]*"start_time_s"[^{}]*\}', text)
                    if not json_match:
                        json_match = _re.search(r"\{[^}]+\}", text)
                    if json_match:
                        refined = json.loads(json_match.group(0))
                        new_start = float(
                            refined.get("start_time_s", clip["start_time_s"])
                        )
                        new_end = float(refined.get("end_time_s", clip["end_time_s"]))
                        # Clamp both bounds to [0, video_duration]
                        new_start = max(0, min(new_start, video_duration - 1))
                        new_end = max(new_start + 1, min(new_end, video_duration))
                        if new_end > new_start:
                            clip["start_time_s"] = new_start
                            clip["end_time_s"] = new_end
                        clip["reason"] = refined.get("reason", clip.get("reason", ""))
                    else:
                        llm_failed = True
                except Exception:
                    llm_failed = True

                if llm_failed:
                    return ToolResult(
                        success=False,
                        error="LLM refinement failed to return valid boundaries",
                        user_message="LLM 调整失败，未能返回有效边界。请尝试用更具体的指令（如'扩5秒'）",
                    )

                # Reset export status
                for key in (
                    "status",
                    "filepath",
                    "thumbnail_path",
                    "export_start_time_s",
                    "export_end_time_s",
                ):
                    if key == "status":
                        clip[key] = "pending"
                    elif key in clip:
                        del clip[key]

            mode = "llm"

        update_task_status(
            task_id,
            task["status"],
            clips_json=json.dumps(clips, ensure_ascii=False),
        )

        return ToolResult(
            success=True,
            data={"clips": clips, "mode": mode},
            user_message=f"已调整 {len(clip_indices)} 个片段（{mode}模式）",
        )


_refine_clips = RefineClips()
register(_refine_clips)
