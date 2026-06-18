"""User tool: re-run ASR (speech recognition) on a video.

Allows the user to re-transcribe a video — for example, after changing the
ASR model or provider, or when the initial transcription was poor.
"""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")


class RunASRUser(Tool):
    name = "run_asr"
    description = (
        "Re-run automatic speech recognition on the video's audio. This retranscribes "
        "speech from scratch and requires an ASR API key, either stored in the task "
        "or provided as input. Use only when the user asks to re-recognize audio, "
        "re-transcribe speech, use a different ASR model/provider, or fix poor speech "
        "recognition quality. Do not use for rebuilding/reformatting existing "
        "subtitles; use regenerate_subtitles for that no-API local action. "
        "Supports: whisper_api (OpenAI Whisper / gpt-4o-transcribe) and qwen (Qwen3-ASR)."
    )
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "api_key": {
                "type": "string",
                "description": "ASR API key required for retranscription (optional only when the task already stores one)",
            },
            "model": {
                "type": "string",
                "description": "ASR model name (optional — e.g. 'gpt-4o-mini-transcribe', 'qwen3-asr-flash-filetrans')",
            },
            "provider": {
                "type": "string",
                "description": "ASR provider: 'whisper_api' or 'qwen' (optional — uses task's stored provider if omitted)",
            },
            "base_url": {
                "type": "string",
                "description": "ASR API base URL (optional — uses task's stored URL if omitted)",
            },
        },
        "required": ["task_id"],
    }

    async def execute(
        self,
        task_id: str,
        api_key: str = "",
        model: str = "",
        provider: str = "",
        base_url: str = "",
    ) -> ToolResult:
        from app.config import settings
        from app.models.task import get_task, update_task_status

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False, error="Task not found", user_message="任务不存在"
            )

        if task.get("status") in ("pending", "queued", "processing"):
            return ToolResult(
                success=False,
                error="Task is processing",
                user_message="任务处理中，请等待完成后再试",
            )

        video_path = task.get("video_path", "")
        if not video_path or not os.path.isfile(video_path):
            return ToolResult(
                success=False,
                error="Video file not found",
                user_message="原始视频文件不存在，无法重新识别",
            )

        config = json.loads(task.get("config_json") or "{}")

        # Resolve provider: override > config > default
        resolved_provider = (
            provider
            or config.get("asr_provider")
            or settings.default_asr_provider
            or ""
        )

        # Resolve model: override > config > sensible default per provider
        if model:
            resolved_model = model
        elif config.get("asr_model"):
            resolved_model = config["asr_model"]
        elif resolved_provider == "qwen":
            resolved_model = "qwen3-asr-flash-filetrans"
        else:
            resolved_model = "whisper-1"

        # Resolve API key: override > config (decrypted)
        resolved_api_key = api_key
        if not resolved_api_key:
            from app.crypto import decrypt_api_key

            encrypted_key = config.get("asr_api_key", "")
            if encrypted_key:
                try:
                    resolved_api_key = decrypt_api_key(encrypted_key)
                except Exception:
                    return ToolResult(
                        success=False,
                        error="API key decryption failed",
                        user_message="API Key 解密失败",
                    )
        if not resolved_api_key:
            return ToolResult(
                success=False,
                error="No ASR API key configured",
                user_message="未配置 ASR API Key，请在设置中配置或调用时提供",
            )

        # Resolve base_url
        resolved_base_url = base_url or config.get("asr_base_url", "") or None

        # Run ASR
        from app.services.asr import (
            ASRError,
            AuthError,
            EmptyTranscript,
            extract_audio,
            transcribe,
        )

        audio_path = None
        try:
            audio_path = extract_audio(video_path)
            segments = transcribe(
                audio_path,
                api_key=resolved_api_key,
                base_url=resolved_base_url,
                model=resolved_model,
                provider=resolved_provider,
            )
        except AuthError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"ASR 认证失败，请检查 API Key: {e}",
            )
        except EmptyTranscript:
            return ToolResult(
                success=False,
                error="Empty transcript",
                user_message="未检测到语音内容，请确认视频包含人声且音质清晰",
            )
        except ASRError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"语音识别失败: {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"语音识别异常: {e}",
            )
        finally:
            if audio_path and os.path.exists(audio_path):
                os.unlink(audio_path)

        from app.services.transcript_validator import sanitize_transcript_timeline

        segments, _warnings = sanitize_transcript_timeline(segments)
        if not segments:
            return ToolResult(
                success=False,
                error="No valid transcript segments after timeline sanitization",
                user_message="语音识别结果没有有效字幕时间轴",
            )

        # Save raw ASR output before display-oriented line-breaking/splitting.
        output_dir = OUTPUT_DIR / task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        from app.services.subtitle import save_raw_transcript

        try:
            save_raw_transcript(segments, str(output_dir))
        except OSError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"原始字幕保存失败: {e}",
            )

        # Apply word-level splitting before saving the display transcript.
        from app.services.line_breaker import split_segments

        segments = split_segments(segments)

        transcript_path = output_dir / "transcript.json"
        try:
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
        except OSError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"字幕保存失败: {e}",
            )

        from app.utils import utcnow_iso

        update_task_status(
            task_id,
            "done",
            subtitle_segment_count=len(segments),
            transcript_source="asr",
            transcript_modified_at=utcnow_iso(),
        )

        return ToolResult(
            success=True,
            data={
                "segment_count": len(segments),
                "model": resolved_model,
                "provider": resolved_provider,
            },
            user_message=(
                f"语音识别完成，使用 {resolved_provider}/{resolved_model}，"
                f"共 {len(segments)} 条字幕"
            ),
        )


_run_asr_user = RunASRUser()
register(_run_asr_user)
