import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EditableSubtitleSegment, SegmentIssue } from "../utils/subtitleEditing";
import { THEME } from "../theme";
import { arrangeTrackRows } from "../utils/subtitleEditing";

interface Props {
  segments: EditableSubtitleSegment[];
  selectedId: string | null;
  currentTime: number;
  duration: number;
  issues: Map<string, SegmentIssue[]>;
  onSeek: (time: number) => void;
  onSelect: (id: string) => void;
  onEditStart: (id: string) => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onMove: (id: string, delta: number) => void;
  onResize: (id: string, edge: "start" | "end", time: number) => void;
}

type DragState =
  | { type: "playhead" }
  | { type: "move"; id: string; startX: number; originalStart: number }
  | { type: "resize"; id: string; edge: "start" | "end" }
  | null;

export default function SubtitleTimeline({
  segments,
  selectedId,
  currentTime,
  duration,
  issues,
  onSeek,
  onSelect,
  onEditStart,
  onDragStart,
  onDragEnd,
  onMove,
  onResize,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState>(null);
  const [zoom, setZoom] = useState(80);

  // ── Viewport culling ────────────────────────────────────────────
  const [scrollLeft, setScrollLeft] = useState(0);
  const scrollRafRef = useRef(0);

  const handleScroll = useCallback(() => {
    // Throttle scroll-left updates to RAF to avoid flooding React renders
    if (!scrollRafRef.current) {
      scrollRafRef.current = requestAnimationFrame(() => {
        if (scrollRef.current) {
          setScrollLeft(scrollRef.current.scrollLeft);
        }
        scrollRafRef.current = 0;
      });
    }
  }, []);

  const rows = useMemo(() => arrangeTrackRows(segments), [segments]);
  const rowCount = Math.max(1, ...Array.from(rows.values(), (row) => row + 1));
  const timelineWidth = Math.max((duration || 60) * zoom, 800);

  // Only render segment blocks that are inside the visible scroll viewport (+ buffer)
  const visibleSegments = useMemo(() => {
    const viewWidth = scrollRef.current?.clientWidth || 800;
    const buffer = 200; // px — extra on each side so scrolling feels seamless
    const minX = scrollLeft - buffer;
    const maxX = scrollLeft + viewWidth + buffer;
    return segments.filter((seg) => {
      const left = seg.start_time_s * zoom;
      const right = seg.end_time_s * zoom;
      return right >= minX && left <= maxX;
    });
  }, [segments, scrollLeft, zoom]);

  // ── Scroll to selected segment (instant, no animation) ──────────
  useEffect(() => {
    if (!selectedId || !scrollRef.current) return;
    const segment = segments.find((item) => item.id === selectedId);
    if (!segment) return;
    const targetLeft = segment.start_time_s * zoom;
    const viewportWidth = scrollRef.current.clientWidth;
    scrollRef.current.scrollLeft = Math.max(0, targetLeft - viewportWidth * 0.25);
  }, [selectedId, segments, zoom]);

  // ── Auto-scroll timeline to follow playhead during playback ─────
  // Uses direct DOM write (scrollLeft) instead of scrollTo({smooth})
  // so animations never stack across successive timeupdate events.
  const autoScrollRafRef = useRef(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || duration <= 0) return;
    const playheadX = currentTime * zoom;
    const viewLeft = el.scrollLeft;
    const viewRight = viewLeft + el.clientWidth;
    const margin = el.clientWidth * 0.15;
    if (playheadX < viewLeft + margin || playheadX > viewRight - margin) {
      cancelAnimationFrame(autoScrollRafRef.current);
      autoScrollRafRef.current = requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollLeft = Math.max(0, playheadX - scrollRef.current.clientWidth * 0.3);
        }
      });
    }
    return () => cancelAnimationFrame(autoScrollRafRef.current);
  }, [currentTime, zoom, duration]);

  useEffect(() => {
    const onMovePointer = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const time = clientXToTime(event.clientX);
      if (drag.type === "playhead") {
        onSeek(time);
      } else if (drag.type === "resize") {
        onResize(drag.id, drag.edge, time);
      } else if (drag.type === "move") {
        onMove(drag.id, time - drag.originalStart);
      }
    };
    const onUp = () => {
      const drag = dragRef.current;
      dragRef.current = null;
      if (drag && drag.type !== "playhead") {
        onDragEnd();
      }
    };
    window.addEventListener("pointermove", onMovePointer);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMovePointer);
      window.removeEventListener("pointerup", onUp);
    };
  });

  const clientXToTime = (clientX: number): number => {
    const rect = scrollRef.current?.getBoundingClientRect();
    if (!rect || !scrollRef.current) return 0;
    const x = clientX - rect.left + scrollRef.current.scrollLeft;
    return Math.max(0, Math.min(duration || 0, x / zoom));
  };

  return (
    <div style={{ height: "100%", display: "grid", gridTemplateRows: "1fr", background: THEME.colors.bgPage }}>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        onWheel={(event) => {
          if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
            event.preventDefault();
            setZoom((value) => Math.min(420, Math.max(30, value + (event.deltaY < 0 ? 16 : -16))));
          }
        }}
        onPointerDown={(event) => {
          if (event.target === event.currentTarget) {
            onSeek(clientXToTime(event.clientX));
            dragRef.current = { type: "playhead" };
          }
        }}
        style={{ overflow: "auto", position: "relative", background: THEME.colors.bgPage }}
      >
        <div style={{ position: "relative", width: timelineWidth, height: Math.max(116, rowCount * 36 + 44) }}>
          <div
            style={{
              position: "sticky",
              top: 0,
              left: 0,
              height: 28,
              borderBottom: `1px solid ${THEME.colors.border}`,
              background: THEME.colors.infoBg,
              zIndex: 3,
            }}
          />
          <div
            onPointerDown={(event) => {
              event.stopPropagation();
              onSeek(clientXToTime(event.clientX));
              dragRef.current = { type: "playhead" };
            }}
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: currentTime * zoom,
              width: 2,
              background: THEME.colors.errorText,
              zIndex: 4,
              cursor: "ew-resize",
            }}
          />
          {visibleSegments.map((segment) => {
            const left = segment.start_time_s * zoom;
            const width = Math.max(12, (segment.end_time_s - segment.start_time_s) * zoom);
            const row = rows.get(segment.id) || 0;
            const hasIssue = (issues.get(segment.id) || []).length > 0;
            return (
              <div
                key={segment.id}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(segment.id);
                }}
                onDoubleClick={(event) => {
                  event.stopPropagation();
                  onEditStart(segment.id);
                }}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  onSelect(segment.id);
                  onDragStart();
                  dragRef.current = {
                    type: "move",
                    id: segment.id,
                    startX: event.clientX,
                    originalStart: segment.start_time_s,
                  };
                }}
                style={{
                  position: "absolute",
                  left,
                  top: 42 + row * 36,
                  width,
                  height: 26,
                  borderRadius: 5,
                  background: hasIssue ? THEME.colors.errorBg : selectedId === segment.id ? THEME.colors.infoBg : THEME.colors.infoBg,
                  border: `1px solid ${hasIssue ? THEME.colors.errorText : selectedId === segment.id ? THEME.colors.infoText : THEME.colors.infoText}`,
                  color: THEME.colors.textPrimary,
                  fontSize: 12,
                  lineHeight: "24px",
                  padding: "0 8px",
                  boxSizing: "border-box",
                  overflow: "hidden",
                  whiteSpace: "nowrap",
                  cursor: "grab",
                  zIndex: 2,
                }}
              >
                <span
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    onSelect(segment.id);
                    onDragStart();
                    dragRef.current = { type: "resize", id: segment.id, edge: "start" };
                  }}
                  style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 6, cursor: "ew-resize" }}
                />
                {segment.text || "空字幕"}
                <span
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    onSelect(segment.id);
                    onDragStart();
                    dragRef.current = { type: "resize", id: segment.id, edge: "end" };
                  }}
                  style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 6, cursor: "ew-resize" }}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
