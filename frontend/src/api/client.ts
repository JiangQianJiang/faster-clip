import type { GlobalSettings, ClipConfig } from "../types/settings";
import { authFetch, getAccessToken, authBlobUrl } from "../auth";

export interface TaskConfig {
  llm_base_url: string;
  llm_model: string;
  asr_base_url: string;
  asr_model: string;
  clip_min_duration: number;
  clip_max_duration: number;
  buffer_seconds: number;
  burn_subtitle: boolean;
}

export interface CreateTaskParams {
  file: File;
  clipConfig: ClipConfig;
  settings: GlobalSettings;
  subtitleFile?: File;
  onProgress?: (pct: number) => void;
}

export interface Clip {
  start_time_s: number;
  end_time_s: number;
  export_start_time_s?: number;
  export_end_time_s?: number;
  score: number;
  reason: string;
  status?: "success" | "failed" | "pending";
  filepath?: string;
  thumbnail_path?: string;
  thumbnail_url?: string;
  download_url?: string;
  error?: string;
}

export interface TaskResponse {
  task_id: string;
  status: "pending" | "queued" | "processing" | "done" | "error";
  stage?: string;
  video_filename?: string;
  config: TaskConfig;
  subtitle_segment_count?: number;
  clips: Clip[];
  error_message?: string;
  failed_stage?: string;
  empty_clips_reason?: string;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  transcript_source?: string;
  transcript_version?: number;
  transcript_modified_at?: string;
  chat_history_json?: string;
  chat_updated_at?: string;
  media_info?: {
    fps: number;
    fps_mode: "stable" | "average" | string;
  };
}

export interface CreateTaskResponse {
  task_id: string;
  imported_count?: number;
  skipped_count?: number;
  warnings?: string[];
}

export interface ApiSettings {
  llmBaseUrl: string;
  llmModel: string;
  llmApiKeyConfigured: boolean;
  asrProvider: "qwen" | "whisper_api";
  asrBaseUrl: string;
  asrModel: string;
  asrApiKeyConfigured: boolean;
}

export interface SaveApiSettingsParams {
  llmBaseUrl: string;
  llmModel: string;
  llmApiKey?: string;
  asrProvider: "qwen" | "whisper_api";
  asrBaseUrl: string;
  asrModel: string;
  asrApiKey?: string;
}

interface ApiSettingsResponse {
  llm_base_url: string;
  llm_model: string;
  llm_api_key_configured: boolean;
  asr_provider: "qwen" | "whisper_api";
  asr_base_url: string;
  asr_model: string;
  asr_api_key_configured: boolean;
}

function mapApiSettings(body: ApiSettingsResponse): ApiSettings {
  return {
    llmBaseUrl: body.llm_base_url,
    llmModel: body.llm_model,
    llmApiKeyConfigured: body.llm_api_key_configured,
    asrProvider: body.asr_provider,
    asrBaseUrl: body.asr_base_url,
    asrModel: body.asr_model,
    asrApiKeyConfigured: body.asr_api_key_configured,
  };
}

export async function getApiSettings(): Promise<ApiSettings> {
  const res = await authFetch("/api/settings/api");
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `加载设置失败 (${res.status})`);
  }
  return mapApiSettings(await res.json());
}

export async function saveApiSettings(params: SaveApiSettingsParams): Promise<ApiSettings> {
  const res = await authFetch("/api/settings/api", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      llm_base_url: params.llmBaseUrl,
      llm_model: params.llmModel,
      llm_api_key: params.llmApiKey ?? "",
      asr_provider: params.asrProvider,
      asr_base_url: params.asrBaseUrl,
      asr_model: params.asrModel,
      asr_api_key: params.asrApiKey ?? "",
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `保存设置失败 (${res.status})`);
  }
  return mapApiSettings(await res.json());
}

export async function createTask({
  file,
  clipConfig,
  settings,
  subtitleFile,
  onProgress,
}: CreateTaskParams): Promise<CreateTaskResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("llm_base_url", settings.llmBaseUrl);
  form.append("llm_model", settings.llmModel);
  form.append("asr_base_url", settings.asrBaseUrl);
  form.append("asr_model", settings.asrModel);
  form.append("asr_provider", settings.asrProvider);
  form.append("clip_min_duration", String(clipConfig.clipMinDuration));
  form.append("clip_max_duration", String(clipConfig.clipMaxDuration));
  form.append("buffer_seconds", String(clipConfig.bufferSeconds));
  form.append("burn_subtitle", String(clipConfig.burnSubtitle));
  if (subtitleFile) {
    form.append("subtitle_file", subtitleFile);
  }

  // Use XHR when progress tracking is needed, fetch otherwise
  if (onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/tasks");
      const token = getAccessToken();
      if (token) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });
      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            reject(new Error("解析响应失败"));
          }
        } else {
          reject(new Error(xhr.responseText || `上传失败 (${xhr.status})`));
        }
      });
      xhr.addEventListener("error", () => reject(new Error("上传请求失败")));
      xhr.send(form);
    });
  }

  const res = await authFetch("/api/tasks", { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `上传失败 (${res.status})`);
  }
  return res.json();
}

export async function getTask(taskId: string): Promise<TaskResponse> {
  const res = await authFetch(`/api/tasks/${taskId}`);
  if (!res.ok) {
    throw new Error(`查询失败 (${res.status})`);
  }
  return res.json();
}

