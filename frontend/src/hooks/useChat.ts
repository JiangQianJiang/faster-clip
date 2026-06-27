import { useState, useRef, useCallback, useEffect } from "react";
import { generateUUID } from "../utils/uuid";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallState[];
  checkpointActions?: CheckpointAction[];
  checkpointConsumed?: boolean;
}

export interface ToolCallState {
  id: string;
  tool: string;
  status: "running" | "done" | "error";
  userMessage: string;
}

export interface CheckpointAction {
  label: string;
  action: string; // "open_editor" | "continue" | "preview" | "reanalyze" | "export"
}

/** Convert Anthropic-format chat history JSON to ChatMessage[]. */
function parseChatHistory(raw: string): ChatMessage[] {
  if (!raw) return [];
  let history: any[];
  try {
    history = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(history)) return [];

  const messages: ChatMessage[] = [];

  for (const entry of history) {
    if (!entry || typeof entry !== "object") continue;

    const role = entry.role;
    const content = entry.content;

    if (role === "user") {
      if (typeof content === "string") {
        // Plain user message
        messages.push({
          id: generateUUID(),
          role: "user",
          content: content,
        });
      } else if (Array.isArray(content)) {
        // Tool result message — extract user_messages for display
        for (const block of content) {
          if (block?.type === "tool_result") {
            try {
              const parsed = JSON.parse(block.content || "{}");
              const userMessage = parsed.user_message || "";
              // Find matching tool call and update its status
              const toolId = block.tool_use_id;
              for (const msg of messages) {
                if (msg.role === "assistant" && msg.toolCalls) {
                  for (const tc of msg.toolCalls) {
                    if (tc.id === toolId && tc.status === "running") {
                      tc.status = parsed.success ? "done" : "error";
                      tc.userMessage = userMessage;
                    }
                  }
                }
              }
            } catch {
              // skip unparseable tool results
            }
          }
        }
      }
    } else if (role === "assistant") {
      const blocks = Array.isArray(content) ? content : [];
      let text = "";
      const toolCalls: ToolCallState[] = [];

      for (const block of blocks) {
        if (block?.type === "text" && typeof block.text === "string") {
          text += block.text;
        } else if (block?.type === "tool_use") {
          toolCalls.push({
            id: block.id || generateUUID(),
            tool: block.name || "unknown",
            status: "running",
            userMessage: "",
          });
        }
      }

      const msg: ChatMessage = {
        id: generateUUID(),
        role: "assistant",
        content: text,
        toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
      };

      // Restore persisted checkpoint actions (including consumed state).
      if (entry._checkpoint && typeof entry._checkpoint === "object") {
        const cp = entry._checkpoint as Record<string, unknown>;
        if (Array.isArray(cp.actions) && cp.actions.length > 0) {
          msg.checkpointActions = cp.actions as CheckpointAction[];
          msg.checkpointConsumed = cp.consumed === true;
        }
      }

      messages.push(msg);
    }
  }

  return messages;
}

