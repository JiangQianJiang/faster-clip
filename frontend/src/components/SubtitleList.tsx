import { THEME } from "../theme";
import { CONFIDENCE, type EditableSubtitleSegment, type SegmentIssue } from "../utils/subtitleEditing";

interface Props {
  segments: EditableSubtitleSegment[];
  selectedId: string | null;
  editingId: string | null;
  issues: Map<string, SegmentIssue[]>;
  onSelect: (id: string) => void;
  onEditStart: (id: string) => void;
  onTextChange: (id: string, text: string) => void;
  onEditEnd: () => void;
}

const BORDER_COLORS = {
  high: "#22c55e",
  medium: "#f59e0b",
  low: "#ef4444",
} as const;

function confidenceBorder(confidence: number | null | undefined): string | undefined {
  if (confidence == null) return undefined;
  if (confidence >= CONFIDENCE.HIGH) return BORDER_COLORS.high;
  if (confidence >= CONFIDENCE.LOW) return BORDER_COLORS.medium;
  return BORDER_COLORS.low;
}

function confidenceTooltip(confidence: number | null | undefined): string | undefined {
  if (confidence == null) return undefined;
  return `置信度 ${(confidence * 100).toFixed(0)}%`;
}

export default function SubtitleList({
  segments,
  selectedId,
  editingId,
  issues,
  onSelect,
  onEditStart,
  onTextChange,
  onEditEnd,
}: Props) {
  const hasConfidence = segments.some((s) => s.confidence != null);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: THEME.colors.bgWhite }}>
      <div style={{ padding: "10px 12px", borderBottom: `1px solid ${THEME.colors.border}`, fontWeight: 600, fontSize: 13 }}>
        字幕列表
      </div>
      <div style={{ overflowY: "auto", flex: 1 }}>
        {segments.map((segment, index) => {
          const selected = segment.id === selectedId;
          const rowIssues = issues.get(segment.id) || [];
          const borderColor = confidenceBorder(segment.confidence);
          return (
            <div
              key={segment.id}
              onClick={() => onSelect(segment.id)}
              onDoubleClick={() => onEditStart(segment.id)}
              title={confidenceTooltip(segment.confidence)}
              style={{
                padding: "8px 10px",
                borderBottom: `1px solid ${THEME.colors.borderLight}`,
                borderLeft: borderColor ? `3px solid ${borderColor}` : "3px solid transparent",
                background: selected ? THEME.colors.infoBg : rowIssues.length ? THEME.colors.errorBg : THEME.colors.bgWhite,
                cursor: "pointer",
              }}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                <span style={{ color: THEME.colors.textSecondary, fontSize: 12, minWidth: 28 }}>
                  #{index + 1}
                </span>
                {rowIssues.map((issue) => (
                  <span
                    key={issue}
                    style={{
                      color: THEME.colors.errorText,
                      background: THEME.colors.errorBg,
                      borderRadius: 4,
                      padding: "1px 5px",
                      fontSize: 11,
                    }}
                  >
                    {issue}
                  </span>
                ))}
              </div>
              {editingId === segment.id ? (
                <input
                  autoFocus
                  value={segment.text}
                  onChange={(event) => onTextChange(segment.id, event.target.value)}
                  onBlur={onEditEnd}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === "Escape") {
                      event.currentTarget.blur();
                    }
                  }}
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    fontSize: 13,
                    padding: "5px 7px",
                    border: `1px solid ${THEME.colors.infoText}`,
                    borderRadius: 4,
                  }}
                />
              ) : (
                <div style={{ fontSize: 13, lineHeight: 1.45, color: THEME.colors.textPrimary, wordBreak: "break-word", whiteSpace: "pre-wrap" }}>
                  {segment.text || <span style={{ color: THEME.colors.textMuted }}>空字幕</span>}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {hasConfidence && (
        <div
          style={{
            padding: "8px 12px",
            borderTop: `1px solid ${THEME.colors.border}`,
            display: "flex",
            gap: 12,
            fontSize: 12,
            color: THEME.colors.textSecondary,
          }}
        >
          {[
            { color: BORDER_COLORS.high, key: "high" },
            { color: BORDER_COLORS.medium, key: "medium" },
            { color: BORDER_COLORS.low, key: "low" },
          ].map(({ color, key }) => {
            const count = segments.filter((s) => {
              const c = s.confidence;
              if (c == null) return false;
              if (key === "high") return c >= CONFIDENCE.HIGH;
              if (key === "medium") return c >= CONFIDENCE.LOW && c < CONFIDENCE.HIGH;
              return c < CONFIDENCE.LOW;
            }).length;
            if (count === 0) return null;
            return (
              <span key={key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    background: color,
                  }}
                />
                {count}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
