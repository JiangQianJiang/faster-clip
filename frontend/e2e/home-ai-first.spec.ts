import { test, expect } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const TEST_VIDEO = path.resolve(__dirname, "fixtures", "test-video.mp4");

test.describe("Home AI-First Flow", () => {
  test("unconfigured: selecting a file does not create a task", async ({ page }) => {
    // Track whether POST /api/tasks is ever called
    let taskPostCalled = false;

    await page.route("**/api/tasks", (route) => {
      if (route.request().method() === "POST") {
        taskPostCalled = true;
        route.fulfill({ json: {} });
      } else {
        // GET /api/tasks — return empty task list for sidebar
        route.fulfill({ json: [] });
      }
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Clear localStorage to simulate unconfigured, then reload
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Verify the configuration warning is visible
    await expect(page.getByText("请先配置 LLM API Key")).toBeVisible({ timeout: 10000 });

    // Select a video file via the hidden file input
    const fileInput = page.locator('input[type="file"]');
    await expect(fileInput).toBeAttached({ timeout: 5000 });
    await fileInput.setInputFiles(TEST_VIDEO);

    await page.waitForTimeout(1000);

    // Assert: no task creation request was made
    expect(taskPostCalled).toBe(false);

    // Assert: URL is still /
    expect(page.url()).not.toContain("/tasks/");
  });

  test("configured: selecting a file creates a task and navigates", async ({ page }) => {
    const TASK_ID = "test-home-task-001";

    let postFormFields: string[] = [];

    // Mock GET /api/tasks (task list) and POST /api/tasks (create)
    await page.route("**/api/tasks", async (route) => {
      if (route.request().method() === "POST") {
        const postData = route.request().postDataBuffer();
        if (postData) {
          postFormFields.push(new TextDecoder().decode(postData));
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ task_id: TASK_ID }),
        });
      } else {
        // GET /api/tasks — return empty task list
        await route.fulfill({ json: [] });
      }
    });

    // Mock the task detail and status endpoints
    await page.route(`**/api/tasks/${TASK_ID}`, (route) => {
      route.fulfill({
        json: {
          task_id: TASK_ID,
          status: "processing",
          stage: "extracting_subtitles",
          video_filename: "test-video.mp4",
          config: { llm_base_url: "https://api.anthropic.com", llm_model: "claude" },
          subtitle_segment_count: 0,
          clips: [],
          media_info: { fps: 30, fps_mode: "average" },
        },
      });
    });

    await page.route(`**/api/tasks/${TASK_ID}/status`, (route) => {
      route.fulfill({
        json: {
          task_id: TASK_ID,
          status: "processing",
          stage: "extracting_subtitles",
          video_filename: "test-video.mp4",
          subtitle_segment_count: 0,
          updated_at: new Date().toISOString(),
        },
      });
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Seed settings and reload
    await page.evaluate(() => {
      localStorage.setItem(
        "global_llm_settings",
        JSON.stringify({
          llmBaseUrl: "https://api.anthropic.com",
          llmModel: "claude",
          llmApiKey: "sk-ant-test-key-12345",
          asrProvider: "qwen",
          asrBaseUrl: "https://dashscope.aliyuncs.com",
          asrModel: "qwen3-asr-flash-filetrans",
          asrApiKey: "",
        }),
      );
    });
    await page.reload();
    await page.waitForLoadState("networkidle");

    // No configuration warning should be visible
    await expect(page.getByText("请先配置 LLM API Key")).not.toBeVisible();

    // Select a video file
    const fileInput = page.locator('input[type="file"]');
    await expect(fileInput).toBeAttached({ timeout: 5000 });
    await fileInput.setInputFiles(TEST_VIDEO);

    // Wait for navigation to task detail
    await page.waitForURL(`**/tasks/${TASK_ID}`, { timeout: 15000 });

    // Verify the AI tab is available (not disabled), click it, verify chat input
    const aiTab = page.getByRole("button", { name: "AI" });
    await expect(aiTab).toBeVisible({ timeout: 5000 });
    await expect(aiTab).toBeEnabled();
    await aiTab.click();

    // Verify ChatPanel is rendered and input is available
    const chatInput = page.getByPlaceholder("输入你的指令...");
    await expect(chatInput).toBeVisible({ timeout: 5000 });
    await expect(chatInput).toBeEnabled();

    // Verify POST body contains exact default clip params and configured LLM fields
    const formBody = postFormFields.join("");

    // Helper: check that a form field name is followed by its expected value
    // in raw multipart body (name="field"\r\n\r\nvalue\r\n)
    function assertFormField(body: string, name: string, value: string) {
      const pattern = `name="${name}"`;
      const idx = body.indexOf(pattern);
      if (idx === -1) throw new Error(`Field "${name}" not found in multipart body`);
      // The value appears after the name header, in the next body part
      const afterName = body.substring(idx + pattern.length);
      expect(afterName).toContain(value);
    }

    assertFormField(formBody, "clip_min_duration", "30");
    assertFormField(formBody, "clip_max_duration", "120");
    assertFormField(formBody, "buffer_seconds", "3");
    assertFormField(formBody, "burn_subtitle", "false");
    assertFormField(formBody, "llm_base_url", "https://api.anthropic.com");
    assertFormField(formBody, "llm_model", "claude");
    assertFormField(formBody, "llm_api_key", "sk-ant-test-key-12345");
  });
});
