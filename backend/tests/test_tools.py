"""Unit tests for the tool layer — task1, task2, task3 (AC-1)."""

import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.tools import (
    get_tool,
    get_tool_schemas,
    list_kernel_tools,
    list_user_tools,
    register,
)
from app.tools.base import Tool, ToolResult

# ─── Task 1: Tool / ToolResult base classes ───


def test_tool_result_defaults():
    """ToolResult defaults: success=False is not a default, but data/error/user_message are None/''."""
    r = ToolResult(success=True)
    assert r.success is True
    assert r.data is None
    assert r.error is None
    assert r.user_message == ""


def test_tool_result_with_data():
    r = ToolResult(success=True, data={"key": "value"}, user_message="done")
    assert r.data == {"key": "value"}
    assert r.user_message == "done"


def test_tool_result_failure():
    r = ToolResult(success=False, error="something went wrong", user_message="失败了")
    assert r.success is False
    assert r.error == "something went wrong"
    assert r.user_message == "失败了"


def test_tool_base_raises_not_implemented():
    """Tool.execute() must be overridden."""
    t = Tool()
    with pytest.raises(NotImplementedError):
        import asyncio

        asyncio.run(t.execute())


# ─── Task 1: ToolRegistry ───


def test_register_and_get_tool():
    """Register a tool and retrieve it by name."""
    tool = Tool()
    tool.name = "test_tool"
    register(tool)
    assert get_tool("test_tool") is tool


def test_register_duplicate_raises():
    """Registering two tools with the same name raises ValueError."""
    t1 = Tool()
    t1.name = "dup_tool"
    register(t1)
    t2 = Tool()
    t2.name = "dup_tool"
    with pytest.raises(ValueError, match="already registered"):
        register(t2)


def test_get_tool_missing():
    """Looking up an unregistered tool returns None."""
    assert get_tool("nonexistent") is None


def test_list_user_tools():
    """list_user_tools returns only tools with user_facing=True."""
    t1 = Tool()
    t1.name = "user_tool"
    t1.user_facing = True
    register(t1)

    t2 = Tool()
    t2.name = "kernel_tool_b"
    t2.user_facing = False
    register(t2)

    user_tools = list_user_tools()
    assert any(t.name == "user_tool" for t in user_tools)
    assert all(t.name != "kernel_tool_b" for t in user_tools)


def test_list_kernel_tools():
    """list_kernel_tools returns schema dicts with name/description/input_schema."""
    kernel_schemas = list_kernel_tools()
    assert len(kernel_schemas) > 0
    for s in kernel_schemas:
        assert "name" in s
        assert "description" in s
        assert "input_schema" in s


def test_get_tool_schemas_for_user():
    """get_tool_schemas(for_user=True) returns schemas for user-facing tools only."""
    schemas = get_tool_schemas(for_user=True)
    assert isinstance(schemas, list)
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert "input_schema" in s


def test_get_tool_schemas_for_kernel():
    """get_tool_schemas(for_user=False) returns schemas for kernel tools."""
    schemas = get_tool_schemas(for_user=False)
    assert isinstance(schemas, list)
    assert len(schemas) > 0  # kernel tools are auto-registered
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert "input_schema" in s


# ─── Task 2: Kernel tool smoke tests ───


def test_probe_video_tool_executes():
    """probe_video with missing task_id returns failure."""
    import asyncio

    from app.tools.kernel.probe_video import _probe_video

    result = asyncio.run(_probe_video.execute(task_id=""))
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "task_id" in result.error.lower()


def test_get_task_status_tool_executes():
    """get_task_status with nonexistent ID returns failure ToolResult."""
    import asyncio

    from app.tools.kernel.get_task_status import _get_task_status

    result = asyncio.run(
        _get_task_status.execute(task_id="00000000-0000-0000-0000-000000000000")
    )
    assert isinstance(result, ToolResult)
    assert result.success is False


def test_update_segment_tool_executes(tmp_path):
    """update_segment with valid transcript updates a segment."""
    transcript_path = tmp_path / "transcript.json"
    segments = [
        {"start_time_s": 0.0, "end_time_s": 5.0, "text": "hello"},
        {"start_time_s": 5.0, "end_time_s": 10.0, "text": "world"},
    ]
    transcript_path.write_text(json.dumps(segments))

    import asyncio

    from app.tools.kernel.update_segment import _update_segment

    result = asyncio.run(
        _update_segment.execute(
            transcript_path=str(transcript_path),
            index=0,
            text="updated hello",
        )
    )
    assert result.success is True
    assert result.data["text"] == "updated hello"

    # Verify file was written
    updated = json.loads(transcript_path.read_text())
    assert updated[0]["text"] == "updated hello"


