"""User tool: apply subtitle burn-in style preset."""

import json

from app.tools import register
from app.tools.base import Tool, ToolResult


class ApplySubtitleStyle(Tool):
    name = "apply_subtitle_style"
    description = (
        "应用字幕烧录样式预设。设置后，后续的导出和字幕烧录操作将使用指定样式。"
        "支持 douyin（抖音短视频）和 minimal（简约对话）两种预设，可覆盖个别参数。"
    )
    user_facing = True
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "任务 ID"},
            "preset": {
                "type": "string",
                "enum": ["douyin", "minimal"],
                "description": "样式预设：douyin（抖音短视频，黄色大字 32px）、minimal（简约对话，白色小字 26px）",
            },
            "overrides": {
                "type": "object",
                "description": "参数覆盖（可选）：font_size (8-48), font_color, outline_color, alignment (1-3), margin_v (0-200), bold (bool)",
            },
        },
        "required": ["task_id", "preset"],
    }

    async def execute(
        self,
        task_id: str,
        preset: str,
        overrides: dict | None = None,
    ) -> ToolResult:
        from app.models.task import get_task, update_task_status

        task = get_task(task_id)
        if task is None:
            return ToolResult(
                success=False, error="task not found", user_message="任务不存在"
            )

        # Guard: reject while processing (style won't affect in-flight pipeline)
        if task.get("status") in ("queued", "processing"):
            return ToolResult(
                success=False,
                error="Cannot change subtitle style while task is processing",
                user_message="任务处理中，请等待完成后再试",
            )

        # Validate preset exists
        try:
            from app.services.subtitle_style import build_force_style, get_preset

            preset_data = get_preset(preset)
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(
                success=False, error=str(e), user_message=f"无效的样式预设: {preset}"
            )

        # Validate overrides if provided
        if overrides:
            try:
                build_force_style(preset, overrides)
            except ValueError as e:
                return ToolResult(
                    success=False, error=str(e), user_message=f"参数覆盖无效: {e}"
                )

        # Store style config in config_json
        config = json.loads(task.get("config_json") or "{}")
        style_config = {"preset": preset}
        if overrides:
            style_config["overrides"] = overrides
        config["subtitle_style"] = style_config

        update_task_status(
            task_id,
            task.get("status", "done"),
            config_json=json.dumps(config, ensure_ascii=False),
        )

        preset_name = preset_data.get("name", preset)
        msg = f"已应用字幕样式: {preset_name}"
        if overrides:
            msg += f"（含 {len(overrides)} 个自定义参数）"

        return ToolResult(success=True, data=style_config, user_message=msg)


_apply_subtitle_style = ApplySubtitleStyle()
register(_apply_subtitle_style)
