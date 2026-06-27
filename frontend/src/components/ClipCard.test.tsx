import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ClipCard from "./ClipCard";
import type { Clip } from "../api/client";

function makeClip(): Clip {
  return {
    start_time_s: 10,
    end_time_s: 20,
    score: 8.5,
    reason: "精彩片段",
    status: "pending",
  };
}

describe("ClipCard numbering", () => {
  it("renders the first clip with a 1-based visible label", () => {
    const html = renderToStaticMarkup(
      <ClipCard
        clip={makeClip()}
        index={0}
        taskId="task-1"
        onPreview={() => {}}
      />,
    );

    expect(html).toContain("片段 #1");
    expect(html).not.toContain("片段 #0");
  });

  it("renumbers from the current array index after deletion", () => {
    const html = renderToStaticMarkup(
      <ClipCard
        clip={makeClip()}
        index={1}
        taskId="task-1"
        onPreview={() => {}}
      />,
    );

    expect(html).toContain("片段 #2");
    expect(html).not.toContain("片段 #3");
  });
});
