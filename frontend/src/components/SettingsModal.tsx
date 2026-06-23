import { useEffect, useState } from "react";
import { THEME } from "../theme";
import Button from "../ui/Button";
import type { GlobalSettings, ProviderPresets } from "../types/settings";
import { clearAccessToken } from "../auth";
import { getApiSettings, getPresets, saveApiSettings } from "../api/client";

interface Props {
  settings: GlobalSettings;
  onSave: (s: GlobalSettings) => void;
  onClose: () => void;
}

function isValidUrl(s: string): boolean {
  if (!s) return false;
  try {
    new URL(s);
    return true;
  } catch {
    return false;
  }
}

export default function SettingsModal({ settings, onSave, onClose }: Props) {
  const [local, setLocal] = useState<GlobalSettings>({ ...settings });
  const [llmApiKey, setLlmApiKey] = useState("");
  const [asrApiKey, setAsrApiKey] = useState("");
  const [llmApiKeyConfigured, setLlmApiKeyConfigured] = useState(false);
  const [asrApiKeyConfigured, setAsrApiKeyConfigured] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [presets, setPresets] = useState<ProviderPresets>({ llm: [], asr: [] });
  const [selectedLlmPreset, setSelectedLlmPreset] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError("");

    Promise.all([getApiSettings(), getPresets()])
      .then(([serverSettings, presetsData]) => {
        if (cancelled) return;
        setLocal({
          llmBaseUrl: serverSettings.llmBaseUrl,
          llmModel: serverSettings.llmModel,
          asrProvider: serverSettings.asrProvider,
          asrBaseUrl: serverSettings.asrBaseUrl,
          asrModel: serverSettings.asrModel,
        });
        setLlmApiKeyConfigured(serverSettings.llmApiKeyConfigured);
        setAsrApiKeyConfigured(serverSettings.asrApiKeyConfigured);
        setPresets(presetsData);
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleClearAll = () => {
    localStorage.removeItem("global_llm_settings");
    clearAccessToken();
    window.location.reload();
  };

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!local.llmBaseUrl) {
      e.llmBaseUrl = "API 地址不能为空";
    } else if (!isValidUrl(local.llmBaseUrl)) {
      e.llmBaseUrl = "请输入有效的 URL";
    }
    if (!local.llmModel.trim()) {
      e.llmModel = "模型名称不能为空";
    }
    if (local.asrBaseUrl.trim() && !isValidUrl(local.asrBaseUrl)) {
      e.asrBaseUrl = "请输入有效的 URL";
    }
    if (local.asrModel.trim() && !local.asrProvider.trim()) {
      e.asrProvider = "请选择 ASR 提供商";
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    setSaveError("");
    try {
      const saved = await saveApiSettings({
        llmBaseUrl: local.llmBaseUrl,
        llmModel: local.llmModel,
        llmApiKey,
        asrProvider: local.asrProvider as "qwen" | "whisper_api",
        asrBaseUrl: local.asrBaseUrl,
        asrModel: local.asrModel,
        asrApiKey,
      });
      onSave({
        llmBaseUrl: saved.llmBaseUrl,
        llmModel: saved.llmModel,
        asrProvider: saved.asrProvider,
        asrBaseUrl: saved.asrBaseUrl,
        asrModel: saved.asrModel,
      });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const update = (field: keyof GlobalSettings, value: string) => {
    setLocal((prev) => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  const handleLlmPresetSelect = (presetId: string) => {
    setSelectedLlmPreset(presetId);
    const preset = presets.llm.find((p) => p.id === presetId);
    if (!preset) return;
    setLocal((prev) => ({
      ...prev,
      llmBaseUrl: preset.baseUrl,
      llmModel: preset.model,
    }));
  };

  const handleAsrProviderChange = (provider: string) => {
    update("asrProvider", provider);
    const preset = presets.asr.find((p) => p.provider === provider);
    if (preset) {
      setLocal((prev) => ({
        ...prev,
        asrProvider: provider,
        asrBaseUrl: preset.baseUrl,
        asrModel: preset.model,
      }));
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.3)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 2000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: THEME.colors.bgWhite,
          borderRadius: THEME.radius.lg,
          width: 420,
          maxHeight: "80vh",
          overflow: "auto",
          boxShadow: THEME.shadow.modal,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            padding: THEME.spacing.lg,
            borderBottom: `1px solid ${THEME.colors.borderLight}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ fontWeight: 600, fontSize: THEME.fontSize.subheading }}>全局设置</div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              fontSize: 20,
              cursor: "pointer",
              color: THEME.colors.textMuted,
              padding: 0,
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        <div style={{ padding: THEME.spacing.lg }}>
          {/* Server settings note */}
          <div
            style={{
              background: loadError ? "#fef2f2" : "#f1f5f9",
              border: `1px solid ${loadError ? THEME.colors.errorText : THEME.colors.borderLight}`,
              borderRadius: THEME.radius.md,
              padding: "10px 12px",
              marginBottom: 16,
              fontSize: 12,
              color: loadError ? THEME.colors.errorText : THEME.colors.textSecondary,
              lineHeight: 1.5,
            }}
          >
            {loading
              ? "正在读取服务端 setting 文件..."
              : loadError
                ? `读取服务端设置失败：${loadError}`
                : "API Key 会保存到服务端 setting 文件；已配置的 Key 不会回显，留空表示不修改。"}
          </div>

          {/* LLM Section */}
          <div
            style={{
              fontWeight: 600,
              fontSize: 14,
              marginBottom: 12,
              color: "#6c5ce7",
            }}
          >
             LLM 模型
          </div>

          {presets.llm.length > 0 && (
            <>
              <FieldLabel>提供商预设</FieldLabel>
              <select
                onChange={(e) => handleLlmPresetSelect(e.target.value)}
                value={selectedLlmPreset}
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  border: `1px solid ${THEME.colors.border}`,
                  borderRadius: THEME.radius.md,
                  fontSize: THEME.fontSize.sm,
                  background: THEME.colors.bgWhite,
                  marginBottom: THEME.spacing.sm,
                  boxSizing: "border-box",
                }}
              >
                <option value="">自定义（手动输入）</option>
                {presets.llm.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </>
          )}

          <FieldLabel>API 地址</FieldLabel>
          <FieldInput
            value={local.llmBaseUrl}
            onChange={(v) => update("llmBaseUrl", v)}
            placeholder="https://api.deepseek.com/anthropic"
            error={errors.llmBaseUrl}
          />

          <FieldLabel>模型名称</FieldLabel>
          <FieldInput
            value={local.llmModel}
            onChange={(v) => update("llmModel", v)}
            placeholder="deepseek-v4-pro"
            error={errors.llmModel}
          />

          <FieldLabel>API Key</FieldLabel>
          <FieldInput
            value={llmApiKey}
            onChange={setLlmApiKey}
            placeholder={llmApiKeyConfigured ? "已配置，留空不修改" : "输入 LLM API Key"}
            type="password"
          />

          {/* Divider */}
          <div
            style={{
              borderTop: `1px solid ${THEME.colors.borderLight}`,
              margin: `${THEME.spacing.lg}px 0`,
            }}
          />

          {/* ASR Section */}
          <div
            style={{
              fontWeight: 600,
              fontSize: 14,
              marginBottom: 12,
              color: "#e17055",
            }}
          >
             ASR 语音识别
          </div>

          <FieldLabel>提供商</FieldLabel>
          <select
            value={local.asrProvider}
            onChange={(e) => handleAsrProviderChange(e.target.value)}
            style={{
              width: "100%",
              padding: "8px 10px",
              border: `1px solid ${errors.asrProvider ? THEME.colors.errorText : THEME.colors.border}`,
              borderRadius: THEME.radius.md,
              fontSize: THEME.fontSize.sm,
              background: THEME.colors.bgWhite,
              marginBottom: THEME.spacing.sm,
              boxSizing: "border-box",
            }}
          >
            <option value="qwen">千问 ASR</option>
            <option value="whisper_api">Whisper API</option>
          </select>
          {errors.asrProvider && <ErrorText text={errors.asrProvider} />}

          <FieldLabel>API 地址</FieldLabel>
          <FieldInput
            value={local.asrBaseUrl}
            onChange={(v) => update("asrBaseUrl", v)}
            placeholder="https://dashscope.aliyuncs.com"
            error={errors.asrBaseUrl}
          />

          <FieldLabel>模型名称</FieldLabel>
          <FieldInput
            value={local.asrModel}
            onChange={(v) => update("asrModel", v)}
            placeholder="qwen3-asr-flash-filetrans"
          />

          <FieldLabel>API Key</FieldLabel>
          <FieldInput
            value={asrApiKey}
            onChange={setAsrApiKey}
            placeholder={asrApiKeyConfigured ? "已配置，留空不修改" : "输入 ASR API Key"}
            type="password"
          />

          {saveError && <ErrorText text={`保存失败：${saveError}`} />}

        </div>

        <div
          style={{
            borderTop: `1px solid ${THEME.colors.borderLight}`,
            padding: THEME.spacing.md,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", gap: 8 }}>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleClearAll}
              style={{ color: THEME.colors.errorText, borderColor: THEME.colors.errorText }}
            >
              清除全部设置
            </Button>
          </div>
          <div style={{ display: "flex", gap: THEME.spacing.sm }}>
            <Button variant="secondary" size="sm" onClick={onClose}>取消</Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              disabled={loading || saving}
            >
              {saving ? "保存中..." : "保存"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function FieldLabel({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        fontSize: THEME.fontSize.caption,
        color: THEME.colors.textSecondary,
        marginBottom: THEME.spacing.xs,
        marginTop: THEME.spacing.xs,
      }}
    >
      {children}
    </div>
  );
}

function FieldInput({
  value,
  onChange,
  placeholder,
  type = "text",
  error,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  error?: string;
}) {
  return (
    <div style={{ marginBottom: THEME.spacing.sm }}>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%",
          padding: "8px 10px",
          border: `1px solid ${error ? THEME.colors.errorText : THEME.colors.border}`,
          borderRadius: THEME.radius.md,
          fontSize: THEME.fontSize.sm,
          outline: "none",
          boxSizing: "border-box",
        }}
      />
      {error && <ErrorText text={error} />}
    </div>
  );
}

function ErrorText({ text }: { text: string }) {
  return (
    <div style={{ fontSize: THEME.fontSize.caption, color: THEME.colors.errorText, marginTop: 2 }}>{text}</div>
  );
}
