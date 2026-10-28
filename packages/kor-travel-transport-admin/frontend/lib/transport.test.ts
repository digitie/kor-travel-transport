import { describe, expect, it } from "vitest";

import { isAllowedTransportPath } from "./transport";

describe("isAllowedTransportPath", () => {
  it("수집 상태와 공개 교통 조회 API만 허용한다", () => {
    expect(isAllowedTransportPath(["transport", "collector-status"])).toBe(true);
    expect(isAllowedTransportPath(["transport", "bus", "terminals"])).toBe(true);
    expect(isAllowedTransportPath(["transport", "bus", "timetable"])).toBe(true);
    expect(isAllowedTransportPath(["transport", "rail", "timetables"])).toBe(true);
    expect(isAllowedTransportPath(["transport", "rail", "collect"])).toBe(false);
    expect(isAllowedTransportPath(["admin", "backups"])).toBe(false);
  });
  it("가격 이력은 정확한 양수 주유소 ID의 읽기 경로만 허용한다", () => {
    expect(isAllowedTransportPath(["transport", "fuel", "stations", "12", "price-history"])).toBe(true);
    for (const id of ["0", "-1", "01", "12/collect", "1e2"]) expect(isAllowedTransportPath(["transport", "fuel", "stations", id, "price-history"])).toBe(false);
    expect(isAllowedTransportPath(["transport", "fuel", "stations", "12", "collect"])).toBe(false);
    expect(isAllowedTransportPath(["transport", "fuel", "stations", "12", "price-history", "extra"])).toBe(false);
  });
});
