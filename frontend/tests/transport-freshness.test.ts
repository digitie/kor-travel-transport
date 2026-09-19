import { isFreshHighwayObservation } from "../e2e/transport-freshness";

const now = Date.parse("2026-09-19T13:30:00Z");
const fresh = "2026-09-19T13:29:00Z";

describe("교통정보 운영 E2E 최신성", () => {
  test("최근 관측과 저장을 인정한다", () => {
    expect(isFreshHighwayObservation({ observed_at: fresh, collected_at: fresh }, now)).toBe(true);
  });

  test("방금 저장했더라도 오래된 관측은 거부한다", () => {
    expect(isFreshHighwayObservation({ observed_at: "2026-09-19T12:45:00Z", collected_at: fresh }, now)).toBe(false);
  });

  test.each(["observed_at", "collected_at"] as const)("%s의 누락·잘못된 값·미래·지연을 거부한다", (field) => {
    for (const value of [undefined, null, "invalid", "2026-09-19T13:31:01Z", "2026-09-19T13:14:59Z"]) {
      expect(isFreshHighwayObservation({ observed_at: fresh, collected_at: fresh, [field]: value }, now)).toBe(false);
    }
  });

  test("15분 지연과 60초 시계 오차의 경계를 인정한다", () => {
    expect(isFreshHighwayObservation({ observed_at: "2026-09-19T13:15:00Z", collected_at: "2026-09-19T13:31:00Z" }, now)).toBe(true);
  });
});
