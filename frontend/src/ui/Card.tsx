import { useState } from "react";
import type { HTMLAttributes, ReactNode } from "react";
import { THEME } from "../theme";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  onClick?: () => void;
}

export default function Card({ children, onClick, style, onMouseEnter, onMouseLeave, ...rest }: CardProps) {
  const [hovered, setHovered] = useState(false);
  const interactive = onClick
    ? { cursor: "pointer" as const, background: hovered ? THEME.colors.bgHover : THEME.colors.bgWhite }
    : {};

  return (
    <div
      onClick={onClick}
      onMouseEnter={(e) => {
        setHovered(true);
        onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        setHovered(false);
        onMouseLeave?.(e);
      }}
      style={{
        background: THEME.colors.bgWhite,
        border: `1px solid ${THEME.colors.border}`,
        borderRadius: THEME.radius.lg,
        padding: THEME.spacing.lg,
        boxShadow: THEME.shadow.card,
        transition: "background 0.15s",
        ...interactive,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