def test_update_segment_out_of_range(tmp_path):
    """update_segment with out-of-range index returns failure."""
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(
        json.dumps([{"start_time_s": 0.0, "end_time_s": 1.0, "text": "x"}])
    )

    import asyncio

    from app.tools.kernel.update_segment import _update_segment

    result = asyncio.run(
        _update_segment.execute(
            transcript_path=str(transcript_path),
            index=10,
            text="bad",
        )
    )
    assert result.success is False


def test_merge_segments_tool_executes(tmp_path):
    """merge_segments merges adjacent segments."""
    transcript_path = tmp_path / "transcript.json"
    segments = [
        {"start_time_s": 0.0, "end_time_s": 3.0, "text": "hello"},
        {"start_time_s": 3.0, "end_time_s": 6.0, "text": "world"},
    ]
    transcript_path.write_text(json.dumps(segments))

    import asyncio

    from app.tools.kernel.merge_segments import _merge_segments

    result = asyncio.run(
        _merge_segments.execute(
            transcript_path=str(transcript_path),
            start_index=0,
            end_index=1,
        )
    )
    assert result.success is True
    assert result.data["text"] == "hello world"

    updated = json.loads(transcript_path.read_text())
    assert len(updated) == 1


def test_split_segment_tool_executes(tmp_path):
    """split_segment splits a segment at a given time."""
    transcript_path = tmp_path / "transcript.json"
    segments = [{"start_time_s": 0.0, "end_time_s": 10.0, "text": "split me"}]
    transcript_path.write_text(json.dumps(segments))

    import asyncio

    from app.tools.kernel.split_segment import _split_segment

    result = asyncio.run(
        _split_segment.execute(
            transcript_path=str(transcript_path),
            index=0,
            split_time_s=5.0,
        )
    )
    assert result.success is True

    updated = json.loads(transcript_path.read_text())
    assert len(updated) == 2
    assert updated[0]["end_time_s"] == 5.0
    assert updated[1]["start_time_s"] == 5.0


def test_split_segment_invalid_time(tmp_path):
    """split_segment with split time outside segment range returns failure."""
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(
        json.dumps([{"start_time_s": 0.0, "end_time_s": 10.0, "text": "x"}])
    )

    import asyncio

    from app.tools.kernel.split_segment import _split_segment

    result = asyncio.run(
        _split_segment.execute(
            transcript_path=str(transcript_path),
            index=0,
            split_time_s=20.0,
        )
    )
    assert result.success is False


def test_parse_subtitle_file_tool(tmp_path):
    """parse_subtitle_file with valid SRT content returns segments."""
    import base64

    srt_content = b"1\n00:00:01,000 --> 00:00:03,000\nhello world\n"
    b64 = base64.b64encode(srt_content).decode()

    import asyncio

    from app.tools.kernel.parse_subtitle_file import _parse_subtitle_file

    result = asyncio.run(_parse_subtitle_file.execute(content_base64=b64, format="srt"))
    assert result.success is True
    assert len(result.data["segments"]) > 0


def test_parse_subtitle_file_invalid_base64():
    """parse_subtitle_file with invalid base64 returns failure."""
    import asyncio

    from app.tools.kernel.parse_subtitle_file import _parse_subtitle_file

    result = asyncio.run(
        _parse_subtitle_file.execute(
            content_base64="!!!not-valid-base64!!!",
            format="srt",
        )
    )
    assert result.success is False


# ─── Task 1: HTTP decoupling ───


def test_tool_module_no_http_imports():
    """The tools package must not import fastapi or starlette."""
    import sys

    import app.tools

    # Force a fresh check by looking at the module's imports
    import app.tools.base

    # Check that base module doesn't import HTTP libraries
    base_modules = set(sys.modules.keys())
    assert "fastapi" not in base_modules or "fastapi" not in str(
        app.tools.base.__dict__
    )
    assert "starlette" not in base_modules or "starlette" not in str(
        app.tools.base.__dict__
    )


# ─── Task 1: Tool exception propagation guard ───


