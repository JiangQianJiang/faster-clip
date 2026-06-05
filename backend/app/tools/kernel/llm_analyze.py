"""Kernel tool: call LLM to analyze transcript and find highlights."""

from app.tools import register
from app.tools.base import Tool, ToolResult


class LLMAnalyze(Tool):
    name = "llm_analyze"
    description = "Call the LLM to analyze transcript segments and identify highlight clips. Returns clip objects with start_time_s, end_time_s, score, and reason."
    parameters = {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Transcript segments to analyze",
            },
            "config": {
                "type": "object",
                "description": "LLM config: {llm_base_url, llm_model, llm_api_key, clip_min_duration, clip_max_duration}",
            },
        },
        "required": ["segments", "config"],
    }

    async def execute(self, segments: list[dict], config: dict) -> ToolResult:
        try:
            from app.services.analyzer import (
                AuthError as LLMAuthError,
            )
            from app.services.analyzer import (
                ConnectionError_ as LLMConnectionError,
            )
            from app.services.analyzer import (
                LLMError,
                ParseError,
                analyze,
                build_prompt,
                validate_clips,
            )

            llm_api_key = config.get("llm_api_key", "")
            llm_base_url = config.get("llm_base_url", "")
            llm_model = config.get("llm_model", "")
            clip_min = config.get("clip_min_duration", 30)
            clip_max = config.get("clip_max_duration", 120)

            prompt = build_prompt(
                segments, {"clip_min_duration": clip_min, "clip_max_duration": clip_max}
            )
            raw_clips = analyze(
                api_key=llm_api_key,
                base_url=llm_base_url,
                model=llm_model,
                prompt=prompt,
            )

            validated = validate_clips(
                raw_clips,
                video_duration=float("inf"),
                min_duration=clip_min,
                max_duration=clip_max,
            )

            return ToolResult(
                success=True,
                data=validated,
                user_message=f"分析完成，找到 {len(validated)} 个精彩片段",
            )
        except LLMAuthError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message="LLM 认证失败，请检查 API Key",
            )
        except LLMConnectionError:
            return ToolResult(
                success=False,
                error="LLM connection failed",
                user_message="LLM 服务连接失败，请检查网络或稍后重试",
            )
        except ParseError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message="LLM 返回结果解析失败，可以尝试重新分析",
            )
        except LLMError as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"LLM 分析失败: {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                user_message=f"分析过程异常: {e}",
            )


_llm_analyze = LLMAnalyze()
register(_llm_analyze)
