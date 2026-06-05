import { useState } from "react";
import { THEME } from "../theme";
import Button from "../ui/Button";
import type { GlobalSettings } from "../types/settings";
import { clearAccessToken } from "../auth";

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
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);

  const handleClearApiKeys = () => {
    const cleared = { ...local, llmApiKey: "", asrApiKey: "" };
    setLocal(cleared);
  };

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
    if (local.asrApiKey.trim()) {
      if (!local.asrProvider.trim()) {
        e.asrProvider = "请选择 ASR 提供商";
      }
      if (!local.asrBaseUrl.trim()) {
        e.asrBaseUrl = "ASR API 地址不能为空";
      } else if (!isValidUrl(local.asrBaseUrl)) {
        e.asrBaseUrl = "请输入有效的 URL";
      }
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSave = () => {
    if (validate()) {
      onSave({ ...local });
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
          {/* Risk Warning */}
          <div
            style={{
              background: "#fff3cd",
              border: "1px solid #ffc107",
              borderRadius: THEME.radius.md,
              padding: "10px 12px",
              marginBottom: 16,
              fontSize: 12,
              color: "#856404",
              lineHeight: 1.5,
            }}
          >
            <strong> 安全提示：</strong>
            API Key 将以明文保存在当前浏览器的 localStorage 中。
            浏览器扩展、XSS 攻击和共享此电脑的其他用户可能读取这些密钥。
            关闭标签页后访问令牌将自动清除，但 API Key 会持久保留。
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
            value={local.llmApiKey}
            onChange={(v) => update("llmApiKey", v)}
            placeholder="sk-..."
            type="password"
            error={errors.llmApiKey}
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
            onChange={(e) => update("asrProvider", e.target.value)}
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

          <FieldLabel>
            API Key{" "}
            <span style={{ color: THEME.colors.textMuted, fontWeight: 400 }}>(可选)</span>
          </FieldLabel>
          <FieldInput
            value={local.asrApiKey}
            onChange={(v) => update("asrApiKey", v)}
            placeholder="留空则仅提取内嵌字幕"
            type="password"
          />
        </div>

        {/* Save confirmation */}
        {local.llmApiKey.trim() && (
          <div style={{ padding: "0 16px 8px" }}>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 12,
                color: THEME.colors.textSecondary,
                cursor: "pointer",
              }}
            >
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              我了解 API Key 将以明文保存在浏览器中
            </label>
          </div>
        )}

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
            <Button variant="secondary" size="sm" onClick={handleClearApiKeys}>
              清除 API Key
            </Button>
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
              disabled={!!local.llmApiKey.trim() && !confirmed}
            >
              保存
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
