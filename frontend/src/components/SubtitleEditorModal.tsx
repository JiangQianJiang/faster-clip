import { useEffect, useMemo, useRef, useState } from "react";
import {
  getTranscriptExportBlobUrl,
  patchTranscript,
  type TaskResponse,
  type TranscriptAfterSave,
  type TranscriptResponse,
} from "../api/client";
import {
  binarySearch,
  deleteSegment,
  detectSegmentIssues,
  editingReducer,
  initialEditingState,
  toTranscriptPayload,
  updateSegmentText,
  moveSegment,
  resizeSegment,
  type EditableSubtitleSegment,
} from "../utils/subtitleEditing";
import SubtitleList from "./SubtitleList";
import SubtitleTimeline from "./SubtitleTimeline";
import { THEME } from "../theme";
import VideoPlayer from "./VideoPlayer";
import { getAccessToken } from "../auth";

interface Props {
  task: TaskResponse;
  transcript: TranscriptResponse;
  onClose: () => void;
  onSaved: () => void;
}

const exportFormats = ["srt", "vtt", "ass"];

export default function SubtitleEditorModal({ task, transcript, onClose, onSaved }: Props) {
  const initialSegments = useMemo<EditableSubtitleSegment[]>(
    () => transcript.segments.map((segment, index) => ({
      id: `segment-${index}-${segment.start_time_s}-${segment.end_time_s}`,
      ...segment,
    })),
    [transcript.segments],
  );
  const [state, dispatch] = useState(() => initialEditingState(initialSegments));
  const [selectedId, setSelectedId] = useState<string | null>(initialSegments[0]?.id || null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [listWidth, setListWidth] = useState(25);
  const [timelineHeight, setTimelineHeight] = useState(30);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [afterSaveAction, setAfterSaveAction] =
    useState<TranscriptAfterSave>("save_only");
  const [exportOpen, setExportOpen] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLElement | null>(document.activeElement as HTMLElement | null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const dragStartRef = useRef<EditableSubtitleSegment[] | null>(null);
  const durationRef = useRef(duration);
  durationRef.current = duration;
  const dirty = state.past.length > 0;
  const fps = task.media_info?.fps && task.media_info.fps > 0 ? task.media_info.fps : 0;
  const issues = useMemo(() => detectSegmentIssues(state.present), [state.present]);

  useEffect(() => {
    modalRef.current?.focus();
    return () => triggerRef.current?.focus?.();
  }, []);

  // Authenticated video URL using query-param token so the <video> tag
  // can request the resource without custom headers.
  const videoUrl = `/api/tasks/${task.task_id}/video?token=${getAccessToken() || ""}`;

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const editingText = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        dispatch((current) => editingReducer(current, { type: event.shiftKey ? "REDO" : "UNDO" }));
        return;
      }
      if (event.key === "Tab") {
        trapFocus(event);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        requestClose();
        return;
      }
      if (editingText) return;
      if (event.key === " " && (target === modalRef.current || modalRef.current?.contains(target))) {
        event.preventDefault();
        togglePlayback();
      }
      if (event.key === "Delete" && selectedId) {
        event.preventDefault();
        dispatch((current) => editingReducer(current, deleteSegment(selectedId)));
        setSelectedId(null);
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const video = videoRef.current;
        const dur = durationRef.current;
        if (!video || !dur) return;
        const step = event.shiftKey ? 5 : 1;
        const delta = event.key === "ArrowLeft" ? -step : step;
        const next = Math.max(0, Math.min(dur, video.currentTime + delta));
        video.currentTime = next;
        setCurrentTime(next);
      }
    };
    // Use capture phase so arrow keys work even when focus is on scrollable children (timeline)
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  });

  const requestClose = async () => {
    if (!dirty) {
      onClose();
      return;
    }
    const shouldSave = window.confirm("有未保存的修改。是否先保存？");
    if (shouldSave) {
      const saved = await handleSave();
      if (saved) onClose();
      return;
    }
    if (window.confirm("放弃未保存的修改并关闭？")) {
      onClose();
    }
  };

  const seekTo = (time: number, preservePlay = isPlaying) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(time, duration || time));
    setCurrentTime(video.currentTime);
    if (preservePlay) {
      video.play().catch(() => undefined);
    }
  };

  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) video.play().catch(() => undefined);
    else video.pause();
  };

  const trapFocus = (event: KeyboardEvent) => {
    const modal = modalRef.current;
    if (!modal) return;
    const focusable = Array.from(
      modal.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => element.offsetParent !== null || element === modal);
    if (focusable.length === 0) {
      event.preventDefault();
      modal.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    } else if (active && !modal.contains(active)) {
      event.preventDefault();
      first.focus();
    }
  };

  const selectSegment = (id: string, jump = false) => {
    setSelectedId(id);
    if (jump) {
      const segment = state.present.find((item) => item.id === id);
      if (segment) seekTo(segment.start_time_s, isPlaying);
    }
  };

  const handleSave = async (): Promise<boolean> => {
    setSaveError(null);
    if (issues.size > 0) {
      setSaveError("存在重叠或非法时长，请修正后再保存。");
      return false;
    }
    setSaving(true);
    try {
      await patchTranscript(
        task.task_id,
        toTranscriptPayload(state.present),
        afterSaveAction,
        task.transcript_version,
      );
      onSaved();
      return true;
    } catch (error) {
      setSaveError(String(error));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const startTimelineDrag = () => {
    if (!dragStartRef.current) {
      dragStartRef.current = state.present.map((segment) => ({ ...segment }));
    }
  };

  const commitTimelineDrag = () => {
    const before = dragStartRef.current;
    dragStartRef.current = null;
    if (!before) return;
    const after = state.present.map((segment) => ({ ...segment }));
    if (JSON.stringify(before) === JSON.stringify(after)) return;
    dispatch((current) => ({
      past: [...current.past, before],
      present: current.present,
      future: [],
    }));
  };

  const previewMove = (id: string, delta: number) => {
    dispatch((current) => ({
      ...current,
      present: moveSegment(current.present, id, delta, fps, duration),
    }));
  };

  const previewResize = (id: string, edge: "start" | "end", time: number) => {
    dispatch((current) => ({
      ...current,
      present: resizeSegment(current.present, id, edge, time, fps, duration),
    }));
  };

  const dragVertical = (event: React.PointerEvent<HTMLDivElement>) => {
    const startX = event.clientX;
    const start = listWidth;
    const onMove = (move: PointerEvent) => {
      const width = window.innerWidth * 0.7;
      const deltaPct = ((startX - move.clientX) / width) * 100;
      setListWidth(Math.min(45, Math.max(18, start + deltaPct)));
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const dragHorizontal = (event: React.PointerEvent<HTMLDivElement>) => {
    const startY = event.clientY;
    const start = timelineHeight;
    const onMove = (move: PointerEvent) => {
      const height = window.innerHeight * 0.7;
      const deltaPct = ((startY - move.clientY) / height) * 100;
      setTimelineHeight(Math.min(55, Math.max(18, start + deltaPct)));
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const timelinePct = timelineHeight;
  const videoPct = 100 - timelinePct;
  const mainWidth = 100 - listWidth;

  return (
    <div
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.42)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1200,
      }}
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
        style={{
          width: "70vw",
          height: "70vh",
          background: THEME.colors.bgWhite,
          borderRadius: THEME.radius.md,
          boxShadow: THEME.shadow.modal,
          display: "grid",
          gridTemplateRows: "48px 1fr",
          overflow: "hidden",
          outline: "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 14px", borderBottom: `1px solid ${THEME.colors.borderLight}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <strong style={{ fontSize: THEME.fontSize.body, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: THEME.colors.textPrimary }}>
              {task.video_filename || "编辑字幕"}
            </strong>
            <span style={{ fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary }}>{state.present.length} 条</span>
            {dirty && <span style={{ fontSize: THEME.fontSize.sm, color: THEME.colors.warningText }}>未保存</span>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button onClick={() => dispatch((current) => editingReducer(current, { type: "UNDO" }))} disabled={state.past.length === 0} style={toolbarButton()}>
              撤销
            </button>
            <button onClick={() => dispatch((current) => editingReducer(current, { type: "REDO" }))} disabled={state.future.length === 0} style={toolbarButton()}>
              重做
            </button>
            <button
              onClick={() => dispatch((current) => editingReducer(current, { type: "ADD_SEGMENT", playhead: currentTime, fps, videoDuration: duration }))}
              style={toolbarButton()}
            >
              新增字幕
            </button>
            <button
              disabled={!selectedId || !canSplit(state.present, selectedId, currentTime)}
              onClick={() => selectedId && dispatch((current) => editingReducer(current, { type: "SPLIT_SEGMENT", id: selectedId, playhead: currentTime, fps }))}
              style={toolbarButton()}
            >
              分割
            </button>
            <div style={{ position: "relative" }}>
              <button onClick={() => setExportOpen((open) => !open)} style={toolbarButton()}>导出</button>
              {exportOpen && (
                <div style={{ position: "absolute", right: 0, top: "100%", marginTop: 4, background: THEME.colors.bgWhite, border: `1px solid ${THEME.colors.border}`, borderRadius: THEME.radius.md, boxShadow: THEME.shadow.modal, zIndex: 3 }}>
                  {exportFormats.map((format) => (
                    <button
                      key={format}
                      onClick={async () => {
                        try {
                          const url = await getTranscriptExportBlobUrl(task.task_id, format);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = `transcript.${format}`;
                          a.click();
                        } catch {
                          // silently fail
                        }
                        setExportOpen(false);
                      }}
                      style={{ display: "block", width: "100%", padding: "7px 18px", border: "none", background: THEME.colors.bgWhite, cursor: "pointer", textAlign: "left", color: THEME.colors.textPrimary, fontSize: THEME.fontSize.sm }}
                    >
                      {format.toUpperCase()}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <select
              value={afterSaveAction}
              onChange={(e) =>
                setAfterSaveAction(e.target.value as TranscriptAfterSave)
              }
              style={{
                padding: "4px 8px",
                border: `1px solid ${THEME.colors.border}`,
                borderRadius: THEME.radius.sm,
                fontSize: THEME.fontSize.sm,
                background: THEME.colors.bgWhite,
                color: THEME.colors.textPrimary,
              }}
            >
              <option value="save_only">仅保存</option>
              <option value="regenerate_clip_subtitles">
                保存并重新生成字幕
              </option>
              <option value="reanalyze">保存并重新分析</option>
            </select>
            <button onClick={handleSave} disabled={saving} style={{ ...toolbarButton(), background: THEME.colors.primary, color: THEME.colors.bgWhite, borderColor: THEME.colors.primary }}>
              {saving ? "保存中..." : "保存"}
            </button>
            <button onClick={requestClose} style={toolbarButton()}>关闭</button>
          </div>
        </div>

        <div style={{ display: "flex", minHeight: 0 }}>
          <div style={{ width: `${mainWidth}%`, display: "grid", gridTemplateRows: `${videoPct}% 6px ${timelinePct}%`, minWidth: 0 }}>
            <VideoPlayer
              ref={videoRef}
              taskId={task.task_id}
              src={videoUrl}
              activeText={
                state.present.length > 0 && currentTime >= 0
                  ? (() => {
                      const idx = binarySearch(state.present, currentTime);
                      return idx >= 0 ? state.present[idx].text : "";
                    })()
                  : ""
              }
              onTimeUpdate={setCurrentTime}
              onDurationChange={setDuration}
              onPlayStateChange={setIsPlaying}
            />
            <div onPointerDown={dragHorizontal} style={{ background: "#e2e8f0", cursor: "row-resize" }} />
            <SubtitleTimeline
              segments={state.present}
              selectedId={selectedId}
              currentTime={currentTime}
              duration={duration}
              issues={issues}
              onSeek={seekTo}
              onSelect={(id) => selectSegment(id)}
              onEditStart={setEditingId}
              onDragStart={startTimelineDrag}
              onDragEnd={commitTimelineDrag}
              onMove={previewMove}
              onResize={previewResize}
            />
          </div>
          <div onPointerDown={dragVertical} style={{ width: 6, background: "#e2e8f0", cursor: "col-resize" }} />
          <div style={{ width: `${listWidth}%`, minWidth: 0 }}>
            <SubtitleList
              segments={state.present}
              selectedId={selectedId}
              editingId={editingId}
              issues={issues}
              onSelect={(id) => selectSegment(id, true)}
              onEditStart={setEditingId}
              onTextChange={(id, text) => dispatch((current) => editingReducer(current, updateSegmentText(id, text)))}
              onEditEnd={() => setEditingId(null)}
            />
          </div>
        </div>
        {saveError && (
          <div style={{ position: "absolute", bottom: 20, left: "50%", transform: "translateX(-50%)", background: "#fee2e2", color: "#991b1b", border: "1px solid #fecaca", padding: "8px 12px", borderRadius: 6, fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
            <span>{saveError}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function canSplit(segments: EditableSubtitleSegment[], id: string, currentTime: number): boolean {
  const segment = segments.find((item) => item.id === id);
  return !!segment && currentTime > segment.start_time_s && currentTime < segment.end_time_s;
}

function toolbarButton(): React.CSSProperties {
  return {
    padding: "5px 10px",
    fontSize: 12,
    border: `1px solid ${THEME.colors.border}`,
    borderRadius: THEME.radius.sm,
    background: THEME.colors.bgWhite,
    color: THEME.colors.textPrimary,
    cursor: "pointer",
  };
}
