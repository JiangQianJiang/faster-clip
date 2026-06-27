import { describe, expect, it } from "vitest";
import { clipDisplayLabel, clipDownloadFilename } from "./clipNumbering";

describe("clip numbering helpers", () => {
  it("uses 1-based labels for user-visible clip numbers", () => {
    expect(clipDisplayLabel(0)).toBe("片段 #1");
    expect(clipDisplayLabel(2)).toBe("片段 #3");
  });

  it("uses 1-based padded filenames for downloads", () => {
    expect(clipDownloadFilename(0, "mp4")).toBe("clip_001.mp4");
    expect(clipDownloadFilename(1, "srt")).toBe("clip_002.srt");
    expect(clipDownloadFilename(11, "vtt")).toBe("clip_012.vtt");
  });

  it("renumbers remaining clips from their current array index", () => {
    const remainingInternalIndices = [0, 1];
    expect(remainingInternalIndices.map(clipDisplayLabel)).toEqual(["片段 #1", "片段 #2"]);
    expect(remainingInternalIndices.map((index) => clipDownloadFilename(index, "mp4"))).toEqual([
      "clip_001.mp4",
      "clip_002.mp4",
    ]);
  });
});
