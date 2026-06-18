"""Video processing pipeline orchestration."""

import json
import logging
import os
import subprocess
import time as time_mod

from app.config import settings
from app.models.task import update_task_status
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
from app.services.asr import (
    ASRError,
    EmptyTranscript,
    extract_audio,
    transcribe,
)
from app.services.asr import (
    AuthError as ASRAuthError,
)
from app.services.ffprobe import probe
from app.services.line_breaker import split_segments
from app.services.subtitle import (
    extract_embedded_subtitles,
    generate_clip_subtitles,
    has_text_subtitles,
    save_raw_transcript,
    save_transcript,
)
from app.services.transcript_validator import sanitize_transcript_timeline
from app.utils import utcnow_iso


class StageError(Exception):
    def __init__(self, stage: str, message: str, retryable: bool = True):
        self.stage = stage
        self.retryable = retryable
        super().__init__(message)


# Containers that browsers can play natively via <video> element
BROWSER_PLAYABLE_CONTAINERS = {"mp4", "webm"}


def _generate_preview(video_path: str, container: str) -> str | None:
    """Generate an H.264 MP4 preview for non-browser-playable containers.

    Returns the preview path, or None if no preview is needed / generation failed.
    """
    if container.lower() in BROWSER_PLAYABLE_CONTAINERS:
        return None  # already browser-playable

    video_dir = os.path.dirname(video_path)
    preview_path = os.path.join(video_dir, "preview.mp4")

    if os.path.isfile(preview_path):
        return preview_path  # already generated

    logger = logging.getLogger(__name__)
    logger.info(
        "Generating browser-playable preview for %s → %s", video_path, preview_path
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        preview_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=settings.ffmpeg_timeout_seconds
        )
        if result.returncode != 0:
            logger.error("Preview generation failed: %s", result.stderr.strip()[-300:])
            return None
        logger.info("Preview generated: %s", preview_path)
        return preview_path
    except Exception as e:
        logger.error("Preview generation error: %s", e)
        return None


