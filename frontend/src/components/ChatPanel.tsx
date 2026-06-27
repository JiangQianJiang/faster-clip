import { useState, useEffect, useRef } from "react";
import { useChat, ChatMessage, CheckpointAction, ToolCallState } from "../hooks/useChat";
import { useSettingsContext } from "../context/SettingsContext";
import { THEME } from "../theme";
import Button from "../ui/Button";
import MarkdownRenderer from "./MarkdownRenderer";

interface Props {
  taskId: string;
  hasTranscript: boolean;
  chatHistoryJson?: string;
  taskStatus: string;
  clipsCount: number;
  exportedClipsCount: number;
  onOpenEditor: () => void;
  onPreviewClip: (index: number) => void;
  onTaskChanged?: () => void;
}

const CHECKPOINT_TOOLS = [
  "extract_embedded_subtitles",
  "run_asr",
  "analyze_highlights",
  "export_clips",
  "add_clip",
  "refine_clips",
  "delete_clip",
];

export function shouldRefreshTaskAfterCheckpoint(
  messages: ChatMessage[],
  isStreaming: boolean,
): boolean {
  if (isStreaming) return false;
  const lastMsg = messages[messages.length - 1];
  if (lastMsg?.checkpointActions?.length) return false;
  return (
    lastMsg?.toolCalls?.some(
      (tc) => tc.status === "done" && CHECKPOINT_TOOLS.includes(tc.tool),
    ) ?? false
  );
}

