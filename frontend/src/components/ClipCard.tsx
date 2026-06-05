import { useState, useRef, useEffect } from "react";
import type { Clip } from "../api/client";
import { getClipSubtitleUrl, getThumbnailBlobUrl } from "../api/client";
import { authBlobUrl } from "../auth";
import { THEME } from "../theme";
import Button from "../ui/Button";
import Badge from "../ui/Badge";

interface Props {
  clip: Clip;
  index: number;
  taskId: string;
  onPreview: (index: number) => void;
  onDelete?: (index: number) => void;
}

const SUB_FORMATS = [
  { label: "SRT", value: "srt" },
  { label: "VTT", value: "vtt" },
  { label: "ASS", value: "ass" },
];

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function ClipCard({ clip, index, taskId, onPreview, onDelete }: Props) {
  const [subMenuOpen, setSubMenuOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [thumbBlobUrl, setThumbBlobUrl] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const subMenuRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const thumbBlobRef = useRef<string | null>(null); // Track for cleanup

  const isExported = clip.status === "success";
  const isPending = clip.status === "pending" || !clip.status;

  // Load thumbnail via authenticated fetch (img tag can't send auth headers)
  // Thumbnails are small (~12KB) so eager loading is fine
  useEffect(() => {
    if (!isExported) return;
    let cancelled = false;
    getThumbnailBlobUrl(taskId, index)
      .then((url) => {
        if (!cancelled) {
          setThumbBlobUrl(url);
          thumbBlobRef.current = url;
        }
      })
      .catch(() => {}); // Silent fail — show placeholder
    return () => {
      cancelled = true;
      // Revoke blob URL on unmount to free memory
      if (thumbBlobRef.current) {
        URL.revokeObjectURL(thumbBlobRef.current);
        thumbBlobRef.current = null;
      }
    };
  }, [taskId, index, isExported]);

  // Close subtitle menu on outside click
  useEffect(() => {
    if (!subMenuOpen) return;
    const close = (e: MouseEvent) => {
      if (subMenuRef.current && !subMenuRef.current.contains(e.target as Node)) {
        setSubMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [subMenuOpen]);

  // Close more menu on outside click
  useEffect(() => {
    if (!moreOpen) return;
    const close = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setMoreOpen(false);
        setConfirmDelete(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [moreOpen]);

  const handleSubDownload = async (format: string) => {
    setSubMenuOpen(false);
    try {
      const url = await authBlobUrl(getClipSubtitleUrl(taskId, index, format));
      const a = document.createElement("a");
      a.href = url;
      a.download = `clip_${String(index).padStart(3, "0")}.${format}`;
      a.click();
    } catch {
      // silently fail
    }
  };

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setDownloading(true);
    try {
      const url = await authBlobUrl(`/api/tasks/${taskId}/clips/${index}/download`);
      const a = document.createElement("a");
      a.href = url;
      a.download = `clip_${String(index).padStart(3, "0")}.mp4`;
      a.click();
    } catch {
      // Silently fail
    } finally {
      setDownloading(false);
    }
  };
  const handleDeleteConfirm = () => {
    setConfirmDelete(false);
    setMoreOpen(false);
    onDelete?.(index);
  };

  return (
    <div
      onClick={() => {
        if (isExported) onPreview(index);
      }}
      style={{
        position: "relative",
        zIndex: subMenuOpen || moreOpen ? 10 : "auto",
        border: `1px solid ${THEME.colors.border}`,
        borderRadius: THEME.radius.md,
        background: THEME.colors.bgWhite,
        cursor: isExported ? "pointer" : "default",
        opacity: isExported ? 1 : 0.7,
      }}
    >
      {/* Thumbnail with more menu */}
      <div style={{ aspectRatio: "16/9", overflow: "hidden", background: THEME.colors.bgHover, position: "relative", borderRadius: `${THEME.radius.md}px ${THEME.radius.md}px 0 0` }}>
        {thumbBlobUrl ? (
          <img
            src={thumbBlobUrl}
            alt={`片段 ${index + 1}`}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <div
            style={{
              width: "100%", height: "100%",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: THEME.colors.textMuted, fontSize: THEME.fontSize.sm,
              background: THEME.colors.bgHover,
            }}
          >
            缩略图
          </div>
        )}

        {/* More menu button */}
        {onDelete && (
          <div style={{ position: "absolute", top: 4, right: 4 }} onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => { setMoreOpen(!moreOpen); setConfirmDelete(false); }}
              style={{
                background: moreOpen ? "rgba(0,0,0,0.6)" : "rgba(0,0,0,0.35)",
                color: "#fff",
                border: "none",
                borderRadius: THEME.radius.sm,
                padding: "2px 8px",
                fontSize: 16,
                lineHeight: 1,
                cursor: "pointer",
                fontWeight: 700,
              }}
            >
              ···
            </button>
            {moreOpen && (
              <div
                ref={moreRef}
                style={{
                  position: "absolute",
                  top: "100%",
                  right: 0,
                  marginTop: 4,
                  background: THEME.colors.bgWhite,
                  border: `1px solid ${THEME.colors.border}`,
                  borderRadius: THEME.radius.md,
                  boxShadow: THEME.shadow.modal,
                  zIndex: 10,
                  minWidth: 120,
                  padding: THEME.spacing.xs,
                }}
              >
                {confirmDelete ? (
                  <div style={{ padding: THEME.spacing.sm }}>
                    <div style={{ fontSize: THEME.fontSize.sm, color: THEME.colors.errorText, marginBottom: THEME.spacing.sm }}>
                      确认删除？
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button
                        onClick={handleDeleteConfirm}
                        style={{
                          padding: "3px 12px", background: THEME.colors.errorText, color: THEME.colors.bgWhite,
                          border: "none", borderRadius: THEME.radius.sm, fontSize: THEME.fontSize.caption, cursor: "pointer",
                        }}
                      >
                        删除
                      </button>
                      <button
                        onClick={() => setConfirmDelete(false)}
                        style={{
                          padding: "3px 12px", background: THEME.colors.bgHover, color: THEME.colors.textPrimary,
                          border: "none", borderRadius: THEME.radius.sm, fontSize: THEME.fontSize.caption, cursor: "pointer",
                        }}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDelete(true)}
                    style={{
                      display: "block", width: "100%", padding: "6px 12px",
                      background: "none", border: "none", cursor: "pointer",
                      textAlign: "left", fontSize: THEME.fontSize.sm, color: THEME.colors.errorText,
                      borderRadius: THEME.radius.sm,
                    }}
                    onMouseEnter={(e) => { (e.target as HTMLElement).style.background = THEME.colors.bgHover; }}
                    onMouseLeave={(e) => { (e.target as HTMLElement).style.background = "none"; }}
                  >
                    删除片段
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: THEME.spacing.md }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: THEME.spacing.xs,
          }}
        >
          <span style={{ fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary }}>
            {fmt(clip.export_start_time_s ?? clip.start_time_s)} - {fmt(clip.export_end_time_s ?? clip.end_time_s)}
          </span>
          <span style={{ fontSize: THEME.fontSize.caption, color: THEME.colors.textMuted }}>
            {(() => {
              const start = clip.export_start_time_s ?? clip.start_time_s;
              const end = clip.export_end_time_s ?? clip.end_time_s;
              const d = end - start;
              const m = Math.floor(d / 60);
              const s = Math.floor(d % 60);
              return `⏱ ${m}:${String(s).padStart(2, "0")}`;
            })()}
          </span>
          <Badge
            variant={clip.score >= 7 ? "success" : clip.score >= 4 ? "warning" : "error"}
          >
            {clip.score.toFixed(1)}
          </Badge>
        </div>
        <p style={{ margin: `${THEME.spacing.xs}px 0 ${THEME.spacing.sm}px`, fontSize: THEME.fontSize.sm, color: THEME.colors.textPrimary, lineHeight: 1.4 }}>
          {clip.reason}
        </p>
        {isExported ? (
          <div
            style={{ display: "flex", gap: THEME.spacing.sm }}
            onClick={(e) => e.stopPropagation()}
          >
            <Button variant="primary" size="sm" onClick={handleDownload} disabled={downloading}>
              {downloading ? "下载中..." : "下载"}
            </Button>
            <div style={{ position: "relative" }}>
              <Button variant="primary" size="sm" onClick={() => setSubMenuOpen(!subMenuOpen)}>字幕 ▼</Button>
              {subMenuOpen && (
                <div
                  ref={subMenuRef}
                  style={{
                    position: "absolute",
                    top: "100%",
                    right: 0,
                    marginTop: 4,
                    background: THEME.colors.bgWhite,
                    border: `1px solid ${THEME.colors.border}`,
                    borderRadius: THEME.radius.md,
                    boxShadow: THEME.shadow.modal,
                    zIndex: 10,
                    minWidth: 80,
                  }}
                >
                  {SUB_FORMATS.map((f) => (
                    <button
                      key={f.value}
                      onClick={() => handleSubDownload(f.value)}
                      style={{
                        display: "block", width: "100%",
                        padding: `${THEME.spacing.sm}px ${THEME.spacing.md}px`,
                        fontSize: THEME.fontSize.sm, color: THEME.colors.textPrimary,
                        background: "none", border: "none", cursor: "pointer", textAlign: "left",
                      }}
                      onMouseEnter={(e) => { (e.target as HTMLElement).style.background = THEME.colors.bgHover; }}
                      onMouseLeave={(e) => { (e.target as HTMLElement).style.background = "none"; }}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : isPending ? (
          <Badge variant="warning">待导出</Badge>
        ) : (
          <Badge variant="error">导出失败</Badge>
        )}
      </div>
    </div>
  );
}
