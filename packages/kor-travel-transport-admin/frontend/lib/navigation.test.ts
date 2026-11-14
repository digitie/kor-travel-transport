import { describe, expect, it } from "vitest";

import { sanitizeLocalPath } from "./navigation";

describe("sanitizeLocalPath", () => {
  it("같은 origin의 상대 경로만 유지한다", () => {
    expect(sanitizeLocalPath("/transport?days=7")).toBe("/transport?days=7");
    expect(sanitizeLocalPath("https://example.com")).toBe("/");
    expect(sanitizeLocalPath("//example.com")).toBe("/");
  });

  it("정규화 뒤 //로 시작하는 경로는 외부 이동으로 보고 막는다", () => {
    for (const value of ["/.//evil.com", "/a/..//evil.com", "/%2e//evil.com"]) expect(sanitizeLocalPath(value)).toBe("/");
  });
});
