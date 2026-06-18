"""User tool: regenerate local subtitles from the existing transcript."""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")


def _remove_display_breaks(segments: list[dict]) -> list[dict]:
    """Remove generated display newlines before re-running the line breaker."""
    cleaned = []
    for seg in segments:
        entry = dict(seg)
        text = str(entry.get("text", ""))
        entry["text"] = text.replace("\n", "")
        cleaned.append(entry)
    return cleaned


def _restore_word_timings(
    valid_segments: list[dict],
    source_segments: list[dict],
) -> list[dict]:
    """Copy word-level timings from matching source segments after validation."""
    words_by_key: dict[tuple[float, float, str], list[list[dict]]] = {}
    for seg in source_segments:
        words = seg.get("words")
        if not isinstance(words, list):
            continue
        try:
            key = (
                round(float(seg["start_time_s"]), 3),
                round(float(seg["end_time_s"]), 3),
                str(seg.get("text", "")).strip(),
            )
        except (KeyError, TypeError, ValueError):
            continue
        words_by_key.setdefault(key, []).append(words)

    restored = []
    for seg in valid_segments:
        entry = dict(seg)
        key = (
            entry["start_time_s"],
            entry["end_time_s"],
            entry["text"],
        )
        matching_words = words_by_key.get(key)
        if matching_words:
            entry["words"] = matching_words.pop(0)
        restored.append(entry)
    return restored


class RegenerateSubtitles(Tool):
    name = "regenerate_subtitles"
    description = (
        "Regenerate subtitles locally from the existing transcript: reflow line "
        "breaks, re-split long segments, and refresh clip SRT/VTT/ASS sidecar "
        "files. Does not call ASR, does not transcribe audio, and does not "
        "require any API key. Use this when the user asks to regenerate, rebuild, "
        "refresh, or reformat existing subtitles. If the user asks to re-recognize "
        "speech from audio, use run_asr instead."
    )
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "regenerate_clip_files": {
                "type": "boolean",
                "description": "Whether to refresh existing clip SRT/VTT/ASS files",
                "default": True,
            },
        },
        "required": ["task_id"],
    }

    async def execute(
        self,
        task_id: str,
        regenerate_clip_files: bool = True,
    ) -> ToolResult:
        from app.models.task import get_task, update_task_status

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False, error="Task not found", user_message="任务不存在"
            )

        if task.get("status") in ("pending", "queued", "processing"):
            return ToolResult(
                success=False,
                error="Cannot regenerate subtitles while task is processing",
                user_message="任务处理中，无法重新生成字幕，请等待完成",
            )

        output_dir = OUTPUT_DIR / task_id
        transcript_path = output_dir / "transcript.json"
        if not os.path.isfile(transcript_path):
            return ToolResult(
                success=False,
                error="Transcript not found",
                user_message="字幕文件不存在，请先提取字幕或导入字幕",
            )

        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                error="Transcript file corrupted",
                user_message="字幕文件格式错误",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"字幕读取失败: {e}",
            )

        if not isinstance(segments, list):
            return ToolResult(
                success=False,
                error="Transcript root is not a list",
                user_message="字幕文件格式错误",
            )

        from app.services.line_breaker import split_segments
        from app.services.transcript_validator import sanitize_transcript_timeline

        cleaned_segments = _remove_display_breaks(segments)
        valid_segments, warnings = sanitize_transcript_timeline(cleaned_segments)
        if not valid_segments:
            return ToolResult(
                success=False,
                error="No valid transcript segments",
                user_message="没有可重新生成的有效字幕",
            )

        regenerated = split_segments(
            _restore_word_timings(valid_segments, cleaned_segments)
        )

        try:
            tmp_path = str(transcript_path) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(regenerated, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, transcript_path)
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"字幕保存失败: {e}",
            )

        clip_file_count = 0
        clip_count = 0
        if regenerate_clip_files:
            try:
                clips = json.loads(task.get("clips_json") or "[]")
            except json.JSONDecodeError:
                clips = []

            from app.services.subtitle import generate_clip_subtitles

            for i, clip in enumerate(clips):
                if not isinstance(clip, dict) or clip.get("status") == "failed":
                    continue
                window_start = clip.get(
                    "export_start_time_s", clip.get("start_time_s", 0.0)
                )
                window_end = clip.get("export_end_time_s", clip.get("end_time_s", 0.0))
                written = generate_clip_subtitles(
                    regenerated,
                    float(window_start),
                    float(window_end),
                    str(output_dir),
                    i,
                )
                clip_count += 1
                clip_file_count += len(written)

        from app.utils import utcnow_iso

        update_task_status(
            task_id,
            task.get("status", "done"),
            subtitle_segment_count=len(regenerated),
            transcript_source="regenerated_subtitles",
            transcript_modified_at=utcnow_iso(),
        )

        message = (
            f"已基于现有字幕重新生成 {len(regenerated)} 条字幕，无需 ASR API Key"
        )
        if regenerate_clip_files:
            message += f"，并刷新 {clip_count} 个片段的 {clip_file_count} 个字幕文件"
        if warnings:
            message += f"（已跳过 {len(warnings)} 条格式警告）"

        return ToolResult(
            success=True,
            data={
                "segment_count": len(regenerated),
                "clip_count": clip_count,
                "clip_subtitle_files": clip_file_count,
            },
            user_message=message,
        )


_regenerate_subtitles = RegenerateSubtitles()
register(_regenerate_subtitles)
