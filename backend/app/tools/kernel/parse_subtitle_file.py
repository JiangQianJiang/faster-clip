"""Kernel tool: parse an uploaded subtitle file (SRT/VTT/ASS)."""

from app.tools import register
from app.tools.base import Tool, ToolResult


class ParseSubtitleFile(Tool):
    name = "parse_subtitle_file"
    description = "Parse an uploaded subtitle file (SRT, VTT, or ASS format) into normalized segments. Use when the user provides a subtitle file instead of ASR."
    parameters = {
        "type": "object",
        "properties": {
            "content_base64": {
                "type": "string",
                "description": "Base64-encoded subtitle file content",
            },
            "format": {
                "type": "string",
                "enum": ["srt", "vtt", "ass"],
                "description": "Subtitle file format",
            },
        },
        "required": ["content_base64", "format"],
    }

    async def execute(self, content_base64: str, format: str) -> ToolResult:
        import base64

        try:
            content = base64.b64decode(content_base64)
        except Exception:
            return ToolResult(
                success=False,
                error="Base64 decode failed",
                user_message="字幕文件数据解码失败",
            )

        try:
            from app.services.subtitle import parse_subtitle_bytes

            segments, warnings = parse_subtitle_bytes(content, format)
            msg = f"解析 {format.upper()} 字幕成功，共 {len(segments)} 条"
            if warnings:
                msg += f"，{len(warnings)} 条警告"
            return ToolResult(
                success=True,
                data={"segments": segments, "warnings": warnings},
                user_message=msg,
            )
        except ValueError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"字幕解析失败: {e}",
            )


_parse_subtitle_file = ParseSubtitleFile()
register(_parse_subtitle_file)
