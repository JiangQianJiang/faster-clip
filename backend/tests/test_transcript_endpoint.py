"""Tests for transcript import/export/GET/PATCH endpoints."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_routes import (
    _insert_task_full,
    _make_client,
    _make_info,
    _setup_temp_db,
)

# ── transcript endpoint ───────────────────────────────────────────────────────


class TestTranscriptEndpoint:
    """Transcript endpoint tests."""

    T1 = "00000000-0000-0000-0000-000000000001"
    T2 = "00000000-0000-0000-0000-000000000002"
    T3 = "00000000-0000-0000-0000-000000000003"
    T4 = "00000000-0000-0000-0000-000000000004"
    T5 = "00000000-0000-0000-0000-000000000005"
    T6 = "00000000-0000-0000-0000-000000000006"
    T7 = "00000000-0000-0000-0000-000000000007"
    T8 = "00000000-0000-0000-0000-000000000008"

    def test_success_returns_transcript(self):
        """GET /api/tasks/{id}/transcript returns 200 + available:true with sorted segments."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = tempfile.mkdtemp()
            task_output = Path(tmp_output) / task_id
            task_output.mkdir(parents=True, exist_ok=True)
            transcript = [
                {"start_time_s": 30.0, "end_time_s": 35.0, "text": "second"},
                {"start_time_s": 10.0, "end_time_s": 15.0, "text": "first"},
            ]
            with open(task_output / "transcript.json", "w") as f:
                json.dump(transcript, f)

            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 200
            body = response.json()
            assert body["task_id"] == task_id
            assert body["available"] is True
            assert body["segment_count"] == 2
            assert len(body["segments"]) == 2
            assert body["segments"][0]["start_time_s"] == 10.0
            assert body["segments"][1]["start_time_s"] == 30.0
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_task_not_found_returns_404(self):
        """GET /api/tasks/{id}/transcript returns 404 for non-existent task."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.get(f"/api/tasks/{self.T2}/transcript")
            assert response.status_code == 404
            assert "不存在" in response.json()["detail"]
        finally:
            os.unlink(db_path)

    def test_missing_transcript_available_false(self):
        """GET transcript returns 200 + available:false when transcript.json missing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T3
            tmp_output = tempfile.mkdtemp()
            task_output = Path(tmp_output) / task_id
            task_output.mkdir(parents=True, exist_ok=True)

            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is False
            assert body["segment_count"] == 0
            assert body["segments"] == []
            assert "detail" in body
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_pending_task_available_false(self):
        """GET transcript returns 200 + available:false for pending task."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T4
            _insert_task_full(db_path, task_id, status="pending")

            client = _make_client()
            response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is False
            assert "尚未开始" in body["detail"]
        finally:
            os.unlink(db_path)

    def test_queued_task_available_false(self):
        """GET transcript returns 200 + available:false for queued task."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T5
            _insert_task_full(db_path, task_id, status="queued")

            client = _make_client()
            response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is False
            assert "尚未开始" in body["detail"]
        finally:
            os.unlink(db_path)

    def test_extracting_subtitles_available_false(self):
        """GET transcript returns 200 + available:false while extracting subtitles."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T6
            _insert_task_full(
                db_path, task_id, status="processing", stage="extracting_subtitles"
            )

            client = _make_client()
            response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is False
            assert "字幕提取中" in body["detail"]
        finally:
            os.unlink(db_path)

    def test_error_extraction_failed_available_false(self):
        """GET transcript returns 200 + available:false when extraction failed."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T7
            _insert_task_full(
                db_path,
                task_id,
                status="error",
                stage="extracting_subtitles",
                failed_stage="extracting_subtitles",
                error_message="ASR service timeout",
            )

            client = _make_client()
            response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is False
            assert "字幕提取失败" in body["detail"]
            assert "ASR service timeout" in body["detail"]
        finally:
            os.unlink(db_path)

    def test_malformed_json_returns_500(self):
        """GET transcript returns 500 when transcript.json is invalid JSON."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T8
            tmp_output = tempfile.mkdtemp()
            task_output = Path(tmp_output) / task_id
            task_output.mkdir(parents=True, exist_ok=True)
            with open(task_output / "transcript.json", "w") as f:
                f.write("not valid json {{{")

            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 500
            assert "格式错误" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_filters_invalid_segments(self):
        """GET transcript filters out segments with invalid timestamps or empty text."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = tempfile.mkdtemp()
            task_output = Path(tmp_output) / task_id
            task_output.mkdir(parents=True, exist_ok=True)
            transcript = [
                {"start_time_s": 10.0, "end_time_s": 15.0, "text": "valid"},
                {"start_time_s": -1.0, "end_time_s": 5.0, "text": "bad start"},
                {"start_time_s": 20.0, "end_time_s": 18.0, "text": "inverted"},
                {"start_time_s": 25.0, "end_time_s": 30.0, "text": ""},
                {"start_time_s": 35.0, "end_time_s": 40.0, "text": "also valid"},
            ]
            with open(task_output / "transcript.json", "w") as f:
                json.dump(transcript, f)

            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(f"/api/tasks/{task_id}/transcript")

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is True
            assert body["segment_count"] == 2
            texts = [s["text"] for s in body["segments"]]
            assert texts == ["valid", "also valid"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_transcript_traversal_encoded_dot_returns_400(self):
        """GET transcript returns 400 for URL-encoded ../ (%2E%2E) traversal."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.get("/api/tasks/%2E%2E/transcript")
            assert response.status_code == 400
        finally:
            os.unlink(db_path)

    def test_transcript_traversal_encoded_slash_returns_400(self):
        """GET transcript returns 400 for URL-encoded / (%2F) traversal."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.get("/api/tasks/..%2Ffoo/transcript")
            assert response.status_code == 400
        finally:
            os.unlink(db_path)

    def test_transcript_traversal_encoded_slash_internal_returns_400(self):
        """GET transcript returns 400 for %2F with .. inside the task_id segment."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.get("/api/tasks/foo%2F..%2Fbar/transcript")
            assert response.status_code == 400
        finally:
            os.unlink(db_path)


# ── Subtitle Import Integration Tests ──────────────────────────────────────


class TestSubtitleImport:
    """Import subtitle during upload (task13)."""

    import tempfile

    def _make_srt_content(self):
        return (
            b"1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n"
            b"2\n00:00:05,000 --> 00:00:08,000\nSecond cue\n\n"
        )

    def test_upload_with_valid_srt(self):
        """Upload video + valid SRT -> 201 with import metadata and transcript saved."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            tmp_output = tempfile.mkdtemp()
            client = _make_client()

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
                patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
                patch("app.worker.celery_app.process_video_task.apply_async"),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": (
                            "test.srt",
                            self._make_srt_content(),
                            "text/plain",
                        ),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 201
            body = response.json()
            assert "task_id" in body
            assert body.get("imported_count") == 2
            assert body.get("skipped_count") == 0

            # Verify transcript.json was saved
            task_id = body["task_id"]
            transcript_path = Path(tmp_output) / task_id / "transcript.json"
            assert transcript_path.exists()
            with open(transcript_path) as f:
                saved = json.load(f)
            assert len(saved) == 2
            assert saved[0]["text"] == "Hello world"

            # Verify task model fields
            from app.models.task import get_task

            task = get_task(task_id)
            assert task["transcript_source"] == "subtitle_import"
            assert task["transcript_modified_at"] is not None
            assert task["subtitle_segment_count"] == 2
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)
            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_upload_with_warnings(self):
        """Upload with some invalid segments -> 200 with warnings."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            tmp_output = tempfile.mkdtemp()
            client = _make_client()

            # SRT with one bad segment (negative timestamp) and one valid
            content = (
                b"1\n00:00:01,000 --> 00:00:03,500\nValid\n\n"
                b"2\n00:00:05,000 --> 00:00:03,000\nBad timing\n\n"
            )
            # Note: _parse_srt will parse both, validate_transcript will skip bad timing

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
                patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
                patch("app.worker.celery_app.process_video_task.apply_async"),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": ("test.srt", content, "text/plain"),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 201
            body = response.json()
            assert body.get("imported_count") == 1
            assert body.get("skipped_count") == 1
            assert len(body.get("warnings", [])) == 1
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)
            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_subtitle_unsupported_format(self):
        """Upload with unsupported subtitle format -> 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            client = _make_client()

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": ("test.txt", b"text", "text/plain"),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 400
            assert "不支持的字幕格式" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)

    def test_subtitle_file_too_large(self):
        """Upload subtitle >5MB -> 413 with cleanup."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            client = _make_client()

            # Create content > 5MB
            large = b"x" * (5 * 1024 * 1024 + 1)

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": ("large.srt", large, "text/plain"),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 413
            detail = response.json()["detail"]
            assert "5MB" in detail or "大小" in detail
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)

    def test_subtitle_non_utf8(self):
        """Upload non-UTF-8 subtitle -> 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            client = _make_client()

            # UTF-16LE content
            utf16 = b"\xff\xfeH\x00e\x00l\x00l\x00o\x00"

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": ("bad.srt", utf16, "text/plain"),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 400
            assert "Encoding" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)

    def test_subtitle_malformed(self):
        """Upload unparseable subtitle -> 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            client = _make_client()

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": (
                            "bad.srt",
                            b"not valid srt content",
                            "text/plain",
                        ),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 400
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)

    def test_subtitle_all_segments_invalid(self):
        """Upload with all segments invalid -> 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            tmp_output = tempfile.mkdtemp()
            client = _make_client()

            # SRT where both segments have invalid timing
            content = (
                b"1\n00:00:05,000 --> 00:00:03,000\nBad end\n\n"
                b"2\n00:00:08,000 --> 00:00:06,000\nAlso bad end\n\n"
            )

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
                patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": ("bad.srt", content, "text/plain"),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 400
            assert "No valid segments" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)
            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_subtitle_too_many_segments(self):
        """Upload subtitle with >5000 segments -> 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            tmp_output = tempfile.mkdtemp()
            client = _make_client()

            # Generate >5000 segments
            lines = []
            for i in range(5001):
                s = int(i)
                ms = 0
                h = s // 3600
                m = (s % 3600) // 60
                sec = s % 60
                ts = f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
                te = f"{h:02d}:{m:02d}:{sec:02d},500"
                lines.append(f"{i + 1}\n{ts} --> {te}\nSegment {i}\n")
            large_srt = "\n".join(lines).encode("utf-8")

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
                patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                        "subtitle_file": ("large.srt", large_srt, "text/plain"),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 400
            assert "Too many segments" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)
            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_upload_without_subtitle_still_works(self):
        """Upload without subtitle_file still returns 201 (backward compat)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_videos = tempfile.mkdtemp()
            tmp_output = tempfile.mkdtemp()
            client = _make_client()

            with (
                patch("app.api.tasks_crud.probe", return_value=_make_info()),
                patch("app.api.tasks_crud.VIDEOS_DIR", Path(tmp_videos)),
                patch("app.api.tasks_crud.OUTPUT_DIR", Path(tmp_output)),
                patch("app.worker.celery_app.process_video_task.apply_async"),
            ):
                response = client.post(
                    "/api/tasks",
                    files={
                        "file": ("test.mp4", b"fake mp4", "video/mp4"),
                    },
                    data={
                        "llm_base_url": "https://api.example.com",
                        "llm_model": "m",
                        "llm_api_key": "sk-test",
                    },
                )

            assert response.status_code == 201
            body = response.json()
            assert "task_id" in body
            assert "imported_count" not in body
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_videos, ignore_errors=True)
            shutil.rmtree(tmp_output, ignore_errors=True)


