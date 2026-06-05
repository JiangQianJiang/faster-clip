import { useEffect, useState, useRef, useCallback } from "react";

interface Props {
  taskId: string;
  text: string;
}

function loadPosition(taskId: string) {
  try {
    const raw = localStorage.getItem(`subtitle-overlay-pos-${taskId}`);
    if (raw) {
      const parsed = JSON.parse(raw) as { x: number; y: number };
      if (
        typeof parsed.x === "number" &&
        typeof parsed.y === "number" &&
        parsed.x >= 0 && parsed.x <= 100 &&
        parsed.y >= 0 && parsed.y <= 100
      ) {
        return parsed;
      }
    }
  } catch {
    // ignore corrupt data
  }
  return { x: 50, y: 85 };
}

function savePosition(taskId: string, pos: { x: number; y: number }) {
  try {
    localStorage.setItem(`subtitle-overlay-pos-${taskId}`, JSON.stringify(pos));
  } catch {
    // ignore quota errors
  }
}

export default function DraggableSubtitleOverlay({ taskId, text }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const dragState = useRef<{
    startX: number; startY: number;
    origX: number; origY: number;
    pointerId: number;
  } | null>(null);

  const [overlayPos, setOverlayPos] = useState(() => loadPosition(taskId));
  const [isDragging, setIsDragging] = useState(false);

  const releaseDrag = useCallback(() => {
    if (dragState.current) {
      try {
        overlayRef.current?.releasePointerCapture(dragState.current.pointerId);
      } catch {
        // already released
      }
      savePosition(taskId, overlayPos);
      dragState.current = null;
    }
    setIsDragging(false);
  }, [taskId, overlayPos]);

  // Clean up pointer capture on unmount
  useEffect(() => {
    return () => {
      if (dragState.current) {
        try {
          overlayRef.current?.releasePointerCapture(dragState.current.pointerId);
        } catch {
          // already released
        }
      }
    };
  }, []);

  const handlePointerDown = (e: React.PointerEvent) => {
    overlayRef.current?.setPointerCapture(e.pointerId);
    dragState.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: overlayPos.x,
      origY: overlayPos.y,
      pointerId: e.pointerId,
    };
    setIsDragging(true);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!dragState.current) return;
    const container = overlayRef.current?.parentElement;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const dx = ((e.clientX - dragState.current.startX) / rect.width) * 100;
    const dy = ((e.clientY - dragState.current.startY) / rect.height) * 100;
    setOverlayPos({
      x: Math.max(0, Math.min(100, dragState.current.origX + dx)),
      y: Math.max(0, Math.min(100, dragState.current.origY + dy)),
    });
  };

  const handlePointerUp = () => {
    releaseDrag();
  };

  if (!text) return null;

  return (
    <div
      ref={overlayRef}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onLostPointerCapture={releaseDrag}
      style={{
        position: "absolute",
        left: `${overlayPos.x}%`,
        top: `${overlayPos.y}%`,
        transform: "translate(-50%, -50%)",
        background: "rgba(0,0,0,0.75)",
        color: "#fff",
        padding: "6px 18px",
        borderRadius: 4,
        fontSize: 15,
        maxWidth: "80%",
        textAlign: "center",
        cursor: isDragging ? "grabbing" : "grab",
        userSelect: "none",
        touchAction: "none",
        zIndex: 5,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {text}
    </div>
  );
}
