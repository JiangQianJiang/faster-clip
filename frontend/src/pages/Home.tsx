import { useState } from "react";
import { useNavigate } from "react-router-dom";
import UploadZone from "../components/UploadZone";
import { createTask } from "../api/client";
import { useSettingsContext } from "../context/SettingsContext";
import { DEFAULT_CLIP_CONFIG } from "../types/settings";
import { THEME } from "../theme";
import Button from "../ui/Button";

export default function Home() {
  const navigate = useNavigate();
  const { settings, isConfigured, openSettings } = useSettingsContext();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [uploadKey, setUploadKey] = useState(0);

  const handleFile = async (f: File) => {
    setFile(f);
    setError("");


    if (!isConfigured) {
      setError("请先配置 LLM 模型");
      setFile(null);
      setUploadKey((k) => k + 1);
      openSettings();
      return;
    }

    setUploading(true);
    setProgress(0);
    try {
      const res = await createTask({
        file: f,
        clipConfig: DEFAULT_CLIP_CONFIG,
        settings,
        onProgress: setProgress,
      });
      navigate(`/tasks/${res.task_id}`);
    } catch (e) {
      setError(String(e));
      setUploading(false);
    }
  };

  return (
    <div style={{
      maxWidth: 600,
      margin: "0 auto",
      padding: 48,
      textAlign: "center",
    }}>
      <h1 style={{ fontSize: THEME.fontSize.heading, fontWeight: 700, color: THEME.colors.textPrimary, marginBottom: THEME.spacing.md }}>
        直播切片助手
      </h1>
      <p style={{ fontSize: THEME.fontSize.body, color: THEME.colors.textSecondary, lineHeight: 1.8, marginBottom: THEME.spacing.sm }}>
        上传直播录像，用自然语言描述你想要什么
      </p>
      <p style={{ fontSize: THEME.fontSize.sm, color: THEME.colors.textMuted, marginBottom: THEME.spacing.xl }}>
        例如：「帮我找 5 个适合小红书的高能片段，每个 30 秒内，保留字幕」
      </p>

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
          <span>请先配置 LLM 模型</span>
          <Button variant="secondary" size="sm" onClick={openSettings}>配置</Button>
        </div>
      )}

      {!uploading && (
        <UploadZone key={uploadKey} onFile={handleFile} />
      )}

      {file && !uploading && (
        <p style={{ marginTop: THEME.spacing.sm, fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary }}>
          已选择: {file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)
        </p>
      )}

      {uploading && (
        <div style={{ maxWidth: 400, margin: "0 auto" }}>
          <div style={{
            display: "flex", justifyContent: "space-between",
            fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary, marginBottom: THEME.spacing.sm,
          }}>
            <span>正在上传...</span>
            <span>{progress}%</span>
          </div>
          <div style={{
            width: "100%", height: 8, background: THEME.colors.border,
            borderRadius: THEME.radius.sm, overflow: "hidden",
          }}>
            <div style={{
              width: `${progress}%`, height: "100%",
              background: THEME.colors.primary, borderRadius: THEME.radius.sm,
              transition: "width 0.2s",
            }} />
          </div>
        </div>
      )}

      {error && (
        <p style={{ color: THEME.colors.errorText, marginTop: THEME.spacing.lg, fontSize: THEME.fontSize.sm }}>
          {error}
        </p>
      )}

      {isConfigured && (
        <p style={{ marginTop: THEME.spacing.lg, fontSize: THEME.fontSize.caption, color: THEME.colors.textMuted }}>
          模型：{settings.llmModel} · ASR：{settings.asrProvider}
        </p>
      )}
    </div>
  );
}
