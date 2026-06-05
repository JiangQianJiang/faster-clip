interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确定",
  cancelLabel = "取消",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 2000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 12,
          padding: 28,
          boxShadow: "0 4px 24px rgba(0,0,0,0.12)",
          maxWidth: 420,
          width: "90%",
        }}
      >
        <h3 style={{ margin: "0 0 12px", fontSize: 16, fontWeight: 600, color: "#1f2937" }}>
          {title}
        </h3>
        <p style={{ margin: "0 0 24px", fontSize: 14, color: "#6b7280", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
          {message}
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button
            onClick={onCancel}
            style={{
              padding: "8px 20px",
              borderRadius: 6,
              border: "1px solid #d1d5db",
              background: "#fff",
              color: "#374151",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            style={{
              padding: "8px 20px",
              borderRadius: 6,
              border: "none",
              background: danger ? "#ef4444" : "#3b82f6",
              color: "#fff",
              fontSize: 14,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
