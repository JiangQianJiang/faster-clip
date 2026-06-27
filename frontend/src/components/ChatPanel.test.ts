import { describe, expect, it } from "vitest";
import { shouldRefreshTaskAfterCheckpoint } from "./ChatPanel";
import type { ChatMessage } from "../hooks/useChat";

function assistantWithTool(tool: string, status: "running" | "done" | "error"): ChatMessage[] {
  return [
    {
      id: "assistant-1",
      role: "assistant",
      content: "",
      toolCalls: [
        {
          id: "tool-1",
          tool,
          status,
          userMessage: "完成",
        },
      ],
    },
  ];
}

describe("shouldRefreshTaskAfterCheckpoint", () => {
  it("does not refresh while the SSE stream is still open", () => {
    expect(shouldRefreshTaskAfterCheckpoint(assistantWithTool("export_clips", "done"), true)).toBe(false);
  });

  it("refreshes after a checkpoint tool completes and streaming has stopped", () => {
    expect(shouldRefreshTaskAfterCheckpoint(assistantWithTool("export_clips", "done"), false)).toBe(true);
  });

  it("does not refresh while a checkpoint action is waiting for user input", () => {
    const messages = assistantWithTool("analyze_highlights", "done");
    messages[0].checkpointActions = [{ label: "继续", action: "continue" }];

    expect(shouldRefreshTaskAfterCheckpoint(messages, false)).toBe(false);
  });

  it("ignores non-checkpoint tool completions", () => {
    expect(shouldRefreshTaskAfterCheckpoint(assistantWithTool("get_export_progress", "done"), false)).toBe(false);
  });
});
