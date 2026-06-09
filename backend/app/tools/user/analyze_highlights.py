"""User tool: analyze transcript for highlights."""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")

_MERGE_MIN_OVERLAP = 0.5  # ratio — clips with ≥50% overlap are considered the same
_MERGE_TIGHT_OVERLAP = (
    0.85  # ratio — only keep "success" if overlap ≥85%, else reset to pending
)


def _merge_clips_with_existing(
    new_clips: list[dict], existing_clips: list[dict]
) -> list[dict]:
    """Preserve export metadata (status, filepath, download_url, etc.)
    from existing clips that match newly-analyzed clips by timestamp.

    Matching is based on overlap ratio (one-to-one): once an existing clip
    is matched to a new clip it is removed from the candidate pool so it
    cannot be matched again.

    If the overlap is below ``_MERGE_TIGHT_OVERLAP`` the export metadata
    is still carried over for download-URL continuity, but ``status`` is
    reset to ``"pending"`` so the user knows the clip may need re-export.

    New clips with no match get ``status: "pending"``.  Existing clips that
    are NOT matched by any new clip are **preserved as-is** — this means
    running analysis with different focuses accumulates clips rather than
    replacing them (the user sees old + new cards instead of only the most
    recent analysis).
    """
    export_keys = (
        "status",
        "filepath",
        "thumbnail_path",
        "download_url",
        "thumbnail_url",
        "export_start_time_s",
        "export_end_time_s",
    )
    matched_existing: set[int] = set()

    def _overlap_ratio(a: dict, b: dict) -> float:
        """Intersection duration / min individual duration (0–1)."""
        a_s = float(a.get("start_time_s", 0))
        a_e = float(a.get("end_time_s", 0))
        b_s = float(b.get("start_time_s", 0))
        b_e = float(b.get("end_time_s", 0))
        inter = max(0.0, min(a_e, b_e) - max(a_s, b_s))
        min_dur = min(a_e - a_s, b_e - b_s)
        if min_dur <= 0:
            return 0.0
        return inter / min_dur

    def _match(new_clip: dict) -> tuple[int | None, float]:
        """Return (existing_index, overlap_ratio) of best *unmatched* match."""
        best_idx = None
        best_overlap = _MERGE_MIN_OVERLAP
        for i, ex in enumerate(existing_clips):
            if i in matched_existing:
                continue
            ratio = _overlap_ratio(new_clip, ex)
            if ratio > best_overlap:
                best_idx = i
                best_overlap = ratio
        return best_idx, best_overlap

    merged = []
    for nc in new_clips:
        idx, overlap = _match(nc)
        if idx is not None:
            matched_existing.add(idx)
            match = existing_clips[idx]
            # Only carry over export metadata from *successful* exports.
            # Failed exports (e.g. ffmpeg issues) have no valid filepaths
            # and must be re-exported, so reset to pending.
            if match.get("status") == "success":
                for k in export_keys:
                    if k in match:
                        nc[k] = match[k]
                # If the overlap isn't tight, the timestamps have shifted
                # enough that the old export may not match — reset to pending.
                if overlap < _MERGE_TIGHT_OVERLAP:
                    nc["status"] = "pending"
            else:
                nc["status"] = "pending"
        else:
            nc.setdefault("status", "pending")
        merged.append(nc)

    # Preserve unmatched existing clips — they represent previous analysis
    # results (possibly already exported) that the user expects to keep.
    for i, ec in enumerate(existing_clips):
        if i not in matched_existing:
            merged.append(ec)

    return merged


