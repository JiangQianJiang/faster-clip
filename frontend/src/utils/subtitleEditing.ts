import { generateUUID } from "./uuid";

export interface EditableSubtitleSegment {
  id: string;
  start_time_s: number;
  end_time_s: number;
  text: string;
  /** ASR confidence score in [0, 1], or null when unavailable or after editing. */
  confidence?: number | null;
  words?: SubtitleWordTiming[] | null;
}

export interface SubtitleWordTiming {
  text: string;
  start_time_s: number;
  end_time_s: number;
}

/** Confidence visualisation thresholds — shared constants, not magic numbers. */
export const CONFIDENCE = {
  HIGH: 0.7,
  LOW: 0.4,
} as const;

export type SegmentIssue = "重叠" | "非法时长" | "校验错误";

export interface TranscriptSegmentLike {
  start_time_s: number;
  end_time_s: number;
}

/** Binary search over sorted subtitle segments. Returns the index of the segment
 *  whose time range contains `currentTime`, or -1 if no segment matches.
 *  O(log n). Segments must be sorted by start_time_s ascending. */
export function binarySearch(segments: TranscriptSegmentLike[], currentTime: number): number {
  let lo = 0;
  let hi = segments.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const seg = segments[mid];
    if (currentTime >= seg.start_time_s && currentTime < seg.end_time_s) return mid;
    if (currentTime < seg.start_time_s) hi = mid - 1;
    else lo = mid + 1;
  }
  return -1;
}

export interface EditingState {
  past: EditableSubtitleSegment[][];
  present: EditableSubtitleSegment[];
  future: EditableSubtitleSegment[][];
}

export type EditingAction =
  | { type: "SET_TEXT"; id: string; text: string }
  | { type: "ADD_SEGMENT"; playhead: number; fps: number; videoDuration?: number }
  | { type: "ADD_SEGMENT_CLIP_WINDOW"; playhead: number; fps: number; clipStart: number; clipEnd: number }
  | { type: "DELETE_SEGMENT"; id: string }
  | { type: "SPLIT_SEGMENT"; id: string; playhead: number; fps: number }
  | { type: "MOVE_SEGMENT"; id: string; delta: number; fps: number; videoDuration: number }
  | { type: "MOVE_SEGMENT_CLIP_WINDOW"; id: string; delta: number; fps: number; clipStart: number; clipEnd: number }
  | { type: "RESIZE_SEGMENT"; id: string; edge: "start" | "end"; time: number; fps: number; videoDuration: number }
  | { type: "RESIZE_SEGMENT_CLIP_WINDOW"; id: string; edge: "start" | "end"; time: number; fps: number; clipStart: number; clipEnd: number }
  | { type: "PREVIEW_REPLACE"; segments: EditableSubtitleSegment[] }
  | { type: "COMMIT_DRAG"; snapshot: EditableSubtitleSegment[]; present: EditableSubtitleSegment[] }
  | { type: "REPLACE"; segments: EditableSubtitleSegment[] }
  | { type: "RESET"; segments: EditableSubtitleSegment[] }
  | { type: "UNDO" }
  | { type: "REDO" };

let nextId = 1;

export function snapToFrame(seconds: number, fps: number): number {
  if (!Number.isFinite(seconds) || seconds < 0) return 0;
  if (!Number.isFinite(fps) || fps <= 0) return roundSeconds(seconds);
  const frameDuration = 1 / fps;
  return roundSeconds(Math.round(seconds / frameDuration) * frameDuration);
}

export function initialEditingState(segments: EditableSubtitleSegment[]): EditingState {
  return { past: [], present: cloneSegments(segments), future: [] };
}

export function updateSegmentText(id: string, text: string): EditingAction {
  return { type: "SET_TEXT", id, text };
}

export function deleteSegment(id: string): EditingAction {
  return { type: "DELETE_SEGMENT", id };
}

