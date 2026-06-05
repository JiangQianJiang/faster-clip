import { useRef, useState, useCallback, useEffect } from "react";
import type { EditableSubtitleSegment, SegmentIssue } from "../utils/subtitleEditing";
import { arrangeTrackRows } from "../utils/subtitleEditing";

interface Props {
  segments: EditableSubtitleSegment[];
  clipStart: number;
  clipEnd: number;
  currentTime: number;
  selectedId: string | null;
  issues: Map<string, SegmentIssue[]>;
  onSeek: (time: number) => void;
  onSelect: (id: string) => void;
  onEditStart: (id: string) => void;
  onMove: (id: string, deltaSeconds: number) => void;
  onResize: (id: string, edge: "start" | "end", newTime: number) => void;
  onDragEnd?: () => void;
}

type DragState =
  | { type: "playhead"; pointerId: number; startX: number; startTime: number }
  | { type: "move"; pointerId: number; id: string; lastX: number }
  | { type: "resize"; pointerId: number; id: string; edge: "start" | "end" }
  | null;

export default function ClipSubtitleTrack({
  segments,
  clipStart,
  clipEnd,
  currentTime,
  selectedId,
  issues,
  onSeek,
  onSelect,
  onEditStart,
  onMove,
  onResize,
  onDragEnd,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<DragState>(null);
  const [lastClickId, setLastClickId] = useState<string | null>(null);
  const [lastClickTime, setLastClickTime] = useState(0);

  const duration = clipEnd - clipStart;
  const trackWidth = Math.max(duration * 40, 400); // 40px/sec, min 400px

  const rows = arrangeTrackRows(segments);
  const maxRow = Math.max(0, ...Array.from(rows.values()));
  const rowHeight = 28;
  const trackHeight = 36 + (maxRow + 1) * rowHeight;

  const timeToX = useCallback(
    (time: number) => ((time - clipStart) / duration) * trackWidth,
    [clipStart, duration, trackWidth],
  );

  const xToTime = useCallback(
    (x: number) => clipStart + (x / trackWidth) * duration,
    [clipStart, duration, trackWidth],
  );

  const handlePointerDown = (e: React.PointerEvent) => {
    const target = e.target as HTMLElement;
    const blockEl = target.closest("[data-segment-id]") as HTMLElement | null;
    const edge = target.getAttribute("data-edge") as "start" | "end" | null;

    if (edge && blockEl) {
      e.preventDefault();
      e.stopPropagation();
      const id = blockEl.getAttribute("data-segment-id")!;
      setDrag({ type: "resize", pointerId: e.pointerId, id, edge });
      (trackRef.current as HTMLElement).setPointerCapture(e.pointerId);
      return;
    }

    if (blockEl) {
      const id = blockEl.getAttribute("data-segment-id")!;

      // Double-click detection
      const now = Date.now();
      if (id === lastClickId && now - lastClickTime < 400) {
        onEditStart(id);
        setLastClickId(null);
        return;
      }
      setLastClickId(id);
      setLastClickTime(now);

      onSelect(id);

      // Start move drag if clicking on the block body
      setDrag({ type: "move", pointerId: e.pointerId, id, lastX: e.clientX });
      (trackRef.current as HTMLElement).setPointerCapture(e.pointerId);
      return;
    }

    // Click on playhead area
    const rect = trackRef.current?.getBoundingClientRect();
    if (rect) {
      const playheadX = timeToX(currentTime);
      const clickX = e.clientX - rect.left;
      if (Math.abs(clickX - playheadX) < 10) {
        setDrag({ type: "playhead", pointerId: e.pointerId, startX: e.clientX, startTime: currentTime });
        (trackRef.current as HTMLElement).setPointerCapture(e.pointerId);
        return;
      }
    }

    // Click on empty track background
    if (rect && trackRef.current) {
      const clickX = e.clientX - rect.left;
      onSeek(Math.max(clipStart, Math.min(clipEnd, xToTime(clickX))));
    }
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!drag) return;

    const trackEl = trackRef.current;
    if (!trackEl) return;
    const rect = trackEl.getBoundingClientRect();
    if (drag.type === "playhead") {
      const dx = e.clientX - drag.startX;
      const newTime = Math.max(clipStart, Math.min(clipEnd, drag.startTime + dx / (trackWidth / duration)));
      onSeek(newTime);
    } else if (drag.type === "move") {
      const dx = e.clientX - drag.lastX;
      const delta = dx / (trackWidth / duration);
      onMove(drag.id, delta);
      setDrag({ ...drag, lastX: e.clientX });
    } else if (drag.type === "resize") {
      const clickX = e.clientX - rect.left;
      const newTime = Math.max(clipStart, Math.min(clipEnd, xToTime(clickX)));
      onResize(drag.id, drag.edge, newTime);
    }
  };

  const handlePointerUp = () => {
    const pointerId = drag?.pointerId;
    const wasDragging = drag?.type === "move" || drag?.type === "resize";
    setDrag(null);
    if (trackRef.current && pointerId !== undefined) {
      (trackRef.current as HTMLElement).releasePointerCapture?.(pointerId);
    }
    if (wasDragging) onDragEnd?.();
  };

  const playheadX = timeToX(Math.max(clipStart, Math.min(clipEnd, currentTime)));

  // Scroll to selected segment
  const wrapperRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!selectedId || !wrapperRef.current) return;
    const seg = segments.find((s) => s.id === selectedId);
    if (!seg) return;
    const x = timeToX(seg.start_time_s);
    const wrapper = wrapperRef.current;
    const viewStart = wrapper.scrollLeft;
    const viewEnd = viewStart + wrapper.clientWidth;
    if (x < viewStart || x > viewEnd) {
      wrapper.scrollTo({ left: Math.max(0, x - 40), behavior: "smooth" });
    }
  }, [selectedId, segments, timeToX]);

  return (
    <div
      ref={wrapperRef}
      style={{
        position: "relative",
        borderTop: "1px solid #e5e7eb",
        background: "#fafafa",
        flexShrink: 0,
        height: trackHeight,
        overflowX: "auto",
        overflowY: "hidden",
        userSelect: "none",
      }}
    >
      <div
        ref={trackRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={{
          position: "relative",
          width: trackWidth,
          height: trackHeight,
          touchAction: "none",
        }}
      >
        {/* Row backgrounds */}
        {Array.from({ length: maxRow + 1 }, (_, r) => (
          <div
            key={r}
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 36 + r * rowHeight,
              height: rowHeight,
              borderBottom: "1px solid #f0f0f0",
            }}
          />
        ))}

        {/* Segment blocks */}
        {segments.map((seg) => {
          const x = timeToX(seg.start_time_s);
          const w = Math.max(4, timeToX(seg.end_time_s) - x);
          const row = rows.get(seg.id) || 0;
          const isSelected = seg.id === selectedId;
          const segIssues = issues.get(seg.id) || [];
          const hasIssue = segIssues.length > 0;

          return (
            <div
              key={seg.id}
              data-segment-id={seg.id}
              style={{
                position: "absolute",
                left: x,
                top: 36 + row * rowHeight + 2,
                width: w,
                height: rowHeight - 4,
                background: hasIssue ? "#fecaca" : isSelected ? "#93c5fd" : "#dbeafe",
                border: `1px solid ${hasIssue ? "#ef4444" : isSelected ? "#2563eb" : "#60a5fa"}`,
                borderRadius: 4,
                cursor: "grab",
                fontSize: 9,
                color: "#374151",
                padding: "0 4px",
                overflow: "hidden",
                whiteSpace: "nowrap",
                textOverflow: "ellipsis",
                lineHeight: `${rowHeight - 4}px`,
                boxSizing: "border-box",
              }}
            >
              {/* Resize handle left */}
              <span
                data-edge="start"
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  width: 6,
                  height: "100%",
                  cursor: "ew-resize",
                }}
              />
              {/* Resize handle right */}
              <span
                data-edge="end"
                style={{
                  position: "absolute",
                  right: 0,
                  top: 0,
                  width: 6,
                  height: "100%",
                  cursor: "ew-resize",
                }}
              />
              {seg.text}
            </div>
          );
        })}

        {/* Playhead */}
        <div
          style={{
            position: "absolute",
            left: playheadX,
            top: 0,
            width: 1,
            height: "100%",
            background: "#ef4444",
            pointerEvents: "none",
            zIndex: 10,
          }}
        />
        {/* Playhead triangle */}
        <div
          style={{
            position: "absolute",
            left: playheadX - 5,
            top: 0,
            width: 0,
            height: 0,
            borderLeft: "5px solid transparent",
            borderRight: "5px solid transparent",
            borderTop: "6px solid #ef4444",
            pointerEvents: "none",
            zIndex: 10,
          }}
        />
      </div>
    </div>
  );
}
