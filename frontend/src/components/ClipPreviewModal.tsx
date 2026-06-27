import { useEffect, useState, useRef, useCallback, useReducer } from "react";
import type { Clip, TranscriptSegment } from "../api/client";
import {
  getClipSubtitleUrl,
  fetchClipSubtitles,
  getTranscript,
  patchTranscript,
  type TranscriptAfterSave,
} from "../api/client";
import { authBlobUrl, getAccessToken } from "../auth";
import ClipSubtitleTrack from "./ClipSubtitleTrack";
import { THEME } from "../theme";
import VideoPlayer from "./VideoPlayer";
import {
  initialEditingState,
  editingReducer,
  updateSegmentText,
  deleteSegment,
  detectSegmentIssues,
  mergeClipEditsToTranscript,
  moveSegmentClipWindow,
  resizeSegmentClipWindow,
  isInsideClipWindow,
  parseServerValidationErrors,
  buildMergeRowList,
  binarySearch,
  type EditableSubtitleSegment,
  type ServerValidationIssue,
  type SegmentIssue,
} from "../utils/subtitleEditing";
import { clipDisplayLabel, clipDownloadFilename } from "../utils/clipNumbering";

interface Props {
  clip: Clip;
  index: number;
  taskId: string;
  onSaved?: () => void;
  onClose: () => void;
}

type Mode = "preview" | "edit";

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

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function buildClipPreviewVideoUrl(
  taskId: string,
  clipIndex: number,
  token: string | null,
): string {
  const params = new URLSearchParams();
  params.set("inline", "true");
  if (token) params.set("token", token);
  return `/api/tasks/${taskId}/clips/${clipIndex}/download?${params.toString()}`;
}

export function mediaErrorMessage(code: number | undefined): string {
  if (code === 4) {
    return "当前浏览器不支持该视频编码，请尝试下载后查看或使用 Chrome/Safari。";
  }
  if (code === 2) {
    return "视频加载失败，请检查网络后重试。";
  }
  if (code === 3) {
    return "视频解码失败，请尝试下载后查看。";
  }
  return "视频无法播放，请尝试下载后查看。";
}

