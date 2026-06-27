"""Tests for Celery task retry behavior."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.crypto import encrypt_api_key
from app.worker.pipeline import StageError


class Retry(Exception):
    """Simulates Celery's Retry exception."""


def _enc(key: str) -> str:
    return encrypt_api_key(key)


def test_retryable_error_triggers_retry():
    """StageError with retryable=True → self.retry() is called."""
    from app.worker.celery_app import process_video_task

    mock_retry = MagicMock(side_effect=Retry("retry"))
    with (
        patch.object(process_video_task, "retry", mock_retry),
        patch(
            "app.worker.celery_app._run_pipeline",
            side_effect=StageError("extracting_subtitles", "API failed"),
        ),
        patch("app.models.task.update_task_status"),
    ):
        try:
            process_video_task.run("t1", "/v.mp4", {}, _enc("sk-llm"), _enc("sk-asr"))
        except Retry:
            pass

    mock_retry.assert_called_once()


def test_non_retryable_error_marks_error_directly():
    """retryable=False → update_task_status('error') directly, no retry."""
    from app.worker.celery_app import process_video_task

    mock_retry = MagicMock()
    mock_update = MagicMock()

    with (
        patch.object(process_video_task, "retry", mock_retry),
        patch(
            "app.worker.celery_app._run_pipeline",
            side_effect=StageError("analyzing", "key invalid", retryable=False),
        ),
        patch("app.models.task.update_task_status", side_effect=mock_update),
    ):
        process_video_task.run("t2", "/v.mp4", {}, _enc("sk-llm"), _enc("sk-asr"))

    mock_retry.assert_not_called()
    error_calls = [c for c in mock_update.call_args_list if len(c[0]) >= 2 and c[0][1] == "error"]
    assert len(error_calls) == 1
    assert error_calls[0][1]["failed_stage"] == "analyzing"


def test_max_retries_exceeded_marks_error():
    """self.retry raises MaxRetriesExceededError → update_task_status('error')."""
    from app.worker.celery_app import process_video_task

    class MaxRetriesExceededError(Exception):
        pass

    mock_retry = MagicMock(side_effect=MaxRetriesExceededError("exhausted"))
    mock_update = MagicMock()

    with (
        patch.object(process_video_task, "retry", mock_retry),
        patch.object(process_video_task, "MaxRetriesExceededError", MaxRetriesExceededError),
        patch(
            "app.worker.celery_app._run_pipeline",
            side_effect=StageError("extracting_subtitles", "timeout"),
        ),
        patch("app.models.task.update_task_status", side_effect=mock_update),
    ):
        process_video_task.run("t3", "/v.mp4", {}, _enc("sk-llm"), _enc("sk-asr"))

    error_calls = [c for c in mock_update.call_args_list if len(c[0]) >= 2 and c[0][1] == "error"]
    assert len(error_calls) == 1


def test_successful_pipeline_no_error_or_retry():
    """Successful pipeline → no retry, no error status."""
    from app.worker.celery_app import process_video_task

    mock_retry = MagicMock()
    mock_update = MagicMock()

    with (
        patch.object(process_video_task, "retry", mock_retry),
        patch("app.worker.celery_app._run_pipeline"),
        patch("app.models.task.update_task_status", side_effect=mock_update),
    ):
        process_video_task.run("t4", "/v.mp4", {}, _enc("sk-llm"), _enc("sk-asr"))

    mock_retry.assert_not_called()
    error_calls = [c for c in mock_update.call_args_list if len(c[0]) >= 2 and c[0][1] == "error"]
    assert len(error_calls) == 0


def test_retries_exhausted_marks_error_directly():
    """When retries >= max_retries, mark error without calling retry()."""
    from app.worker.celery_app import process_video_task

    mock_retry = MagicMock()
    mock_update = MagicMock()
    orig_retries = process_video_task.request.retries

    try:
        with (
            patch.object(process_video_task, "retry", mock_retry),
            patch(
                "app.worker.celery_app._run_pipeline",
                side_effect=StageError("analyzing", "LLM timeout"),
            ),
            patch("app.models.task.update_task_status", side_effect=mock_update),
        ):
            process_video_task.request.retries = 1
            process_video_task.run("t6", "/v.mp4", {}, _enc("sk-llm"), _enc("sk-asr"))
    finally:
        process_video_task.request.retries = orig_retries

    mock_retry.assert_not_called()
    error_calls = [c for c in mock_update.call_args_list if len(c[0]) >= 2 and c[0][1] == "error"]
    assert len(error_calls) == 1
    assert error_calls[0][1]["failed_stage"] == "analyzing"


def test_max_retries_is_one():
    """process_video_task.max_retries == 1 to enforce at most one retry after SIGTERM."""
    from app.worker.celery_app import process_video_task

    assert process_video_task.max_retries == 1, (
        f"Expected max_retries=1, got {process_video_task.max_retries}"
    )


