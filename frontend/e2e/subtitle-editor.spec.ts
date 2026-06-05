import { expect, test } from "@playwright/test";

const taskId = "00000000-0000-0000-0000-000000000001";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/tasks", async (route) => {
    await route.fulfill({ contentType: "application/json", body: "[]" });
  });

  await page.route(`**/api/tasks/${taskId}`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        task_id: taskId,
        status: "done",
        video_filename: "demo.mp4",
        config: {
          llm_base_url: "https://example.com",
          llm_model: "m",
          asr_base_url: "",
          asr_model: "",
          clip_min_duration: 30,
          clip_max_duration: 120,
          buffer_seconds: 3,
          burn_subtitle: false,
        },
        subtitle_segment_count: 2,
        clips: [],
        created_at: "2026-05-28T00:00:00+00:00",
        updated_at: "2026-05-28T00:00:00+00:00",
        completed_at: "2026-05-28T00:00:00+00:00",
        transcript_source: "subtitle_import",
        transcript_modified_at: "2026-05-28T00:00:00+00:00",
        media_info: { fps: 25, fps_mode: "stable" },
      }),
    });
  });

  await page.route(`**/api/tasks/${taskId}/transcript`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        task_id: taskId,
        available: true,
        segment_count: 2,
        segments: [
          { start_time_s: 0, end_time_s: 2, text: "第一句字幕" },
          { start_time_s: 4, end_time_s: 6, text: "第二句字幕" },
        ],
      }),
    });
  });

  await page.route(`**/api/tasks/${taskId}/video`, async (route) => {
    await route.fulfill({ status: 404, body: "" });
  });
});

test("opens the subtitle editor from the read-only transcript panel", async ({ page }) => {
  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { name: "demo.mp4" })).toBeVisible();
  await expect(page.getByText("来源: subtitle_import · 2 条")).toBeVisible();
  await expect(page.getByText("第一句字幕")).toBeVisible();
  await expect(page.locator("textarea")).toHaveCount(0);

  await page.getByRole("button", { name: "编辑字幕" }).click();

  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("字幕列表")).toBeVisible();
  await expect(page.getByRole("button", { name: "新增字幕" })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存" })).toBeVisible();
  await expect(page.getByText("第一句字幕").last()).toBeVisible();
  await expect(page.getByText("响度加载中...")).toHaveCount(0);
  await expect(page.getByText("响度加载失败")).toHaveCount(0);
});
