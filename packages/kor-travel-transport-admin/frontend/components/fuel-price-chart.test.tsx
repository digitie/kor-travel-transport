// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import FuelPriceChart from "./fuel-price-chart";
const capture = vi.hoisted(() => ({ options: {} as Record<string, unknown> }));
vi.mock("./evilcharts/charts/echarts-line-chart", () => ({ EChartsLineChart: ({ chartOptions }: { chartOptions: Record<string, unknown> }) => { capture.options = chartOptions; return <div data-official-chart="true" />; } }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
test("공식 EvilCharts에 실제 시간축·최저최고 whisker·안전한 수치 툴팁을 전달한다", async () => {
  const container = document.createElement("div"), root = createRoot(container);
  try {
    await act(async () => root.render(<FuelPriceChart label="검증 차트" series={[{ product: "B027", points: [
      { time: "2026-11-01", average: 1700.35, minimum: 1600.25, maximum: 1900.85, generated_at: "2026-11-01T01:00:00Z", cheapest: { name: '<img src=x onerror="evil()">', longitude: 127, latitude: 37 } },
      { time: "2026-11-04", average: 1701.25, minimum: null, maximum: null },
    ] }]} />));
    await act(async () => { await vi.waitFor(() => expect(capture.options.series).toBeDefined()); });
    expect(container.querySelector('[data-official-chart="true"]')).not.toBeNull();
    expect(capture.options.xAxis).toMatchObject({ type: "time", axisLabel: { hideOverlap: true } });
    const charts = capture.options.series as { id: string; type: string; data: unknown[]; renderItem?: (params: unknown, api: unknown) => { children: unknown[] } }[];
    expect(charts[0].data).toHaveLength(3); // 관측 두 점과 실제 날짜 공백 null.
    expect(charts[1].type).toBe("custom"); expect(charts[1].data).toHaveLength(1);
    const whisker = charts[1].renderItem!({}, { value: (index: number) => [1, 2, 3][index], coord: (pair: number[]) => pair });
    expect(whisker.children).toHaveLength(3);
    const tooltip = capture.options.tooltip as { triggerOn: string; formatter: (params: unknown) => string };
    expect(tooltip.triggerOn).toContain("click");
    const html = tooltip.formatter([{ seriesId: "B027:average", value: (charts[0].data[0]) }]);
    for (const value of ["2026-11-01 00:00", "1,700.35", "1,600.25", "1,900.85", "2026-11-01 10:00", "/fuel?longitude=127&amp;latitude=37"]) expect(html).toContain(value);
    expect(html).not.toContain("<img"); expect(html).toContain("&lt;img");
    const chart = container.querySelector(".fuel-chart-keyboard")!;
    await act(async () => chart.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(container.querySelector('[role="status"]')?.textContent).toContain("미제공");
  } finally { await act(async () => root.unmount()); }
});

test("주·월 버킷 점의 툴팁·키보드 안내는 시작일 하루가 아니라 기록 범위와 일수를 보인다", async () => {
  const container = document.createElement("div"), root = createRoot(container);
  const week = { first_day: "2026-01-05", last_day: "2026-01-11", day_count: 7 };
  try {
    await act(async () => root.render(<FuelPriceChart label="주 차트" maxGapDays={7} series={[
      { product: "B027", points: [{ time: "2026-01-05", average: 1700, minimum: 1600, maximum: 1800, generated_at: "2026-01-11T00:17:00Z", span: week }] },
      { product: "D047", points: [{ time: "2026-01-05", average: 1500, minimum: 1400, maximum: 1600, generated_at: "2026-01-11T00:17:00Z", span: week }] },
    ]} />));
    await act(async () => { await vi.waitFor(() => expect(capture.options.series).toBeDefined()); });
    const charts = capture.options.series as { id: string; data: unknown[] }[];
    const tooltip = capture.options.tooltip as { formatter: (params: unknown) => string };
    const average = (id: string) => charts.find(chart => chart.id === id)!;
    const same = tooltip.formatter([{ seriesId: "B027:average", value: average("B027:average").data[0] }, { seriesId: "D047:average", value: average("D047:average").data[0] }]);
    // 공통 범위는 머리글에 한 번, 시작일 00:00 시각은 보이지 않는다.
    expect(same).toContain("<strong>2026-01-05 → 2026-01-11 KST · 기록 7일</strong>");
    expect(same.match(/기록 7일/g)).toHaveLength(1);
    expect(same).not.toContain("2026-01-05 00:00");
    expect(same).toContain("마지막 기록일 수집 2026-01-11 09:17 KST");
    const chart = container.querySelector(".fuel-chart-keyboard")!;
    await act(async () => chart.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(container.querySelector('[role="status"]')?.textContent).toContain("휘발유 · 2026-01-05 → 2026-01-11 KST · 기록 7일");

    // 유종마다 기록 범위가 다르면 행마다 적는다.
    await act(async () => root.render(<FuelPriceChart label="주 차트" maxGapDays={7} series={[
      { product: "B027", points: [{ time: "2026-01-05", average: 1700, span: week }] },
      { product: "D047", points: [{ time: "2026-01-05", average: 1500, span: { first_day: "2026-01-07", last_day: "2026-01-07", day_count: 1 } }] },
    ]} />));
    const next = capture.options.series as { id: string; data: unknown[] }[];
    const differ = (capture.options.tooltip as { formatter: (params: unknown) => string }).formatter([
      { seriesId: "B027:average", value: next.find(chart => chart.id === "B027:average")!.data[0] },
      { seriesId: "D047:average", value: next.find(chart => chart.id === "D047:average")!.data[0] }]);
    expect(differ).toContain("<br/>2026-01-05 → 2026-01-11 KST · 기록 7일");
    expect(differ).toContain("<br/>2026-01-07 KST · 기록 1일");
    expect(differ).not.toContain("<strong>2026-01-05");
  } finally { await act(async () => root.unmount()); }
});
