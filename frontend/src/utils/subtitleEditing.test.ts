import { describe, expect, it } from "vitest";
import {
  addSegmentAtPlayhead,
  addSegmentAtPlayheadClipWindow,
  binarySearch,
  buildMergeRowList,
  deleteSegment,
  detectSegmentIssues,
  editingReducer,
  initialEditingState,
  mergeClipEditsToTranscript,
  moveSegment,
  moveSegmentClipWindow,
  parseServerValidationErrors,
  arrangeTrackRows,
  resizeSegment,
  resizeSegmentClipWindow,
  snapToFrame,
  splitSegmentAtPlayhead,
  updateSegmentText,
  type EditableSubtitleSegment,
} from "./subtitleEditing";

const base: EditableSubtitleSegment[] = [
  { id: "a", start_time_s: 0, end_time_s: 2, text: "first" },
  { id: "b", start_time_s: 4, end_time_s: 7, text: "second" },
];

describe("subtitleEditing", () => {
  it("snaps seconds to nearest frame", () => {
    expect(snapToFrame(1.02, 25)).toBe(1.04);
    expect(snapToFrame(1.021, 0)).toBe(1.021);
  });

  it("adds a three second segment at the playhead", () => {
    const next = addSegmentAtPlayhead(base, 2.5, 25);
    expect(next).toHaveLength(3);
    expect(next[1]).toMatchObject({
      start_time_s: 2.52,
      end_time_s: 5.52,
      text: "",
    });
  });

  it("splits only when the playhead is inside a segment", () => {
    const split = splitSegmentAtPlayhead(base, "b", 5.24, 25);
    expect(split).not.toBeNull();
    expect(split?.map((s) => [s.start_time_s, s.end_time_s, s.text])).toEqual([
      [0, 2, "first"],
      [4, 5.24, "second"],
      [5.24, 7, "second"],
    ]);

    expect(splitSegmentAtPlayhead(base, "b", 7, 25)).toBeNull();
  });

  it("moves and resizes by frame while clamping to video bounds", () => {
    const moved = moveSegment(base, "a", 1.02, 25, 8);
    expect(moved[0]).toMatchObject({ start_time_s: 1.04, end_time_s: 3.04 });

    const resized = resizeSegment(base, "b", "end", 8.99, 25, 8);
    expect(resized[1].end_time_s).toBe(8);
  });

  it("detects illegal times and overlaps after sorting", () => {
    const issues = detectSegmentIssues([
      { id: "a", start_time_s: 3, end_time_s: 1, text: "bad" },
      { id: "b", start_time_s: 2, end_time_s: 4, text: "one" },
      { id: "c", start_time_s: 3, end_time_s: 5, text: "two" },
    ]);
    expect(issues.get("a")).toContain("非法时长");
    expect(issues.get("b")).toContain("重叠");
    expect(issues.get("c")).toContain("重叠");
  });

  it("arranges overlapping segments into temporary rows", () => {
    const rows = arrangeTrackRows([
      { id: "a", start_time_s: 0, end_time_s: 3, text: "a" },
      { id: "b", start_time_s: 1, end_time_s: 2, text: "b" },
      { id: "c", start_time_s: 3, end_time_s: 4, text: "c" },
    ]);
    expect(rows.get("a")).toBe(0);
    expect(rows.get("b")).toBe(1);
    expect(rows.get("c")).toBe(0);
  });

  it("keeps undo and redo history for editing actions", () => {
    let state = initialEditingState(base);
    state = editingReducer(state, updateSegmentText("a", "updated"));
    state = editingReducer(state, deleteSegment("b"));
    expect(state.present.map((s) => s.text)).toEqual(["updated"]);

    state = editingReducer(state, { type: "UNDO" });
    expect(state.present.map((s) => s.text)).toEqual(["updated", "second"]);

    state = editingReducer(state, { type: "UNDO" });
    expect(state.present.map((s) => s.text)).toEqual(["first", "second"]);

    state = editingReducer(state, { type: "REDO" });
    expect(state.present.map((s) => s.text)).toEqual(["updated", "second"]);
  });

  it("resets state without marking the editor dirty", () => {
    let state = initialEditingState([]);
    state = editingReducer(state, { type: "RESET", segments: base });
    expect(state.present).toEqual(base);
    expect(state.past).toHaveLength(0);
    expect(state.future).toHaveLength(0);
  });

  it("adds clip-window segments only when the playhead is inside the clip", () => {
    const state = initialEditingState([]);
    const outside = editingReducer(state, {
      type: "ADD_SEGMENT_CLIP_WINDOW",
      playhead: 4.5,
      fps: 25,
      clipStart: 5,
      clipEnd: 15,
    });
    expect(outside.present).toHaveLength(0);

    const inside = editingReducer(state, {
      type: "ADD_SEGMENT_CLIP_WINDOW",
      playhead: 13,
      fps: 25,
      clipStart: 5,
      clipEnd: 15,
    });
    expect(inside.present[0]).toMatchObject({ start_time_s: 13, end_time_s: 15 });
    expect(inside.past).toHaveLength(1);
  });
});