def test_generic_exception_defaults_to_retryable():
    """A plain Exception without retryable attr → treated as retryable."""
    from app.worker.celery_app import process_video_task

    mock_retry = MagicMock(side_effect=Retry("retry"))
    with (
        patch.object(process_video_task, "retry", mock_retry),
        patch(
            "app.worker.celery_app._run_pipeline",
            side_effect=RuntimeError("unexpected"),
        ),
        patch("app.models.task.update_task_status"),
    ):
        try:
            process_video_task.run("t5", "/v.mp4", {}, _enc("sk-llm"), _enc("sk-asr"))
        except Retry:
            pass

    mock_retry.assert_called_once()


# ─── export_clips_task regression tests ───


def test_export_clips_task_full_success():
    """export_clips_task: full success writes correct artifact paths."""
    import json

    from app.worker.celery_app import export_clips_task

    task_id = "test-export-full"
    clips = [
        {"start_time_s": 0, "end_time_s": 10, "score": 9},
        {"start_time_s": 10, "end_time_s": 20, "score": 8},
    ]

    def fake_get_task(tid):
        return {
            "id": tid,
            "status": "done",
            "video_path": "/tmp/v.mp4",
            "config_json": "{}",
            "clips_json": json.dumps(clips),
        }

    fake_statuses = []

    def fake_update(tid, status, **kw):
        fake_statuses.append((status, kw))

    def fake_clip(
        vp,
        od,
        idx,
        cl,
        buf,
        burn,
        segs=None,
        max_duration=120,
        video_duration=0,
        subtitle_style_cfg=None,
    ):
        return {
            "video": f"{od}/clip_{idx + 1:03d}.mp4",
            "thumbnail": f"{od}/thumb_{idx:03d}.jpg",
            "export_start": 0,
            "export_end": 13,
        }

    with (
        patch("app.models.task.get_task", fake_get_task),
        patch("app.models.task.update_task_status", fake_update),
        patch("app.worker.pipeline._export_clip", fake_clip),
        patch("app.services.ffprobe.probe", return_value=MagicMock(duration=300.0)),
        patch("os.makedirs"),
        patch("os.path.isfile", return_value=False),
        patch("builtins.open", new_callable=lambda: None),
    ):
        export_clips_task.run(task_id=task_id, clip_indices=None, burn_subtitle=False)

    final = fake_statuses[-1]
    assert final[0] == "done"
    final_clips = json.loads(final[1]["clips_json"])
    assert "filepath" in final_clips[0]
    assert "thumbnail_path" in final_clips[0]


def test_export_clips_task_patches_current_clip_by_clip_id_after_reorder():
    """export_clips_task maps export results back by clip_id, not stale index."""
    import json

    from app.worker.celery_app import export_clips_task

    task_id = "test-export-reordered"
    original_clips = [
        {"clip_id": "clip-a", "start_time_s": 0, "end_time_s": 10, "score": 9},
        {"clip_id": "clip-b", "start_time_s": 10, "end_time_s": 20, "score": 8},
    ]
    reordered_clips = [
        {"clip_id": "clip-b", "start_time_s": 10, "end_time_s": 20, "score": 8},
        {"clip_id": "clip-a", "start_time_s": 0, "end_time_s": 10, "score": 9},
    ]
    get_task_calls = 0

    def fake_get_task(tid):
        nonlocal get_task_calls
        get_task_calls += 1
        clips = original_clips if get_task_calls == 1 else reordered_clips
        return {
            "id": tid,
            "status": "done",
            "video_path": "/tmp/v.mp4",
            "config_json": "{}",
            "clips_json": json.dumps(clips),
        }

    fake_statuses = []

    def fake_update(tid, status, **kw):
        fake_statuses.append((status, kw))

    def fake_clip(
        vp,
        od,
        idx,
        cl,
        buf,
        burn,
        segs=None,
        max_duration=120,
        video_duration=0,
        subtitle_style_cfg=None,
    ):
        return {
            "video": f"{od}/{cl['clip_id']}.mp4",
            "thumbnail": f"{od}/{cl['clip_id']}.jpg",
            "export_start": cl["start_time_s"],
            "export_end": cl["end_time_s"],
        }

    with (
        patch("app.models.task.get_task", fake_get_task),
        patch("app.models.task.update_task_status", fake_update),
        patch("app.worker.pipeline._export_clip", fake_clip),
        patch("app.services.ffprobe.probe", return_value=MagicMock(duration=300.0)),
        patch("os.makedirs"),
        patch("os.path.isfile", return_value=False),
        patch("builtins.open", new_callable=lambda: None),
    ):
        export_clips_task.run(task_id=task_id, clip_indices=None, burn_subtitle=False)

    final_clips = json.loads(fake_statuses[-1][1]["clips_json"])
    assert final_clips[0]["clip_id"] == "clip-b"
    assert final_clips[0]["filepath"].endswith("clip-b.mp4")
    assert final_clips[1]["clip_id"] == "clip-a"
    assert final_clips[1]["filepath"].endswith("clip-a.mp4")