export function editingReducer(state: EditingState, action: EditingAction): EditingState {
  if (action.type === "UNDO") {
    const previous = state.past[state.past.length - 1];
    if (!previous) return state;
    return {
      past: state.past.slice(0, -1),
      present: cloneSegments(previous),
      future: [cloneSegments(state.present), ...state.future],
    };
  }

  if (action.type === "REDO") {
    const next = state.future[0];
    if (!next) return state;
    return {
      past: [...state.past, cloneSegments(state.present)],
      present: cloneSegments(next),
      future: state.future.slice(1),
    };
  }

  if (action.type === "RESET") {
    return initialEditingState(action.segments);
  }

  if (action.type === "PREVIEW_REPLACE") {
    return { ...state, present: cloneSegments(action.segments) };
  }

  if (action.type === "COMMIT_DRAG") {
    if (sameSegments(action.snapshot, action.present)) return state;
    // Clear confidence on segments whose timing changed during drag.
    const present = action.present.map((seg) => {
      const snap = action.snapshot.find((s) => s.id === seg.id);
      if (snap && (snap.start_time_s !== seg.start_time_s || snap.end_time_s !== seg.end_time_s)) {
        return { ...seg, confidence: null };
      }
      return seg;
    });
    // Trim past to prevent unbounded growth (keep last 199 entries)
    const past = state.past.length >= 200 ? state.past.slice(-199) : state.past;
    return {
      past: [...past, cloneSegments(action.snapshot)],
      present: present,
      future: [],
    };
  }

  const nextPresent = applyEdit(state.present, action);
  if (sameSegments(state.present, nextPresent)) return state;
  return {
    past: [...state.past, cloneSegments(state.present)],
    present: nextPresent,
    future: [],
  };
}

export function addSegmentAtPlayhead(
  segments: EditableSubtitleSegment[],
  playhead: number,
  fps: number,
  videoDuration = Number.POSITIVE_INFINITY,
): EditableSubtitleSegment[] {
  const start = clamp(snapToFrame(playhead, fps), 0, videoDuration);
  const end = clamp(snapToFrame(start + 3, fps), start, videoDuration);
  return sortSegments([
    ...cloneSegments(segments),
    { id: createSegmentId(), start_time_s: start, end_time_s: end, text: "", confidence: null },
  ]);
}

export function addSegmentAtPlayheadClipWindow(
  segments: EditableSubtitleSegment[],
  playhead: number,
  fps: number,
  clipStart: number,
  clipEnd: number,
): EditableSubtitleSegment[] {
  if (playhead < clipStart || playhead > clipEnd) return cloneSegments(segments);
  const start = clamp(snapToFrame(playhead, fps), clipStart, clipEnd);
  const minDuration = frameDuration(fps);
  const end = clamp(snapToFrame(start + 3, fps), roundSeconds(start + minDuration), clipEnd);
  if (end <= start) return cloneSegments(segments);
  return sortSegments([
    ...cloneSegments(segments),
    { id: createSegmentId(), start_time_s: start, end_time_s: end, text: "", confidence: null },
  ]);
}

export function splitSegmentAtPlayhead(
  segments: EditableSubtitleSegment[],
  id: string,
  playhead: number,
  fps: number,
): EditableSubtitleSegment[] | null {
  const target = segments.find((segment) => segment.id === id);
  if (!target) return null;
  const splitAt = snapToFrame(playhead, fps);
  if (splitAt <= target.start_time_s || splitAt >= target.end_time_s) return null;

  const result = segments.flatMap((segment) => {
    if (segment.id !== id) return [{ ...segment }];
    return [
      { ...segment, end_time_s: splitAt, confidence: null },
      { ...segment, id: createSegmentId(), start_time_s: splitAt, confidence: null },
    ];
  });
  return sortSegments(result);
}

export function moveSegment(
  segments: EditableSubtitleSegment[],
  id: string,
  delta: number,
  fps: number,
  videoDuration: number,
): EditableSubtitleSegment[] {
  return sortSegments(segments.map((segment) => {
    if (segment.id !== id) return { ...segment };
    const duration = segment.end_time_s - segment.start_time_s;
    const start = clamp(snapToFrame(segment.start_time_s + delta, fps), 0, Math.max(0, videoDuration - duration));
    const end = roundSeconds(start + duration);
    const timingChanged = start !== segment.start_time_s || end !== segment.end_time_s;
    return {
      ...segment,
      start_time_s: start,
      end_time_s: end,
      ...(timingChanged ? { confidence: null } : {}),
    };
  }));
}

