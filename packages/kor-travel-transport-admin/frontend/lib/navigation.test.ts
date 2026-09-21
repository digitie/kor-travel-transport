import { describe, expect, it } from "vitest";

import { sanitizeLocalPath } from "./navigation";

describe("sanitizeLocalPath", () => {
  it("같은 origin의 상대 경로만 유지한다", () => {
    expect(sanitizeLocalPath("/transport?days=7")).toBe("/transport?days=7");
    expect(sanitizeLocalPath("https://example.com")).toBe("/");
    expect(sanitizeLocalPath("//example.com")).toBe("/");
  });
});
