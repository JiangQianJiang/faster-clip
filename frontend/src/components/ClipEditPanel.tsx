import { THEME } from "../theme";
import VideoPlayer from "./VideoPlayer";
import ClipSubtitleTrack from "./ClipSubtitleTrack";
import {
  updateSegmentText,
  deleteSegment,
  isInsideClipWindow,
  type EditingState,
  type EditingAction,
  type EditableSubtitleSegment,
  type SegmentIssue,
} from "../utils/subtitleEditing";
import type { TranscriptSegment, TranscriptAfterSave } from "../api/client";

interface ClipEditPanelProps {
  // ── State from useClipEdit ──
  editingState: EditingState;
  selectedId: string | null;
  editingId: string | null;
  currentTime: number;

  saveError: string | null;
  saving: boolean;
  afterSaveAction: TranscriptAfterSave;
  clipWindow: { start: number; end: number } | null;

  // ── Setters from useClipEdit ──
  setSelectedId: (id: string | null) => void;
  setEditingId: (id: string | null) => void;
  setSaveError: (err: string | null) => void;
  setAfterSaveAction: (action: TranscriptAfterSave) => void;
  setIsPlaying: (playing: boolean) => void;

  // ── Computed ──
  displaySegments: (TranscriptSegment | EditableSubtitleSegment)[];
  displayIssues: Map<string, SegmentIssue[]>;

  // ── Handlers from useClipEdit ──
  editDispatch: (action: EditingAction) => void;
  syncSubtitle: () => void;
  exitEditMode: () => void;
  selectSegment: (id: string, seek: boolean) => void;
  previewMove: (id: string, delta: number) => void;
  previewResize: (id: string, edge: "start" | "end", time: number) => void;
  commitDragSnapshot: () => void;
  handleSave: () => Promise<boolean>;
  enterEditMode: () => Promise<void>;

  // ── Helpers ──

  fmtTime: (sec: number) => string;
  toAbsolute: (local: number) => number;
  toLocal: (absolute: number) => number;

  // ── Other ──
  clipDownloadUrl: string;

  videoHeight: number;
  taskId: string;

  // ── Refs ──
  activeRef: React.RefObject<HTMLDivElement>;
  videoRef: React.RefObject<HTMLVideoElement>;

  // ── Video callbacks ──
  onLoadedMetadata: () => void;
}