describe("mergeClipEditsToTranscript", () => {
  const full = [
    { start_time_s: 0, end_time_s: 5, text: "A" },
    { start_time_s: 5, end_time_s: 10, text: "B" },
    { start_time_s: 10, end_time_s: 15, text: "C" },
    { start_time_s: 15, end_time_s: 20, text: "D" },
  ];

  it("replaces fully-inside segments and preserves outside segments", () => {
    // edited must include ALL segments for the window, including unmodified ones
    const edited = [
      { id: "b2", start_time_s: 5.5, end_time_s: 9.5, text: "B-edited" },
      { id: "c1", start_time_s: 10, end_time_s: 15, text: "C" },
    ];
    const result = mergeClipEditsToTranscript(full, 5, 15, edited);
    const texts = result.map((s: { text: string }) => s.text);
    expect(texts).toEqual(["A", "B-edited", "C", "D"]);
  });

  it("preserves segment crossing start boundary", () => {
    // boundary-start [2, 6] crosses clipStart=5 — not fully inside, preserved
    // inside [6, 9] is fully inside, editable
    const withBoundary = [
      { start_time_s: 2, end_time_s: 6, text: "boundary-start" },
      { start_time_s: 6, end_time_s: 9, text: "inside" },
    ];
    const edited = [
      { id: "i2", start_time_s: 6, end_time_s: 9, text: "inside-edited" },
    ];
    const result = mergeClipEditsToTranscript(withBoundary, 5, 10, edited);
    expect(result).toHaveLength(2);
    expect(result[0].text).toBe("boundary-start"); // preserved
    expect(result[1].text).toBe("inside-edited");
  });

  it("preserves segment crossing end boundary", () => {
    // boundary-end [4, 11] crosses clipEnd=10 — not fully inside, preserved
    // P [0, 4] is fully inside [0, 10], so replaced
    const withBoundary = [
      { start_time_s: 0, end_time_s: 4, text: "P" },
      { start_time_s: 4, end_time_s: 11, text: "boundary-end" },
    ];
    const edited = [
      { id: "p2", start_time_s: 0, end_time_s: 4, text: "P-edited" },
    ];
    const result = mergeClipEditsToTranscript(withBoundary, 0, 10, edited);
    expect(result).toHaveLength(2);
    expect(result[0].text).toBe("P-edited");
    expect(result[1].text).toBe("boundary-end"); // preserved
  });

  it("preserves segment spanning entire clip window", () => {
    const spanning = [
      { start_time_s: 2, end_time_s: 18, text: "spans" },
    ];
    const edited: Array<{ id: string; start_time_s: number; end_time_s: number; text: string }> = [];
    const result = mergeClipEditsToTranscript(spanning, 5, 15, edited);
    expect(result).toHaveLength(1);
    expect(result[0].text).toBe("spans");
  });

  it("ignores edited payload entries that cross clip boundaries", () => {
    const withBoundary = [
      { start_time_s: 2, end_time_s: 7, text: "boundary-start" },
      { start_time_s: 8, end_time_s: 10, text: "inside" },
    ];
    const edited = [
      { id: "boundary-copy", start_time_s: 2, end_time_s: 7, text: "should-not-save" },
      { id: "inside-copy", start_time_s: 8, end_time_s: 10, text: "inside-edited" },
    ];
    const result = mergeClipEditsToTranscript(withBoundary, 5, 15, edited);
    expect(result.map((s) => s.text)).toEqual(["boundary-start", "inside-edited"]);
  });

  it("handles empty edited window (user deleted all in-window segments)", () => {
    const edited: Array<{ id: string; start_time_s: number; end_time_s: number; text: string }> = [];
    const result = mergeClipEditsToTranscript(full, 5, 10, edited);
    // B [5,10] is fully inside [5,10], removed; A, C, D outside, preserved
    expect(result.map((s: { text: string }) => s.text)).toEqual(["A", "C", "D"]);
  });

  it("handles newly added segment at exact clip boundaries", () => {
    const edited = [
      { id: "new1", start_time_s: 5, end_time_s: 7, text: "at-start" },
      { id: "new2", start_time_s: 13, end_time_s: 15, text: "at-end" },
    ];
    const result = mergeClipEditsToTranscript(full, 5, 15, edited);
    expect(result[1].text).toBe("at-start");
    expect(result[2].text).toBe("at-end");
  });

  it("preserves outside segments when all inside segments deleted", () => {
    const edited: Array<{ id: string; start_time_s: number; end_time_s: number; text: string }> = [];
    const result = mergeClipEditsToTranscript(full, 0, 20, edited);
    // All segments fully inside [0,20], so all removed — but that's correct
    // since user deleted everything in the window
    expect(result).toHaveLength(0);
  });
});

