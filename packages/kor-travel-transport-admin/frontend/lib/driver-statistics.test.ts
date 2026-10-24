import { describe, expect, it } from "vitest";
import { currentSpeeds, fuelDrivingCosts } from "./driver-statistics";
import { serviceInstant } from "./journey";
import { nearestPlaces } from "./nearby";

describe("운전자 통계와 예정 시각", () => {
  it("구간 중복·노후·미래·결측 속도를 제외하며 실제 정지는 남긴다", () => {
    const now = Date.parse("2026-10-24T01:00:00Z");
    const row = (id: string, speed: number | null, age: number) => ({ identity_key: id, speed, observed_at: new Date(now - age * 60_000).toISOString(), route_no: "1" });
    const stats = currentSpeeds([row("a", 100, 3), row("a", 0, 1), row("b", 40, 1), row("c", 80, 1), row("old", 30, 16), row("null", null, 1), row("future", 20, -1)], now);
    expect(stats.rows).toHaveLength(3); expect(stats.stopped).toBe(1); expect(stats.mean).toBe(40);
    expect(stats.median).toBe(40); expect(stats.slowRatio).toBeCloseTo(200 / 3); expect(stats.excluded).toBe(3);
    expect(currentSpeeds([], now).mean).toBeNull();
  });
  it("연료 비용은 입력 가정으로 계산하고 잘못된 연비를 0원으로 만들지 않는다", () => {
    const metrics = { average_price: 1700, minimum_price: 1600, maximum_price: 1800 };
    expect(fuelDrivingCosts(metrics, 50, 10)).toMatchObject({ averageFill: 85000, minimumFill: 80000, maximumFill: 90000, saving: 5000, costPer100Km: 17000 });
    expect(fuelDrivingCosts(metrics, 0, 0)).toMatchObject({ averageFill: null, costPer100Km: null });
  });
  it("TAGO 당일·익일과 잘못된 달력 날짜를 구분한다", () => {
    expect(serviceInstant("202610250030", "2026-10-24")).toBe(Date.parse("2026-10-25T00:30:00+09:00"));
    expect(serviceInstant("2430", "2026-10-24")).toBe(Date.parse("2026-10-25T00:30:00+09:00"));
    expect(serviceInstant("202602300930", "2026-10-24")).toBeNull();
    expect(serviceInstant("1260", "2026-10-24")).toBeNull();
  });
  it("현재 위치에서 실제 좌표가 있는 장소만 거리 순으로 정렬한다", () => {
    const position = { longitude: 127, latitude: 37, accuracy: 10 };
    const rows = nearestPlaces([{ id: 1, longitude: 128, latitude: 37 }, { id: 2, longitude: null, latitude: null }, { id: 3, longitude: 127, latitude: 37.01 }], position);
    expect(rows.map((row) => row.place.id)).toEqual([3, 1]);
    expect(rows[0].distance).toBeCloseTo(1.112, 2);
  });
});
