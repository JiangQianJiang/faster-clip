import type { ReactNode } from "react";
import { THEME } from "../theme";

type BadgeVariant = "success" | "info" | "warning" | "error" | "neutral";

interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
}

const badgeStyles: Record<BadgeVariant, React.CSSProperties> = {
  success: { background: THEME.colors.successBg, color: THEME.colors.successText },
  info: { background: THEME.colors.infoBg, color: THEME.colors.infoText },
  warning: { background: THEME.colors.warningBg, color: THEME.colors.warningText },
  error: { background: THEME.colors.errorBg, color: THEME.colors.errorText },
  neutral: { background: THEME.colors.bgHover, color: THEME.colors.textPrimary },
};

const VALID_VARIANTS = new Set(["success", "info", "warning", "error", "neutral"]);

export default function Badge({ variant, children }: BadgeProps) {
  const resolved: BadgeVariant = variant && VALID_VARIANTS.has(variant) ? variant as BadgeVariant : "neutral";
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: THEME.radius.sm,
        fontSize: THEME.fontSize.caption,
        fontWeight: 500,
        lineHeight: 1.5,
        whiteSpace: "nowrap",
        ...badgeStyles[resolved],
      }}
    >
      {children}
    </span>
  );
}