# ── Export Endpoint Tests ──────────────────────────────────────────────────


class TestExportTranscript:
    """Export transcript endpoint tests (task15)."""

    T1 = "00000000-0000-0000-0000-000000000001"

    def _setup_transcript(self, db_path, task_id, segments):
        import tempfile

        tmp_output = tempfile.mkdtemp()
        task_output = Path(tmp_output) / task_id
        task_output.mkdir(parents=True, exist_ok=True)
        with open(task_output / "transcript.json", "w") as f:
            json.dump(segments, f)
        return tmp_output

    def test_export_srt(self):
        """Export as SRT returns 200 with proper format."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(
                db_path,
                task_id,
                [
                    {"start_time_s": 1.0, "end_time_s": 3.5, "text": "Hello"},
                ],
            )
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(
                    f"/api/tasks/{task_id}/transcript/export?format=srt"
                )

            assert response.status_code == 200
            cd = response.headers["content-disposition"]
            assert "attachment" in cd
            assert f"transcript_{task_id}.srt" in cd
            assert "text/plain" in response.headers["content-type"]
            body = response.text
            assert "Hello" in body
            assert "00:00:01,000 --> 00:00:03,500" in body
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_export_vtt(self):
        """Export as VTT returns 200 with WEBVTT header."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(
                db_path,
                task_id,
                [
                    {"start_time_s": 1.0, "end_time_s": 3.5, "text": "Hello"},
                ],
            )
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(
                    f"/api/tasks/{task_id}/transcript/export?format=vtt"
                )

            assert response.status_code == 200
            body = response.text
            assert body.startswith("WEBVTT")
            assert "Hello" in body
            assert "00:00:01.000 --> 00:00:03.500" in body
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_export_ass(self):
        """Export as ASS returns 200 with Script Info header."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(
                db_path,
                task_id,
                [
                    {"start_time_s": 1.0, "end_time_s": 3.0, "text": "Hello"},
                ],
            )
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(
                    f"/api/tasks/{task_id}/transcript/export?format=ass"
                )

            assert response.status_code == 200
            assert "text/x-ssa" in response.headers["content-type"]
            body = response.text
            assert "[Script Info]" in body
            assert "[Events]" in body
            assert "Dialogue:" in body
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_export_invalid_format(self):
        """Export with unsupported format returns 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(db_path, task_id, [])
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(
                    f"/api/tasks/{task_id}/transcript/export?format=pdf"
                )

            assert response.status_code == 400
            assert "Unsupported format" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_export_invalid_task_id(self):
        """Export with invalid task_id returns 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.get("/api/tasks/not-a-uuid/transcript/export")
            assert response.status_code == 400
        finally:
            os.unlink(db_path)

    def test_export_task_not_found(self):
        """Export for non-existent task returns 404."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.get(
                "/api/tasks/00000000-0000-0000-0000-000000000099/transcript/export"
            )
            assert response.status_code == 404
        finally:
            os.unlink(db_path)

    def test_export_no_transcript(self):
        """Export when transcript doesn't exist returns 404."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = tempfile.mkdtemp()
            # Don't create transcript.json
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(
                    f"/api/tasks/{task_id}/transcript/export?format=srt"
                )

            assert response.status_code == 404
            assert "not available" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)


# ── PATCH Transcript Endpoint Tests ───────────────────────────────────────


class TestPatchTranscript:
    """PATCH transcript editing tests (task18)."""

    T1 = "00000000-0000-0000-0000-000000000001"

    def _setup_transcript(self, task_id, segments):
        import tempfile

        tmp_output = tempfile.mkdtemp()
        task_output = Path(tmp_output) / task_id
        task_output.mkdir(parents=True, exist_ok=True)
        with open(task_output / "transcript.json", "w") as f:
            json.dump(segments, f)
        return tmp_output

    def test_patch_valid_transcript(self):
        """PATCH with valid segments persists and returns success."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [
                {"start_time_s": 1.0, "end_time_s": 3.0, "text": "Old"},
                {"start_time_s": 5.0, "end_time_s": 8.0, "text": "Second old"},
            ]
            tmp_output = self._setup_transcript(task_id, original)
            _insert_task_full(db_path, task_id)

            # Text-only: same timestamps, same count, only text changes
            new_segments = [
                {"start_time_s": 1.0, "end_time_s": 3.0, "text": "New text"},
                {"start_time_s": 5.0, "end_time_s": 8.0, "text": "Second new"},
            ]

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={"segments": new_segments, "base_transcript_version": 0},
                )

            assert response.status_code == 200
            body = response.json()
            assert body["task_id"] == task_id
            assert body["segment_count"] == 2
            assert body["transcript_modified_at"] is not None

            # Verify persisted
            transcript_path = Path(tmp_output) / task_id / "transcript.json"
            with open(transcript_path) as f:
                saved = json.load(f)
            assert len(saved) == 2
            assert saved[0]["text"] == "New text"
            assert saved[1]["text"] == "Second new"

            # Verify model fields
            from app.models.task import get_task

            task = get_task(task_id)
            assert task["transcript_source"] == "manual_edit"
            assert task["transcript_modified_at"] is not None
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_accepts_segment_count_and_timing_changes(self):
        """PATCH replaces the full transcript, including timing and count changes."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            _insert_task_full(db_path, task_id)

            new_segments = [
                {"start_time_s": 5.0, "end_time_s": 8.0, "text": "second", "_line": 99},
                {"start_time_s": 0.0, "end_time_s": 2.0, "text": "first"},
            ]

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={"segments": new_segments, "base_transcript_version": 0},
                )

            assert response.status_code == 200
            assert response.json()["segment_count"] == 2

            transcript_path = Path(tmp_output) / task_id / "transcript.json"
            with open(transcript_path) as f:
                saved = json.load(f)
            assert [s["text"] for s in saved] == ["first", "second"]
            assert "_line" not in saved[1]

            from app.models.task import get_task

            task = get_task(task_id)
            assert task["subtitle_segment_count"] == 2
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_rejected_during_processing(self):
        """PATCH while task is processing returns 409."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            _insert_task_full(db_path, task_id, status="processing")
            client = _make_client()
            response = client.patch(
                f"/api/tasks/{task_id}/transcript",
                json={
                    "segments": [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "X"}],
                    "base_transcript_version": 0,
                },
            )
            assert response.status_code == 409
        finally:
            os.unlink(db_path)

    def test_patch_rejected_during_queued(self):
        """PATCH while task is queued returns 409."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            _insert_task_full(db_path, task_id, status="queued")
            client = _make_client()
            response = client.patch(
                f"/api/tasks/{task_id}/transcript",
                json={
                    "segments": [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "X"}],
                    "base_transcript_version": 0,
                },
            )
            assert response.status_code == 409
        finally:
            os.unlink(db_path)

    def test_patch_invalid_task_id(self):
        """PATCH with invalid task_id returns 400."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.patch(
                "/api/tasks/not-a-uuid/transcript",
                json={"segments": [], "base_transcript_version": 0},
            )
            assert response.status_code == 400
        finally:
            os.unlink(db_path)

    def test_patch_task_not_found(self):
        """PATCH for non-existent task returns 404."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            client = _make_client()
            response = client.patch(
                "/api/tasks/00000000-0000-0000-0000-000000000099/transcript",
                json={
                    "segments": [{"start_time_s": 1.0, "end_time_s": 2.0, "text": "x"}],
                    "base_transcript_version": 0,
                },
            )
            assert response.status_code == 404
        finally:
            os.unlink(db_path)

    def test_patch_empty_text(self):
        """PATCH with empty text returns 422."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(task_id, [])
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 1.0, "end_time_s": 3.0, "text": ""},
                        ],
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 422
            assert "empty" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_timing_violation(self):
        """PATCH with end <= start returns 422."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(task_id, [])
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 5.0, "end_time_s": 3.0, "text": "bad"},
                        ],
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 422
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_rejects_overlapping_segments_after_sort(self):
        """PATCH with overlapping segments returns 422 after sorting."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(task_id, [])
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 3.0, "end_time_s": 5.0, "text": "second"},
                            {"start_time_s": 1.0, "end_time_s": 4.0, "text": "first"},
                        ],
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 422
            assert "overlap" in response.json()["detail"].lower()
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_negative_timestamp(self):
        """PATCH with negative timestamp returns 422."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(task_id, [])
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": -1.0, "end_time_s": 3.0, "text": "bad"},
                        ],
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 422
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_text_too_long(self):
        """PATCH with text >1000 chars returns 422."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            tmp_output = self._setup_transcript(task_id, [])
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {
                                "start_time_s": 1.0,
                                "end_time_s": 3.0,
                                "text": "x" * 1001,
                            },
                        ],
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 422
            assert "text" in response.json()["detail"].lower()
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_unicode_preserved(self):
        """PATCH with Unicode text preserves characters."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {
                                "start_time_s": 1.0,
                                "end_time_s": 3.0,
                                "text": "你好世界",
                            },
                        ],
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 200

            # Verify via GET
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                get_resp = client.get(f"/api/tasks/{task_id}/transcript")
            assert get_resp.json()["segments"][0]["text"] == "你好世界"
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_regenerates_clip_subtitle_sidecars(self):
        """PATCH after_save=regenerate_clip_subtitles rewrites SRT/VTT/ASS files."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            clips = [
                {
                    "start_time_s": 0.0,
                    "end_time_s": 6.0,
                    "export_start_time_s": 0.0,
                    "export_end_time_s": 6.0,
                    "status": "success",
                    "filepath": str(Path(tmp_output) / task_id / "clip_000.mp4"),
                }
            ]
            _insert_task_full(db_path, task_id, clips_json=json.dumps(clips))

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {
                                "start_time_s": 1.0,
                                "end_time_s": 3.0,
                                "text": "fresh text",
                            },
                        ],
                        "after_save": "regenerate_clip_subtitles",
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 200
            for ext in ("srt", "vtt", "ass"):
                path = Path(tmp_output) / task_id / f"clip_000.{ext}"
                assert path.exists(), f"missing {path}"
                assert "fresh text" in path.read_text(encoding="utf-8")
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_save_only_does_not_dispatch_celery_or_touch_clips(self):
        """PATCH after_save=save_only only writes transcript metadata."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            clips = [{"status": "success", "start_time_s": 1.0, "end_time_s": 3.0}]
            _insert_task_full(db_path, task_id, clips_json=json.dumps(clips))

            client = _make_client()
            with (
                patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)),
                patch(
                    "app.worker.celery_app.process_video_task.apply_async"
                ) as mock_apply,
            ):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "fresh"},
                        ],
                        "after_save": "save_only",
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 200
            mock_apply.assert_not_called()
            from app.models.task import get_task

            task = get_task(task_id)
            assert json.loads(task["clips_json"]) == clips
            assert not (Path(tmp_output) / task_id / "clip_000.srt").exists()
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_regenerate_skips_missing_and_failed_clips(self):
        """PATCH regenerate handles no successful clips without mutating clip status."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            clips = [{"status": "failed", "start_time_s": 1.0, "end_time_s": 3.0}]
            _insert_task_full(db_path, task_id, clips_json=json.dumps(clips))

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "fresh"},
                        ],
                        "after_save": "regenerate_clip_subtitles",
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 200
            assert not (Path(tmp_output) / task_id / "clip_000.srt").exists()
            from app.models.task import get_task

            task = get_task(task_id)
            assert json.loads(task["clips_json"]) == clips
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_rejects_stale_transcript_modified_at(self):
        """PATCH returns 409 if the caller edits an older transcript version."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            _insert_task_full(db_path, task_id)
            from app.models.task import bump_transcript_version_if_current

            assert bump_transcript_version_if_current(
                task_id,
                0,
                "2026-05-28T12:00:00+00:00",
            )

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "new"},
                        ],
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 409
            assert "版本" in response.json()["detail"]
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_reanalyze_saves_transcript_and_queues_task(self):
        """PATCH after_save=reanalyze saves the transcript before dispatching Celery."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            video_path = str(Path(tempfile.mkdtemp()) / "original.mp4")
            Path(video_path).write_bytes(b"fake video")
            _insert_task_full(db_path, task_id, video_path=video_path)

            client = _make_client()
            with (
                patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)),
                patch(
                    "app.worker.celery_app.process_video_task.apply_async"
                ) as mock_apply,
            ):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "fresh"},
                        ],
                        "after_save": "reanalyze",
                        "llm_api_key": "sk-test",
                        "asr_api_key": "",
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 200
            with open(Path(tmp_output) / task_id / "transcript.json") as f:
                saved = json.load(f)
            assert saved[0]["text"] == "fresh"

            from app.models.task import get_task

            task = get_task(task_id)
            assert task["status"] == "queued"

            mock_apply.assert_called_once()
            kwargs = mock_apply.call_args.kwargs["kwargs"]
            assert kwargs["task_id"] == task_id
            assert kwargs["video_path"] == video_path
            assert kwargs["llm_api_key"] != "sk-test"
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)
            shutil.rmtree(str(Path(video_path).parent), ignore_errors=True)

    def test_patch_reanalyze_requires_llm_api_key(self):
        """PATCH after_save=reanalyze rejects requests without a fresh LLM key."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            original = [{"start_time_s": 1.0, "end_time_s": 3.0, "text": "old"}]
            tmp_output = self._setup_transcript(task_id, original)
            _insert_task_full(db_path, task_id)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={
                        "segments": [
                            {"start_time_s": 1.0, "end_time_s": 3.0, "text": "fresh"},
                        ],
                        "after_save": "reanalyze",
                        "base_transcript_version": 0,
                    },
                )

            assert response.status_code == 422
            with open(Path(tmp_output) / task_id / "transcript.json") as f:
                saved = json.load(f)
            assert saved[0]["text"] == "old"
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_patch_accepts_unnormalized_existing_timestamps(self):
        """Text-only edit succeeds when existing transcript has >3 decimal timestamps."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            task_id = self.T1
            # Simulate ASR output with high-precision floats
            original = [
                {"start_time_s": 1.234567, "end_time_s": 2.345678, "text": "old text"},
                {
                    "start_time_s": 5.123456,
                    "end_time_s": 8.987654,
                    "text": "second old",
                },
            ]
            tmp_output = self._setup_transcript(task_id, original)
            _insert_task_full(db_path, task_id)

            # Client sends back normalized timestamps (as GET /transcript would return)
            new_segments = [
                {"start_time_s": 1.235, "end_time_s": 2.346, "text": "new text"},
                {"start_time_s": 5.123, "end_time_s": 8.988, "text": "second new"},
            ]

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{task_id}/transcript",
                    json={"segments": new_segments, "base_transcript_version": 0},
                )

            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.json()}"
            )
            body = response.json()
            assert body["segment_count"] == 2
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)
