"""Confidence endpoint tests: GET preserves confidence, PATCH nullifies it.

Requires auth headers — uses the configured test ACCESS_TOKEN from conftest.py.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_routes import _insert_task_full, _make_client, _setup_temp_db

# The test token set by conftest.py.
AUTH = {"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN', 'test-token-missing')}"}

T1 = "00000000-0000-0000-0000-000000000001"
T2 = "00000000-0000-0000-0000-000000000002"


def _setup_transcript(task_id, segments, tmp_output):
    task_output = Path(tmp_output) / task_id
    task_output.mkdir(parents=True, exist_ok=True)
    with open(task_output / "transcript.json", "w") as f:
        json.dump(segments, f)


class TestConfidenceGetEndpoint:
    def test_get_preserves_confidence(self):
        """Authenticated GET returns confidence from saved transcript."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_output = tempfile.mkdtemp()
            segments = [
                {
                    "start_time_s": 1.0,
                    "end_time_s": 5.0,
                    "text": "with confidence",
                    "confidence": 0.72,
                },
                {
                    "start_time_s": 6.0,
                    "end_time_s": 10.0,
                    "text": "no confidence",
                },
            ]
            _setup_transcript(T1, segments, tmp_output)
            _insert_task_full(db_path, T1)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(
                    f"/api/tasks/{T1}/transcript",
                    headers=AUTH,
                )

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is True
            assert body["segment_count"] == 2
            returned = body["segments"]
            assert returned[0]["confidence"] == 0.72
            # Second segment has no confidence — absent or null.
            assert returned[1].get("confidence") is None
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_get_old_transcript_without_confidence_works(self):
        """Old transcript.json without confidence field loads normally."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_output = tempfile.mkdtemp()
            segments = [
                {"start_time_s": 1.0, "end_time_s": 3.0, "text": "old format"},
            ]
            _setup_transcript(T2, segments, tmp_output)
            _insert_task_full(db_path, T2)

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.get(
                    f"/api/tasks/{T2}/transcript",
                    headers=AUTH,
                )

            assert response.status_code == 200
            body = response.json()
            assert body["available"] is True
            assert body["segment_count"] == 1
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)


class TestConfidencePatchEndpoint:
    def test_patch_accepts_confidence_and_saves_as_null(self):
        """Authenticated PATCH with confidence values persists them as null."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_output = tempfile.mkdtemp()
            original = [
                {"start_time_s": 1.0, "end_time_s": 3.0, "text": "original"},
            ]
            _setup_transcript(T1, original, tmp_output)
            _insert_task_full(db_path, T1)

            new_segments = [
                {
                    "start_time_s": 1.0,
                    "end_time_s": 3.0,
                    "text": "edited",
                    "confidence": 0.99,
                },
                {
                    "start_time_s": 5.0,
                    "end_time_s": 8.0,
                    "text": "added",
                    "confidence": 0.55,
                },
            ]

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                response = client.patch(
                    f"/api/tasks/{T1}/transcript",
                    json={
                        "segments": new_segments,
                        "base_transcript_version": 0,
                    },
                    headers=AUTH,
                )

            assert response.status_code == 200
            body = response.json()
            assert body["segment_count"] == 2

            # Verify saved transcript has confidence nullified.
            transcript_path = Path(tmp_output) / T1 / "transcript.json"
            with open(transcript_path) as f:
                saved = json.load(f)
            assert len(saved) == 2
            for seg in saved:
                assert seg.get("confidence") is None, (
                    f"Expected confidence null, got {seg.get('confidence')}"
                )
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)

    def test_get_after_patch_returns_null_confidence(self):
        """After PATCH nullifies confidence, GET returns null from saved transcript."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _setup_temp_db(db_path)
            tmp_output = tempfile.mkdtemp()
            original = [
                {"start_time_s": 1.0, "end_time_s": 3.0, "text": "original"},
            ]
            _setup_transcript(T2, original, tmp_output)
            _insert_task_full(db_path, T2)

            # Submit with confidence value — backend nullifies it.
            new_segments = [
                {
                    "start_time_s": 1.0,
                    "end_time_s": 5.0,
                    "text": "edited text",
                    "confidence": 0.88,
                },
            ]

            client = _make_client()
            with patch("app.api.subtitles.OUTPUT_DIR", Path(tmp_output)):
                patch_resp = client.patch(
                    f"/api/tasks/{T2}/transcript",
                    json={
                        "segments": new_segments,
                        "base_transcript_version": 0,
                    },
                    headers=AUTH,
                )
                assert patch_resp.status_code == 200

                # Verify via GET that confidence is null.
                get_resp = client.get(
                    f"/api/tasks/{T2}/transcript",
                    headers=AUTH,
                )
                assert get_resp.status_code == 200
                returned = get_resp.json()["segments"]
                assert len(returned) == 1
                assert returned[0].get("confidence") is None
        finally:
            os.unlink(db_path)
            import shutil

            shutil.rmtree(tmp_output, ignore_errors=True)
