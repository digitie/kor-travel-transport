// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
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

test("갱신 지연과 가격 읽기 모델 갱신 시각을 통계 세대 기준과 구분한다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[metrics]} pending={false} pricesStale pricesLastRefreshedAt="2026-10-20T03:10:00Z" />);
  const container = document.createElement("div"); container.innerHTML = html;
  expect(container.querySelector(".error")?.textContent).toContain("갱신 지연 · 가격 갱신 26. 10. 20.");
  expect(container.querySelector(".fuel-viewport-context")?.textContent).toContain("통계 기준 26. 10. 21.");
  expect(container.textContent).toContain("1,700");
  expect(container.textContent).not.toContain("판매 여부");
});

test.each([{ pending: true, failed: false }, { pending: false, failed: true }])("조회 상태 $pending/$failed에서 이전 가격과 지연 경고를 함께 숨긴다", ({ pending, failed }) => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[metrics]} pending={pending} failed={failed} pricesStale pricesLastRefreshedAt="2026-10-20T03:10:00Z" />);
  expect(html).not.toContain("1,700");
  expect(html).not.toContain("갱신 지연");
  expect(html).not.toContain("26. 10. 20.");
});

test("갱신 시각과 통계 기준 시각이 없으면 확인되지 않음으로 남긴다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[{ ...metrics, generated_at: "" }]} pending={false} pricesStale pricesLastRefreshedAt={null} />);
  const container = document.createElement("div"); container.innerHTML = html;
  expect(container.textContent).toContain("갱신 지연 · 가격 갱신 확인되지 않음");
  expect(container.textContent).toContain("통계 기준 확인되지 않음");
});

test("열어 둔 통계 안내는 재조회·실패에도 초점을 유지하고 이전 수치를 남기지 않는다", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending={false} />));
    const trigger = container.querySelector<HTMLButtonElement>('button[aria-label="지도 범위 유가 통계 안내"]')!;
    await act(async () => { trigger.focus(); trigger.click(); });
    const popup = document.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(popup).not.toBeNull();
    await act(async () => popup.querySelector<HTMLAnchorElement>('a[href="/fuel/statistics"]')!.focus());
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending />));
    await vi.waitFor(() => { expect(popup.isConnected).toBe(true); expect(popup.contains(document.activeElement)).toBe(true); });
    expect(popup.textContent).toContain("통계 조회 중");
    expect(popup.textContent).not.toContain("1,700");
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending={false} failed />));
    expect(popup.contains(document.activeElement)).toBe(true);
    expect(popup.textContent).toContain("통계를 불러오지 못했습니다");
    expect(popup.textContent).not.toContain("1,700");
    await act(async () => root.render(<FuelViewportSummary items={[{ ...metrics, average_price: 1800 }]} pending={false} />));
    expect(popup.contains(document.activeElement)).toBe(true);
    expect(popup.textContent).toContain("1,800");
    expect(popup.textContent).not.toContain("1,700");
    await act(async () => popup.querySelector<HTMLButtonElement>('button[aria-label="안내 닫기"]')!.click());
    await vi.waitFor(() => expect(document.activeElement).toBe(trigger));
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending />));
    expect(document.activeElement).toBe(trigger);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("열린 안내에서 다른 입력으로 옮긴 초점은 통계 재조회가 빼앗지 않는다", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const container = document.createElement("div"), input = document.createElement("input"); document.body.append(container, input);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending={false} />));
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="지도 범위 유가 통계 안내"]')!.click());
    const popup = document.querySelector<HTMLElement>('[role="dialog"]')!;
    await act(async () => popup.querySelector<HTMLAnchorElement>('a[href="/fuel/statistics"]')!.focus());
    await act(async () => input.focus());
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending />));
    expect(document.activeElement).toBe(input);
    await act(async () => root.render(<FuelViewportSummary items={[metrics]} pending={false} failed />));
    expect(document.activeElement).toBe(input);
  } finally { await act(async () => root.unmount()); container.remove(); input.remove(); }
});