def test_export_clips_task_does_not_patch_different_clip_when_clip_id_missing_from_fresh_data():
    """If a clip changes during export, stale export fields are not patched by index."""
    import json

    from app.worker.celery_app import export_clips_task

    task_id = "test-export-changed"
    original_clips = [
        {"clip_id": "clip-a", "start_time_s": 0, "end_time_s": 10, "score": 9},
    ]
    changed_clips = [
        {"clip_id": "clip-c", "start_time_s": 40, "end_time_s": 50, "score": 7},
    ]
    get_task_calls = 0

    def fake_get_task(tid):
        nonlocal get_task_calls
        get_task_calls += 1
        clips = original_clips if get_task_calls == 1 else changed_clips
        return {
            "id": tid,
            "status": "done",
            "video_path": "/tmp/v.mp4",
            "config_json": "{}",
            "clips_json": json.dumps(clips),
        }

    fake_statuses = []

    def fake_clip(
        vp,
        od,
        idx,
        cl,
        buf,
        burn,
        segs=None,
        max_duration=120,
        video_duration=0,
        subtitle_style_cfg=None,
    ):
        return {
            "video": f"{od}/{cl['clip_id']}.mp4",
            "thumbnail": f"{od}/{cl['clip_id']}.jpg",
            "export_start": cl["start_time_s"],
            "export_end": cl["end_time_s"],
        }

    with (
        patch("app.models.task.get_task", fake_get_task),
        patch(
            "app.models.task.update_task_status",
            side_effect=lambda tid, status, **kw: fake_statuses.append((status, kw)),
        ),
        patch("app.worker.pipeline._export_clip", fake_clip),
        patch("app.services.ffprobe.probe", return_value=MagicMock(duration=300.0)),
        patch("os.makedirs"),
        patch("os.path.isfile", return_value=False),
        patch("builtins.open", new_callable=lambda: None),
    ):
        export_clips_task.run(task_id=task_id, clip_indices=None, burn_subtitle=False)

    final_clips = json.loads(fake_statuses[-1][1]["clips_json"])
    assert final_clips == changed_clips


def test_export_clips_task_total_failure():
    """export_clips_task: all ffmpeg failures → error."""
    import json

    from app.worker.celery_app import export_clips_task

    task_id = "test-export-fail"
    clips = [{"start_time_s": 0, "end_time_s": 10, "score": 9}]
    fake_statuses = []

    mock_probe = MagicMock(duration=300.0)
    with (
        patch(
            "app.models.task.get_task",
            return_value={
                "id": task_id,
                "status": "done",
                "video_path": "/tmp/v.mp4",
                "config_json": "{}",
                "clips_json": json.dumps(clips),
            },
        ),
        patch(
            "app.models.task.update_task_status",
            side_effect=lambda tid, s, **kw: fake_statuses.append((s, kw)),
        ),
        patch("app.worker.pipeline._export_clip", side_effect=Exception("ffmpeg crash")),
        patch("app.services.ffprobe.probe", return_value=mock_probe),
        patch("os.makedirs"),
        patch("os.path.isfile", return_value=False),
    ):
        export_clips_task.run(task_id=task_id, clip_indices=None, burn_subtitle=False)

    final = fake_statuses[-1]
    assert final[0] == "error"
    assert final[1].get("failed_stage") == "ai_exporting"


def test_export_clips_task_empty_selection():
    """export_clips_task: no valid clips → error (not processing)."""
    import json

    from app.worker.celery_app import export_clips_task

    task_id = "test-export-empty"
    clips = [{"start_time_s": 0, "end_time_s": 10, "status": "failed", "score": 9}]
    fake_statuses = []
    mock_probe = MagicMock(duration=300.0)

    with (
        patch(
            "app.models.task.get_task",
            return_value={
                "id": task_id,
                "status": "processing",
                "video_path": "/tmp/v.mp4",
                "config_json": "{}",
                "clips_json": json.dumps(clips),
            },
        ),
        patch(
            "app.models.task.update_task_status",
            side_effect=lambda tid, s, **kw: fake_statuses.append((s, kw)),
        ),
        patch("app.services.ffprobe.probe", return_value=mock_probe),
        patch("os.path.isdir", return_value=True),
    ):
        export_clips_task.run(task_id=task_id, clip_indices=[0], burn_subtitle=False)

    final = fake_statuses[-1]
    assert final[0] == "error"
    assert final[1].get("failed_stage") == "ai_exporting"
