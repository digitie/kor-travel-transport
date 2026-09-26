import { describe, expect, it } from "vitest";

import { effectiveFerryServiceDate } from "./transport-reference-list";

describe("effectiveFerryServiceDate", () => {
  it("자정 이후에도 이전 화면의 운항일을 오늘로 보정한다", () => {
    expect(effectiveFerryServiceDate("2026-09-26", "2026-09-27")).toBe("2026-09-27");
  });

  it("오늘과 미래의 명시 선택은 유지한다", () => {
    expect(effectiveFerryServiceDate("2026-09-27", "2026-09-27")).toBe("2026-09-27");
    expect(effectiveFerryServiceDate("2026-10-01", "2026-09-27")).toBe("2026-10-01");
  });
});