export function resizeSegment(
  segments: EditableSubtitleSegment[],
  id: string,
  edge: "start" | "end",
  time: number,
  fps: number,
  videoDuration: number,
): EditableSubtitleSegment[] {
  return sortSegments(segments.map((segment) => {
    if (segment.id !== id) return { ...segment };
    const snapped = clamp(snapToFrame(time, fps), 0, videoDuration);
    if (edge === "start") {
      const timingChanged = snapped !== segment.start_time_s;
      return { ...segment, start_time_s: snapped, ...(timingChanged ? { confidence: null } : {}) };
    }
    const timingChanged = snapped !== segment.end_time_s;
    return { ...segment, end_time_s: snapped, ...(timingChanged ? { confidence: null } : {}) };
  }));
}

export function detectSegmentIssues(
  segments: EditableSubtitleSegment[],
): Map<string, SegmentIssue[]> {
  const issues = new Map<string, SegmentIssue[]>();
  const addIssue = (id: string, issue: SegmentIssue) => {
    const current = issues.get(id) || [];
    if (!current.includes(issue)) current.push(issue);
    issues.set(id, current);
  };

  for (const segment of segments) {
    if (segment.end_time_s <= segment.start_time_s) {
      addIssue(segment.id, "非法时长");
    }
  }

  const sorted = sortSegments(segments).filter((segment) => segment.end_time_s > segment.start_time_s);
  for (let i = 1; i < sorted.length; i += 1) {
    const previous = sorted[i - 1];
    const current = sorted[i];
    if (current.start_time_s < previous.end_time_s) {
      addIssue(previous.id, "重叠");
      addIssue(current.id, "重叠");
    }
  }

  return issues;
}

export function arrangeTrackRows(segments: EditableSubtitleSegment[]): Map<string, number> {
  const rows: number[] = [];
  const result = new Map<string, number>();
  for (const segment of sortSegments(segments)) {
    let row = rows.findIndex((end) => segment.start_time_s >= end);
    if (row === -1) {
      row = rows.length;
      rows.push(segment.end_time_s);
    } else {
      rows[row] = segment.end_time_s;
    }
    result.set(segment.id, row);
  }
  return result;
}

// Predicate: segment is fully inside the clip window.
// Used by merge to determine which segments are replaced by edits.
// Boundary-crossing segments (partially overlapping) are preserved as-is.
export function isInsideClipWindow(
  segment: { start_time_s: number; end_time_s: number },
  clipStart: number,
  clipEnd: number,
): boolean {
  return segment.start_time_s >= clipStart && segment.end_time_s <= clipEnd;
}

export function mergeClipEditsToTranscript(
  fullTranscript: { start_time_s: number; end_time_s: number; text: string; confidence?: number | null; words?: SubtitleWordTiming[] | null }[],
  clipStart: number,
  clipEnd: number,
  editedSegments: EditableSubtitleSegment[],
): { start_time_s: number; end_time_s: number; text: string; confidence?: number | null; words?: SubtitleWordTiming[] | null }[] {
  const outside = fullTranscript
    .filter((s) => !isInsideClipWindow(s, clipStart, clipEnd))
    .map(({ start_time_s, end_time_s, text, confidence, words }) => {
      const entry: { start_time_s: number; end_time_s: number; text: string; confidence?: number | null; words?: SubtitleWordTiming[] | null } = {
        start_time_s: roundSeconds(start_time_s),
        end_time_s: roundSeconds(end_time_s),
        text,
      };
      if (confidence !== undefined) {
        entry.confidence = confidence;
      }
      if (words !== undefined) {
        entry.words = cloneWords(words);
      }
      return entry;
    });
  const editedPayload = editedSegments
    .filter((segment) => isInsideClipWindow(segment, clipStart, clipEnd))
    .map(({ start_time_s, end_time_s, text, confidence, words }) => {
      const entry: { start_time_s: number; end_time_s: number; text: string; confidence?: number | null; words?: SubtitleWordTiming[] | null } = {
        start_time_s: roundSeconds(start_time_s),
        end_time_s: roundSeconds(end_time_s),
        text,
      };
      if (confidence !== undefined) {
        entry.confidence = confidence;
      }
      if (words !== undefined) {
        entry.words = cloneWords(words);
      }
      return entry;
    });
  const merged = [...outside, ...editedPayload];
  merged.sort((a, b) =>
    a.start_time_s === b.start_time_s
      ? a.end_time_s - b.end_time_s
      : a.start_time_s - b.start_time_s,
  );
  return merged;
}

