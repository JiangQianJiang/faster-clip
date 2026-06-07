"""Tests for new user tools: apply_subtitle_style."""

import asyncio
import json


def _init_db():
    from app.models.task import init_db

    init_db()


def _make_task(
    status="done", clips=None, extra_config=None, stage=None, video_path="/tmp/test.mp4"
):
    """Create a task and return its ID."""
    from app.models.task import create_task, update_task_status

    config = {"llm_base_url": "https://api.test.com", "llm_model": "claude"}
    if extra_config:
        config.update(extra_config)
    task_id = create_task(video_path, "test.mp4", config)
    kwargs = {}
    if clips is not None:
        kwargs["clips_json"] = json.dumps(clips)
    if stage:
        kwargs["stage"] = stage
    update_task_status(task_id, status, **kwargs)
    return task_id


# --- apply_subtitle_style ---


def test_apply_subtitle_style_valid():
    _init_db()
    task_id = _make_task()
    from app.tools.user.apply_subtitle_style import _apply_subtitle_style

    result = asyncio.run(
        _apply_subtitle_style.execute(task_id=task_id, preset="douyin")
    )
    assert result.success is True
    assert "已应用" in result.user_message


def test_apply_subtitle_style_invalid_preset():
    _init_db()
    task_id = _make_task()
    from app.tools.user.apply_subtitle_style import _apply_subtitle_style

    result = asyncio.run(
        _apply_subtitle_style.execute(task_id=task_id, preset="nonexistent")
    )
    assert result.success is False


def test_apply_subtitle_style_invalid_overrides():
    _init_db()
    task_id = _make_task()
    from app.tools.user.apply_subtitle_style import _apply_subtitle_style

    result = asyncio.run(
        _apply_subtitle_style.execute(
            task_id=task_id,
            preset="douyin",
            overrides={"font_size": 999},
        )
    )
    assert result.success is False


def test_apply_subtitle_style_with_overrides():
    _init_db()
    task_id = _make_task()
    from app.tools.user.apply_subtitle_style import _apply_subtitle_style

    result = asyncio.run(
        _apply_subtitle_style.execute(
            task_id=task_id,
            preset="minimal",
            overrides={"font_size": 30, "outline_color": "&H000000"},
        )
    )
    assert result.success is True
    assert "已应用" in result.user_message


def test_apply_subtitle_style_processing_guard():
    _init_db()
    task_id = _make_task("processing", stage="exporting_clips")
    from app.tools.user.apply_subtitle_style import _apply_subtitle_style

    result = asyncio.run(
        _apply_subtitle_style.execute(task_id=task_id, preset="douyin")
    )
    assert result.success is False
    assert "处理中" in result.user_message