export default function ClipPreviewModal({
  clip,
  index,
  taskId,
  onSaved,
  onClose,
}: Props) {
  // Shared state
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [subMenuOpen, setSubMenuOpen] = useState(false);
  const [videoHeight, setVideoHeight] = useState(0);

  // Edit mode state
  const [mode, setMode] = useState<Mode>("preview");
  const [fullTranscript, setFullTranscript] = useState<TranscriptSegment[]>([]);
  const [boundarySegments, setBoundarySegments] = useState<EditableSubtitleSegment[]>([]);
  const [clipWindow, setClipWindow] = useState<{ start: number; end: number } | null>(null);
  const [editingState, dispatch] = useReducer(
    editingReducer,
    [],
    () => initialEditingState([]),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [afterSaveAction, setAfterSaveAction] =
    useState<TranscriptAfterSave>("save_only");
  const [exitDialog, setExitDialog] = useState<"exit" | "close" | null>(null);
  const [transcriptLoadError, setTranscriptLoadError] = useState(false);
  const [baseTranscriptVersion, setBaseTranscriptVersion] = useState<number | undefined>(
    undefined,
  );
  const [serverIssues, setServerIssues] = useState<ServerValidationIssue[]>([]);

  const editDispatch = (action: Parameters<typeof dispatch>[0]) => {
    setServerIssues([]);
    dispatch(action);
  };

  const dragSnapshotRef = useRef<EditableSubtitleSegment[]>([]);

  const videoRef = useRef<HTMLVideoElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);
  const subMenuRef = useRef<HTMLDivElement>(null);

  const videoUrl = buildClipPreviewVideoUrl(taskId, index, getAccessToken());

  // Time conversion: video uses local clip time (0 = clip start), editing uses absolute transcript time
  const toLocal = (absolute: number) => {
    if (!clipWindow) return absolute;
    return Math.max(0, Math.min(clipWindow.end - clipWindow.start, absolute - clipWindow.start));
  };
  const toAbsolute = (local: number) => {
    if (!clipWindow) return local;
    return clipWindow.start + local;
  };

  const dirty = editingState.past.length > 0;

  // localIssues = blocking issues (overlap, bad duration, empty text); serverIssues = display-only
  const localIssues = new Map<string, SegmentIssue[]>();
  const displayIssues = new Map<string, SegmentIssue[]>();
  if (mode === "edit" && clipWindow) {
    const outside = fullTranscript.filter(
      (s) => !(s.start_time_s >= clipWindow.start && s.end_time_s <= clipWindow.end),
    );
    const editableIds = new Set(editingState.present.map((s) => s.id));
    const allForCheck: EditableSubtitleSegment[] = [
      ...outside.map((s, i) => ({ id: `locked-${i}`, ...s })),
      ...editingState.present,
    ].sort((a, b) =>
      a.start_time_s === b.start_time_s ? a.end_time_s - b.end_time_s : a.start_time_s - b.start_time_s,
    );

    for (const [id, iss] of detectSegmentIssues(allForCheck)) {
      if (editableIds.has(id)) {
        localIssues.set(id, iss);
      } else if (id.startsWith("locked-")) {
        const lockedSeg = allForCheck.find((s) => s.id === id);
        if (lockedSeg) {
          for (const es of editingState.present) {
            if (es.end_time_s > lockedSeg.start_time_s && es.start_time_s < lockedSeg.end_time_s) {
              const existing = localIssues.get(es.id) || [];
              if (!existing.includes("重叠")) existing.push("重叠");
              localIssues.set(es.id, existing);
            }
          }
        }
      }
    }
    const MAX_TEXT_LENGTH = 1000;
    for (const seg of editingState.present) {
      if (!seg.text.trim() || seg.text.trim().length > MAX_TEXT_LENGTH) {
        const existing = localIssues.get(seg.id) || [];
        if (!existing.includes("非法时长")) existing.push("非法时长");
        localIssues.set(seg.id, existing);
      }
    }
    // Copy local to display, then merge server
    for (const [id, iss] of localIssues) displayIssues.set(id, [...iss]);
    for (const si of serverIssues) {
      const existing = displayIssues.get(si.editableId) || [];
      if (!existing.includes(si.label)) existing.push(si.label);
      displayIssues.set(si.editableId, existing);
    }
  }

  // Fetch clip subtitles
  useEffect(() => {
    let cancelled = false;
    fetchClipSubtitles(taskId, index)
      .then((data) => {
        if (!cancelled) {
          setSegments(data.segments);
          setLoading(false);
          // Store clip window from response
          setClipWindow({ start: data.start_time_s, end: data.end_time_s });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [taskId, index]);

  // Escape key
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (mode === "edit" && dirty) {
          setExitDialog("close");
        } else {
          onClose();
        }
      }
    };
    // Use capture phase so shortcuts work even when focus is on scrollable children
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose, mode, dirty]);

  // Keyboard shortcuts for edit mode
  useEffect(() => {
    if (mode !== "edit") return;
    const onKey = (e: KeyboardEvent) => {
      if (editingId) return; // Don't intercept when editing text
      if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        editDispatch({ type: "UNDO" });
      } else if ((e.ctrlKey || e.metaKey) && e.key === "z" && e.shiftKey) {
        e.preventDefault();
        editDispatch({ type: "REDO" });
      } else if (e.key === "Delete" && selectedId) {
        editDispatch(deleteSegment(selectedId));
        setSelectedId(null);
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [mode, selectedId, editingId]);

  // Click outside submenu
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

  const syncSubtitle = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const localTime = video.currentTime;
    if (mode === "preview") {
      // Preview mode: clip subtitle JSON is relative to clip window, search with local time
      setCurrentTime(localTime);
      setCurrentIndex(
        segments.length === 0 ? -1 : binarySearch(segments, localTime),
      );
    } else {
      // Edit mode: convert local clip time to absolute transcript time
      const absTime = toAbsolute(localTime);
      setCurrentTime(absTime);
      setCurrentIndex(
        editingState.present.length === 0
          ? -1
          : binarySearch(editingState.present as TranscriptSegment[], absTime),
      );
    }
  }, [segments, mode, editingState.present, toAbsolute]);

  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [currentIndex, selectedId]);

  // Enter edit mode
  const enterEditMode = async () => {
    try {
      setTranscriptLoadError(false);
      setServerIssues([]);
      const transcript = await getTranscript(taskId);
      setFullTranscript(transcript.segments);
      if (transcript.transcript_version !== undefined) {
        setBaseTranscriptVersion(transcript.transcript_version);
      }

      if (!clipWindow) return; // Wait for clip subtitles to load
      const windowRange = clipWindow;
      if (windowRange) {
        const intersecting = transcript.segments.filter(
          (s) => s.start_time_s < windowRange.end && s.end_time_s > windowRange.start,
        );
        const editable: EditableSubtitleSegment[] = [];
        const boundary: EditableSubtitleSegment[] = [];
        intersecting.forEach((s, i) => {
          const segment: EditableSubtitleSegment = {
            id: `segment-${i}-${s.start_time_s}-${s.end_time_s}`,
            start_time_s: s.start_time_s,
            end_time_s: s.end_time_s,
            text: s.text,
            confidence: s.confidence,
            words: s.words,
          };
          if (isInsideClipWindow(s, windowRange.start, windowRange.end)) {
            editable.push(segment);
          } else {
            boundary.push(segment);
          }
        });
        setBoundarySegments(boundary);
        dispatch({ type: "RESET", segments: editable });
        setSelectedId(editable[0]?.id || null);
      }
      setMode("edit");
    } catch {
      setTranscriptLoadError(true);
    }
  };

  const exitEditMode = () => {
    if (dirty) {
      setExitDialog("exit");
    } else {
      setMode("preview");
      setSelectedId(null);
      setEditingId(null);
    }
  };

  const handleLoadedMetadata = () => {
    if (videoRef.current) setVideoHeight(videoRef.current.clientHeight);
    setIsPlaying(!videoRef.current?.paused);
  };

  const handleSubDownload = async (format: string) => {
    setSubMenuOpen(false);
    try {
      const url = await authBlobUrl(getClipSubtitleUrl(taskId, index, format));
      const a = document.createElement("a");
      a.href = url;
      a.download = clipDownloadFilename(index, format);
      a.click();
    } catch {
      // silently fail
    }
  };

  const handleVideoDownload = () => {
    const a = document.createElement("a");
    a.href = `/api/tasks/${taskId}/clips/${index}/download?token=${encodeURIComponent(getAccessToken() || "")}`;
    a.download = clipDownloadFilename(index, "mp4");
    a.click();
  };

  // Select subtitle and navigate video (seek uses local clip time)
  const selectSegment = (id: string, seek: boolean) => {
    setSelectedId(id);
    // Save pre-drag snapshot for coalesced undo
    dragSnapshotRef.current = editingState.present.map((s) => ({ ...s }));
    if (seek && videoRef.current) {
      const seg = editingState.present.find((s) => s.id === id);
      if (seg) {
        videoRef.current.currentTime = toLocal(seg.start_time_s);
        if (isPlaying) videoRef.current.play();
      }
    }
  };

  // Drag handlers — live preview without undo history
  const commitDragSnapshot = () => {
    if (dragSnapshotRef.current.length === 0) return;
    dispatch({
      type: "COMMIT_DRAG",
      snapshot: dragSnapshotRef.current,
      present: editingState.present,
    });
    dragSnapshotRef.current = [];
  };

  const previewMove = (id: string, delta: number) => {
    if (!clipWindow) return;
    const moved = moveSegmentClipWindow(
      editingState.present,
      id,
      delta,
      0,
      clipWindow.start,
      clipWindow.end,
    );
    dispatch({ type: "PREVIEW_REPLACE", segments: moved });
  };

  const previewResize = (id: string, edge: "start" | "end", time: number) => {
    if (!clipWindow) return;
    const resized = resizeSegmentClipWindow(
      editingState.present,
      id,
      edge,
      time,
      0,
      clipWindow.start,
      clipWindow.end,
    );
    dispatch({ type: "PREVIEW_REPLACE", segments: resized });
  };

  // Save flow
  const handleSave = async (): Promise<boolean> => {
    if (localIssues.size > 0) {
      setSaveError("存在重叠或非法时长，请修正后再保存。");
      return false;
    }
    if (!clipWindow) return false;

    setSaving(true);
    setSaveError(null);
    setServerIssues([]);
    try {
      const merged = mergeClipEditsToTranscript(
        fullTranscript,
        clipWindow.start,
        clipWindow.end,
        editingState.present,
      );
      const result = await patchTranscript(taskId, merged, afterSaveAction, baseTranscriptVersion);
      if (result.transcript_version !== undefined) {
        setBaseTranscriptVersion(result.transcript_version);
      }
      setSaving(false);
      // Refresh clip subtitles and transcript for preview mode
      try {
        const freshSubtitles = await fetchClipSubtitles(taskId, index);
        setSegments(freshSubtitles.segments);
        const freshTranscript = await getTranscript(taskId);
        setFullTranscript(freshTranscript.segments);
        if (freshTranscript.transcript_version !== undefined) {
          setBaseTranscriptVersion(freshTranscript.transcript_version);
        }
      } catch {
        // Preview refresh is best-effort; don't block save success
      }
      dispatch({ type: "RESET", segments: editingState.present });
      setBoundarySegments([]);
      setMode("preview");
      setSelectedId(null);
      setEditingId(null);
      onSaved?.();
      return true;
    } catch (err: unknown) {
      setSaving(false);
      const e = err as Error & { status?: number; detail?: string };
      if (e.status === 409) {
        setSaveError("409:conflict");
      } else if (e.status === 422) {
        setSaveError(e.detail || e.message || "保存失败：数据校验未通过");
        const mergeRows = buildMergeRowList(
          fullTranscript,
          clipWindow.start,
          clipWindow.end,
          editingState.present,
        );
        const parsed = parseServerValidationErrors(
          e.detail || e.message || "",
          mergeRows,
        );
        setServerIssues(parsed);
      } else {
        setSaveError(e.message || "保存失败");
      }
      return false;
    }
  };

  // Dirty exit handlers
  const handleExitDialogSave = async () => {
    const target = exitDialog;
    setExitDialog(null);
    const saved = await handleSave();
    if (!saved) return;
    if (target === "close") onClose();
  };

  const handleExitDialogDiscard = () => {
    const target = exitDialog;
    setExitDialog(null);
    if (target === "close") {
      onClose();
      return;
    }
    setMode("preview");
    setSelectedId(null);
    setEditingId(null);
    setBoundarySegments([]);
    dispatch({ type: "RESET", segments: [] });
  };

  const handleExitDialogCancel = () => {
    setExitDialog(null);
  };

  // Close with dirty check
  const requestClose = () => {
    if (mode === "edit" && dirty) {
      setExitDialog("close");
    } else {
      onClose();
    }
  };

  const displaySegments = mode === "edit"
    ? [...boundarySegments, ...editingState.present].sort((a, b) => (
      a.start_time_s === b.start_time_s
        ? a.end_time_s - b.end_time_s
        : a.start_time_s - b.start_time_s
    ))
    : segments;

  return (
    <div
      onClick={requestClose}
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
      {/* Dirty exit dialog */}
      {exitDialog && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 2000,
            background: "rgba(0,0,0,0.3)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff",
              borderRadius: 10,
              padding: 24,
              boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
              minWidth: 300,
            }}
          >
            <p style={{ margin: "0 0 16px", fontSize: 14, color: THEME.colors.textPrimary }}>
              有未保存的修改，是否保存？
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={handleExitDialogCancel} style={btnSecondary}>
                取消
              </button>
              <button onClick={handleExitDialogDiscard} style={{ ...btnSecondary, color: THEME.colors.errorText }}>
                放弃
              </button>
              <button onClick={handleExitDialogSave} style={btnPrimary}>
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
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
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ color: THEME.colors.textPrimary, fontSize: 14, fontWeight: 600 }}>
              {clipDisplayLabel(index)}
            </span>
            <span style={{ color: THEME.colors.textMuted, fontSize: 13 }}>
              {fmt(clip.export_start_time_s ?? clip.start_time_s)} – {fmt(clip.export_end_time_s ?? clip.end_time_s)}
            </span>
            <span
              style={{
                background: THEME.colors.successText,
                color: "#fff",
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: 10,
                fontWeight: 600,
              }}
            >
              {clip.score.toFixed(1)}
            </span>
            {dirty && (
              <span style={{ color: "#f59e0b", fontSize: 11 }}>未保存</span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {mode === "preview" ? (
              <>
                <button onClick={handleVideoDownload} style={btnPrimary}>
                  下载视频
                </button>
                <div style={{ position: "relative" }}>
                  <button
                    onClick={() => setSubMenuOpen(!subMenuOpen)}
                    style={btnSecondary}
                  >
                    字幕 <span style={{ fontSize: 10 }}>▼</span>
                  </button>
                  {subMenuOpen && (
                    <div
                      ref={subMenuRef}
                      style={{
                        position: "absolute",
                        top: "100%",
                        right: 0,
                        marginTop: 4,
                        background: "#fff",
                        border: "1px solid #e5e7eb",
                        borderRadius: 6,
                        boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                        zIndex: 10,
                        minWidth: 80,
                      }}
                    >
                      {SUB_FORMATS.map((f) => (
                        <button
                          key={f.value}
                          onClick={() => handleSubDownload(f.value)}
                          style={subMenuItem}
                          onMouseEnter={(e) => {
                            (e.target as HTMLElement).style.background = "#f3f4f6";
                          }}
                          onMouseLeave={(e) => {
                            (e.target as HTMLElement).style.background = "none";
                          }}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={enterEditMode}
                  disabled={loading || transcriptLoadError}
                  title={loading ? "字幕加载中..." : transcriptLoadError ? "无法加载完整字幕" : undefined}
                  style={{
                    ...btnSecondary,
                    opacity: loading || transcriptLoadError ? 0.5 : 1,
                    cursor: loading || transcriptLoadError ? "not-allowed" : "pointer",
                  }}
                >
                  编辑字幕
                </button>
              </>
            ) : (
              <>
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
              </>
            )}
            <button onClick={requestClose} style={closeBtn}>
              ✕
            </button>
          </div>
        </div>

        {/* Save error */}
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
            }}
          >
            <span style={{ flex: 1 }}>
              {saveError === "409:conflict"
                ? "字幕已被其他操作修改，请刷新后重试。"
                : saveError}
            </span>
            {saveError === "409:conflict" && (
              <button
                onClick={() => { setSaveError(null); enterEditMode(); }}
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

        {videoError && (
          <div
            style={{
              padding: "8px 16px",
              background: "#fef2f2",
              color: THEME.colors.errorText,
              fontSize: 12,
              borderBottom: "1px solid #fecaca",
            }}
          >
            {videoError}
          </div>
        )}

        {/* Body */}
        <div style={{ display: "flex", flex: 1, minHeight: 0, flexDirection: "column" }}>
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
                src={videoUrl}
                autoPlay
                activeText={
                  mode === "edit"
                    ? (currentIndex >= 0 ? editingState.present[currentIndex]?.text ?? "" : "")
                    : (currentIndex >= 0 ? segments[currentIndex]?.text ?? "" : "")
                }
                onTimeUpdate={syncSubtitle}
                onLoadedMetadata={handleLoadedMetadata}
                onPlayStateChange={setIsPlaying}
                onError={(err) => setVideoError(mediaErrorMessage(err?.code))}
                onEnded={() => {
                  if (mode === "edit") {
                    const last = editingState.present[editingState.present.length - 1];
                    if (last) setSelectedId(last.id);
                  } else if (segments.length > 0) {
                    setCurrentIndex(segments.length - 1);
                  }
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
              {loading && (
                <div style={{ padding: 20, textAlign: "center", color: THEME.colors.textMuted, fontSize: 13 }}>
                  加载中...
                </div>
              )}
              {error && (
                <div style={{ padding: 20, textAlign: "center", color: THEME.colors.errorText, fontSize: 13 }}>
                  字幕加载失败
                </div>
              )}
              {!loading && !error && displaySegments.length === 0 && (
                <div style={{ padding: 20, textAlign: "center", color: THEME.colors.textMuted, fontSize: 13 }}>
                  暂无字幕
                </div>
              )}
              {displaySegments.map((seg: TranscriptSegment | EditableSubtitleSegment, i: number) => {
                const segId = "id" in seg ? seg.id : `seg-${i}`;
                const isSelected = mode === "edit" && segId === selectedId;
                const isEditing = mode === "edit" && segId === editingId;
                const isActive = mode === "preview" && i === currentIndex;
                const segIssues = mode === "edit" ? displayIssues.get(segId) || [] : [];
                const hasIssue = segIssues.length > 0;

                // Boundary check for edit mode
                const isBoundary =
                  mode === "edit" &&
                  clipWindow !== null &&
                  !isInsideClipWindow(seg, clipWindow.start, clipWindow.end);

                return (
                  <div
                    key={segId}
                    ref={(mode === "edit" ? isSelected : i === currentIndex) ? activeRef : undefined}
                    onClick={() => {
                      if (mode === "edit" && !isBoundary) {
                        selectSegment(segId, true);
                      }
                    }}
                    onDoubleClick={() => {
                      if (mode === "edit" && !isBoundary) {
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
                          : isActive
                            ? "#eff6ff"
                            : "transparent",
                      borderLeft: isSelected
                        ? "3px solid #3b82f6"
                        : isActive
                          ? "3px solid #3b82f6"
                          : "3px solid transparent",
                      cursor: mode === "edit" && !isBoundary ? "pointer" : "default",
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
                          color: isSelected || isActive ? "#3b82f6" : "#bbb",
                          fontWeight: isSelected || isActive ? 600 : 400,
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
                          color: isSelected || isActive ? "#1e40af" : "#666",
                          fontWeight: isSelected || isActive ? 500 : 400,
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

          {/* Subtitle track (edit mode only) */}
          {mode === "edit" && clipWindow && (
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
      </div>
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

const subMenuItem: React.CSSProperties = {
  display: "block",
  width: "100%",
  padding: "6px 14px",
  fontSize: THEME.fontSize.sm,
  color: THEME.colors.textPrimary,
  background: "none",
  border: "none",
  cursor: "pointer",
  textAlign: "left",
};

const closeBtn: React.CSSProperties = {
  color: THEME.colors.textMuted,
  fontSize: 18,
  cursor: "pointer",
  marginLeft: 8,
  lineHeight: 1,
  padding: "2px 6px",
  background: "none",
  border: "none",
};