export function moveSegmentClipWindow(
  segments: EditableSubtitleSegment[],
  id: string,
  delta: number,
  fps: number,
  clipStart: number,
  clipEnd: number,
): EditableSubtitleSegment[] {
  return sortSegments(segments.map((segment) => {
    if (segment.id !== id) return { ...segment };
    const duration = segment.end_time_s - segment.start_time_s;
    const start = clamp(
      snapToFrame(segment.start_time_s + delta, fps),
      clipStart,
      Math.max(clipStart, clipEnd - duration),
    );
    const end = roundSeconds(start + duration);
    const timingChanged = start !== segment.start_time_s || end !== segment.end_time_s;
    return {
      ...segment,
      start_time_s: start,
      end_time_s: end,
      ...(timingChanged ? { confidence: null } : {}),
    };
  }));
}

export function resizeSegmentClipWindow(
  segments: EditableSubtitleSegment[],
  id: string,
  edge: "start" | "end",
  time: number,
  fps: number,
  clipStart: number,
  clipEnd: number,
): EditableSubtitleSegment[] {
  const minDuration = frameDuration(fps);
  return sortSegments(segments.map((segment) => {
    if (segment.id !== id) return { ...segment };
    const snapped = clamp(snapToFrame(time, fps), clipStart, clipEnd);
    if (edge === "start") {
      const newStart = Math.min(snapped, roundSeconds(segment.end_time_s - minDuration));
      const timingChanged = newStart !== segment.start_time_s;
      return {
        ...segment,
        start_time_s: newStart,
        ...(timingChanged ? { confidence: null } : {}),
      };
    }
    const newEnd = Math.max(snapped, roundSeconds(segment.start_time_s + minDuration));
    const timingChanged = newEnd !== segment.end_time_s;
    return {
      ...segment,
      end_time_s: newEnd,
      ...(timingChanged ? { confidence: null } : {}),
    };
  }));
}

export function toTranscriptPayload(segments: EditableSubtitleSegment[]) {
  return sortSegments(segments).map(({ id: _id, start_time_s, end_time_s, text, confidence, words }) => {
    const entry: { start_time_s: number; end_time_s: number; text: string; confidence?: number | null; words?: SubtitleWordTiming[] | null } = {
      start_time_s,
      end_time_s,
      text,
    };
    if (confidence !== undefined) {
      entry.confidence = confidence;
    }
    if (words !== undefined) {
      entry.words = cloneWords(words);
    }
    return entry;
  });
}

function applyEdit(segments: EditableSubtitleSegment[], action: EditingAction): EditableSubtitleSegment[] {
  switch (action.type) {
    case "SET_TEXT":
      return segments.map((segment) => (
        segment.id === action.id ? { ...segment, text: action.text, confidence: null } : { ...segment }
      ));
    case "ADD_SEGMENT":
      return addSegmentAtPlayhead(segments, action.playhead, action.fps, action.videoDuration);
    case "ADD_SEGMENT_CLIP_WINDOW":
      return addSegmentAtPlayheadClipWindow(
        segments,
        action.playhead,
        action.fps,
        action.clipStart,
        action.clipEnd,
      );
    case "DELETE_SEGMENT":
      return segments.filter((segment) => segment.id !== action.id).map((segment) => ({ ...segment }));
    case "SPLIT_SEGMENT":
      return splitSegmentAtPlayhead(segments, action.id, action.playhead, action.fps) || cloneSegments(segments);
    case "MOVE_SEGMENT":
      return moveSegment(segments, action.id, action.delta, action.fps, action.videoDuration);
    case "MOVE_SEGMENT_CLIP_WINDOW":
      return moveSegmentClipWindow(
        segments,
        action.id,
        action.delta,
        action.fps,
        action.clipStart,
        action.clipEnd,
      );
    case "RESIZE_SEGMENT":
      return resizeSegment(segments, action.id, action.edge, action.time, action.fps, action.videoDuration);
    case "RESIZE_SEGMENT_CLIP_WINDOW":
      return resizeSegmentClipWindow(
        segments,
        action.id,
        action.edge,
        action.time,
        action.fps,
        action.clipStart,
        action.clipEnd,
      );
    case "REPLACE":
      return cloneSegments(action.segments);
    default:
      return cloneSegments(segments);
  }
}

