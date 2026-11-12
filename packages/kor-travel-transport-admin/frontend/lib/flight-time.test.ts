import { describe, expect, it } from "vitest";
import { flightMoment } from "./flight-time";

describe("이후 항공편 시각", () => {
  it("KST와 UTC는 같은 순간이며 서버/브라우저 로컬 시각을 더하지 않는다", () => {
    expect(flightMoment({ scheduled_at: "2026-11-13T14:00:00+09:00", estimated_at: null })).toBe(Date.parse("2026-11-13T05:00:00Z"));
  });
  it.each([null, "", "invalid"])("변경 시각 %s가 유효하지 않으면 예정 시각으로 미래편을 보존한다", (estimated_at) => {
    expect(flightMoment({ scheduled_at: "2026-11-13T15:00:00+09:00", estimated_at })).toBeGreaterThan(Date.parse("2026-11-13T14:00:00+09:00"));
  });
  it("실제로 앞당긴 변경 시각은 예정 시각으로 덮지 않는다", () => {
    expect(flightMoment({ scheduled_at: "2026-11-13T15:00:00+09:00", estimated_at: "2026-11-13T13:00:00+09:00" })).toBeLessThan(Date.parse("2026-11-13T14:00:00+09:00"));
  });
  it("둘 다 잘못된 시각은 미래로 꾸미지 않는다", () => {
    expect(flightMoment({ scheduled_at: "invalid", estimated_at: null })).toBeNaN();
  });
});
