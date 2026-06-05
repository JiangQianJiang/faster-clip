import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import Button from "../ui/Button";
import Badge from "../ui/Badge";
import { THEME } from "../theme";
import {
  getTranscript,
  TranscriptResponse,
  getTranscriptExportBlobUrl,
} from "../api/client";

interface Props {
  taskId: string;
  status: string;
  stage?: string;
  completedAt?: string;
  transcriptModifiedAt?: string;
  transcriptSource?: string;
  onEdit?: (data: TranscriptResponse) => void;
  onBrowse?: () => void;
}

export default function TranscriptPanel({
  taskId,
  status,
  stage,
  completedAt,
  transcriptModifiedAt,
  transcriptSource,
  onEdit,
  onBrowse,
}: Props) {
  const [data, setData] = useState<TranscriptResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Export dropdown
  const [exportOpen, setExportOpen] = useState(false);

  // Stale output warning
  const [staleWarning, setStaleWarning] = useState(false);
  const [localModifiedAt, setLocalModifiedAt] = useState<string | undefined>(
    transcriptModifiedAt,
  );

  useEffect(() => {
    setLocalModifiedAt(transcriptModifiedAt);
  }, [transcriptModifiedAt]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTranscript(taskId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [taskId, status, stage]);

  useEffect(() => {
    if (localModifiedAt && completedAt) {
      setStaleWarning(localModifiedAt > completedAt);
    } else {
      setStaleWarning(false);
    }
  }, [localModifiedAt, completedAt]);

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "#999" }}>
        加载字幕中...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24, textAlign: "center" }}>
        <p style={{ color: "#ef4444", margin: "0 0 8px" }}>字幕加载失败: {error}</p>
        <Link to="/" style={{ color: "#3b82f6", fontSize: 14 }}>返回首页</Link>
      </div>
    );
  }

  const segments = Array.isArray(data?.segments) ? data.segments : [];

  if (!data || !data.available || segments.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "#999" }}>
        暂无字幕
      </div>
    );
  }

  const formatTime = (seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  const handleExport = async (format: string) => {
    setExportOpen(false);
    try {
      const url = await getTranscriptExportBlobUrl(taskId, format);
      const a = document.createElement("a");
      a.href = url;
      a.download = `transcript.${format}`;
      a.click();
    } catch {
      // silently fail
    }
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <h3 style={{ margin: 0 }}>字幕</h3>
        <span style={{ color: "#6b7280", fontSize: 13 }}>
          {transcriptSource ? `来源: ${transcriptSource} · ` : ""}{segments.length} 条
        </span>

        <div style={{ display: "flex", gap: 8 }}>
          {segments.length > 0 && onBrowse && (
            <Button variant="secondary" size="sm" onClick={onBrowse}>浏览</Button>
          )}
          {segments.length > 0 && (
            <Button variant="secondary" size="sm" onClick={() => data && onEdit?.(data)}>编辑字幕</Button>
          )}

          <div style={{ position: "relative" }}>
            <Button variant="secondary" size="sm" onClick={() => setExportOpen(!exportOpen)}>导出 ▾</Button>
            {exportOpen && (
              <div
                style={{
                  position: "absolute",
                  right: 0,
                  top: "100%",
                  marginTop: 4,
                  background: "#fff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                  boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                  zIndex: 10,
                  minWidth: 80,
                }}
              >
                {["srt", "vtt", "ass"].map((fmt) => (
                  <button
                    key={fmt}
                    onClick={() => handleExport(fmt)}
                    style={{
                      display: "block",
                      width: "100%",
                      padding: "6px 16px",
                      border: "none",
                      background: "transparent",
                      cursor: "pointer",
                      fontSize: 13,
                      textAlign: "left",
                    }}
                  >
                    {fmt.toUpperCase()}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {staleWarning && (
        <div
          style={{
            padding: "8px 12px",
            marginBottom: 12,
            background: THEME.colors.warningBg,
            border: `1px solid ${THEME.colors.warningText}`,
            borderRadius: THEME.radius.sm,
            fontSize: 13,
            color: THEME.colors.warningText,
          }}
        >
          <Badge variant="warning">字幕已修改</Badge> 现有片段可能已过时，如需更新片段请重新分析。
        </div>
      )}

      <div
        style={{
          maxHeight: 400,
          overflowY: "auto",
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          padding: "8px 0",
        }}
      >
        {segments.map((seg, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 12,
              padding: "6px 16px",
              fontSize: 14,
              lineHeight: 1.5,
              background: i % 2 === 0 ? "#f9fafb" : "#fff",
              alignItems: "flex-start",
            }}
          >
            <span
              style={{
                color: "#6b7280",
                fontVariantNumeric: "tabular-nums",
                whiteSpace: "nowrap",
                minWidth: 48,
              }}
            >
              {formatTime(seg.start_time_s)}
            </span>
            <span style={{ color: "#111827" }}>{seg.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
