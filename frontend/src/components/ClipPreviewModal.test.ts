import { describe, expect, it } from "vitest";
import { buildClipPreviewVideoUrl, mediaErrorMessage } from "./ClipPreviewModal";

describe("ClipPreviewModal media helpers", () => {
  it("builds an inline authenticated video URL instead of a blob download URL", () => {
    expect(buildClipPreviewVideoUrl("task-1", 2, "token value")).toBe(
      "/api/tasks/task-1/clips/2/download?inline=true&token=token+value",
    );
  });

  it("omits token when none is configured", () => {
    expect(buildClipPreviewVideoUrl("task-1", 2, null)).toBe(
      "/api/tasks/task-1/clips/2/download?inline=true",
    );
  });

  it("maps unsupported media errors to an actionable message", () => {
    expect(mediaErrorMessage(4)).toContain("不支持");
  });
});
