import { forwardRef, useState } from "react";
import type { InputHTMLAttributes } from "react";
import { THEME } from "../theme";

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  size?: "sm" | "md";
}

const sizeStyles: Record<"sm" | "md", React.CSSProperties> = {
  sm: { padding: "6px 10px", fontSize: THEME.fontSize.sm },
  md: { padding: "10px 14px", fontSize: THEME.fontSize.body },
};

const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { size = "md", style, disabled, onFocus, onBlur, ...rest },
  ref,
) {
  const [focused, setFocused] = useState(false);

  return (
    <input
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
        width: "100%",
        boxSizing: "border-box",
        opacity: disabled ? 0.5 : 1,
        transition: "border-color 0.15s",
        ...sizeStyles[size],
        ...style,
      }}
      {...rest}
    />
  );
});

export default Input;
