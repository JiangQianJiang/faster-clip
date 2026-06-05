import { useEffect, type ReactNode } from "react";
import { THEME } from "../theme";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  maxWidth?: number;
}

export default function Modal({ title, onClose, children, maxWidth = 1000 }: ModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: THEME.zIndex.modal,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: THEME.colors.bgWhite,
          borderRadius: THEME.radius.lg,
          overflow: "hidden",
          boxShadow: THEME.shadow.modal,
          width: "90vw",
          maxWidth,
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: `14px ${THEME.spacing.lg}px`,
            borderBottom: `1px solid ${THEME.colors.borderLight}`,
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: THEME.fontSize.body, fontWeight: 600, color: THEME.colors.textPrimary }}>
            {title}
          </span>
          <button
            onClick={onClose}
            style={{
              color: THEME.colors.textMuted,
              fontSize: 18,
              cursor: "pointer",
              lineHeight: 1,
              padding: "2px 6px",
              background: "none",
              border: "none",
            }}
          >
            ✕
          </button>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>{children}</div>
      </div>
    </div>
  );
}
