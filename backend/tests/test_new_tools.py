"""Tests for new user tools: apply_subtitle_style, regenerate_subtitles."""

import asyncio
import json
from pathlib import Path


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


# --- regenerate_subtitles ---


def _use_temp_task_store(monkeypatch, tmp_path):
    """Point task DB and subtitle output at a temp directory for tool tests."""
    import app.models.task as task_model
    import app.tools.user.regenerate_subtitles as regen
    import app.tools.user.run_asr as run_asr

    db_path = tmp_path / "tasks.db"
    output_dir = tmp_path / "output"
    monkeypatch.setattr(task_model, "DB_PATH", db_path)
    monkeypatch.setattr(task_model, "_MIGRATION_LOCK_FILE", db_path.parent / ".migration.lock")
    monkeypatch.setattr(regen, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(run_asr, "OUTPUT_DIR", output_dir)
    task_model.init_db()
    return output_dir


def test_regenerate_subtitles_reflows_existing_transcript_without_asr_key(monkeypatch, tmp_path):
    """Regenerating existing subtitles should not require an ASR API key."""
    output_dir = _use_temp_task_store(monkeypatch, tmp_path)
    task_id = _make_task(
        extra_config={
            "asr_provider": "qwen",
            "asr_model": "qwen3-asr-flash-filetrans",
        }
    )
    transcript_dir = output_dir / task_id
    transcript_dir.mkdir(parents=True)
    transcript_path = transcript_dir / "transcript.json"
    transcript_path.write_text(
        json.dumps(
            [
                {
                    "start_time_s": 0.0,
                    "end_time_s": 5.0,
                    "text": "这是一条已经存在但是需要重新断行整理的字幕内容",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from app.models.task import get_task
    from app.tools.user.regenerate_subtitles import _regenerate_subtitles

    result = asyncio.run(_regenerate_subtitles.execute(task_id=task_id))

    assert result.success is True
    assert "无需 ASR API Key" in result.user_message
    updated_segments = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert len(updated_segments) >= 1
    assert all(len(s["text"].replace("\n", "")) <= 24 for s in updated_segments)
    task = get_task(task_id)
    assert task["subtitle_segment_count"] == len(updated_segments)
    assert task["transcript_source"] == "regenerated_subtitles"


def test_regenerate_subtitles_preserves_word_timings(monkeypatch, tmp_path):
    """Regenerating existing subtitles should keep ASR word-level timings."""
    output_dir = _use_temp_task_store(monkeypatch, tmp_path)
    task_id = _make_task()
    transcript_dir = output_dir / task_id
    transcript_dir.mkdir(parents=True)
    transcript_path = transcript_dir / "transcript.json"
    words = [
        {"text": "今天", "start_time_s": 0.0, "end_time_s": 0.5},
        {"text": "我们", "start_time_s": 0.5, "end_time_s": 1.0},
        {"text": "聊聊", "start_time_s": 1.0, "end_time_s": 1.5},
        {"text": "字幕", "start_time_s": 1.5, "end_time_s": 2.0},
    ]
    transcript_path.write_text(
        json.dumps(
            [
                {
                    "start_time_s": 0.0,
                    "end_time_s": 2.0,
                    "text": "今天我们\n聊聊字幕",
                    "words": words,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from app.tools.user.regenerate_subtitles import _regenerate_subtitles

    result = asyncio.run(_regenerate_subtitles.execute(task_id=task_id))

    assert result.success is True
    regenerated = json.loads(transcript_path.read_text(encoding="utf-8"))
    output_words = [w for segment in regenerated for w in segment.get("words", [])]
    assert output_words == words


def test_regenerate_subtitles_rewrites_clip_sidecars(monkeypatch, tmp_path):
    """The local regeneration tool should refresh existing clip subtitle files."""
    output_dir = _use_temp_task_store(monkeypatch, tmp_path)
    clips = [
        {
            "start_time_s": 0.0,
            "end_time_s": 4.0,
            "export_start_time_s": 0.0,
            "export_end_time_s": 4.0,
            "status": "success",
        }
    ]
    task_id = _make_task(clips=clips)
    transcript_dir = output_dir / task_id
    transcript_dir.mkdir(parents=True)
    (transcript_dir / "transcript.json").write_text(
        json.dumps(
            [
                {"start_time_s": 0.0, "end_time_s": 2.0, "text": "第一句字幕"},
                {"start_time_s": 2.0, "end_time_s": 4.0, "text": "第二句字幕"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from app.tools.user.regenerate_subtitles import _regenerate_subtitles

    result = asyncio.run(_regenerate_subtitles.execute(task_id=task_id))

    assert result.success is True
    assert result.data["clip_subtitle_files"] == 3
    for ext in ("srt", "vtt", "ass"):
        path = Path(output_dir / task_id / f"clip_000.{ext}")
        assert path.exists()
        assert "第一句字幕" in path.read_text(encoding="utf-8")


def test_regenerate_subtitles_uses_current_transcript_when_raw_exists(monkeypatch, tmp_path):
    """Regeneration should use transcript.json as the source of truth."""
    output_dir = _use_temp_task_store(monkeypatch, tmp_path)
    task_id = _make_task()
    transcript_dir = output_dir / task_id
    transcript_dir.mkdir(parents=True)
    raw_path = transcript_dir / "transcript.raw.json"
    raw_payload = [
        {
            "start_time_s": 0.0,
            "end_time_s": 5.0,
            "text": "那个那个今天我们来看看这个非常有趣的节目内容介绍",
        }
    ]
    raw_path.write_text(
        json.dumps(
            raw_payload,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (transcript_dir / "transcript.json").write_text(
        json.dumps(
            [{"start_time_s": 0.0, "end_time_s": 5.0, "text": "被编辑过的字幕"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from app.tools.user.regenerate_subtitles import _regenerate_subtitles

    result = asyncio.run(_regenerate_subtitles.execute(task_id=task_id))

    assert result.success is True
    regenerated = json.loads((transcript_dir / "transcript.json").read_text(encoding="utf-8"))
    joined = "".join(s["text"].replace("\n", "") for s in regenerated)
    assert "被编辑过的字幕" in joined
    assert "那个今天我们来看看" not in joined
    assert json.loads(raw_path.read_text(encoding="utf-8")) == raw_payload


def test_regenerate_subtitles_fails_without_current_transcript(monkeypatch, tmp_path):
    """Raw transcript sidecars are not a fallback for missing transcript.json."""
    output_dir = _use_temp_task_store(monkeypatch, tmp_path)
    task_id = _make_task()
    transcript_dir = output_dir / task_id
    transcript_dir.mkdir(parents=True)
    (transcript_dir / "transcript.raw.json").write_text(
        json.dumps(
            [{"start_time_s": 0.0, "end_time_s": 5.0, "text": "raw only"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from app.tools.user.regenerate_subtitles import _regenerate_subtitles

    result = asyncio.run(_regenerate_subtitles.execute(task_id=task_id))

    assert result.success is False
    assert result.error == "Transcript not found"
    assert not (transcript_dir / "transcript.json").exists()


def test_run_asr_preserves_raw_transcript_before_line_breaking(monkeypatch, tmp_path):
    """ASR reruns should save raw provider output beside the display transcript."""
    output_dir = _use_temp_task_store(monkeypatch, tmp_path)
    video_path = tmp_path / "video.mp4"
    audio_path = tmp_path / "audio.wav"
    video_path.write_bytes(b"fake video")
    audio_path.write_bytes(b"fake audio")
    raw_text = "那个那个今天我们来看看这个非常有趣的节目内容介绍"
    task_id = _make_task(video_path=str(video_path))

    import app.services.asr as asr_service

    monkeypatch.setattr(asr_service, "extract_audio", lambda _path: str(audio_path))
    monkeypatch.setattr(
        asr_service,
        "transcribe",
        lambda *_args, **_kwargs: [
            {"start_time_s": 0.0, "end_time_s": 5.0, "text": raw_text}
        ],
    )

    from app.tools.user.run_asr import _run_asr_user

    result = asyncio.run(_run_asr_user.execute(task_id=task_id, api_key="sk-test"))

    assert result.success is True
    raw_segments = json.loads(
        (output_dir / task_id / "transcript.raw.json").read_text(encoding="utf-8")
    )
    display_segments = json.loads(
        (output_dir / task_id / "transcript.json").read_text(encoding="utf-8")
    )
    assert raw_segments == [{"start_time_s": 0.0, "end_time_s": 5.0, "text": raw_text}]
    display_text = "".join(s["text"].replace("\n", "") for s in display_segments)
    assert display_text != raw_text
    assert "那个那个" not in display_text


def test_subtitle_tool_schemas_separate_rebuild_from_retranscribe():
    """LLM-facing tool descriptions should not conflate rebuild and ASR."""
    from app.tools import get_tool

    regenerate = get_tool("regenerate_subtitles")
    run_asr = get_tool("run_asr")

    assert regenerate is not None
    assert run_asr is not None
    assert "Does not call ASR" in regenerate.description
    assert "requires an ASR API key" in run_asr.description
