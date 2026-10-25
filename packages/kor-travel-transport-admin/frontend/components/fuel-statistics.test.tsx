// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import { FuelPriceTrend, FuelStatisticsCard, FuelViewportSummary, type FuelViewportStatistics } from "./fuel-statistics";

const metrics: FuelViewportStatistics = { product_code: "B027", station_count: 1000, average_price: 1700,
  minimum_price: 1600, maximum_price: 1800, price_spread: 200, standard_deviation: 50,
  saving_50l: 5000, cheapest_station_count: 2, generated_at: "2026-10-21T01:00:00Z",
  cheapest_station: { name: "최저가 주유소", address: "서울" } };

test("평균·최저·편차·절감액과 동률 주유소를 표시한다", () => {
  const html = renderToStaticMarkup(<FuelStatisticsCard title="휘발유" metrics={metrics} />);
  for (const value of ["1,700", "1,600", "5,000", "최저가 주유소", "외 1곳", "가격 표준편차"]) expect(html).toContain(value);
});

test("지도 재조회 중 이전 범위의 통계를 표시하지 않는다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[metrics]} pending />);
  expect(html).toContain("통계 조회 중");
  expect(html).not.toContain("최저가 주유소");
  expect(html).toContain('aria-busy="true"');
});

test("지도 범위 통계는 마커 개수 대신 API의 전체 주유소 개수를 쓴다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[metrics]} pending={false} />);
  expect(html).toContain("1,000개 주유소");
  expect(html).toContain("휘발유");
});

test("수집 기록이 없는 날짜의 간격을 유지하고 선을 연결하지 않는다", () => {
  const html = renderToStaticMarkup(<FuelPriceTrend rows={["2026-10-15", "2026-10-16", "2026-10-21"].map((day) => ({ day, average_price: 1700, station_count: 1 }))} />);
  const element = document.createElement("div"); element.innerHTML = html;
  const points = [...element.querySelectorAll("circle")].map((point) => Number(point.getAttribute("cx")));
  expect(points[1] - points[0]).toBeCloseTo((points[2] - points[1]) / 5);
  expect(element.querySelectorAll("line")).toHaveLength(1);
});

test("지도 통계가 최신 수집을 반영하지 못했으면 대기를 표시한다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[{ ...metrics, update_pending: true }]} pending={false} />);
  expect(html).toContain("최신 수집 통계 반영 대기");
});

test("지도 통계 유종을 바꾸면 같은 서버 집계의 가격과 주유소 수가 함께 바뀐다", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<FuelViewportSummary items={[metrics, { ...metrics, product_code: "D047", average_price: 1550, minimum_price: 1450, station_count: 700 }]} pending={false} />));
    const select = container.querySelector("select")!;
    await act(async () => { select.value = "D047"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(container.textContent).toContain("1,550");
    expect(container.textContent).toContain("700개 주유소");
    expect(container.textContent).not.toContain("1,700");
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending={false} />));
    expect(container.textContent).toContain("1,700");
    expect(container.textContent).toContain("1,000개 주유소");
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("지도 통계 실패는 이전 응답의 가격이나 0원으로 표시하지 않는다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[metrics]} pending={false} failed />);
  expect(html).toContain('role="alert"');
  expect(html).toContain("통계를 불러오지 못했습니다");
  expect(html).not.toContain("1,700");
});
