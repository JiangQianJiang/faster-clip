import { forwardRef, useState } from "react";
import type { SelectHTMLAttributes, ReactNode } from "react";
import { THEME } from "../theme";

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  size?: "sm" | "md";
  children: ReactNode;
}

const sizeStyles: Record<"sm" | "md", React.CSSProperties> = {
  sm: { padding: "6px 10px", fontSize: THEME.fontSize.sm },
  md: { padding: "10px 14px", fontSize: THEME.fontSize.body },
};

const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { size = "md", style, disabled, children, onFocus, onBlur, ...rest },
  ref,
) {
  const [focused, setFocused] = useState(false);

  return (
    <select
      ref={ref}
      disabled={disabled}
      onFocus={(e) => {
        setFocused(true);
        onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        onBlur?.(e);
      }}
      style={{
        border: `1px solid ${focused && !disabled ? THEME.colors.textPrimary : THEME.colors.border}`,
        borderRadius: THEME.radius.md,
        outline: "none",
        color: THEME.colors.textPrimary,
        background: THEME.colors.bgWhite,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        boxSizing: "border-box",
        transition: "border-color 0.15s",
        ...sizeStyles[size],
        ...style,
      }}
      {...rest}
    >
      {children}
    </select>
  );
});

export default Select;