def run(
    task_id: str, video_path: str, config: dict, llm_api_key: str, asr_api_key: str
):
    try:
        info = probe(video_path)
    except Exception as e:
        raise StageError("extracting_subtitles", f"视频读取失败: {e}")

    # Cache media info in DB so status polls don't need to re-probe
    update_task_status(
        task_id,
        "processing",
        media_info_json=json.dumps(
            {
                "duration": info.duration,
                "width": info.width,
                "height": info.height,
                "codec": info.codec,
                "container": info.container,
                "fps": info.fps,
                "fps_mode": info.fps_mode,
            }
        ),
    )

    # Generate browser-playable preview for non-MP4 containers (e.g. FLV)
    _generate_preview(video_path, info.container)

    output_dir = os.path.join("data", "output", task_id)
    os.makedirs(output_dir, exist_ok=True)
    transcript_path = os.path.join(output_dir, "transcript.json")

    # Stage 1: Subtitle extraction (skip if already done, e.g. on retry)
    segments = None
    if os.path.exists(transcript_path):
        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
            segments, _warnings = sanitize_transcript_timeline(segments)
            # Re-split in case this transcript predates word-level splitting.
            segments = split_segments(segments)
            update_task_status(
                task_id, "processing", subtitle_segment_count=len(segments)
            )
        except Exception:
            segments = None

    if not segments:
        update_task_status(task_id, "processing", stage="extracting_subtitles")

        if info.subtitle_streams and has_text_subtitles(info.subtitle_streams):
            segments = extract_embedded_subtitles(video_path, info.subtitle_streams)

        if not segments and asr_api_key:
            audio_path = None
            try:
                audio_path = extract_audio(video_path)
                provider = config.get("asr_provider") or settings.default_asr_provider
                segments = transcribe(
                    audio_path,
                    asr_api_key,
                    base_url=config.get("asr_base_url"),
                    model=config.get("asr_model", "whisper-1"),
                    provider=provider,
                )
            except ASRAuthError as e:
                raise StageError("extracting_subtitles", str(e), retryable=False)
            except EmptyTranscript as e:
                raise StageError("extracting_subtitles", str(e), retryable=False)
            except ASRError as e:
                raise StageError("extracting_subtitles", str(e))
            finally:
                if audio_path and os.path.exists(audio_path):
                    os.unlink(audio_path)

        if not segments:
            raise StageError(
                "extracting_subtitles", "无法获取字幕：无内嵌字幕且未配置 ASR API key"
            )

        segments, _warnings = sanitize_transcript_timeline(segments)
        if not segments:
            raise StageError("extracting_subtitles", "字幕时间轴无有效片段", retryable=False)

        # Preserve provider/extractor output before display-oriented processing.
        save_raw_transcript(segments, output_dir)

        # Apply word-level segment splitting before persisting so all
        # downstream consumers (export, frontend, LLM analysis) see the
        # split transcript.
        segments = split_segments(segments)
        save_transcript(segments, output_dir)
        update_task_status(task_id, "processing", subtitle_segment_count=len(segments))

    # Stage 2: LLM analysis
    update_task_status(task_id, "processing", stage="analyzing")

    prompt = build_prompt(segments, config)
    try:
        raw_clips = analyze(
            prompt,
            base_url=config["llm_base_url"],
            model=config["llm_model"],
            api_key=llm_api_key,
        )
    except LLMAuthError as e:
        raise StageError("analyzing", str(e), retryable=False)
    except LLMConnectionError as e:
        raise StageError("analyzing", str(e))
    except ParseError as e:
        raise StageError("analyzing", str(e), retryable=False)
    except LLMError as e:
        raise StageError("analyzing", str(e))

    video_duration = info.duration
    clips = validate_clips(
        raw_clips,
        video_duration=video_duration,
        min_duration=config.get("clip_min_duration", 30),
        max_duration=config.get("clip_max_duration", 120),
    )

    if not clips:
        update_task_status(
            task_id,
            "done",
            clips_json="[]",
            empty_clips_reason="未找到精彩片段",
            completed_at=utcnow_iso(),
        )
        return

    # Stage 3: Clip export
    update_task_status(task_id, "processing", stage="exporting_clips")

    buffer = config.get("buffer_seconds", 3)
    burn = config.get("burn_subtitle", False)
    max_dur = config.get("clip_max_duration", 120)
    subtitle_style_cfg = config.get("subtitle_style") or {}
    exported = []
    all_failed = True

    for i, clip in enumerate(clips):
        try:
            out = _export_clip(
                video_path,
                output_dir,
                i,
                clip,
                buffer,
                burn,
                segments,
                max_dur,
                info.duration,
                subtitle_style_cfg=subtitle_style_cfg,
            )
            exported.append(
                {
                    "start_time_s": clip["start_time_s"],
                    "end_time_s": clip["end_time_s"],
                    "export_start_time_s": out["export_start"],
                    "export_end_time_s": out["export_end"],
                    "score": clip["score"],
                    "reason": clip["reason"],
                    "status": "success",
                    "filepath": out["video"],
                    "thumbnail_path": out["thumbnail"],


                }
            )
            all_failed = False
        except Exception as e:
            exported.append(
                {
                    "start_time_s": clip["start_time_s"],
                    "end_time_s": clip["end_time_s"],
                    "score": clip["score"],
                    "reason": clip["reason"],
                    "status": "failed",
                    "error": str(e)[:500],
                }
            )

    # Stage 4: Finalize
    manifest = {
        "task_id": task_id,
        "clips": exported,
    }
    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    if all_failed:
        update_task_status(
            task_id,
            "error",
            stage=None,
            clips_json=json.dumps(exported, ensure_ascii=False),
            error_message="所有片段导出均失败",
            failed_stage="exporting_clips",
            completed_at=utcnow_iso(),
        )
    else:
        update_task_status(
            task_id,
            "done",
            stage=None,
            clips_json=json.dumps(exported, ensure_ascii=False),
            completed_at=utcnow_iso(),
        )


def _compute_export_window(
    clip_start: float,
    clip_end: float,
    buffer: float,
    max_duration: float,
    video_duration: float,
) -> tuple[float, float]:
    """Pure helper: compute buffered export window that always preserves the highlight."""
    export_start = clip_start
    export_end = clip_end
    budget = max_duration - (clip_end - clip_start)

    buf_before = min(buffer, clip_start, budget)
    export_start -= buf_before
    budget -= buf_before
    buf_after = min(buffer, video_duration - clip_end, budget)
    export_end += buf_after
    return (export_start, export_end)


