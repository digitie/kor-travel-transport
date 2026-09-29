import { describe, expect, it } from "vitest";

import { effectiveFerryServiceDate, referenceDescription } from "./transport-reference-list";

describe("referenceDescription", () => {
  const place = { line_names: [], provider_id: "101", latitude: null, longitude: null };
  it("노선이 없는 역을 항구나 운항 검색으로 설명하지 않는다", () => {
    expect(referenceDescription(place, true)).toBe("역 코드 101 · 좌표 미등록");
    expect(referenceDescription({ ...place, provider_id: null }, true)).toBe("좌표 미등록");
  });
  it("항구 코드와 노선 정보는 기존대로 표시한다", () => {
    expect(referenceDescription(place, false)).toBe("항구 코드 101 · 좌표 미등록 · 운항 검색 가능");
    expect(referenceDescription({ ...place, line_names: ["1호선"] }, true)).toBe("1호선");
  });
});

describe("effectiveFerryServiceDate", () => {
  it("자정 이후에도 이전 화면의 운항일을 오늘로 보정한다", () => {
    expect(effectiveFerryServiceDate("2026-09-26", "2026-09-27")).toBe("2026-09-27");
  });

  it("오늘과 미래의 명시 선택은 유지한다", () => {
    expect(effectiveFerryServiceDate("2026-09-27", "2026-09-27")).toBe("2026-09-27");
    expect(effectiveFerryServiceDate("2026-10-01", "2026-09-27")).toBe("2026-10-01");
  });
});
