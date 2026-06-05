import { useEffect, useState, useRef, useCallback } from "react";
import { binarySearch } from "../utils/subtitleEditing";
import { THEME } from "../theme";
import Button from "../ui/Button";
import VideoPlayer from "./VideoPlayer";
import { getAccessToken } from "../auth";
import type { TranscriptSegment } from "../api/client";

export type BrowseStatus =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; segments: TranscriptSegment[] };

interface Props {
  taskId: string;
  browseStatus: BrowseStatus;
  onClose: () => void;
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function SubtitleBrowserModal({ taskId, browseStatus, onClose }: Props) {
  const segments = browseStatus.status === "ready" ? browseStatus.segments : [];
  const videoRef = useRef<HTMLVideoElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);

  const [currentIndex, setCurrentIndex] = useState(-1);

  // Authenticated video URL using query-param token so the <video> tag
  // can request the resource without custom headers.
  const videoUrl = `/api/tasks/${taskId}/video?token=${getAccessToken() || ""}`;

  // Binary-search the active subtitle on every timeupdate.
  // Only update state when the index actually changes to avoid needless re-renders.
  const syncSubtitle = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const idx = segments.length === 0 ? -1 : binarySearch(segments, video.currentTime);
    setCurrentIndex((prev) => (prev === idx ? prev : idx));
  }, [segments]);

  // Run initial sync when video metadata is loaded (so time=0 is matched immediately)
  const handleLoadedMetadata = useCallback(() => {
    syncSubtitle();
  }, [syncSubtitle]);

  // Auto-scroll subtitle list when active row changes
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [currentIndex]);

  // Escape key closes the modal
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const handleRowClick = (index: number, startTime: number) => {
    // No-op if clicking the already-active row (AC-5 negative test)
    if (index === currentIndex) return;
    if (videoRef.current) {
      videoRef.current.currentTime = startTime;
    }
  };

  const activeText = currentIndex >= 0 ? segments[currentIndex]?.text : "";

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
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: THEME.colors.bgWhite,
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 4px 24px rgba(0,0,0,0.12)",
          width: "90vw",
          maxWidth: 1000,
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "14px 20px",
            borderBottom: `1px solid ${THEME.colors.borderLight}`,
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 600, color: THEME.colors.textPrimary }}>字幕浏览</span>
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

        {/* Body */}
        {browseStatus.status === "loading" && (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", minHeight: 300 }}>
            <span style={{ color: THEME.colors.textMuted, fontSize: 14 }}>加载字幕中...</span>
          </div>
        )}

        {browseStatus.status === "error" && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 300, gap: 16 }}>
            <span style={{ color: THEME.colors.errorText, fontSize: 14 }}>字幕加载失败: {browseStatus.message}</span>
            <Button variant="primary" size="sm" onClick={onClose}>关闭</Button>
          </div>
        )}

        {browseStatus.status === "ready" && (
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          {/* Video panel */}
          <div
            style={{
              flex: "0 0 62%",
              borderRight: "1px solid #333",
            }}
          >
            <VideoPlayer
              ref={videoRef}
              taskId={taskId}
              src={videoUrl}
              activeText={activeText}
              onTimeUpdate={syncSubtitle}
              onLoadedMetadata={handleLoadedMetadata}
            />
          </div>

          {/* Subtitle list panel */}
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              background: THEME.colors.bgWhite,
              maxHeight: "calc(90vh - 54px)",
            }}
          >
            <div
              style={{
                padding: "10px 16px",
                fontSize: 11,
                color: THEME.colors.textMuted,
                borderBottom: "1px solid #f5f5f5",
                fontWeight: 500,
              }}
            >
              字幕列表 ({segments.length})
            </div>

            {segments.length === 0 && (
              <div style={{ padding: 40, textAlign: "center", color: THEME.colors.textMuted, fontSize: 13 }}>
                暂无字幕
              </div>
            )}

            {segments.map((seg, i) => {
              const isActive = i === currentIndex;
              return (
                <div
                  key={i}
                  ref={isActive ? activeRef : undefined}
                  onClick={() => handleRowClick(i, seg.start_time_s)}
                  style={{
                    padding: "10px 16px",
                    borderBottom: `1px solid ${THEME.colors.borderLight}`,
                    background: isActive ? THEME.colors.infoBg : "transparent",
                    borderLeft: isActive ? `3px solid ${THEME.colors.infoText}` : "3px solid transparent",
                    cursor: "pointer",
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      color: isActive ? THEME.colors.infoText : THEME.colors.textSecondary,
                      fontWeight: isActive ? 600 : 400,
                    }}
                  >
                    {fmtTime(seg.start_time_s)}
                  </span>
                  <div
                    style={{
                      fontSize: 13,
                      lineHeight: 1.5,
                      color: isActive ? THEME.colors.infoText : THEME.colors.textSecondary,
                      fontWeight: isActive ? 500 : 400,
                      marginTop: 2,
                    }}
                  >
                    {seg.text}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        )}
      </div>
    </div>
  );
}
