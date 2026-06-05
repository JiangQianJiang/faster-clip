import { THEME } from "../theme";
import type { EditableSubtitleSegment, SegmentIssue } from "../utils/subtitleEditing";

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
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: THEME.colors.bgWhite }}>
      <div style={{ padding: "10px 12px", borderBottom: `1px solid ${THEME.colors.border}`, fontWeight: 600, fontSize: 13 }}>
        字幕列表
      </div>
      <div style={{ overflowY: "auto", flex: 1 }}>
        {segments.map((segment, index) => {
          const selected = segment.id === selectedId;
          const rowIssues = issues.get(segment.id) || [];
          return (
            <div
              key={segment.id}
              onClick={() => onSelect(segment.id)}
              onDoubleClick={() => onEditStart(segment.id)}
              style={{
                padding: "8px 10px",
                borderBottom: `1px solid ${THEME.colors.borderLight}`,
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
                <div style={{ fontSize: 13, lineHeight: 1.45, color: THEME.colors.textPrimary, wordBreak: "break-word" }}>
                  {segment.text || <span style={{ color: THEME.colors.textMuted }}>空字幕</span>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
