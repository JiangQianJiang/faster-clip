"""Kernel tool: run ASR (speech-to-text) on a video."""

from app.tools import register
from app.tools.base import Tool, ToolResult


class RunASR(Tool):
    name = "run_asr"
    description = "Run automatic speech recognition on a video to extract subtitles. Use when no embedded subtitles are available."
    parameters = {
        "type": "object",
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Absolute path to the video file",
            },
            "api_key": {"type": "string", "description": "ASR API key"},
            "base_url": {
                "type": "string",
                "description": "ASR API base URL (optional)",
            },
            "model": {
                "type": "string",
                "description": "ASR model name, e.g. 'qwen3-asr-flash-filetrans'",
            },
            "provider": {
                "type": "string",
                "description": "ASR provider: 'whisper_api' or 'qwen'",
            },
        },
        "required": ["video_path", "api_key", "provider"],
    }

    async def execute(
        self,
        video_path: str,
        api_key: str,
        base_url: str = "",
        model: str = "qwen3-asr-flash-filetrans",
        provider: str = "qwen",
    ) -> ToolResult:
        try:
            from app.services.asr import (
                ASRError,
                AuthError,
                EmptyTranscript,
                extract_audio,
                transcribe,
            )

            audio_path = extract_audio(video_path)
            try:
                segments = transcribe(
                    audio_path,
                    api_key=api_key,
                    base_url=base_url or None,
                    model=model,
                    provider=provider,
                )
            finally:
                import os

                if os.path.isfile(audio_path):
                    os.unlink(audio_path)

            return ToolResult(
                success=True,
                data=segments,
                user_message=f"语音识别完成，共 {len(segments)} 条字幕",
            )
        except AuthError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"ASR 认证失败: {e}",
            )
        except EmptyTranscript as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message="语音识别未检测到任何语音内容",
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
                user_message=f"ASR 处理异常: {e}",
            )


_run_asr = RunASR()
register(_run_asr)