function ToolCallsSummary({
  toolCalls,
  defaultExpanded,
}: {
  toolCalls: ToolCallState[];
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  // Auto-collapse when all tools finish
  const allDone = toolCalls.every((tc) => tc.status !== "running");
  useEffect(() => {
    if (allDone && !defaultExpanded) setExpanded(false);
  }, [allDone, defaultExpanded]);

  const running = toolCalls.filter((tc) => tc.status === "running").length;
  const failed = toolCalls.filter((tc) => tc.status === "error").length;
  const done = toolCalls.filter((tc) => tc.status === "done").length;

  const statusIcon = running > 0 ? "⟳" : failed > 0 ? "✗" : "✓";
  const statusColor = running > 0 ? "#f59e0b" : failed > 0 ? "#ef4444" : "#16a34a";
  const statusText = running > 0
    ? `${running} 运行中`
    : failed > 0
      ? `${done}/${toolCalls.length} 完成, ${failed} 失败`
      : `${done} 个工具`;

  const toolNames = toolCalls.map((tc) => tc.tool).join(", ");

  return (
    <div style={{ marginBottom: 8 }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          width: "100%",
          padding: "6px 10px",
          border: "none",
          borderRadius: 6,
          background: "#f9fafb",
          cursor: "pointer",
          fontSize: 12,
          color: "#6b7280",
          textAlign: "left",
        }}
      >
        <span style={{ color: statusColor, fontSize: 14, flexShrink: 0 }}>{statusIcon}</span>
        <span style={{ fontWeight: 500, color: "#374151" }}>{statusText}</span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {toolNames}
        </span>
        <span style={{ marginLeft: "auto", flexShrink: 0, fontSize: 10 }}>
          {expanded ? "▲" : "▼"}
        </span>
      </button>
      {expanded && (
        <div style={{ padding: "4px 0 0" }}>
          {toolCalls.map((tc) => (
            <ToolCallCard
              key={tc.id}
              tool={tc.tool}
              status={tc.status}
              userMessage={tc.userMessage}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ToolCallCard({
  tool,
  status,
  userMessage,
}: {
  tool: string;
  status: string;
  userMessage: string;
}) {
  const icon = status === "running" ? "⟳" : status === "done" ? "✓" : "✗";
  const borderColor =
    status === "running" ? "#f59e0b" : status === "done" ? "#16a34a" : "#ef4444";
  const bg =
    status === "running"
      ? "#fef3c7"
      : status === "done"
        ? "#f0fdf4"
        : "#fef2f2";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "10px 14px",
        borderLeft: `3px solid ${borderColor}`,
        background: bg,
        borderRadius: 8,
        fontSize: 13,
        marginBottom: 8,
      }}
    >
      <span style={{ fontSize: 18, flexShrink: 0 }}>{icon}</span>
      <div>
        <div style={{ fontWeight: 600 }}>{tool}</div>
        {status === "running" && (
          <div style={{ color: "#6b7280", fontSize: 12 }}>处理中...</div>
        )}
        {status !== "running" && userMessage && (
          <div style={{ color: "#374151", fontSize: 12, marginTop: 2 }}>
            {userMessage}
          </div>
        )}
      </div>
    </div>
  );
}

function CheckpointButtons({
  actions,
  hasTranscript,
  consumed = false,
  onOpenEditor,
  onPreviewClip,
  onContinue,
}: {
  actions: CheckpointAction[];
  hasTranscript: boolean;
  consumed?: boolean;
  onOpenEditor: () => void;
  onPreviewClip: (index: number) => void;
  onContinue: () => void;
}) {
  const visible = actions.filter((a) => {
    if (a.action === "open_editor" && !hasTranscript) return false;
    return true;
  });

  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8, opacity: consumed ? 0.5 : 1 }}>
      {visible.map((a, i) => {
        const isPrimary = a.action === "open_editor" || a.action === "export";
        return (
          <button
            key={i}
            disabled={consumed}
            onClick={() => {
              if (a.action === "open_editor") onOpenEditor();
              else if (a.action === "preview") onPreviewClip(0);
              else if (a.action === "continue") onContinue();
            }}
            style={{
              padding: "5px 14px",
              borderRadius: 6,
              border: isPrimary ? "none" : "1px solid #d1d5db",
              background: isPrimary ? "#3b82f6" : "#fff",
              color: isPrimary ? "#fff" : "#374151",
              fontSize: 13,
              cursor: consumed ? "not-allowed" : "pointer",
              fontWeight: isPrimary ? 500 : 400,
            }}
          >
            {a.label}
          </button>
        );
      })}
    </div>
  );
}

export default function ChatPanel({
  taskId,
  hasTranscript,
  chatHistoryJson,
  taskStatus,
  clipsCount,
  exportedClipsCount,
  onOpenEditor,
  onPreviewClip,
  onTaskChanged,
}: Props) {
  const { settings, isConfigured, openSettings } = useSettingsContext();
  const { messages, isStreaming, error, sendMessage, cancelStream } = useChat(
    taskId,
    chatHistoryJson,
  );
  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamHadStartedRef = useRef(false);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (isStreaming) {
      streamHadStartedRef.current = true;
    }
  }, [isStreaming]);

  const handleSend = () => {
    if (!inputValue.trim()) return;
    sendMessage(inputValue.trim());
    setInputValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };


  const handleCheckpointContinue = () => {
    sendMessage("继续");
  };

  // Refresh task data only after the stream closes. Refreshing as soon as a
  // tool_result arrives unmounts ChatPanel before the backend saves the turn,
  // which makes the in-flight user message disappear.
  const shouldRefreshTask = shouldRefreshTaskAfterCheckpoint(messages, isStreaming);
  useEffect(() => {
    if (shouldRefreshTask && streamHadStartedRef.current && onTaskChanged) {
      streamHadStartedRef.current = false;
      onTaskChanged();
    }
  }, [shouldRefreshTask, onTaskChanged]);

  const handleRetry = () => {
    const lastUserMsg = [...messages]
      .reverse()
      .find((m) => m.role === "user");
    if (lastUserMsg) sendMessage(lastUserMsg.content);
  };

  // Generate smart suggestion chips based on task state
  const getSuggestions = (): string[] => {
    const isDone = taskStatus === "done";
    const isError = taskStatus === "error";
    const hasClips = clipsCount > 0;
    const allExported = hasClips && exportedClipsCount === clipsCount;
    const hasPendingClips = hasClips && exportedClipsCount < clipsCount;

    if (isError) {
      return ["查看失败原因", "重新开始分析"];
    }
    if (!hasTranscript && !hasClips) {
      return ["帮我提取视频字幕", "用语音识别生成字幕"];
    }
    if (hasTranscript && !hasClips) {
      return ["帮我找3个精彩片段", "搜索字幕中出现的关键词", "给这个视频做总结"];
    }
    if (hasPendingClips) {
      return ["导出所有片段", "调整第一个片段的起止时间"];
    }
    if (allExported && isDone) {
      return ["重新分析寻找不同片段", "导出带字幕的剪辑版本", "删除不需要的片段重新导出"];
    }
    // Fallback for any state
    return ["分析精彩片段", "查看字幕内容"];
  };

  const suggestions = getSuggestions();

  const renderMessage = (msg: ChatMessage) => {
    if (msg.role === "user") {
      return (
        <div
          key={msg.id}
          style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}
        >
          <div
            style={{
              maxWidth: "80%",
              background: "#3b82f6",
              color: "#fff",
              padding: "10px 16px",
              borderRadius: "14px 14px 4px 14px",
              fontSize: 14,
              lineHeight: 1.6,
            }}
          >
            {msg.content}
          </div>
        </div>
      );
    }

    return (
      <div key={msg.id} style={{ marginBottom: 12 }}>
        {msg.toolCalls && msg.toolCalls.length > 0 && (
          <ToolCallsSummary
            toolCalls={msg.toolCalls}
            defaultExpanded={msg.toolCalls.some((tc) => tc.status === "running")}
          />
        )}
        {msg.content && msg.content !== "正在思考..." && (
          <div
            style={{
              maxWidth: "80%",
              background: "#f3f4f6",
              padding: "10px 16px",
              borderRadius: "14px 14px 14px 4px",
              fontSize: 14,
              lineHeight: 1.6,
              display: "inline-block",
            }}
          >
            <MarkdownRenderer content={msg.content} />
          </div>
        )}
        {msg.content === "正在思考..." && (
          <div
            style={{ color: "#9ca3af", fontSize: 13, fontStyle: "italic" }}
          >
            正在思考...
          </div>
        )}
        {msg.checkpointActions && msg.checkpointActions.length > 0 && (
          <CheckpointButtons
            actions={msg.checkpointActions}
            hasTranscript={hasTranscript}
            consumed={msg.checkpointConsumed}
            onOpenEditor={onOpenEditor}
            onPreviewClip={onPreviewClip}
            onContinue={handleCheckpointContinue}
          />
        )}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 400 }}>
      {/* Header with model name */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
          fontSize: 13,
        }}
      >
        <div style={{ fontWeight: 600, color: THEME.colors.textPrimary }}> AI 对话</div>
        <div style={{ color: THEME.colors.textMuted, fontSize: THEME.fontSize.caption }}>
          {settings.llmModel || "未配置"}
        </div>
      </div>

      {/* Unconfigured warning */}
      {!isConfigured && (
        <div
          style={{
            padding: THEME.spacing.md,
            background: THEME.colors.errorBg,
            borderRadius: THEME.radius.md,
            marginBottom: THEME.spacing.md,
            fontSize: THEME.fontSize.sm,
            color: THEME.colors.errorText,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span>请先配置 LLM 模型</span>
          <Button variant="secondary" size="sm" onClick={openSettings}>配置</Button>
        </div>
      )}

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "0 4px 16px",
          maxHeight: "calc(100vh - 280px)",
        }}
      >
        {messages.length === 0 && !isStreaming && (
          <div style={{ textAlign: "center", padding: "20px 0" }}>
            <p style={{ color: "#9ca3af", fontSize: 14, marginBottom: 16 }}>
              AI 助手已就绪，试试以下操作：
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(s)}
                  disabled={!isConfigured}
                  style={{
                    padding: "8px 16px",
                    borderRadius: 20,
                    border: `1px solid ${THEME.colors.border}`,
                    background: THEME.colors.bgWhite,
                    color: THEME.colors.textPrimary,
                    fontSize: 13,
                    cursor: isConfigured ? "pointer" : "not-allowed",
                    transition: "border-color 0.2s, background 0.2s",
                    whiteSpace: "nowrap",
                  }}
                  onMouseEnter={(e) => {
                    if (isConfigured) {
                      e.currentTarget.style.borderColor = "#3b82f6";
                      e.currentTarget.style.background = "#eff6ff";
                    }
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = THEME.colors.border;
                    e.currentTarget.style.background = THEME.colors.bgWhite;
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map(renderMessage)}
        <div ref={messagesEndRef} />
        {error && (
          <div
            style={{
              padding: 10,
              background: "#fef2f2",
              borderRadius: 8,
              color: "#991b1b",
              fontSize: 13,
              marginBottom: 8,
            }}
          >
            {error}
            <button
              onClick={handleRetry}
              style={{
                marginLeft: 8,
                padding: "2px 10px",
                fontSize: 12,
                border: "1px solid #ef4444",
                borderRadius: 4,
                background: "#fff",
                cursor: "pointer",
              }}
            >
              重试
            </button>
          </div>
        )}
      </div>
      {/* Compact suggestion chips above input (visible when messages exist) */}
      {messages.length > 0 && !isStreaming && suggestions.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", paddingBottom: THEME.spacing.sm }}>
          {suggestions.map((s, i) => (
            <button
              key={i}
              onClick={() => sendMessage(s)}
              disabled={!isConfigured}
              style={{
                padding: "4px 12px",
                borderRadius: 16,
                border: `1px solid ${THEME.colors.border}`,
                background: THEME.colors.bgWhite,
                color: THEME.colors.textSecondary,
                fontSize: 12,
                cursor: isConfigured ? "pointer" : "not-allowed",
                transition: "border-color 0.2s",
                whiteSpace: "nowrap",
              }}
              onMouseEnter={(e) => {
                if (isConfigured) {
                  e.currentTarget.style.borderColor = "#3b82f6";
                  e.currentTarget.style.color = "#3b82f6";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = THEME.colors.border;
                e.currentTarget.style.color = THEME.colors.textSecondary;
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div
        style={{
          display: "flex",
          gap: THEME.spacing.sm,
          paddingTop: THEME.spacing.md,
          borderTop: `1px solid ${THEME.colors.borderLight}`,
        }}
      >
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isConfigured ? "输入你的指令..." : "请先配置 LLM 模型"}
          disabled={isStreaming || !isConfigured}
          style={{
            flex: 1,
            padding: "10px 14px",
            border: `1px solid ${THEME.colors.border}`,
            borderRadius: THEME.radius.md,
            fontSize: THEME.fontSize.body,
            outline: "none",
          }}
        />
        {isStreaming ? (
          <Button variant="danger" size="md" onClick={cancelStream}>停止</Button>
        ) : (
          <Button variant="primary" size="md" onClick={handleSend} disabled={!isConfigured}>发送</Button>
        )}
      </div>
      {isConfigured && (
        <div
          style={{
            fontSize: 9,
            color: "#bbb",
            marginTop: 4,
            textAlign: "center",
          }}
        >
          使用全局 LLM 模型
        </div>
      )}
    </div>
  );
}
