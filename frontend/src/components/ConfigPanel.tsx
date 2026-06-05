import { useState } from "react";
import { THEME } from "../theme";
import type { ClipConfig } from "../types/settings";

interface Props {
  clipConfig: ClipConfig;
  onChange: (c: ClipConfig) => void;
}

const fieldStyle = { marginBottom: 12 } as const;
const labelStyle = {
  display: "block",
  marginBottom: THEME.spacing.xs,
  fontSize: THEME.fontSize.sm,
  color: THEME.colors.textPrimary,
} as const;
const inputStyle = {
  width: "100%",
  padding: "6px 8px",
  border: `1px solid ${THEME.colors.border}`,
  borderRadius: THEME.radius.sm,
  boxSizing: "border-box" as const,
};

export default function ConfigPanel({ clipConfig, onChange }: Props) {
  const [errors, setErrors] = useState<Record<string, string>>({});

  const set = (k: keyof ClipConfig, v: number | boolean) => {
    const next = { ...clipConfig, [k]: v };
    const errs: Record<string, string> = {};

    if (next.clipMinDuration <= 0) errs.clipMinDuration = "必须为正数";
    if (next.clipMaxDuration <= 0) errs.clipMaxDuration = "必须为正数";
    if (next.clipMaxDuration < next.clipMinDuration)
      errs.clipMaxDuration = "不能小于最小时长";
    if (next.bufferSeconds < 0) errs.bufferSeconds = "不能为负数";

    setErrors(errs);
    onChange(next);
  };

  return (
    <div>
      <h3 style={{ marginBottom: THEME.spacing.lg, color: THEME.colors.textPrimary }}>片段参数</h3>

      <div style={{ display: "flex", gap: 12 }}>
        <div style={{ ...fieldStyle, flex: 1 }}>
          <label style={labelStyle}>最小时长（秒）</label>
          <input
            style={inputStyle}
            type="number"
            min={1}
            value={clipConfig.clipMinDuration}
            onChange={(e) => set("clipMinDuration", Number(e.target.value))}
          />
          {errors.clipMinDuration && (
            <span style={{ color: THEME.colors.errorText, fontSize: 12 }}>
              {errors.clipMinDuration}
            </span>
          )}
        </div>
        <div style={{ ...fieldStyle, flex: 1 }}>
          <label style={labelStyle}>最大时长（秒）</label>
          <input
            style={inputStyle}
            type="number"
            min={1}
            value={clipConfig.clipMaxDuration}
            onChange={(e) => set("clipMaxDuration", Number(e.target.value))}
          />
          {errors.clipMaxDuration && (
            <span style={{ color: THEME.colors.errorText, fontSize: 12 }}>
              {errors.clipMaxDuration}
            </span>
          )}
        </div>
      </div>

      <div style={fieldStyle}>
        <label style={labelStyle}>缓冲秒数</label>
        <input
          style={inputStyle}
          type="number"
          min={0}
          value={clipConfig.bufferSeconds}
          onChange={(e) => set("bufferSeconds", Number(e.target.value))}
        />
        {errors.bufferSeconds && (
          <span style={{ color: THEME.colors.errorText, fontSize: 12 }}>
            {errors.bufferSeconds}
          </span>
        )}
      </div>

      <div style={fieldStyle}>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 13,
          }}
        >
          <input
            type="checkbox"
            checked={clipConfig.burnSubtitle}
            onChange={(e) => set("burnSubtitle", e.target.checked)}
          />
          烧录字幕
        </label>
      </div>
    </div>
  );
}
