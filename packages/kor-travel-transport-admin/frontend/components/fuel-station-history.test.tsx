// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";
import { FuelStationHistoryChart, FuelStationPriceHistory } from "./fuel-station-history";
import { FuelBrandIcon } from "./fuel-brand-icon";
import * as history from "@/lib/fuel-station-history";

const fixture = (station_id = 1): history.FuelStationHistory => ({ station_id, source: "opinet_browser", provider_id: "A001", brand_code: "SOL", brand_name: "S-OIL",
  window: { from_at: "2026-10-21T03:00:00Z", to_at: "2026-10-28T03:00:00Z", timezone: "Asia/Seoul", mode: "rolling" },
  items: [], latest: [], meta: { generated_at: "2026-10-28T03:00:00Z", source_collected_at: null, source_status: "success", item_count: 0 }, source_last_success_at: null, source_revision: "r1", has_more: false, next_cursor: null });
const price = (observed_at: string, value: number | null, product_code = "B027") => ({ observed_at, price: value, product_code });
afterEach(() => vi.restoreAllMocks());
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("유종별 마지막 실제 가격과 전체 관측 표를 표시하고 빈 날짜를 연결하지 않는다", () => {
  const data = fixture(); data.items = [price("2026-10-21T03:00:00Z", 1700), price("2026-10-28T02:00:00Z", 1705), price("2026-10-28T02:00:00Z", 1550, "D047"), price("2026-10-27T02:00:00Z", 0, "C004")];
  const node = document.createElement("div"); node.innerHTML = renderToStaticMarkup(<FuelStationHistoryChart data={data} />);
  expect(node.querySelector('[data-latest-product="B027"]')?.textContent).toBe("1,705");
  expect(node.querySelector('[data-latest-product="D047"]')?.textContent).toBe("1,550");
  expect(node.querySelector('[data-latest-product="C004"]')).toBeNull();
  expect(node.querySelector('path[data-product="B027"]')?.getAttribute("d")?.match(/M/g)).toHaveLength(2);
  expect(node.querySelectorAll("tbody tr")).toHaveLength(3);
  expect(node.querySelector("details")?.open).toBe(false);
});
test("빈 이력과 한 관측을 가짜 7일 선으로 채우지 않는다", () => {
  expect(renderToStaticMarkup(<FuelStationHistoryChart data={fixture()} />)).toContain("유효한 가격 관측이 없습니다");
  const data = fixture(); data.items = [price("2026-10-28T02:00:00Z", 1700)];
  const html = renderToStaticMarkup(<FuelStationHistoryChart data={data} />);
  expect(html).toContain("1,700"); expect(html).not.toMatch(/ d="[^"]*L/);
});
test("키보드 방향키와 End로 관측 날짜·가격을 확인한다", async () => {
  const container = document.createElement("div"), root = createRoot(container);
  const data = fixture(); data.items = [price("2026-10-27T02:00:00Z", 1700), price("2026-10-28T02:00:00Z", 1705)];
  try {
    await act(async () => root.render(<FuelStationHistoryChart data={data} />));
    await act(async () => container.querySelector("svg")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true })));
    expect(container.querySelector('[role="status"]')?.textContent).toContain("1,700원/L");
    await act(async () => container.querySelector("svg")!.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(container.querySelector('[role="status"]')?.textContent).toContain("1,705원/L");
  } finally { await act(async () => root.unmount()); }
});
test("주유소를 빠르게 바꾸면 취소된 이전 응답이 새 주유소를 오염시키지 않는다", async () => {
  let resolveOld!: (value: history.FuelStationHistory) => void;
  const old = new Promise<history.FuelStationHistory>((resolve) => { resolveOld = resolve; });
  const fresh = fixture(2); fresh.items = [price("2026-10-28T02:00:00Z", 1800)];
  const load = vi.spyOn(history, "loadFuelStationHistory").mockReturnValueOnce(old).mockResolvedValueOnce(fresh);
  const container = document.createElement("div"), root = createRoot(container);
  try {
    await act(async () => root.render(<FuelStationPriceHistory place={{ id: 1, source: "opinet_browser" }} />));
    await act(async () => root.render(<FuelStationPriceHistory place={{ id: 2, source: "opinet_browser" }} />));
    const stale = fixture(1); stale.items = [price("2026-10-28T02:00:00Z", 9999)];
    await act(async () => resolveOld(stale));
    expect(load.mock.calls[0][2].aborted).toBe(true); expect(container.textContent).toContain("1,800"); expect(container.textContent).not.toContain("9,999");
  } finally { await act(async () => root.unmount()); }
});
test("지원하지 않는 출처는 요청하지 않고 오류는 재조회할 수 있다", async () => {
  const load = vi.spyOn(history, "loadFuelStationHistory").mockRejectedValue(new Error("이력 조회 실패"));
  const container = document.createElement("div"), root = createRoot(container);
  try {
    await act(async () => root.render(<FuelStationPriceHistory place={{ id: -1, source: "highway_rest_area" }} />)); expect(load).not.toHaveBeenCalled();
    await act(async () => root.render(<FuelStationPriceHistory place={{ id: 1, source: "opinet_browser" }} />));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("이력 조회 실패");
    await act(async () => container.querySelector<HTMLButtonElement>('[role="alert"] button')!.click());
    expect(load).toHaveBeenCalledTimes(2);
  } finally { await act(async () => root.unmount()); }
});
test("로고 읽기 실패 시 상표 접근 이름을 보존하고 일반 아이콘으로 돌아간다", async () => {
  const container = document.createElement("div"), root = createRoot(container);
  try {
    await act(async () => root.render(<FuelBrandIcon code="SOL" />));
    expect(container.querySelector("img")?.alt).toBe("S-OIL");
    await act(async () => container.querySelector("img")!.dispatchEvent(new Event("error")));
    expect(container.querySelector("img")).toBeNull(); expect(container.textContent).toContain("S-OIL");
  } finally { await act(async () => root.unmount()); }
});
