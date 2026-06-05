import type { ButtonHTMLAttributes, ReactNode } from "react";
import { THEME } from "../theme";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant: "primary" | "secondary" | "text" | "danger";
  size?: "sm" | "md";
  children: ReactNode;
}

const variantStyles: Record<ButtonProps["variant"], React.CSSProperties> = {
  primary: {
    background: THEME.colors.primary,
    color: THEME.colors.bgWhite,
    border: "none",
  },
  secondary: {
    background: THEME.colors.bgWhite,
    color: THEME.colors.textPrimary,
    border: `1px solid ${THEME.colors.border}`,
  },
  text: {
    background: "none",
    color: THEME.colors.textSecondary,
    border: "none",
  },
  danger: {
    background: THEME.colors.errorText,
    color: THEME.colors.bgWhite,
    border: "none",
  },
};

const sizeStyles: Record<"sm" | "md", React.CSSProperties> = {
  sm: { padding: "6px 10px", fontSize: THEME.fontSize.sm, borderRadius: THEME.radius.sm },
  md: { padding: "10px 20px", fontSize: THEME.fontSize.body, borderRadius: THEME.radius.md },
};

export default function Button({
  variant,
  size = "md",
  disabled,
  style,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      style={{
        fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: THEME.spacing.sm,
        lineHeight: 1.4,
        ...variantStyles[variant],
        ...sizeStyles[size],
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  );
}
