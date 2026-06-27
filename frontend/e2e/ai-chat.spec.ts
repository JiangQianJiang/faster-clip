import { test, expect } from "@playwright/test";

const TASK_WITH_TRANSCRIPT = {
  task_id: "test-ai-task-001",
  status: "done",
  stage: null,
  video_filename: "test-video.mp4",
  config: { llm_base_url: "https://api.anthropic.com", llm_model: "claude" },
  subtitle_segment_count: 100,
  clips: [],
  transcript_source: "asr",
  transcript_modified_at: new Date().toISOString(),
  media_info: { fps: 30, fps_mode: "average" },
};

const TASK_NO_TRANSCRIPT = {
  ...TASK_WITH_TRANSCRIPT,
  task_id: "test-ai-task-002",
  subtitle_segment_count: 0,
  transcript_source: null,
};

function sseEvent(type: string, data: unknown): string {
  return `data: ${JSON.stringify({ type, data })}\n\n`;
}

async function seedGlobalSettings(
  page: import("@playwright/test").Page,
) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "global_llm_settings",
      JSON.stringify({
        llmBaseUrl: "https://api.anthropic.com",
        llmModel: "claude",
        asrProvider: "qwen",
        asrBaseUrl: "https://dashscope.aliyuncs.com",
        asrModel: "qwen3-asr-flash-filetrans",
      }),
    );
  });
}

async function mockTaskList(page: import("@playwright/test").Page) {
  await page.route(/\/api\/tasks(?:\?.*)?$/, (route) => {
    route.fulfill({ json: [] });
  });
}

function statusFromTask(task: typeof TASK_WITH_TRANSCRIPT) {
  return {
    task_id: task.task_id,
    status: task.status,
    stage: task.stage,
    video_filename: task.video_filename,
    subtitle_segment_count: task.subtitle_segment_count,
    updated_at: new Date().toISOString(),
  };
}

async function mockTask(
  page: import("@playwright/test").Page,
  task: typeof TASK_WITH_TRANSCRIPT,
) {
  await page.route(new RegExp(`/api/tasks/${task.task_id}$`), (route) => {
    route.fulfill({ json: task });
  });
  await page.route(new RegExp(`/api/tasks/${task.task_id}/status$`), (route) => {
    route.fulfill({ json: statusFromTask(task) });
  });
  await page.route(new RegExp(`/api/tasks/${task.task_id}/transcript$`), (route) => {
    route.fulfill({
      json: {
        task_id: task.task_id,
        available: task.subtitle_segment_count > 0,
        segment_count: task.subtitle_segment_count > 0 ? 2 : 0,
        segments:
          task.subtitle_segment_count > 0
            ? [
                { start_time_s: 0, end_time_s: 5, text: "hello" },
                { start_time_s: 5, end_time_s: 10, text: "world" },
              ]
            : [],
      },
    });
  });
  await mockTaskList(page);
}