class AnalyzeHighlights(Tool):
    name = "analyze_highlights"
    description = (
        "Analyze the transcript to find highlight clips. "
        "Supports custom focus, optional time_ranges to constrain analysis scope, "
        "and configurable clip count."
    )
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "focus": {
                "type": "string",
                "description": "What kind of highlights to find (optional)",
            },
            "count": {
                "type": "integer",
                "description": "Max number of clips (1-5)",
                "default": 3,
                "minimum": 1,
                "maximum": 5,
            },
            "time_ranges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_time_s": {"type": "number"},
                        "end_time_s": {"type": "number"},
                    },
                    "required": ["start_time_s", "end_time_s"],
                },
                "description": "Optional list of time ranges to constrain analysis",
            },
        },
        "required": ["task_id"],
    }

    async def execute(
        self,
        task_id: str,
        focus: str | None = None,
        count: int = 3,
        time_ranges: list[dict] | None = None,
        _runtime_api_key: str = "",
    ) -> ToolResult:
        from app.models.task import get_task

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False, error="Task not found", user_message="任务不存在"
            )

        # Guard: reject mutations while task is processing (any stage)
        if task.get("status") in ("pending", "queued", "processing"):
            return ToolResult(
                success=False,
                error="Cannot analyze while task is processing",
                user_message="任务处理中，请等待完成后再试",
            )

        config = json.loads(task.get("config_json") or "{}")

        # Read transcript
        transcript_path = OUTPUT_DIR / task_id / "transcript.json"
        if not os.path.isfile(transcript_path):
            return ToolResult(
                success=False,
                error="Transcript not available",
                user_message="字幕不可用，请先提取字幕",
            )

        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
        except Exception as e:
            return ToolResult(success=False, error=str(e), user_message="字幕读取失败")

        if not segments:
            return ToolResult(
                success=False,
                error="Empty transcript",
                user_message="字幕为空，无法分析",
            )

        # Resolve API key: prefer runtime key, fall back to encrypted config key
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

        # Build prompt — allow focus override and time_ranges
        from app.services.analyzer import (
            AuthError,
            ConnectionError_,
            LLMError,
            ParseError,
            analyze,
            build_prompt,
            validate_clips,
        )

        clip_min = config.get("clip_min_duration", 30)
        clip_max = config.get("clip_max_duration", 120)

        # Validate time_ranges — any invalid entry fails the call
        analysis_segments = segments
        if time_ranges:
            valid_ranges = []
            for tr in time_ranges:
                s = float(tr.get("start_time_s", -1))
                e = float(tr.get("end_time_s", -1))
                if s < 0 or e <= s:
                    return ToolResult(
                        success=False,
                        error=f"Invalid time_range: start={s}, end={e}",
                        user_message=f"时间范围无效: start={s}, end={e}",
                    )
                valid_ranges.append((s, e))
            # Filter segments to those within any of the specified ranges
            analysis_segments = [
                seg
                for seg in segments
                if any(
                    r[0] <= seg["end_time_s"] and seg["start_time_s"] <= r[1]
                    for r in valid_ranges
                )
            ]
            if not analysis_segments:
                return ToolResult(
                    success=False,
                    error="No segments in specified time ranges",
                    user_message="指定时间范围内无字幕内容",
                )

        # Reuse the existing prompt builder but with optional focus
        prompt = build_prompt(
            analysis_segments,
            {"clip_min_duration": clip_min, "clip_max_duration": clip_max},
        )
        if focus:
            focus_line = f"\n额外要求：只关注「{focus}」相关的内容。\n"
            prompt = prompt.replace("\n字幕内容：\n", focus_line + "\n字幕内容：\n")

        if time_ranges:
            ranges_desc = "、".join(f"{s:.0f}s-{e:.0f}s" for s, e in valid_ranges)
            time_line = f"\n注意：只分析以下时间段的内容：{ranges_desc}。\n"
            prompt = prompt.replace("\n字幕内容：\n", time_line + "\n字幕内容：\n")

        try:
            raw_clips = analyze(
                api_key=api_key,
                base_url=config.get("llm_base_url", ""),
                model=config.get("llm_model", ""),
                prompt=prompt,
            )
        except AuthError:
            return ToolResult(
                success=False,
                error="LLM auth failed",
                user_message="LLM 认证失败，请检查 API Key",
            )
        except ConnectionError_:
            return ToolResult(
                success=False,
                error="LLM connection failed",
                user_message="LLM 连接失败，请稍后重试",
            )
        except ParseError as e:
            return ToolResult(
                success=False, error=str(e), user_message="LLM 返回解析失败，可以重试"
            )
        except LLMError as e:
            return ToolResult(
                success=False, error=str(e), user_message=f"分析失败: {e}"
            )

        # Get actual video duration for validation
        video_duration = float("inf")
        video_path = task.get("video_path", "")
        if video_path and os.path.isfile(video_path):
            try:
                from app.services.ffprobe import probe as _ffprobe

                info = _ffprobe(video_path)
                video_duration = info.duration
            except Exception:
                pass

        validated = validate_clips(
            raw_clips,
            video_duration=video_duration,
            min_duration=clip_min,
            max_duration=clip_max,
        )

        # If time_ranges were specified, filter clips to those within the requested windows
        if time_ranges:
            validated = [
                c
                for c in validated
                if any(
                    r[0] <= c["start_time_s"] and c["end_time_s"] <= r[1]
                    for r in valid_ranges
                )
            ]

        from app.models.task import update_task_status

        if not validated:
            # Clear stale clips and error state — the analysis found nothing.
            update_task_status(
                task_id,
                "done",
                stage=None,
                clips_json="[]",
                error_message=None,
                failed_stage=None,
                empty_clips_reason="AI 分析未找到符合要求的精彩片段",
            )
            return ToolResult(
                success=True,
                data={"clips": [], "count": 0},
                user_message="未找到符合要求的精彩片段",
            )

        # Merge with existing clips to preserve export metadata (status,
        # filepath, download_url, etc.) for clips that match previous analysis.
        existing_clips = json.loads(task.get("clips_json") or "[]")
        merged = _merge_clips_with_existing(validated, existing_clips)

        # Reset to "done" and clear stage / error state — re-analysis
        # success should recover from any previous failure.
        update_task_status(
            task_id,
            "done",
            stage=None,
            clips_json=json.dumps(merged, ensure_ascii=False),
            error_message=None,
            failed_stage=None,
            empty_clips_reason=None,
        )

        summary = "\n".join(
            f"片段 {i + 1}: [{c['start_time_s']:.0f}s-{c['end_time_s']:.0f}s] 评分 {c.get('score', '?')}/10 — {c.get('reason', '')}"
            for i, c in enumerate(merged)
        )

        return ToolResult(
            success=True,
            data={"clips": validated, "count": len(validated)},
            user_message=f"找到 {len(validated)} 个精彩片段：\n{summary}",
        )


_analyze_highlights = AnalyzeHighlights()
register(_analyze_highlights)