describe("moveSegmentClipWindow", () => {
  const segments = [
    { id: "a", start_time_s: 6, end_time_s: 9, text: "inside" },
  ];

  it("moves segment within clip window", () => {
    const result = moveSegmentClipWindow(segments, "a", 2, 25, 5, 15);
    expect(result[0].start_time_s).toBe(8);
    expect(result[0].end_time_s).toBe(11);
  });

  it("clamps to clip start boundary", () => {
    const result = moveSegmentClipWindow(segments, "a", -10, 25, 5, 15);
    expect(result[0].start_time_s).toBe(5);
  });

  it("clamps to clip end boundary", () => {
    const result = moveSegmentClipWindow(segments, "a", 10, 25, 5, 15);
    expect(result[0].end_time_s).toBe(15);
  });
});

describe("resizeSegmentClipWindow", () => {
  const segments = [
    { id: "a", start_time_s: 6, end_time_s: 9, text: "inside" },
  ];

  it("resizes end edge within clip window", () => {
    const result = resizeSegmentClipWindow(segments, "a", "end", 12, 25, 5, 15);
    expect(result[0].end_time_s).toBe(12);
  });

  it("clamps resize to clip start boundary", () => {
    const result = resizeSegmentClipWindow(segments, "a", "start", 3, 25, 5, 15);
    expect(result[0].start_time_s).toBe(5);
  });

  it("clamps resize to clip end boundary", () => {
    const result = resizeSegmentClipWindow(segments, "a", "end", 20, 25, 5, 15);
    expect(result[0].end_time_s).toBe(15);
  });

  it("keeps at least one frame when the start edge crosses the end edge", () => {
    const result = resizeSegmentClipWindow(segments, "a", "start", 12, 25, 5, 15);
    expect(result[0].start_time_s).toBe(8.96);
    expect(result[0].end_time_s).toBe(9);
  });

  it("keeps at least one frame when the end edge crosses the start edge", () => {
    const result = resizeSegmentClipWindow(segments, "a", "end", 4, 25, 5, 15);
    expect(result[0].start_time_s).toBe(6);
    expect(result[0].end_time_s).toBe(6.04);
  });
});

describe("parseServerValidationErrors", () => {
  // Source-aware rows: index 0 locked, index 1-2 editable
  const rows = [
    { start_time_s: 0, end_time_s: 5, text: "locked-A", source: "locked" as const },
    { start_time_s: 5, end_time_s: 10, text: "B", source: "editable" as const, id: "edit-b" },
    { start_time_s: 10, end_time_s: 15, text: "C", source: "editable" as const, id: "edit-c" },
  ];

  it("maps invalid segment index to editable id with correct label", () => {
    const result = parseServerValidationErrors(
      "invalid segment at index 1: text must not be empty",
      rows,
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ editableId: "edit-b", label: "校验错误" });
  });

  it("maps overlap indices to editable ids with overlap label", () => {
    const result = parseServerValidationErrors(
      "segments overlap at index 1 and 2",
      rows,
    );
    expect(result).toHaveLength(2);
    expect(result[0].label).toBe("重叠");
    expect(result[1].label).toBe("重叠");
    expect(result[0].editableId).toBe("edit-b");
    expect(result[1].editableId).toBe("edit-c");
  });

  it("does not map locked/outside row indices", () => {
    const result = parseServerValidationErrors(
      "invalid segment at index 0: text too long",
      rows,
    );
    expect(result).toHaveLength(0);
  });

  it("ignores out-of-range indices", () => {
    const result = parseServerValidationErrors(
      "invalid segment at index 99: bad",
      rows,
    );
    expect(result).toHaveLength(0);
  });
});