test.describe("AI Chat Mode", () => {
  test("renders chat UI without sending API key in POST body", async ({ page }) => {
    await seedGlobalSettings(page);

    await mockTask(page, TASK_WITH_TRANSCRIPT);

    // Capture POST body to verify key
    let postedBody: Record<string, string> = {};
    await page.route(/\/api\/tasks\/test-ai-task-001\/chat$/, (route) => {
      postedBody = route.request().postDataJSON() || {};
      const stream = [
        sseEvent("thinking", "thinking"),
        sseEvent("text", "Hello! How can I help?"),
      ].join("");
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: stream,
      });
    });

    await page.goto("/tasks/test-ai-task-001");
    await page.click("button:has-text('AI')");

    // Send message; provider key is resolved by the backend settings file.
    await page.fill('input[placeholder*="输入你的指令"]', "hello");
    await page.click("text=发送");

    // Wait for stream to process
    await page.waitForTimeout(500);

    // Verify no provider key was sent from the browser
    expect(postedBody.llm_api_key).toBeUndefined();
    expect(postedBody.message).toBe("hello");

    // Verify response rendered
    await expect(page.locator("text=Hello! How can I help?")).toBeVisible();
  });

  test("checkpoint shows editor button when transcript exists, opens editor", async ({ page }) => {
    await seedGlobalSettings(page);

    await mockTask(page, TASK_WITH_TRANSCRIPT);

    // Mock transcript endpoint for editor open
    await page.route(/\/api\/tasks\/test-ai-task-001\/transcript$/, (route) => {
      route.fulfill({
        json: {
          task_id: "test-ai-task-001",
          available: true,
          segment_count: 2,
          segments: [
            { start_time_s: 0, end_time_s: 5, text: "hello" },
            { start_time_s: 5, end_time_s: 10, text: "world" },
          ],
        },
      });
    });

    // Mock chat: return analyze_highlights tool_use then checkpoint
    await page.route(/\/api\/tasks\/test-ai-task-001\/chat$/, (route) => {
      const stream = [
        sseEvent("thinking", "thinking"),
        sseEvent("text", "Let me analyze."),
        sseEvent("tool_start", { tool: "analyze_highlights", input: {} }),
        sseEvent("tool_result", { tool: "analyze_highlights", success: true, user_message: "found 2 clips" }),
        sseEvent("checkpoint", {
          actions: [
            { label: "打开字幕编辑器", action: "open_editor" },
            { label: "继续", action: "continue" },
          ],
        }),
      ].join("");
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: stream,
      });
    });

    await page.goto("/tasks/test-ai-task-001");
    await page.click("button:has-text('AI')");

    await page.fill('input[placeholder*="输入你的指令"]', "analyze");
    await page.click("text=发送");

    // Wait for tool card and result text
    await expect(page.locator("text=analyze_highlights").first()).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /analyze_highlights/ }).first().click();
    await expect(page.locator("text=found 2 clips")).toBeVisible({ timeout: 5000 });

    // Editor button should be visible (transcript exists)
    const editorBtn = page.locator("button:has-text('打开字幕编辑器')");
    await expect(editorBtn).toBeVisible({ timeout: 5000 });
    await editorBtn.click();

    // Subtitle editor dialog should open
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("字幕列表")).toBeVisible({ timeout: 3000 });
    await expect(page.getByRole("button", { name: "保存" })).toBeVisible({ timeout: 3000 });
  });

  test("checkpoint hides editor button when no transcript", async ({ page }) => {
    await seedGlobalSettings(page);

    await mockTask(page, TASK_NO_TRANSCRIPT);

    await page.route(/\/api\/tasks\/test-ai-task-002\/chat$/, (route) => {
      const stream = [
        sseEvent("thinking", "thinking"),
        sseEvent("tool_start", { tool: "analyze_highlights", input: {} }),
        sseEvent("tool_result", { tool: "analyze_highlights", success: true, user_message: "no clips" }),
        sseEvent("checkpoint", {
          actions: [
            { label: "打开字幕编辑器", action: "open_editor" },
            { label: "继续", action: "continue" },
          ],
        }),
      ].join("");
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: stream,
      });
    });

    await page.goto("/tasks/test-ai-task-002");
    await page.click("button:has-text('AI')");

    await page.fill('input[placeholder*="输入你的指令"]', "analyze");
    await page.click("text=发送");

    await page.waitForTimeout(500);
    // Non-editor checkpoint button should be present
    await expect(page.locator("button:has-text('继续')")).toBeVisible({ timeout: 5000 });
    // Editor button should NOT be visible (no transcript)
    await expect(page.locator("button:has-text('打开字幕编辑器')")).not.toBeVisible({ timeout: 3000 });
  });

  test("shows retry UI on stream failure without losing messages", async ({ page }) => {
    await seedGlobalSettings(page);

    await mockTask(page, TASK_WITH_TRANSCRIPT);

    // Mock chat: return error after connection
    await page.route(/\/api\/tasks\/test-ai-task-001\/chat$/, (route) => {
      route.abort("connectionreset");
    });

    await page.goto("/tasks/test-ai-task-001");
    await page.click("button:has-text('AI')");

    await page.fill('input[placeholder*="输入你的指令"]', "fail me");
    await page.click("text=发送");

    // User message should remain visible
    await expect(page.locator("text=fail me")).toBeVisible({ timeout: 5000 });
    // Retry button should appear
    await expect(page.locator("button:has-text('重试')")).toBeVisible({ timeout: 10000 });
  });

  test("failed checkpoint tool shows error card without checkpoint buttons", async ({ page }) => {
    await seedGlobalSettings(page);

    await mockTask(page, TASK_WITH_TRANSCRIPT);

    await page.route(/\/api\/tasks\/test-ai-task-001\/chat$/, (route) => {
      const stream = [
        sseEvent("thinking", "thinking"),
        sseEvent("tool_start", { tool: "analyze_highlights", input: {} }),
        sseEvent("tool_result", { tool: "analyze_highlights", success: false, user_message: "LLM 分析失败" }),
        sseEvent("text", "Sorry, the analysis failed. Please check your API key or try again."),
      ].join("");
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: stream,
      });
    });

    await page.goto("/tasks/test-ai-task-001");
    await page.click("button:has-text('AI')");
    await page.fill('input[placeholder*="输入你的指令"]', "analyze");
    await page.click("text=发送");

    // Failed tool card
    await expect(page.locator("text=analyze_highlights").first()).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /analyze_highlights/ }).first().click();
    await expect(page.locator("text=LLM 分析失败")).toBeVisible({ timeout: 5000 });
    // Fallback text
    await expect(page.locator("text=Sorry")).toBeVisible({ timeout: 5000 });
    // No checkpoint buttons
    await expect(page.locator("button:has-text('打开字幕编辑器')")).not.toBeVisible({ timeout: 3000 });
    await expect(page.locator("button:has-text('继续')")).not.toBeVisible({ timeout: 3000 });
  });
});