export interface TaskStatus {
  task_id: string;
  status: "pending" | "queued" | "processing" | "done" | "error";
  stage?: string;
  error_message?: string;
  failed_stage?: string;
  empty_clips_reason?: string;
  subtitle_segment_count?: number;
  video_filename?: string;
  updated_at: string;
}

export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const res = await authFetch(`/api/tasks/${taskId}/status`);
  if (!res.ok) {
    throw new Error(`查询失败 (${res.status})`);
  }
  return res.json();
}

export interface TranscriptSegment {
  start_time_s: number;
  end_time_s: number;
  text: string;
  /** ASR confidence score in [0, 1], or null when unavailable. */
  confidence?: number | null;
  words?: {
    text: string;
    start_time_s: number;
    end_time_s: number;
  }[] | null;
}

export interface TranscriptResponse {
  task_id: string;
  available: boolean;
  segment_count: number;
  segments: TranscriptSegment[];
  source?: string;
  detail?: string;
  transcript_version?: number;
  transcript_modified_at?: string;
}

export async function getTranscript(taskId: string): Promise<TranscriptResponse> {
  const res = await authFetch(`/api/tasks/${taskId}/transcript`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `获取字幕失败 (${res.status})`);
  }
  return res.json();
}

export function getClipDownloadUrl(taskId: string, clipIndex: number): string {
  return `/api/tasks/${taskId}/clips/${clipIndex}/download`;
}

export interface PatchTranscriptResponse {
  task_id: string;
  segment_count: number;
  transcript_version: number;
  transcript_modified_at: string;
  save_status: string;
  after_save?: TranscriptAfterSave;
  follow_up_status?: string;
  follow_up_error?: string;
}

export type TranscriptAfterSave = "save_only" | "regenerate_clip_subtitles" | "reanalyze";

export async function patchTranscript(
  taskId: string,
  segments: TranscriptSegment[],
  afterSave: TranscriptAfterSave = "save_only",
  baseTranscriptVersion?: number,
): Promise<PatchTranscriptResponse> {
  const body: Record<string, unknown> = {
    segments,
    after_save: afterSave,
  };
  if (baseTranscriptVersion !== undefined) {
    body.base_transcript_version = baseTranscriptVersion;
  }
  const res = await authFetch(`/api/tasks/${taskId}/transcript`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const body = JSON.parse(text);
      detail = body.detail || text;
    } catch {
      // Not JSON — use raw text
    }
    const err = new Error(detail || `保存失败 (${res.status})`) as Error & { status: number; detail: string };
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return res.json();
}

export function getTaskVideoUrl(taskId: string): string {
  return `/api/tasks/${taskId}/video`;
}

export function getTranscriptExportUrl(taskId: string, format: string): string {
  return `/api/tasks/${taskId}/transcript/export?format=${format}`;
}

export interface ClipSubtitleResponse {
  clip_index: number;
  start_time_s: number;
  end_time_s: number;
  segments: TranscriptSegment[];
}

export function getClipSubtitleUrl(taskId: string, clipIndex: number, format: string): string {
  return `/api/tasks/${taskId}/clips/${clipIndex}/subtitles?format=${format}`;
}

export function getClipSubtitleJsonUrl(taskId: string, clipIndex: number): string {
  return `/api/tasks/${taskId}/clips/${clipIndex}/subtitles/json`;
}

// Async Blob-based URL accessors for authenticated media elements
// Use these instead of direct URL strings for <video>, <img>, and <a> elements

export async function getVideoBlobUrl(taskId: string): Promise<string> {
  return authBlobUrl(`/api/tasks/${taskId}/video`);
}

export async function getClipDownloadBlobUrl(taskId: string, clipIndex: number): Promise<string> {
  return authBlobUrl(`/api/tasks/${taskId}/clips/${clipIndex}/download`);
}

export async function getThumbnailBlobUrl(taskId: string, clipIndex: number): Promise<string> {
  return authBlobUrl(`/api/tasks/${taskId}/clips/${clipIndex}/thumbnail`);
}

export async function getTranscriptExportBlobUrl(taskId: string, format: string): Promise<string> {
  return authBlobUrl(`/api/tasks/${taskId}/transcript/export?format=${format}`);
}

export { authBlobUrl, revokeBlobUrl } from "../auth";

export async function fetchClipSubtitles(taskId: string, clipIndex: number): Promise<ClipSubtitleResponse> {
  const res = await authFetch(getClipSubtitleJsonUrl(taskId, clipIndex));
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `获取片段字幕失败 (${res.status})`);
  }
  return res.json();
}

export interface TaskListItem {
  task_id: string;
  status: string;
  stage?: string;
  video_filename?: string;
  subtitle_segment_count?: number;
  clips_count: number;
  error_message?: string;
  failed_stage?: string;
  empty_clips_reason?: string;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  transcript_source?: string;
}

export async function listTasks(limit = 20, after?: string): Promise<TaskListItem[]> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (after) params.set("after", after);
  const res = await authFetch(`/api/tasks?${params}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `获取任务列表失败 (${res.status})`);
  }
  return res.json();
}

export async function deleteTask(taskId: string): Promise<void> {
  const res = await authFetch(`/api/tasks/${taskId}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `删除失败 (${res.status})`);
  }
}
