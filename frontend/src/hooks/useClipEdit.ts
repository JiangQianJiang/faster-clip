import { useEffect, useState, useRef, useCallback, useReducer } from "react";
import type { TranscriptSegment } from "../api/client";
import {
  getTranscript,
  patchTranscript,
  fetchClipSubtitles,
  type TranscriptAfterSave,
} from "../api/client";
import {
  initialEditingState,
  editingReducer,
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

type Mode = "preview" | "edit";

export interface UseClipEditParams {

  index: number;
  taskId: string;
  onSaved?: () => void;
  onClose: () => void;
  videoRef: React.RefObject<HTMLVideoElement>;
  settings: { llmApiKey: string };

  segments: TranscriptSegment[];
  setSegments: React.Dispatch<React.SetStateAction<TranscriptSegment[]>>;
}
export function useClipEdit({
  index,
  taskId,
  onSaved,
  onClose,
  videoRef,
  settings,
  segments,
  setSegments,
}: UseClipEditParams) {
  // ── Edit mode state ──────────────────────────────────────────────
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
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
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

  // ── Time conversion helpers ──────────────────────────────────────
  const toLocal = (absolute: number) => {
    if (!clipWindow) return absolute;
    return Math.max(0, Math.min(clipWindow.end - clipWindow.start, absolute - clipWindow.start));
  };
  const toAbsolute = (local: number) => {
    if (!clipWindow) return local;
    return clipWindow.start + local;
  };

  // ── Derived ──────────────────────────────────────────────────────
  const dirty = editingState.past.length > 0;

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

  const displaySegments = mode === "edit"
    ? [...boundarySegments, ...editingState.present].sort((a, b) => (
      a.start_time_s === b.start_time_s
        ? a.end_time_s - b.end_time_s
        : a.start_time_s - b.start_time_s
    ))
    : segments;

  // ── syncSubtitle callback ────────────────────────────────────────
  const syncSubtitle = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const localTime = video.currentTime;
    if (mode === "preview") {
      setCurrentTime(localTime);
      setCurrentIndex(
        segments.length === 0 ? -1 : binarySearch(segments, localTime),
      );
    } else {
      const absTime = toAbsolute(localTime);
      setCurrentTime(absTime);
      setCurrentIndex(
        editingState.present.length === 0
          ? -1
          : binarySearch(editingState.present as TranscriptSegment[], absTime),
      );
    }
  }, [segments, mode, editingState.present, toAbsolute, videoRef]);

  // ── Escape key ───────────────────────────────────────────────────
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
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose, mode, dirty]);

  // ── Keyboard shortcuts for edit mode ─────────────────────────────
  useEffect(() => {
    if (mode !== "edit") return;
    const onKey = (e: KeyboardEvent) => {
      if (editingId) return;
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

  // ── Enter / exit edit mode ───────────────────────────────────────
  const enterEditMode = async () => {
    try {
      setTranscriptLoadError(false);
      setServerIssues([]);
      const transcript = await getTranscript(taskId);
      setFullTranscript(transcript.segments);
      if (transcript.transcript_version !== undefined) {
        setBaseTranscriptVersion(transcript.transcript_version);
      }

      if (!clipWindow) return;
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

  // ── Segment selection / drag ─────────────────────────────────────
  const selectSegment = (id: string, seek: boolean) => {
    setSelectedId(id);
    dragSnapshotRef.current = editingState.present.map((s) => ({ ...s }));
    if (seek && videoRef.current) {
      const seg = editingState.present.find((s) => s.id === id);
      if (seg) {
        videoRef.current.currentTime = toLocal(seg.start_time_s);
        if (isPlaying) videoRef.current.play();
      }
    }
  };

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

  // ── Save flow ────────────────────────────────────────────────────
  const handleSave = async (): Promise<boolean> => {
    if (localIssues.size > 0) {
      setSaveError("存在重叠或非法时长，请修正后再保存。");
      return false;
    }
    if (!clipWindow) return false;

    let llmApiKey: string | undefined;
    if (afterSaveAction === "reanalyze") {
      llmApiKey = settings.llmApiKey.trim() || undefined;
      if (!llmApiKey) {
        setSaveError("未配置 LLM API Key。请在侧边栏底部配置后重试。");
        return false;
      }
    }

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
      const result = await patchTranscript(taskId, merged, afterSaveAction, baseTranscriptVersion, llmApiKey);
      if (result.transcript_version !== undefined) {
        setBaseTranscriptVersion(result.transcript_version);
      }
      setSaving(false);
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

  // ── Dirty exit handlers ──────────────────────────────────────────
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

  // ── Close with dirty check ───────────────────────────────────────
  const requestClose = () => {
    if (mode === "edit" && dirty) {
      setExitDialog("close");
    } else {
      onClose();
    }
  };

  // ── Video ended handler ──────────────────────────────────────────
  const handleVideoEnded = () => {
    if (mode === "edit") {
      const last = editingState.present[editingState.present.length - 1];
      if (last) setSelectedId(last.id);
    } else if (segments.length > 0) {
      setCurrentIndex(segments.length - 1);
    }
  };

  return {
    // State
    mode,
    setMode,
    fullTranscript,
    setFullTranscript,
    boundarySegments,
    setBoundarySegments,
    clipWindow,
    setClipWindow,
    editingState,
    dispatch,
    editDispatch,
    selectedId,
    setSelectedId,
    editingId,
    setEditingId,
    currentTime,
    setCurrentTime,
    currentIndex,
    setCurrentIndex,
    isPlaying,
    setIsPlaying,
    saveError,
    setSaveError,
    saving,
    setSaving,
    afterSaveAction,
    setAfterSaveAction,
    exitDialog,
    setExitDialog,
    transcriptLoadError,
    setTranscriptLoadError,
    baseTranscriptVersion,
    serverIssues,
    // Derived
    dirty,
    localIssues,
    displayIssues,
    displaySegments,
    // Refs
    dragSnapshotRef,
    // Handlers
    enterEditMode,
    exitEditMode,
    handleSave,
    handleExitDialogSave,
    handleExitDialogDiscard,
    handleExitDialogCancel,
    selectSegment,
    previewMove,
    previewResize,
    commitDragSnapshot,
    requestClose,
    syncSubtitle,
    handleVideoEnded,
    // Helpers
    toLocal,
    toAbsolute,
  };
}
