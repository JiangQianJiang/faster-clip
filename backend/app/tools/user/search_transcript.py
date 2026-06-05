"""User tool: search transcript for keywords."""

import json
import os
from pathlib import Path

from app.tools import register
from app.tools.base import Tool, ToolResult

OUTPUT_DIR = Path("data/output")


def _fmt_ts(seconds: float) -> str:
    """Format seconds as MM:SS.ss for compact LLM-friendly output."""
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:05.2f}"


class SearchTranscript(Tool):
    name = "search_transcript"
    description = (
        "Search transcript text for a keyword or phrase. "
        "Returns matching segments with surrounding context as compact timestamped text. "
        "Use the start_time_s/end_time_s from matches to call analyze_highlights "
        "with time_ranges parameter to find clips in those time windows."
    )
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task UUID"},
            "query": {
                "type": "string",
                "description": "Keyword or phrase to search for (substring match)",
            },
            "context_seconds": {
                "type": "number",
                "description": "Seconds of surrounding context to include around each match",
                "default": 10,
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matches to return",
                "default": 20,
            },
        },
        "required": ["task_id", "query"],
    }

    async def execute(
        self,
        task_id: str,
        query: str,
        context_seconds: float = 10,
        max_results: int = 20,
    ) -> ToolResult:
        transcript_path = OUTPUT_DIR / task_id / "transcript.json"
        if not os.path.isfile(transcript_path):
            return ToolResult(
                success=False,
                error="Transcript not available",
                user_message="字幕文件暂不可用，请先提取字幕",
            )

        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message="字幕读取失败",
            )

        if not segments:
            return ToolResult(
                success=True,
                data={"matches": [], "total_matches": 0},
                user_message="字幕为空，无匹配结果",
            )

        # Scan full transcript for total match count
        query_lower = query.lower()
        all_matched: list[int] = []
        for i, seg in enumerate(segments):
            text = (seg.get("text") or "").lower()
            if query_lower in text:
                all_matched.append(i)

        total_matches = len(all_matched)

        # Slice to max_results for response
        returned_indices = all_matched[:max_results]

        # Build results with surrounding context as compact text
        matches = []
        for idx in returned_indices:
            match_seg = segments[idx]
            match_center = (match_seg["start_time_s"] + match_seg["end_time_s"]) / 2

            context_lines = [
                f"[{_fmt_ts(match_seg['start_time_s'])}] {match_seg['text']}"
            ]

            # Scan backward for context
            for j in range(idx - 1, -1, -1):
                s = segments[j]
                if match_center - s["end_time_s"] > context_seconds:
                    break
                context_lines.insert(0, f"[{_fmt_ts(s['start_time_s'])}] {s['text']}")

            # Scan forward for context
            for j in range(idx + 1, len(segments)):
                s = segments[j]
                if s["start_time_s"] - match_center > context_seconds:
                    break
                context_lines.append(f"[{_fmt_ts(s['start_time_s'])}] {s['text']}")

            matches.append(
                {
                    "match_index": idx,
                    "match_text": match_seg["text"],
                    "start_time_s": match_seg["start_time_s"],
                    "end_time_s": match_seg["end_time_s"],
                    "context_text": "\n".join(context_lines),
                }
            )

        truncated = total_matches > max_results

        return ToolResult(
            success=True,
            data={
                "matches": matches,
                "total_matches": total_matches,
                "truncated": truncated,
            },
            user_message=(
                f"搜索「{query}」找到 {total_matches} 处匹配"
                + ("（结果已截断）" if truncated else "")
                + f"，共 {len(matches)} 条结果"
            ),
        )


_search_transcript = SearchTranscript()
register(_search_transcript)