describe("buildMergeRowList", () => {
  const full = [
    { start_time_s: 0, end_time_s: 5, text: "A" },
    { start_time_s: 5, end_time_s: 10, text: "B" },
    { start_time_s: 10, end_time_s: 15, text: "C" },
  ];
  const editable = [
    { id: "edit-b", start_time_s: 5, end_time_s: 10, text: "B-edited" },
  ];

  it("preserves locked outside rows and marks editable rows", () => {
    const result = buildMergeRowList(full, 5, 10, editable);
    expect(result[0]).toMatchObject({ source: "locked", text: "A" });
    expect(result[1]).toMatchObject({ source: "editable", id: "edit-b" });
    expect(result[2]).toMatchObject({ source: "locked", text: "C" });
  });
});

describe("binarySearch", () => {
  const segments = [
    { start_time_s: 0, end_time_s: 5 },
    { start_time_s: 5, end_time_s: 10 },
    { start_time_s: 10, end_time_s: 15 },
    { start_time_s: 20, end_time_s: 25 },
  ];

  it("returns correct index when time is within a segment", () => {
    expect(binarySearch(segments, 2)).toBe(0);
    expect(binarySearch(segments, 7)).toBe(1);
    expect(binarySearch(segments, 12)).toBe(2);
    expect(binarySearch(segments, 22)).toBe(3);
  });

  it("returns -1 when time is before the first segment", () => {
    expect(binarySearch(segments, -5)).toBe(-1);
  });

  it("returns -1 when time is after the last segment", () => {
    expect(binarySearch(segments, 30)).toBe(-1);
  });

  it("returns -1 when time falls in a gap between segments", () => {
    expect(binarySearch(segments, 17)).toBe(-1); // between 15 and 20
  });

  it("returns correct index when time is at exact start boundary", () => {
    expect(binarySearch(segments, 0)).toBe(0);
    expect(binarySearch(segments, 5)).toBe(1);
  });

  it("returns -1 when time is at exact end boundary of last segment", () => {
    expect(binarySearch(segments, 15)).toBe(-1);
    expect(binarySearch(segments, 25)).toBe(-1);
  });

  it("handles empty array", () => {
    expect(binarySearch([], 5)).toBe(-1);
  });

  it("handles single segment array", () => {
    const single = [{ start_time_s: 0, end_time_s: 10 }];
    expect(binarySearch(single, 0)).toBe(0);
    expect(binarySearch(single, 5)).toBe(0);
    expect(binarySearch(single, 9.9)).toBe(0);
    expect(binarySearch(single, 10)).toBe(-1);
    expect(binarySearch(single, -1)).toBe(-1);
  });

  it("does not return out-of-bounds indices with various inputs", () => {
    for (let t = -10; t <= 35; t += 0.5) {
      const idx = binarySearch(segments, t);
      expect(idx).toBeGreaterThanOrEqual(-1);
      expect(idx).toBeLessThan(segments.length);
    }
  });
});

// ── confidence nullification on edit (AC-13) ─────────────────────────────

const segsWithConfidence: EditableSubtitleSegment[] = [
  { id: "a", start_time_s: 0, end_time_s: 2, text: "first", confidence: 0.85 },
  { id: "b", start_time_s: 4, end_time_s: 7, text: "second", confidence: 0.5 },
];