def _export_clip(
    video_path: str,
    output_dir: str,
    index: int,
    clip: dict,
    buffer: float,
    burn: bool,
    segments: list | None = None,
    max_duration: float = 120,
    video_duration: float = 0,
    subtitle_style_cfg: dict | None = None,
) -> dict:
    logger = logging.getLogger(__name__)

    export_start, export_end = _compute_export_window(
        clip["start_time_s"],
        clip["end_time_s"],
        buffer,
        max_duration,
        video_duration,
    )

    clip_name = f"clip_{index:03d}.mp4"
    out_video = os.path.join(output_dir, clip_name)

    # Always pre-generate subtitle files (best-effort, before burn path so SRT
    # is on disk for the subtitles filter)
    try:
        generate_clip_subtitles(
            segments or [],
            export_start,
            export_end,
            output_dir,
            index,
        )
    except Exception:
        logger.warning(
            "Subtitle generation failed for clip %d of task in %s",
            index,
            output_dir,
            exc_info=True,
        )

    if burn:
        srt_path = os.path.join(output_dir, f"clip_{index:03d}.srt")
        # Ensure SRT exists for burn-in: re-generate inline if best-effort pre-gen failed
        if not os.path.isfile(srt_path):
            from app.services.subtitle import (
                get_clip_subtitle_segments,
                segments_to_srt,
            )

            filtered = get_clip_subtitle_segments(
                segments or [],
                export_start,
                export_end,
            )
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(segments_to_srt(filtered))

        # Build subtitle filter: use preset style if configured, else default
        subtitle_cfg = subtitle_style_cfg or {}
        preset_name = subtitle_cfg.get("preset", "")
        if preset_name:
            from app.services.subtitle_style import build_force_style

            overrides = subtitle_cfg.get("overrides") or {}
            style = build_force_style(preset_name, overrides)
            vf_filter = f"subtitles={srt_path}:fontsdir={settings.fonts_dir}:force_style={style}"
        else:
            vf_filter = f"subtitles={srt_path}:fontsdir={settings.fonts_dir}"

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(export_start),
            "-to",
            str(export_end),
            "-i",
            video_path,
            "-vf",
            vf_filter,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-c:a",
            "aac",
            out_video,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(export_start),
            "-to",
            str(export_end),
            "-i",
            video_path,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-c:a",
            "aac",
            out_video,
        ]

    ffmpeg_start = time_mod.monotonic()
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=settings.ffmpeg_timeout_seconds
    )
    ffmpeg_duration = (time_mod.monotonic() - ffmpeg_start) * 1000
    logger.info(
        "ffmpeg.execute",
        extra={
            "command": f"ffmpeg clip_{index:03d}.mp4",
            "duration_ms": round(ffmpeg_duration, 1),
            "returncode": result.returncode,
        },
    )
    if result.returncode != 0:
        logger.error(
            "ffmpeg.execute",
            extra={
                "command": f"ffmpeg clip_{index:03d}.mp4",
                "stderr": result.stderr[-500:],
            },
        )
        # Capture tail of stderr — ffmpeg prints version first, error last
        err_tail = (
            result.stderr.strip()[-500:]
            if result.stderr.strip()
            else "(no stderr output)"
        )
        raise RuntimeError(f"ffmpeg 导出失败: {err_tail}")

    # Thumbnail at 320x180 (16:9)
    thumb_name = f"clip_{index:03d}.jpg"
    out_thumb = os.path.join(output_dir, thumb_name)
    mid = (export_start + export_end) / 2
    thumb_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(mid),
        "-i",
        video_path,
        "-vframes",
        "1",
        "-vf",
        "scale=320:180",
        out_thumb,
    ]
    thumb_result = subprocess.run(thumb_cmd, capture_output=True, text=True, timeout=30)
    if thumb_result.returncode != 0 or not os.path.isfile(out_thumb):
        raise RuntimeError("缩略图生成失败")

    return {
        "video": out_video,
        "thumbnail": out_thumb,
        "export_start": export_start,
        "export_end": export_end,
    }
