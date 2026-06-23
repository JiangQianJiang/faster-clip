"""ASR integration — Whisper API + Qwen DashScope (async)."""

import math
import os
import subprocess
import tempfile
import time

import requests
from openai import OpenAI

SUPPORTED_FORMATS = (
    "flac",
    "m4a",
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "oga",
    "ogg",
    "wav",
    "webm",
)


def _get_attr(obj, name, default):
    val = getattr(obj, name, None)
    if val is not None:
        return val
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


class ASRError(Exception):
    pass


class AuthError(ASRError):
    pass


class EmptyTranscript(ASRError):
    pass


class QwenPollTimeout(ASRError):
    pass


def extract_audio(video_path: str) -> str:
    """Extract mono 16kHz WAV audio from video. Returns temp file path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        tmp_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            os.unlink(tmp_path)
            raise ASRError(f"音频提取失败: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        os.unlink(tmp_path)
        raise ASRError("音频提取超时")
    except FileNotFoundError:
        os.unlink(tmp_path)
        raise ASRError("ffmpeg 不可用")

    return tmp_path


def _get_file_size_mb(path: str) -> float:
    return os.path.getsize(path) / (1024 * 1024)


def _split_audio(audio_path: str, chunk_size_mb: float = 25.0) -> list[str]:
    """Split audio into chunks ≤25MB. Returns list of chunk file paths."""
    duration = _get_duration(audio_path)
    file_size = _get_file_size_mb(audio_path)
    if file_size <= chunk_size_mb:
        return [audio_path]

    num_chunks = math.ceil(file_size / chunk_size_mb)
    chunk_duration = duration / num_chunks
    chunks = []

    for i in range(num_chunks):
        start = i * chunk_duration
        chunk_path = f"{audio_path}.chunk{i}.wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            audio_path,
            "-ss",
            str(start),
            "-t",
            str(chunk_duration + 1),
            "-c",
            "copy",
            chunk_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            for c in chunks:
                if os.path.exists(c):
                    os.unlink(c)
            raise ASRError("音频分块失败")
        chunks.append(chunk_path)

    if audio_path not in chunks:
        os.unlink(audio_path)
    return chunks


def _get_duration(filepath: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        filepath,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        return 0.0


def transcribe(
    audio_path: str,
    api_key: str,
    base_url: str | None = None,
    model: str = "whisper-1",
    provider: str | None = None,
) -> list[dict]:
    if provider == "qwen":
        return _transcribe_qwen(audio_path, api_key, base_url, model)
    return _transcribe_whisper(audio_path, api_key, base_url, model)


def _transcribe_whisper(
    audio_path: str, api_key: str, base_url: str | None = None, model: str = "whisper-1"
) -> list[dict]:
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    chunks = _split_audio(audio_path)
    offset = 0.0
    all_segments = []

    try:
        for chunk_path in chunks:
            chunk_duration = _get_duration(chunk_path)
            last_error = None
            for attempt in range(3):
                try:
                    with open(chunk_path, "rb") as f:
                        resp = client.audio.transcriptions.create(
                            model=model,
                            file=f,
                            response_format="verbose_json",
                            timestamp_granularities=["segment"],
                        )
                    segs = _get_attr(resp, "segments", []) or []
                    for s in segs:
                        avg_logprob = _get_attr(s, "avg_logprob", None)
                        confidence = (
                            round(min(math.exp(avg_logprob), 1.0), 4)
                            if avg_logprob is not None
                            else None
                        )
                        all_segments.append(
                            {
                                "start_time_s": round(
                                    float(_get_attr(s, "start", 0.0)) + offset, 3
                                ),
                                "end_time_s": round(float(_get_attr(s, "end", 0.0)) + offset, 3),
                                "text": str(_get_attr(s, "text", "")).strip(),
                                "confidence": confidence,
                            }
                        )
                    break
                except Exception as e:
                    last_error = e
                    msg = str(e).lower()
                    if "401" in msg or "403" in msg or "unauthorized" in msg:
                        raise AuthError(f"Whisper API key 无效: {e}")
                    if attempt < 2:
                        time.sleep(2**attempt)
            else:
                raise ASRError(f"Whisper API 调用失败（已重试 3 次）: {last_error}")

            offset += chunk_duration
    finally:
        for chunk_path in chunks:
            if chunk_path != audio_path and os.path.exists(chunk_path):
                os.unlink(chunk_path)

    if not all_segments:
        raise EmptyTranscript("未检测到语音或音质问题")

    filtered = [s for s in all_segments if s["text"]]
    if not filtered:
        raise EmptyTranscript("未检测到语音或音质问题")

    return filtered


def _transcribe_qwen(
    audio_path: str,
    api_key: str,
    base_url: str | None = None,
    model: str = "qwen3-asr-flash-filetrans",
) -> list[dict]:
    api_base = (base_url or "https://dashscope.aliyuncs.com").rstrip("/")
    auth_headers = {"Authorization": f"Bearer {api_key}"}

    # Step 1: Upload file to DashScope file management to get a file_url
    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{api_base}/api/v1/files",
                headers=auth_headers,
                files={"file": (os.path.basename(audio_path), f)},
                data={"purpose": "asr"},
                timeout=60,
            )
    except requests.RequestException as e:
        raise ASRError(f"Qwen ASR 文件上传失败: {e}")

    if resp.status_code in (401, 403):
        raise AuthError(f"Qwen API key 无效: {resp.text[:300]}")
    if resp.status_code != 200:
        raise ASRError(f"Qwen ASR 文件上传失败 (HTTP {resp.status_code}): {resp.text[:300]}")

    try:
        upload_data = resp.json()
    except ValueError:
        raise ASRError(f"Qwen ASR 文件上传响应解析失败: {resp.text[:300]}")

    uploaded = upload_data.get("data", {}).get("uploaded_files") or []
    if not uploaded:
        raise ASRError(f"Qwen ASR 文件上传未返回文件信息: {resp.text[:300]}")

    # Get the fresh presigned URL for the uploaded file
    file_id = uploaded[0]["file_id"]
    try:
        resp = requests.get(f"{api_base}/api/v1/files/{file_id}", headers=auth_headers, timeout=15)
        file_url = resp.json()["data"]["url"]
    except Exception as e:
        raise ASRError(f"Qwen ASR 获取文件 URL 失败: {e}")

    # Step 2: Submit transcription task with file_url
    submit_headers = {
        **auth_headers,
        "X-DashScope-Async": "enable",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "input": {"file_url": file_url},
        "parameters": {
            "channel_id": [0],
            "enable_itn": False,
            "enable_words": True,
        },
    }

    try:
        resp = requests.post(
            f"{api_base}/api/v1/services/audio/asr/transcription",
            json=body,
            headers=submit_headers,
            timeout=30,
        )
    except requests.RequestException as e:
        raise ASRError(f"Qwen ASR 提交失败: {e}")

    if resp.status_code in (401, 403):
        raise AuthError(f"Qwen API key 无效: {resp.text[:300]}")
    if resp.status_code != 200:
        raise ASRError(f"Qwen ASR 提交失败 (HTTP {resp.status_code}): {resp.text[:300]}")

    try:
        data = resp.json()
    except ValueError:
        raise ASRError(f"Qwen ASR 响应解析失败: {resp.text[:300]}")

    task_id = data.get("output", {}).get("task_id")
    if not task_id:
        raise ASRError(f"Qwen ASR 未返回 task_id: {resp.text[:300]}")

    # Step 3: Poll for completion, then fetch result JSON
    from app.config import settings

    poll_url = f"{api_base}/api/v1/tasks/{task_id}"
    deadline = time.time() + settings.qwen_poll_timeout_seconds
    last_error = None

    while time.time() < deadline:
        time.sleep(2)
        try:
            poll_resp = requests.get(poll_url, headers=auth_headers, timeout=15)
        except requests.RequestException as e:
            last_error = str(e)
            continue

        if poll_resp.status_code != 200:
            last_error = f"HTTP {poll_resp.status_code}: {poll_resp.text[:200]}"
            continue

        try:
            poll_data = poll_resp.json()
        except ValueError:
            last_error = f"JSON parse: {poll_resp.text[:200]}"
            continue

        output = poll_data.get("output", {})
        status = output.get("task_status", "")

        if status == "SUCCEEDED":
            transcription_url = output.get("result", {}).get("transcription_url")
            if not transcription_url:
                raise ASRError("Qwen ASR 未返回转录结果 URL")
            try:
                result_resp = requests.get(transcription_url, timeout=30)
                result_json = result_resp.json()
            except Exception as e:
                raise ASRError(f"Qwen ASR 获取转录结果失败: {e}")
            return _parse_qwen_results(result_json)
        elif status in ("FAILED", "UNKNOWN"):
            raise ASRError(f"Qwen ASR 任务失败 ({status}): {output.get('message', '未知错误')}")

        last_error = None

    raise QwenPollTimeout(
        f"Qwen ASR 任务 {task_id} 轮询超时（{settings.qwen_poll_timeout_seconds}秒）{': ' + last_error if last_error else ''}"
    )


def _parse_qwen_results(data: dict) -> list[dict]:
    """Parse Qwen FileTrans JSON result into standard segment format.

    Extracts both sentence-level segments and word-level timestamps
    (enable_words=True must be set in the transcription request).
    Word timestamps are converted from milliseconds to seconds.
    """
    segments = []

    for transcript in data.get("transcripts", []):
        sentences = transcript.get("sentences") or []
        for s in sentences:
            text = s.get("text", "").strip()
            if text:
                words = None
                raw_words = s.get("words") or []
                if raw_words:
                    words = [
                        {
                            "text": w.get("text", ""),
                            "start_time_s": round(w.get("begin_time", 0) / 1000.0, 3),
                            "end_time_s": round(w.get("end_time", 0) / 1000.0, 3),
                        }
                        for w in raw_words
                    ]
                segments.append(
                    {
                        "start_time_s": round(s.get("begin_time", 0) / 1000.0, 3),
                        "end_time_s": round(s.get("end_time", 0) / 1000.0, 3),
                        "text": text,
                        "confidence": None,
                        "words": words,
                    }
                )

    if not segments:
        raise EmptyTranscript("未检测到语音或音质问题")

    from app.services.transcript_validator import sanitize_transcript_timeline

    filtered, _warnings = sanitize_transcript_timeline(segments)
    if not filtered:
        raise EmptyTranscript("未检测到语音或音质问题")

    return filtered
