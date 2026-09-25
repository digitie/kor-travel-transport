import { describe, expect, it } from "vitest";

import { isAllowedTransportPath } from "./transport";

describe("isAllowedTransportPath", () => {
  it("수집 상태와 공개 교통 조회 API만 허용한다", () => {
    expect(isAllowedTransportPath(["transport", "collector-status"])).toBe(true);
    expect(isAllowedTransportPath(["transport", "bus", "terminals"])).toBe(true);
    expect(isAllowedTransportPath(["transport", "bus", "timetable"])).toBe(true);
    expect(isAllowedTransportPath(["admin", "backups"])).toBe(false);
  });
});