export default function ClipEditPanel({
  editingState,
  selectedId,
  editingId,
  currentTime,

  saveError,
  saving,
  afterSaveAction,
  clipWindow,
  setSelectedId,
  setEditingId,
  setSaveError,
  setAfterSaveAction,
  setIsPlaying,
  displaySegments,
  displayIssues,
  editDispatch,
  syncSubtitle,
  exitEditMode,
  selectSegment,
  previewMove,
  previewResize,
  commitDragSnapshot,
  handleSave,
  enterEditMode,

  fmtTime,
  toAbsolute,
  toLocal,
  clipDownloadUrl,

  videoHeight,
  taskId,
  activeRef,
  videoRef,
  onLoadedMetadata,
}: ClipEditPanelProps) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* ── Toolbar ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 20px",
          borderBottom: `1px solid ${THEME.colors.borderLight}`,
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => editDispatch({ type: "UNDO" })}
          disabled={editingState.past.length === 0}
          style={toolbarBtn}
        >
          撤销
        </button>
        <button
          onClick={() => editDispatch({ type: "REDO" })}
          disabled={editingState.future.length === 0}
          style={toolbarBtn}
        >
          重做
        </button>
        <button
          onClick={() => {
            if (clipWindow) {
              const absPlayhead = toAbsolute(videoRef.current?.currentTime || 0);
              editDispatch({
                type: "ADD_SEGMENT_CLIP_WINDOW",
                playhead: absPlayhead,
                fps: 0,
                clipStart: clipWindow.start,
                clipEnd: clipWindow.end,
              });
            }
          }}
          disabled={
            !clipWindow ||
            toAbsolute(videoRef.current?.currentTime || 0) < clipWindow.start ||
            toAbsolute(videoRef.current?.currentTime || 0) > clipWindow.end
          }
          style={toolbarBtn}
        >
          新增
        </button>
        <button
          onClick={() => {
            if (selectedId && videoRef.current) {
              const absPlayhead = toAbsolute(videoRef.current.currentTime);
              editDispatch({
                type: "SPLIT_SEGMENT",
                id: selectedId,
                playhead: absPlayhead,
                fps: 0,
              });
            }
          }}
          disabled={
            !selectedId ||
            !(() => {
              if (!selectedId || !videoRef.current) return true;
              const absPlayhead = toAbsolute(videoRef.current.currentTime);
              const seg = editingState.present.find((s) => s.id === selectedId);
              if (!seg) return true;
              return absPlayhead <= seg.start_time_s || absPlayhead >= seg.end_time_s;
            })()
          }
          style={toolbarBtn}
        >
          分割
        </button>
        <button
          onClick={() => {
            if (selectedId) {
              editDispatch(deleteSegment(selectedId));
              setSelectedId(null);
            }
          }}
          disabled={!selectedId}
          style={toolbarBtn}
        >
          删除
        </button>
        <select
          value={afterSaveAction}
          onChange={(e) =>
            setAfterSaveAction(
              e.target.value as TranscriptAfterSave,
            )
          }
          style={{
            padding: "4px 8px",
            border: "1px solid #d1d5db",
            borderRadius: 4,
            fontSize: 12,
            background: "#fff",
          }}
        >
          <option value="save_only">仅保存</option>
          <option value="regenerate_clip_subtitles">
            保存并重新生成字幕
          </option>
          <option value="reanalyze">保存并重新分析</option>
        </select>
        <button onClick={() => { void handleSave(); }} disabled={saving} style={btnPrimary}>
          {saving ? "保存中..." : "保存"}
        </button>
        <button onClick={exitEditMode} style={btnSecondary}>
          退出编辑
        </button>
      </div>

      {/* ── Save error ── */}
      {saveError && (
        <div
          style={{
            padding: "8px 16px",
            background: "#fef2f2",
            color: THEME.colors.errorText,
            fontSize: 12,
            borderBottom: "1px solid #fecaca",
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexShrink: 0,
          }}
        >
          <span style={{ flex: 1 }}>
            {saveError === "409:conflict"
              ? "字幕已被其他操作修改，请刷新后重试。"
              : saveError}
          </span>
          {saveError === "409:conflict" && (
            <button
              onClick={() => { setSaveError(null); void enterEditMode(); }}
              style={{
                padding: "2px 10px",
                background: "#3b82f6",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                fontSize: 11,
                cursor: "pointer",
              }}
            >
              刷新
            </button>
          )}
          <button
            onClick={() => setSaveError(null)}
            style={{ color: THEME.colors.errorText, border: "none", background: "none", cursor: "pointer", fontSize: 14 }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Body ── */}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Video */}
        <div
          style={{
            flex: "0 0 62%",
            borderRight: "1px solid #333",
          }}
        >
          <VideoPlayer
            ref={videoRef}
            taskId={taskId}
            src={clipDownloadUrl}
            autoPlay
            activeText={
              editingState.present.length > 0
                ? (() => {
                    const idx = editingState.present.findIndex(
                      (s) => currentTime >= s.start_time_s && currentTime < s.end_time_s,
                    );
                    return idx >= 0 ? editingState.present[idx].text : "";
                  })()
                : ""
            }
            onTimeUpdate={syncSubtitle}
            onLoadedMetadata={onLoadedMetadata}
            onPlayStateChange={setIsPlaying}
            onEnded={() => {
              const last = editingState.present[editingState.present.length - 1];
              if (last) setSelectedId(last.id);
            }}
          />
        </div>

        {/* Subtitle panel */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            maxHeight: videoHeight || "none",
            background: "#fff",
          }}
        >
          <div
            style={{
              padding: "10px 16px",
              fontSize: 11,
              color: THEME.colors.textMuted,
              borderBottom: "1px solid #f5f5f5",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              fontWeight: 500,
            }}
          >
            字幕
          </div>
          {displaySegments.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: THEME.colors.textMuted, fontSize: 13 }}>
              暂无字幕
            </div>
          )}
          {displaySegments.map((seg: TranscriptSegment | EditableSubtitleSegment, i: number) => {
            const segId = "id" in seg ? seg.id : `seg-${i}`;
            const isSelected = segId === selectedId;
            const isEditing = segId === editingId;
            const segIssues = displayIssues.get(segId) || [];
            const hasIssue = segIssues.length > 0;

            const isBoundary =
              clipWindow !== null &&
              !isInsideClipWindow(seg, clipWindow.start, clipWindow.end);

            return (
              <div
                key={segId}
                ref={isSelected ? activeRef : undefined}
                onClick={() => {
                  if (!isBoundary) {
                    selectSegment(segId, true);
                  }
                }}
                onDoubleClick={() => {
                  if (!isBoundary) {
                    setEditingId(segId);
                  }
                }}
                style={{
                  padding: "10px 16px",
                  borderBottom: "1px solid #f9f9f9",
                  background: isBoundary
                    ? "#f5f5f5"
                    : isSelected
                      ? "#eff6ff"
                      : "transparent",
                  borderLeft: isSelected
                    ? "3px solid #3b82f6"
                    : "3px solid transparent",
                  cursor: !isBoundary ? "pointer" : "default",
                  opacity: isBoundary ? 0.6 : 1,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 2,
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      color: isSelected ? "#3b82f6" : "#bbb",
                      fontWeight: isSelected ? 600 : 400,
                    }}
                  >
                    {fmtTime(seg.start_time_s)}
                  </span>
                  <div style={{ display: "flex", gap: 4 }}>
                    {isBoundary && (
                      <span
                        style={{
                          fontSize: 9,
                          padding: "1px 6px",
                          borderRadius: 8,
                          background: "#e5e7eb",
                          color: "#9ca3af",
                        }}
                      >
                        锁定
                      </span>
                    )}
                    {hasIssue &&
                      segIssues.map((issue: string) => (
                        <span
                          key={issue}
                          style={{
                            fontSize: 9,
                            padding: "1px 6px",
                            borderRadius: 8,
                            background: "#fecaca",
                            color: THEME.colors.errorText,
                          }}
                        >
                          {issue}
                        </span>
                      ))}
                  </div>
                </div>
                {isEditing ? (
                  <input
                    autoFocus
                    value={seg.text}
                    onChange={(e) => {
                      editDispatch(updateSegmentText(segId, e.target.value));
                    }}
                    onBlur={() => setEditingId(null)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") setEditingId(null);
                      if (e.key === " " || e.key === "Delete") e.stopPropagation();
                    }}
                    style={{
                      width: "100%",
                      fontSize: 13,
                      border: "1px solid #3b82f6",
                      borderRadius: 4,
                      padding: "2px 6px",
                      outline: "none",
                    }}
                  />
                ) : (
                  <div
                    style={{
                      fontSize: 13,
                      lineHeight: 1.5,
                      color: isSelected ? "#1e40af" : "#666",
                      fontWeight: isSelected ? 500 : 400,
                    }}
                  >
                    {seg.text}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Subtitle track ── */}
      {clipWindow && (
        <ClipSubtitleTrack
          segments={editingState.present}
          clipStart={clipWindow.start}
          clipEnd={clipWindow.end}
          currentTime={currentTime}
          selectedId={selectedId}
          issues={displayIssues}
          onSeek={(time) => {
            if (videoRef.current) videoRef.current.currentTime = toLocal(time);
          }}
          onSelect={(id) => setSelectedId(id)}
          onEditStart={(id) => setEditingId(id)}
          onMove={(id, delta) => previewMove(id, delta)}
          onResize={(id, edge, time) => previewResize(id, edge, time)}
          onDragEnd={commitDragSnapshot}
        />
      )}
    </div>
  );
}

const btnPrimary: React.CSSProperties = {
  padding: "6px 14px",
  background: THEME.colors.primary,
  color: THEME.colors.bgWhite,
  borderRadius: THEME.radius.md,
  fontSize: THEME.fontSize.sm,
  fontWeight: 500,
  border: "none",
  cursor: "pointer",
};

const btnSecondary: React.CSSProperties = {
  padding: "6px 10px 6px 14px",
  border: `1px solid ${THEME.colors.border}`,
  color: THEME.colors.textPrimary,
  borderRadius: THEME.radius.md,
  fontSize: THEME.fontSize.sm,
  cursor: "pointer",
  background: THEME.colors.bgWhite,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const toolbarBtn: React.CSSProperties = {
  padding: "6px 10px",
  border: `1px solid ${THEME.colors.border}`,
  color: THEME.colors.textPrimary,
  borderRadius: THEME.radius.md,
  fontSize: THEME.fontSize.sm,
  cursor: "pointer",
  background: THEME.colors.bgWhite,
};
