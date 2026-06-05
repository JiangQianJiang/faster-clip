import { useState } from "react";
import { useNavigate } from "react-router-dom";
import UploadZone from "../components/UploadZone";
import ConfigPanel from "../components/ConfigPanel";
import { createTask } from "../api/client";
import { useSettingsContext } from "../context/SettingsContext";
import { THEME } from "../theme";
import Button from "../ui/Button";
import { DEFAULT_CLIP_CONFIG, type ClipConfig } from "../types/settings";

export default function Upload() {
  const [file, setFile] = useState<File | null>(null);
  const [subtitleFile, setSubtitleFile] = useState<File | null>(null);
  const [clipConfig, setClipConfig] = useState<ClipConfig>(DEFAULT_CLIP_CONFIG);
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const { settings, isConfigured, openSettings } = useSettingsContext();

  const canSubmit =
    file &&
    isConfigured &&
    clipConfig.clipMinDuration > 0 &&
    clipConfig.clipMaxDuration >= clipConfig.clipMinDuration;

  const handleSubmit = async () => {
    if (!file || !canSubmit) return;
    setSubmitting(true);
    setUploadProgress(0);
    setError("");
    try {
      if (file.size > 2 * 1024 * 1024 * 1024) {
        setError("文件大小超过 2GB 限制");
        setSubmitting(false);
        return;
      }
      const res = await createTask({
        file,
        clipConfig,
        settings,
        subtitleFile: subtitleFile || undefined,
        onProgress: setUploadProgress,
      });
      navigate(`/tasks/${res.task_id}`);
    } catch (e) {
      setError(String(e));
    }
    setSubmitting(false);
  };

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: THEME.spacing.xl }}>
      <h1 style={{ textAlign: "center", marginBottom: THEME.spacing.xl, color: THEME.colors.textPrimary, fontSize: THEME.fontSize.heading }}>上传视频</h1>

      {!isConfigured && (
        <div
          style={{
            padding: THEME.spacing.md,
            background: THEME.colors.warningBg,
            borderRadius: THEME.radius.md,
            marginBottom: THEME.spacing.lg,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: THEME.fontSize.sm,
            color: THEME.colors.warningText,
          }}
        >
          <span>⚠️ 请先在侧边栏底部配置 LLM 模型</span>
          <Button variant="secondary" size="sm" onClick={openSettings}>配置</Button>
        </div>
      )}

      <div
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}
      >
        <div>
          <h3 style={{ marginBottom: THEME.spacing.md, color: THEME.colors.textPrimary }}>选择视频</h3>
          <UploadZone onFile={setFile} />
          {file && (
            <p style={{ marginTop: THEME.spacing.sm, fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary }}>
              已选择: {file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)
            </p>
          )}

          <div style={{ marginTop: THEME.spacing.lg }}>
            <label
              style={{
                fontSize: THEME.fontSize.sm,
                color: THEME.colors.textSecondary,
                display: "block",
                marginBottom: THEME.spacing.xs,
              }}
            >
              字幕文件（可选，支持 SRT/VTT/ASS）
            </label>
            <input
              type="file"
              accept=".srt,.vtt,.ass"
              onChange={(e) => setSubtitleFile(e.target.files?.[0] || null)}
              style={{ fontSize: THEME.fontSize.sm }}
            />
            {subtitleFile && (
              <p style={{ marginTop: THEME.spacing.xs, fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary }}>
                已选择字幕: {subtitleFile.name}
              </p>
            )}
          </div>
        </div>

        <div>
          <ConfigPanel clipConfig={clipConfig} onChange={setClipConfig} />
        </div>
      </div>

      {isConfigured && (
        <div
          style={{
            textAlign: "center",
            marginTop: THEME.spacing.sm,
            fontSize: THEME.fontSize.caption,
            color: THEME.colors.textMuted,
          }}
        >
          全局模型：{settings.llmModel} · ASR：{settings.asrProvider}
        </div>
      )}

      {error && (
        <p style={{ color: THEME.colors.errorText, marginTop: THEME.spacing.lg, textAlign: "center", fontSize: THEME.fontSize.sm }}>
          {error}
        </p>
      )}

      <div style={{ textAlign: "center", marginTop: THEME.spacing.xl }}>
        {submitting ? (
          <div style={{ maxWidth: 400, margin: "0 auto" }}>
            <div style={{
              display: "flex", justifyContent: "space-between",
              fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary, marginBottom: THEME.spacing.sm,
            }}>
              <span>正在上传...</span>
              <span>{uploadProgress}%</span>
            </div>
            <div style={{
              width: "100%", height: 8, background: THEME.colors.border,
              borderRadius: THEME.radius.sm, overflow: "hidden",
            }}>
              <div style={{
                width: `${uploadProgress}%`, height: "100%",
                background: THEME.colors.primary, borderRadius: THEME.radius.sm,
                transition: "width 0.2s",
              }} />
            </div>
          </div>
        ) : (
          <Button variant="primary" onClick={handleSubmit} disabled={!canSubmit}>
            开始分析
          </Button>
        )}
      </div>
    </div>
  );
}
