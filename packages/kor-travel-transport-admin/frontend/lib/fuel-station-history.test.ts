import { afterEach, expect, test, vi } from "vitest";
import * as journey from "./journey";
import { fuelHistorySeries, isFuelHistoryGap, loadFuelStationHistory, type FuelStationHistory } from "./fuel-station-history";

export const historyFixture = (station_id = 1): FuelStationHistory => ({ station_id, source: "opinet_browser", provider_id: "A001", brand_code: "SOL", brand_name: "S-OIL",
  window: { from_at: "2026-10-21T03:00:00Z", to_at: "2026-10-28T03:00:00Z", timezone: "Asia/Seoul", mode: "rolling" },
  items: [], latest: [], meta: { generated_at: "2026-10-28T03:00:00Z", source_collected_at: "2026-10-28T02:00:00Z", source_status: "success", item_count: 0 }, source_last_success_at: "2026-10-28T02:00:00Z", source_revision: "r1", has_more: false, next_cursor: null });
const price = (observed_at: string, value: number | null, product_code = "B027") => ({ observed_at, price: value, product_code });
afterEach(() => vi.restoreAllMocks());

test("실제 168시간 안의 양수만 시간순으로 표시하고 유종별 최신값을 구한다", () => {
  const data = historyFixture();
  data.latest = [price("2026-10-20T03:00:00Z", 1900)];
  data.items = [price("2026-10-28T02:00:00Z", 1705), price("2026-10-21T03:00:00Z", 1700), price("2026-10-20T02:00:00Z", 900), price("2026-10-29T02:00:00Z", 2000), price("2026-10-27T02:00:00Z", 0), price("2026-10-27T02:00:00Z", null), price("invalid", 1800), price("2026-10-28T02:00:00Z", 1550, "D047")];
  const series = fuelHistorySeries(data);
  expect(series.map((row) => row.points.map((point) => point.price))).toEqual([[1700, 1705], [1550]]);
  expect(isFuelHistoryGap(series[0].points[0], series[0].points[1])).toBe(true);
  expect(series[0].points[0].day).toBe("2026-10-21");
});
test("KST 자정 전후 관측의 날짜를 정확히 구분한다", () => {
  const data = historyFixture(); data.items = [price("2026-10-25T14:59:00Z", 1700), price("2026-10-25T15:01:00Z", 1701)];
  const points = fuelHistorySeries(data)[0].points;
  expect(points.map((point) => point.day)).toEqual(["2026-10-25", "2026-10-26"]);
  expect(isFuelHistoryGap(points[0], points[1])).toBe(false);
});
test("cursor 전량 조회는 고정 창과 source revision을 유지한다", async () => {
  const first = historyFixture(); first.items = [price("2026-10-28T02:00:00Z", 1701)]; first.has_more = true; first.next_cursor = "opaque";
  const second = historyFixture(); second.items = [price("2026-10-27T02:00:00Z", 1700)];
  const get = vi.spyOn(journey, "transportGet").mockResolvedValueOnce(first).mockResolvedValueOnce(second);
  const data = await loadFuelStationHistory(1, "opinet_browser", new AbortController().signal);
  expect(data.items).toHaveLength(2); expect(get.mock.calls[1][0]).toContain("cursor=opaque");
  expect(get.mock.calls[0][0]).toContain("transport/fuel/stations/1/price-history?source=opinet_browser&days=7&limit=1000");
});
test("revision 409는 한 번 새 창으로 시작하고 이전 페이지를 혼합하지 않는다", async () => {
  const first = { ...historyFixture(), items: [price("2026-10-28T02:00:00Z", 9999)], has_more: true, next_cursor: "old" };
  const second = { ...historyFixture(), source_revision: "r2", items: [price("2026-10-28T02:00:00Z", 1700)] };
  const get = vi.spyOn(journey, "transportGet").mockResolvedValueOnce(first).mockRejectedValueOnce(new journey.TransportError("변경", 409, 0)).mockResolvedValueOnce(second);
  expect((await loadFuelStationHistory(1, "opinet_browser", new AbortController().signal)).items).toEqual(second.items);
  expect(get.mock.calls[2][0]).not.toContain("cursor=");
});
test("잘못된 주유소 응답과 반복 cursor를 부분 성공으로 표시하지 않는다", async () => {
  const get = vi.spyOn(journey, "transportGet").mockResolvedValue(historyFixture(2));
  await expect(loadFuelStationHistory(1, "opinet_browser", new AbortController().signal)).rejects.toThrow("일치하지 않습니다");
  get.mockResolvedValue({ ...historyFixture(), has_more: true, next_cursor: "same" });
  await expect(loadFuelStationHistory(1, "opinet_browser", new AbortController().signal)).rejects.toThrow("전체를 확인하지 못했습니다");
});
