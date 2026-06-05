"""Kernel tool: extract embedded subtitles from video."""

from app.tools import register
from app.tools.base import Tool, ToolResult


class ExtractEmbeddedSubtitles(Tool):
    name = "extract_embedded_subtitles"
    description = "Extract embedded subtitle tracks from a video file. Use when probe_video reports subtitle streams."
    parameters = {
        "type": "object",
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Absolute path to the video file",
            },
            "streams": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Subtitle stream metadata from probe_video",
            },
        },
        "required": ["video_path", "streams"],
    }

    async def execute(self, video_path: str, streams: list[dict]) -> ToolResult:
        try:
            from app.services.subtitle import extract_embedded_subtitles

            segments = extract_embedded_subtitles(video_path, streams)
            if segments is None:
                return ToolResult(
                    success=True,
                    data=[],
                    user_message="未找到内嵌字幕",
                )
            return ToolResult(
                success=True,
                data=segments,
                user_message=f"成功提取 {len(segments)} 条内嵌字幕",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"内嵌字幕提取失败: {e}",
            )


_extract_embedded_subtitles = ExtractEmbeddedSubtitles()
register(_extract_embedded_subtitles)