export function useChat(taskId: string | undefined, initialChatHistory?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    // Initialize from persisted history on first render — avoids
    // async race conditions that can cause "flash then disappear".
    if (initialChatHistory) {
      const parsed = parseChatHistory(initialChatHistory);
      if (parsed.length > 0) return parsed;
    }
    return [];
  });
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Reset state when switching tasks. Same-task task refreshes can update
  // chatHistoryJson after a tool run; they should not wipe the active turn.
  useEffect(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setError(null);
    if (initialChatHistory) {
      const parsed = parseChatHistory(initialChatHistory);
      setMessages(parsed.length > 0 ? parsed : []);
    } else {
      setMessages([]);
    }
  }, [taskId]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!taskId || !text.trim()) return;

      setError(null);
      setIsStreaming(true);

      const userMsg: ChatMessage = {
        id: generateUUID(),
        role: "user",
        content: text,
      };
      setMessages((prev) => [...prev, userMsg]);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const { authFetch } = await import("../auth");
        const response = await authFetch(`/api/tasks/${taskId}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text }),
          signal: controller.signal,
        });

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.detail || `请求失败 (${response.status})`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("无法读取响应流");

        const decoder = new TextDecoder();
        let buffer = "";
        let assistantContent = "";
        // Track the current assistant message id so tool_result updates
        // only target the *current* message, not historical ones.
        let currentAssistantId: string | null = null;
        // Track all assistant message IDs created during this turn to avoid
        // attaching tool calls to messages from previous turns.
        const turnAssistantIds = new Set<string>();
        const toolCalls: ToolCallState[] = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;

            try {
              const event = JSON.parse(trimmed.slice(6));
              const { type, data } = event;

              switch (type) {
                case "thinking":
                  setMessages((prev) => {
                    const last = prev[prev.length - 1];
                    if (last?.role === "assistant" && last.content === "正在思考...") return prev;
                    return [
                      ...prev,
                      { id: generateUUID(), role: "assistant", content: "正在思考..." },
                    ];
                  });
                  break;

                case "text_delta":
                  // Incremental token — append to current assistant message
                  assistantContent += data;
                  if (currentAssistantId === null) {
                    currentAssistantId = generateUUID();
                    turnAssistantIds.add(currentAssistantId);
                  }
                  setMessages((prev) => {
                    const updated = [...prev];
                    // Remove thinking message if present
                    const lastIdx = updated.length - 1;
                    if (
                      lastIdx >= 0 &&
                      updated[lastIdx].role === "assistant" &&
                      updated[lastIdx].content === "正在思考..."
                    ) {
                      updated.pop();
                    }
                    const existing = updated.find((m) => m.id === currentAssistantId);
                    if (existing) {
                      existing.content = assistantContent;
                    } else {
                      updated.push({
                        id: currentAssistantId as string,
                        role: "assistant",
                        content: assistantContent,
                      });
                    }
                    return [...updated];
                  });
                  break;

                case "text":
                  // Full text block — replace for reconciliation after streaming,
                  // or standalone text blocks alongside tool_use.
                  assistantContent = data;
                  if (currentAssistantId === null) {
                    currentAssistantId = generateUUID();
                    turnAssistantIds.add(currentAssistantId);
                  }
                  setMessages((prev) => {
                    const updated = [...prev];
                    // Remove thinking message if present
                    const lastIdx = updated.length - 1;
                    if (
                      lastIdx >= 0 &&
                      updated[lastIdx].role === "assistant" &&
                      updated[lastIdx].content === "正在思考..."
                    ) {
                      updated.pop();
                    }
                    const existing = updated.find((m) => m.id === currentAssistantId);
                    if (existing) {
                      existing.content = assistantContent;
                    } else {
                      updated.push({
                        id: currentAssistantId as string,
                        role: "assistant",
                        content: assistantContent,
                      });
                    }
                    return [...updated];
                  });
                  break;

                case "tool_start":
                  toolCalls.push({
                    id: data.tool_use_id || generateUUID(),
                    tool: data.tool,
                    status: "running",
                    userMessage: "",
                  });
                  // Create or reuse an assistant message for tool calls
                  if (currentAssistantId === null) {
                    currentAssistantId = generateUUID();
                    turnAssistantIds.add(currentAssistantId);
                    setMessages((prev) => {
                      const filtered = prev.filter(
                        (m) => !(m.role === "assistant" && m.content === "正在思考...")
                      );
                      return [
                        ...filtered,
                        {
                          id: currentAssistantId as string,
                          role: "assistant" as const,
                          content: assistantContent,
                          toolCalls: [...toolCalls],
                          checkpointConsumed: false,
                        },
                      ];
                    });
                  } else {
                    // Update only the current assistant message
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === currentAssistantId
                          ? { ...m, toolCalls: [...toolCalls] }
                          : m
                      )
                    );
                  }
                  break;

                case "tool_result":
                  // Match by tool_use_id (stable, from backend), fall back to name.
                  const matchId = data.tool_use_id;
                  const tc = matchId
                    ? toolCalls.find((t) => t.id === matchId)
                    : toolCalls.find((t) => t.tool === data.tool && t.status === "running");
                  if (tc) {
                    tc.status = data.success ? "done" : "error";
                    tc.userMessage = data.user_message || "";
                    if (!data.success) {
                      console.error("[chat] tool failed", { taskId, tool: data.tool, tool_use_id: matchId, error: data.user_message });
                    }
                  }
                  // Only update the current assistant message's toolCalls
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === currentAssistantId
                        ? { ...m, toolCalls: [...toolCalls] }
                        : m
                    )
                  );
                  break;

                case "checkpoint":
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === currentAssistantId
                        ? {
                            ...m,
                            checkpointActions: Array.isArray(data.actions)
                              ? (data.actions as CheckpointAction[])
                              : [],
                            checkpointConsumed: false,
                          }
                        : m
                    )
                  );
                  break;

                case "error":
                  setError(data.message || "对话出错");
                  console.error("[chat] SSE error", { taskId, message: data.message, detail: data.detail });
                  // Remove transient thinking indicator on error
                  setMessages((prev) => {
                    const lastIdx = prev.length - 1;
                    if (
                      lastIdx >= 0 &&
                      prev[lastIdx].role === "assistant" &&
                      prev[lastIdx].content === "正在思考..."
                    ) {
                      return prev.slice(0, lastIdx);
                    }
                    return prev;
                  });
                  break;
              }
            } catch {
              // Skip malformed SSE lines
            }
          }
        }

        // Final cleanup — update the current assistant message if it still needs content/tool sync
        if (assistantContent || toolCalls.length > 0) {
          setMessages((prev) => {
            const updated = [...prev];
            // Find the current-turn assistant message (by ID, not just last)
            const target = currentAssistantId
              ? updated.find((m) => m.id === currentAssistantId)
              : null;
            const fallback = updated[updated.length - 1];
            const msg = target || (fallback?.role === "assistant" ? fallback : null);
            if (msg) {
              // Only set content if the message doesn't already have checkpoint actions
              // (checkpoint-carrying messages keep their content intact)
              if (assistantContent && !msg.checkpointActions?.length) {
                msg.content = assistantContent;
              }
              if (toolCalls.length > 0) msg.toolCalls = toolCalls;
            }
            return [...updated];
          });
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        console.warn("[chat] SSE connection error", { taskId, error: String(e) });
        setError(String(e));
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [taskId]
  );

  const cancelStream = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, isStreaming, error, sendMessage, cancelStream, setMessages };
}
