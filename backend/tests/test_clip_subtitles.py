"""Tests for clip subtitle download and JSON API endpoints."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _setup_temp_db(db_path, task_id, clips):
    import app.config
    import app.models.task as task_mod

    app.config.settings.database_path = db_path
    task_mod.DB_PATH = Path(db_path)
    from app.models.task import init_db

    init_db()
    import sqlite3

    conn = sqlite3.connect(db_path)
    now = "2026-05-26T00:00:00+00:00"
    conn.execute(
        """INSERT INTO tasks (id, status, video_path, video_filename,
           config_json, clips_json, created_at, updated_at)
           VALUES (?, 'done', ?, ?, ?, ?, ?, ?)""",
        (
            task_id,
            f"data/videos/{task_id}/original.mp4",
            "test.mp4",
            json.dumps({"llm_base_url": "http://x", "llm_model": "m"}),
            json.dumps(clips),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()


def _make_client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def _write_subtitle_file(output_dir, clip_index, ext, content):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"clip_{clip_index:03d}.{ext}")
    with open(path, "w") as f:
        f.write(content)
    return path


_CLIP_SUCCESS = {
    "start_time_s": 50,
    "end_time_s": 60,
    "export_start_time_s": 47,
    "export_end_time_s": 63,
    "score": 8.5,
    "reason": "Great moment",
    "status": "success",
    "filepath": "data/output/TESTID/clip_000.mp4",
    "thumbnail_path": "data/output/TESTID/clip_000.jpg",
}


# ── Subtitle Download Endpoint ─────────────────────────────────────────────


class TestDownloadSubtitle:
    def test_download_srt_default(self):
        task_id = "11111111-1111-1111-1111-111111111111"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            output_dir = os.path.join("data", "output", task_id)
            _write_subtitle_file(
                output_dir, 0, "srt", "1\n00:00:00,000 --> 00:00:05,000\nHello\n"
            )
            _write_subtitle_file(
                output_dir,
                0,
                "vtt",
                "WEBVTT\n\n1\n00:00:00.000 --> 00:00:05.000\nHello\n",
            )
            _write_subtitle_file(output_dir, 0, "ass", "[Script Info]\n")
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles")
            assert resp.status_code == 200
            assert "attachment" in resp.headers.get("content-disposition", "")
        finally:
            os.unlink(db_path)

    def test_download_vtt_format(self):
        task_id = "22222222-2222-2222-2222-222222222222"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            output_dir = os.path.join("data", "output", task_id)
            _write_subtitle_file(output_dir, 0, "vtt", "WEBVTT\n")
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles?format=vtt")
            assert resp.status_code == 200
        finally:
            os.unlink(db_path)

    def test_download_ass_format(self):
        task_id = "33333333-3333-3333-3333-333333333333"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            output_dir = os.path.join("data", "output", task_id)
            _write_subtitle_file(output_dir, 0, "ass", "[Script Info]\n")
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles?format=ass")
            assert resp.status_code == 200
        finally:
            os.unlink(db_path)

    def test_invalid_format_returns_400(self):
        task_id = "44444444-4444-4444-4444-444444444444"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles?format=pdf")
            assert resp.status_code == 400
        finally:
            os.unlink(db_path)

    def test_clip_not_found_returns_404(self):
        task_id = "55555555-5555-5555-5555-555555555555"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/99/subtitles")
            assert resp.status_code == 404
        finally:
            os.unlink(db_path)

    def test_task_not_found_returns_404(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, "00000000-0000-0000-0000-000000000000", [])
            client = _make_client()
            resp = client.get(
                "/api/tasks/99999999-9999-9999-9999-999999999999/clips/0/subtitles"
            )
            assert resp.status_code == 404
        finally:
            os.unlink(db_path)

    def test_failed_clip_returns_404(self):
        task_id = "66666666-6666-6666-6666-666666666666"
        failed_clip = dict(_CLIP_SUCCESS, status="failed")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [failed_clip])
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles")
            assert resp.status_code == 404
        finally:
            os.unlink(db_path)

    def test_missing_subtitle_file_returns_404(self):
        task_id = "77777777-7777-7777-7777-777777777777"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles")
            assert resp.status_code == 404
        finally:
            os.unlink(db_path)

    def test_non_integer_clip_index_returns_400(self):
        task_id = "88888888-8888-8888-8888-888888888888"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/abc/subtitles")
            assert resp.status_code == 400
        finally:
            os.unlink(db_path)


# ── Subtitle JSON Endpoint ──────────────────────────────────────────────────


class TestSubtitleJson:
    def test_returns_segments_with_offset(self):
        task_id = "99999999-9999-9999-9999-999999999999"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            output_dir = os.path.join("data", "output", task_id)
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, "transcript.json"), "w") as f:
                json.dump(
                    [
                        {"start_time_s": 48, "end_time_s": 52, "text": "A"},
                        {"start_time_s": 55, "end_time_s": 62, "text": "B"},
                    ],
                    f,
                )
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles/json")
            assert resp.status_code == 200
            data = resp.json()
            assert data["clip_index"] == 0
            assert len(data["segments"]) == 2
            assert data["segments"][0]["start_time_s"] == 1.0  # 48-47
            assert data["segments"][0]["text"] == "A"
        finally:
            os.unlink(db_path)


class TestClipSubtitleFiltering:
    def test_clip_boundary_text_matches_clipped_words(self):
        """Partial clip-window cues should not keep text outside the clipped words."""
        from app.services.subtitle import get_clip_subtitle_segments

        words = [
            {"text": "窗", "start_time_s": 10.0, "end_time_s": 10.5},
            {"text": "外", "start_time_s": 10.5, "end_time_s": 11.0},
            {"text": "窗", "start_time_s": 11.0, "end_time_s": 11.5},
            {"text": "内", "start_time_s": 11.5, "end_time_s": 12.0},
            {"text": "字", "start_time_s": 12.0, "end_time_s": 12.5},
            {"text": "幕", "start_time_s": 12.5, "end_time_s": 13.0},
            {"text": "外", "start_time_s": 13.0, "end_time_s": 13.5},
        ]
        segments = [
            {
                "start_time_s": 10.0,
                "end_time_s": 13.5,
                "text": "窗外窗内字幕外",
                "words": words,
            }
        ]

        result = get_clip_subtitle_segments(segments, 11.0, 13.0)

        assert result == [
            {
                "start_time_s": 0.0,
                "end_time_s": 2.0,
                "text": "窗内字幕",
                "words": [
                    {"text": "窗", "start_time_s": 0.0, "end_time_s": 0.5},
                    {"text": "内", "start_time_s": 0.5, "end_time_s": 1.0},
                    {"text": "字", "start_time_s": 1.0, "end_time_s": 1.5},
                    {"text": "幕", "start_time_s": 1.5, "end_time_s": 2.0},
                ],
            }
        ]

    def test_no_transcript_file_returns_empty_segments(self):
        task_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [_CLIP_SUCCESS])
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles/json")
            assert resp.status_code == 200
            data = resp.json()
            assert data["segments"] == []
        finally:
            os.unlink(db_path)

    def test_failed_clip_returns_404(self):
        task_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        failed_clip = dict(_CLIP_SUCCESS, status="failed")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path, task_id, [failed_clip])
            client = _make_client()
            resp = client.get(f"/api/tasks/{task_id}/clips/0/subtitles/json")
            assert resp.status_code == 404
        finally:
            os.unlink(db_path)