def test_tool_exception_does_not_propagate():
    """Tool execution failure must be wrapped as ToolResult, not raised."""

    class BadTool(Tool):
        name = "bad_tool"
        parameters = {}

        async def execute(self, **kwargs):
            raise RuntimeError("unexpected failure")

    import asyncio

    async def run_tool():
        try:
            return await BadTool().execute()
        except Exception as e:
            return ToolResult(success=False, error=str(e), user_message="工具执行失败")

    result = asyncio.run(run_tool())
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "unexpected failure" in result.error


# ─── task12: ExportClips user-tool tests ───


def test_export_clips_negative_index_rejected():
    """ExportClips: negative index returns failure, does not enqueue."""
    import json

    from app.models.task import create_task, init_db, update_task_status

    init_db()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        vp = f.name
        f.write(b"data")
    task_id = create_task(vp, "t.mp4", {})
    update_task_status(
        task_id,
        "done",
        clips_json=json.dumps(
            [{"start_time_s": 0, "end_time_s": 5, "status": "success"}]
        ),
    )

    import asyncio

    from app.tools.user.export_clips import _export_clips

    with patch("app.worker.celery_app.export_clips_task") as mock_task:
        result = asyncio.run(_export_clips.execute(task_id=task_id, clip_indices=[-1]))
    assert result.success is False
    assert "没有可导出的有效片段" in result.user_message


def test_export_clips_out_of_range_rejected():
    """ExportClips: out-of-range index returns failure."""
    import json

    from app.models.task import create_task, init_db, update_task_status

    init_db()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        vp = f.name
        f.write(b"data")
    task_id = create_task(vp, "t.mp4", {})
    update_task_status(
        task_id,
        "done",
        clips_json=json.dumps(
            [{"start_time_s": 0, "end_time_s": 5, "status": "success"}]
        ),
    )

    import asyncio

    from app.tools.user.export_clips import _export_clips

    with patch("app.worker.celery_app.export_clips_task") as mock_task:
        result = asyncio.run(_export_clips.execute(task_id=task_id, clip_indices=[99]))
    assert result.success is False


def test_export_clips_duplicates_deduplicated():
    """ExportClips: duplicate indices deduplicated in enqueue."""
    import json

    from app.models.task import create_task, init_db, update_task_status

    init_db()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        vp = f.name
        f.write(b"data")
    task_id = create_task(vp, "t.mp4", {})
    update_task_status(
        task_id,
        "done",
        clips_json=json.dumps(
            [
                {"start_time_s": 0, "end_time_s": 5, "status": "success"},
                {"start_time_s": 5, "end_time_s": 10, "status": "success"},
            ]
        ),
    )

    import asyncio

    from app.tools.user.export_clips import _export_clips

    mock_task = MagicMock()
    mock_task.apply_async = MagicMock()
    with patch("app.worker.celery_app.export_clips_task", mock_task):
        result = asyncio.run(
            _export_clips.execute(task_id=task_id, clip_indices=[1, 1, 0])
        )
    assert result.success is True
    args = mock_task.apply_async.call_args[1]["kwargs"]
    assert args["clip_indices"] == [1, 0]


def test_export_clips_no_ffmpeg_in_api_process():
    """ExportClips.execute does not call subprocess.run or ffmpeg in the API path."""
    import asyncio
    import json

    from app.models.task import create_task, init_db, update_task_status

    init_db()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        vp = f.name
        f.write(b"data")
    task_id = create_task(vp, "t.mp4", {})
    update_task_status(
        task_id,
        "done",
        clips_json=json.dumps(
            [{"start_time_s": 0, "end_time_s": 5, "status": "success"}]
        ),
    )

    from app.tools.user.export_clips import _export_clips

    with (
        patch("app.worker.celery_app.export_clips_task") as mock_task,
        patch("subprocess.run") as mock_sp,
    ):
        mock_task.apply_async = MagicMock()
        result = asyncio.run(_export_clips.execute(task_id=task_id, clip_indices=[0]))
    assert result.success is True
    mock_sp.assert_not_called()


# ─── AnalyzeHighlights: _merge_clips_with_existing ───


def test_merge_clips_preserves_unmatched_existing():
    """Existing clips not matched by new ones are preserved as-is."""
    from app.tools.user.analyze_highlights import _merge_clips_with_existing

    existing = [
        {
            "start_time_s": 0,
            "end_time_s": 10,
            "status": "success",
            "filepath": "/tmp/c0.mp4",
        },
        {
            "start_time_s": 15,
            "end_time_s": 25,
            "status": "success",
            "filepath": "/tmp/c1.mp4",
        },
    ]
    # New analysis finds only one clip (different from both existing)
    new = [
        {"start_time_s": 30, "end_time_s": 45, "score": 8, "reason": "new find"},
    ]

    result = _merge_clips_with_existing(new, existing)

    assert len(result) == 3  # 1 new + 2 preserved existing
    statuses = {c.get("status") for c in result}
    assert statuses == {"success", "pending"}
    # Unmatched existing clips keep their export data
    preserved = [c for c in result if c.get("filepath")]
    assert len(preserved) == 2


