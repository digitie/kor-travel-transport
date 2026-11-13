import { expect, test } from "vitest";
import { fuelChartTime, fuelInstant, fuelLineValues, fuelStationHref } from "./fuel-chart-model";
test("KST 실제 시간 간격과 결측 날짜만 null로 보존한다", () => {
  const values = fuelLineValues([{ time: "2026-11-01", average: 1600 }, { time: "2026-11-06", average: 1700 }, { time: "2026-11-02", average: 1650 }, { time: "bad", average: 12 }, { time: "2026-11-03", average: 0 }]);
  expect(values).toEqual([[fuelInstant("2026-11-01"), 1600], [fuelInstant("2026-11-02"), 1650], [(fuelInstant("2026-11-02") + fuelInstant("2026-11-06")) / 2, null], [fuelInstant("2026-11-06"), 1700]]);
  expect(fuelChartTime("2026-11-01T15:00:00Z")).toBe("2026-11-02 00:00");
});
test("유효한 좌표만 내부 주유소 지도 링크로 만든다", () => {
  expect(fuelStationHref({ name: "주유소", longitude: 127, latitude: 37 })).toBe("/fuel?longitude=127&latitude=37");
  for (const longitude of [null, undefined, NaN, 181]) expect(fuelStationHref({ name: "없음", longitude, latitude: 37 })).toBeNull();
});