describe("confidence nullification on edit", () => {
  it("SET_TEXT clears confidence on edited segment only", () => {
    const state = initialEditingState(segsWithConfidence);
    const next = editingReducer(state, updateSegmentText("a", "changed"));
    expect(next.present[0].confidence).toBeNull();
    expect(next.present[1].confidence).toBe(0.5); // unchanged
  });

  it("SPLIT_SEGMENT clears confidence on both split outputs", () => {
    const split = splitSegmentAtPlayhead(segsWithConfidence, "b", 5.5, 25);
    expect(split).not.toBeNull();
    const splitB = split!.filter((s) => s.text === "second");
    expect(splitB).toHaveLength(2);
    for (const s of splitB) {
      expect(s.confidence).toBeNull();
    }
    // Unaffected segment preserves confidence.
    expect(split![0].confidence).toBe(0.85);
  });

  it("MOVE_SEGMENT clears confidence on moved segment", () => {
    const moved = moveSegment(segsWithConfidence, "a", 2, 25, 60);
    expect(moved.find((s) => s.id === "a")!.confidence).toBeNull();
    expect(moved.find((s) => s.id === "b")!.confidence).toBe(0.5);
  });

  it("RESIZE_SEGMENT clears confidence on resized segment", () => {
    const resized = resizeSegment(segsWithConfidence, "b", "end", 8, 25, 60);
    expect(resized.find((s) => s.id === "b")!.confidence).toBeNull();
    expect(resized.find((s) => s.id === "a")!.confidence).toBe(0.85);
  });

  it("ADD_SEGMENT creates segment with confidence null", () => {
    const added = addSegmentAtPlayhead(segsWithConfidence, 2.5, 25);
    expect(added).toHaveLength(3);
    const newSeg = added.find((s) => s.id !== "a" && s.id !== "b")!;
    expect(newSeg.confidence).toBeNull();
    // Existing segments preserve confidence.
    expect(added.find((s) => s.id === "a")!.confidence).toBe(0.85);
    expect(added.find((s) => s.id === "b")!.confidence).toBe(0.5);
  });

  it("ADD_SEGMENT_CLIP_WINDOW creates segment with confidence null", () => {
    const clipSegs = [
      { id: "c", start_time_s: 10, end_time_s: 13, text: "clip", confidence: 0.72 },
    ];
    const added = addSegmentAtPlayheadClipWindow(clipSegs, 12, 25, 10, 15);
    expect(added).toHaveLength(2);
    const newSeg = added.find((s) => s.id !== "c")!;
    expect(newSeg.confidence).toBeNull();
    expect(added.find((s) => s.id === "c")!.confidence).toBe(0.72);
  });

  it("MOVE_SEGMENT_CLIP_WINDOW clears confidence on moved segment", () => {
    const clipSegs = [
      { id: "c", start_time_s: 10, end_time_s: 13, text: "a", confidence: 0.7 },
      { id: "d", start_time_s: 14, end_time_s: 17, text: "b", confidence: 0.3 },
    ];
    const moved = moveSegmentClipWindow(clipSegs, "c", 1, 25, 10, 20);
    expect(moved.find((s) => s.id === "c")!.confidence).toBeNull();
    expect(moved.find((s) => s.id === "d")!.confidence).toBe(0.3);
  });

  it("RESIZE_SEGMENT_CLIP_WINDOW clears confidence on resized segment", () => {
    const clipSegs = [
      { id: "c", start_time_s: 10, end_time_s: 13, text: "a", confidence: 0.8 },
      { id: "d", start_time_s: 14, end_time_s: 17, text: "b", confidence: 0.2 },
    ];
    const resized = resizeSegmentClipWindow(clipSegs, "d", "start", 14.5, 25, 10, 20);
    expect(resized.find((s) => s.id === "d")!.confidence).toBeNull();
    expect(resized.find((s) => s.id === "c")!.confidence).toBe(0.8);
  });

  it("DELETE_SEGMENT preserves confidence on remaining segments", () => {
    const state = initialEditingState(segsWithConfidence);
    const next = editingReducer(state, deleteSegment("a"));
    expect(next.present).toHaveLength(1);
    expect(next.present[0].confidence).toBe(0.5);
  });

  it("editingReducer preserves confidence on REPLACE (server load)", () => {
    const state = initialEditingState(segsWithConfidence);
    const incoming: EditableSubtitleSegment[] = [
      { id: "x", start_time_s: 0, end_time_s: 3, text: "new", confidence: 0.62 },
    ];
    const next = editingReducer(state, { type: "REPLACE", segments: incoming });
    expect(next.present[0].confidence).toBe(0.62);
  });

  it("editingReducer preserves confidence on RESET", () => {
    const state = initialEditingState([]);
    const next = editingReducer(state, { type: "RESET", segments: segsWithConfidence });
    expect(next.present[0].confidence).toBe(0.85);
    expect(next.present[1].confidence).toBe(0.5);
  });
});