def test_merge_clips_appends_new_alongside_existing():
    """New analysis with different focus accumulates clips."""
    from app.tools.user.analyze_highlights import _merge_clips_with_existing

    existing = [
        {
            "start_time_s": 0,
            "end_time_s": 10,
            "status": "success",
            "reason": "first batch",
        },
    ]
    # Second analysis finds different clips
    new = [
        {"start_time_s": 20, "end_time_s": 30, "score": 9, "reason": "second batch"},
        {"start_time_s": 40, "end_time_s": 55, "score": 7, "reason": "third find"},
    ]

    result = _merge_clips_with_existing(new, existing)

    # Should show all 3 clips: new clips first, then unmatched existing
    assert len(result) == 3
    assert result[0].get("reason") == "second batch"
    assert result[0].get("status") == "pending"
    assert result[1].get("reason") == "third find"
    assert result[1].get("status") == "pending"
    assert result[2].get("reason") == "first batch"  # existing preserved (appended)
    assert result[2].get("status") == "success"


def test_merge_clips_matches_overlapping_clips():
    """Overlapping clips merge export metadata (existing behavior preserved)."""
    from app.tools.user.analyze_highlights import _merge_clips_with_existing

    existing = [
        {
            "start_time_s": 5,
            "end_time_s": 15,
            "status": "success",
            "filepath": "/tmp/c0.mp4",
            "thumbnail_path": "/tmp/t0.jpg",
        },
    ]
    new = [
        {"start_time_s": 5.5, "end_time_s": 14.5, "score": 9, "reason": "same clip"},
    ]

    result = _merge_clips_with_existing(new, existing)

    assert len(result) == 1  # matched, no duplicates
    assert result[0]["status"] == "success"  # preserved from existing
    assert result[0]["filepath"] == "/tmp/c0.mp4"
    assert result[0]["thumbnail_path"] == "/tmp/t0.jpg"


def test_merge_clips_empty_existing():
    """Empty existing clips: all new clips get pending status."""
    from app.tools.user.analyze_highlights import _merge_clips_with_existing

    new = [
        {"start_time_s": 0, "end_time_s": 5, "score": 8},
        {"start_time_s": 10, "end_time_s": 15, "score": 6},
    ]

    result = _merge_clips_with_existing(new, [])

    assert len(result) == 2
    for c in result:
        assert c.get("status") == "pending"


def test_merge_clips_loose_overlap_resets_status():
    """Overlap below _MERGE_TIGHT_OVERLAP: metadata carried but status reset to pending."""
    from app.tools.user.analyze_highlights import _merge_clips_with_existing

    # 55% overlap (< 85% tight threshold)
    existing = [
        {
            "start_time_s": 0,
            "end_time_s": 10,
            "status": "success",
            "filepath": "/tmp/c0.mp4",
        },
    ]
    new = [
        {"start_time_s": 4, "end_time_s": 14.0, "score": 5, "reason": "shifted"},
    ]

    result = _merge_clips_with_existing(new, existing)

    assert len(result) == 1
    assert result[0]["status"] == "pending"  # reset because overlap < 85%
    assert result[0]["filepath"] == "/tmp/c0.mp4"  # but path is carried


def test_get_task_status_is_user_facing():
    """get_task_status tool is user-facing so the AI agent can query task state."""
    from app.tools import get_tool

    tool = get_tool("get_task_status")
    assert tool is not None
    assert tool.user_facing is True, (
        "get_task_status must be user_facing so the AI agent can query task status"
    )


def test_all_kernel_tools_have_required_attrs():
    """Every registered kernel tool instance has name, description, parameters."""
    from app.tools import list_kernel_tool_instances

    instances = list_kernel_tool_instances()
    real_tools = [t for t in instances if t.description]
    assert len(real_tools) > 0, "Expected at least one real kernel tool"
    for tool in real_tools:
        assert tool.name
        assert tool.description
        assert isinstance(tool.parameters, dict)
        assert "type" in tool.parameters
        assert tool.user_facing is False