function createSegmentId(): string {
  try {
    return generateUUID();
  } catch {
    nextId += 1;
    return `segment-${nextId}`;
  }
}

function cloneSegments(segments: EditableSubtitleSegment[]): EditableSubtitleSegment[] {
  return segments.map((segment) => ({ ...segment, words: cloneWords(segment.words) }));
}

function cloneWords(words: SubtitleWordTiming[] | null | undefined): SubtitleWordTiming[] | null | undefined {
  if (words === undefined || words === null) return words;
  return words.map((word) => ({ ...word }));
}

function sortSegments(segments: EditableSubtitleSegment[]): EditableSubtitleSegment[] {
  return cloneSegments(segments).sort((a, b) => (
    a.start_time_s === b.start_time_s
      ? a.end_time_s - b.end_time_s
      : a.start_time_s - b.start_time_s
  ));
}

function sameSegments(a: EditableSubtitleSegment[], b: EditableSubtitleSegment[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export type ServerValidationIssue = { editableId: string; label: SegmentIssue };

export interface MergeRow {
  start_time_s: number;
  end_time_s: number;
  text: string;
  source: "editable" | "locked";
  id?: string;
}

export function buildMergeRowList(
  fullTranscript: { start_time_s: number; end_time_s: number; text: string }[],
  clipStart: number,
  clipEnd: number,
  editableSegments: EditableSubtitleSegment[],
): MergeRow[] {
  const outside = fullTranscript.filter(
    (s) => !(s.start_time_s >= clipStart && s.end_time_s <= clipEnd),
  );
  const rows: MergeRow[] = [
    ...outside.map((s) => ({ ...s, source: "locked" as const })),
    ...editableSegments.map((s) => ({
      start_time_s: s.start_time_s,
      end_time_s: s.end_time_s,
      text: s.text,
      source: "editable" as const,
      id: s.id,
    })),
  ];
  rows.sort((a, b) =>
    a.start_time_s === b.start_time_s ? a.end_time_s - b.end_time_s : a.start_time_s - b.start_time_s,
  );
  return rows;
}

export function parseServerValidationErrors(
  detail: string,
  mergeRows: MergeRow[],
): ServerValidationIssue[] {
  const result: ServerValidationIssue[] = [];
  const seen = new Set<string>();
  for (const m of detail.matchAll(/invalid segment at index (\d+)/g)) {
    const idx = parseInt(m[1], 10);
    if (idx < 0 || idx >= mergeRows.length) continue;
    const row = mergeRows[idx];
    if (row.source === "editable" && row.id && !seen.has(row.id)) {
      seen.add(row.id);
      result.push({ editableId: row.id, label: "校验错误" });
    }
  }
  const overlapMatch = detail.match(/segments overlap at index (\d+) and (\d+)/);
  if (overlapMatch) {
    for (const idxStr of [overlapMatch[1], overlapMatch[2]]) {
      const idx = parseInt(idxStr, 10);
      if (idx < 0 || idx >= mergeRows.length) continue;
      const row = mergeRows[idx];
      if (row.source === "editable" && row.id && !seen.has(row.id)) {
        seen.add(row.id);
        result.push({ editableId: row.id, label: "重叠" });
      }
    }
  }
  return result;
}

function roundSeconds(seconds: number): number {
  return Math.round(seconds * 1000) / 1000;
}

function frameDuration(fps: number): number {
  if (!Number.isFinite(fps) || fps <= 0) return 0.001;
  return roundSeconds(1 / fps);
}
